from types import SimpleNamespace
from unittest.mock import patch

from celery.exceptions import Retry
from django.test import TestCase
from firebase_admin import exceptions, messaging
from rest_framework.test import APIClient

from apps.accounts.models import User

from .models import DeviceToken
from .service import PushDeliveryRetry, PushResult, send_user_event
from .tasks import deliver_user_event


class NotificationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="push@example.test")
        self.device = DeviceToken.objects.create(
            user=self.user, token="test-registration-token-one", platform="android"
        )
        self.enterContext(patch("apps.notifications.service._firebase_app", return_value=object()))
        self.send = self.enterContext(patch("firebase_admin.messaging.send_each_for_multicast"))

    def response(self, *errors):
        self.send.return_value = SimpleNamespace(responses=[
            SimpleNamespace(success=error is None, exception=error) for error in errors
        ])

    def test_all_event_types_use_expected_channel_and_private_payload(self):
        for event in ["like.received", "match.created", "chat.message", "reveal.requested",
                      "reveal.accepted", "reveal.declined", "reveal.withdrawn", "match.closed",
                      "safety.panic", "safety.safe", "safety.plan_shared", "safety.overdue"]:
            with self.subTest(event=event):
                self.response(None)
                result = send_user_event(user_id=self.user.pk, event_type=event)
                self.assertEqual(result.accepted, 1)
                message = self.send.call_args.args[0]
                self.assertEqual(message.android.notification.channel_id, "anonymoke_events")
                self.assertEqual(message.data, {"type": event})
                self.assertNotIn("body", message.data)

    def test_unregistered_token_is_disabled(self):
        self.response(messaging.UnregisteredError("expired"))
        result = send_user_event(user_id=self.user.pk, event_type="like.received")
        self.device.refresh_from_db()
        self.assertFalse(self.device.is_enabled)
        self.assertEqual(result.unavailable_reason, "no_registered_device")

    def test_invalid_credentials_never_disable_device(self):
        self.response(exceptions.InvalidArgumentError("Invalid credential or payload"))
        with self.assertRaises(PushDeliveryRetry):
            send_user_event(user_id=self.user.pk, event_type="like.received")
        self.device.refresh_from_db()
        self.assertTrue(self.device.is_enabled)

    def test_partial_failure_retries_only_failed_device(self):
        other = DeviceToken.objects.create(
            user=self.user, token="test-registration-token-two", platform="android"
        )
        self.response(None, exceptions.UnavailableError("retry later"))
        result = send_user_event(user_id=self.user.pk, event_type="like.received")
        self.assertEqual(result.accepted, 1)
        self.assertEqual(result.retry_device_ids, (other.pk,))
        self.response(None)
        send_user_event(user_id=self.user.pk, event_type="like.received", device_ids=[other.pk])
        self.assertEqual(self.send.call_args.args[0].tokens, [other.token])

    def test_suspended_accounts_and_disabled_devices_receive_nothing(self):
        self.user.status = "suspended"
        self.user.save(update_fields=["status"])
        result = send_user_event(user_id=self.user.pk, event_type="like.received")
        self.assertEqual(result.unavailable_reason, "account_unavailable")
        self.send.assert_not_called()

    def test_device_registration_is_idempotent_and_can_move_accounts(self):
        client = APIClient()
        client.force_authenticate(self.user)
        payload = {"token": self.device.token, "platform": "android"}
        for _ in range(3):
            response = client.post("/api/v1/me/notifications/devices/", payload)
            self.assertEqual(response.status_code, 200)
        other = User.objects.create_user(email="other-push@example.test")
        client.force_authenticate(other)
        self.assertEqual(client.post("/api/v1/me/notifications/devices/", payload).status_code, 200)
        self.assertEqual(DeviceToken.objects.count(), 1)
        client.force_authenticate(self.user)
        client.delete("/api/v1/me/notifications/devices/", {"token": self.device.token})
        self.device.refresh_from_db()
        self.assertTrue(self.device.is_enabled)
        self.assertEqual(self.device.user_id, other.pk)
        client.force_authenticate(other)
        client.delete("/api/v1/me/notifications/devices/", {"token": self.device.token})
        self.device.refresh_from_db()
        self.assertFalse(self.device.is_enabled)

    def test_task_retries_the_subset_and_uses_consumed_queue(self):
        self.assertEqual(deliver_user_event.queue, "default")
        with (patch("apps.notifications.tasks.send_user_event",
                    return_value=PushResult(accepted=1, retry_device_ids=(2,))),
              patch.object(deliver_user_event, "retry", side_effect=Retry()) as retry):
            with self.assertRaises(Retry):
                deliver_user_event.run(str(self.user.pk), "like.received")
            self.assertEqual(retry.call_args.kwargs["kwargs"]["device_ids"], [2])


class NotificationTriggerTests(TestCase):
    def setUp(self):
        from django.core.cache import cache

        cache.clear()
        self.enqueue = self.enterContext(patch("apps.notifications.tasks.deliver_user_event.delay"))
        self.me = self.profile("first")
        self.other = self.profile("second")

    def profile(self, name):
        from django.contrib.gis.geos import Point
        from django.utils import timezone

        from apps.compliance.models import ConsentRecord
        from apps.profiles.models import MatchingPreference, Profile

        user = User.objects.create_user(email=f"{name}@example.test")
        profile = Profile.objects.create(
            user=user, alias=name, gender="NB", age_years=27,
            verification_level="verified", cell=Point(36.82, -1.28, srid=4326),
            cell_updated_at=timezone.now(), min_age_pref=18, max_age_pref=40,
            max_distance_km=15,
        )
        MatchingPreference.objects.create(profile=profile, target_genders=["ALL"])
        for kind in ["location", "sensitive_data"]:
            ConsentRecord.objects.create(user=user, consent_type=kind, version="test", granted=True)
        return profile

    def test_like_and_reciprocal_match_trigger_once_after_commit(self):
        import uuid

        from apps.matching.services import record_swipe

        identifier = uuid.uuid4()
        with self.captureOnCommitCallbacks(execute=True):
            record_swipe(self.me, self.other.public_id, "like", identifier)
            record_swipe(self.me, self.other.public_id, "like", identifier)
        self.assertEqual([c.args[1] for c in self.enqueue.call_args_list], ["like.received"])
        self.enqueue.reset_mock()
        with self.captureOnCommitCallbacks(execute=True):
            record_swipe(self.other, self.me.public_id, "like", uuid.uuid4())
        self.assertEqual([c.args[1] for c in self.enqueue.call_args_list],
                         ["match.created", "match.created"])

    def test_reveal_request_and_mutual_accept_trigger_correct_events(self):
        from apps.matching.models import Match
        from apps.matching.services import request_unmask, respond_unmask

        match = Match.objects.create(profile_a=self.me, profile_b=self.other)
        with self.captureOnCommitCallbacks(execute=True):
            request_unmask(self.me, match.pk)
            request_unmask(self.me, match.pk)
        self.assertEqual([c.args[1] for c in self.enqueue.call_args_list], ["reveal.requested"])
        self.enqueue.reset_mock()
        with self.captureOnCommitCallbacks(execute=True):
            respond_unmask(self.other, match.pk, True)
        self.assertEqual([c.args[1] for c in self.enqueue.call_args_list],
                         ["reveal.accepted", "reveal.accepted"])

    def test_chat_push_waits_for_moderation_and_is_not_duplicated(self):
        from apps.chat.models import Message
        from apps.chat.services import moderate_message
        from apps.matching.models import Match

        match = Match.objects.create(profile_a=self.me, profile_b=self.other)
        message = Message.objects.create(match=match, sender=self.me,
                                         body="Hello there", moderation_status="queued")
        self.enqueue.assert_not_called()
        with (self.captureOnCommitCallbacks(execute=True),
              patch("apps.chat.services._publish_message")):
            moderate_message(message.pk)
            moderate_message(message.pk)
        self.assertEqual([c.args[1] for c in self.enqueue.call_args_list], ["chat.message"])
