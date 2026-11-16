import uuid
from datetime import timedelta
from unittest.mock import patch

from django.contrib.gis.geos import Point
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from redis.exceptions import ConnectionError as RedisConnectionError
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.compliance.models import ConsentRecord
from apps.notifications.service import PushResult
from apps.profiles.models import Profile

from .delivery import dispatch_pending, process_delivery
from .lifecycle import (
    accept_invite,
    acknowledge_alert,
    issue_invite,
    resolve_plan,
    save_plan,
    trigger_panic,
    unlink_contact,
)
from .models import DateSession, PanicAlert, SafetyAlertRecipient, SafetyDelivery, TrustedContact
from .scheduling import process_due_checkins, purge_old_plans
from .serializers import DateSessionSerializer, DateSessionWriteSerializer, TrustedContactSerializer


class SafetyIntegrationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.owner = self.user("owner")
        self.friend = self.user("friend")
        self.stranger = self.user("stranger")
        self.contact = TrustedContact.objects.create(
            user=self.owner, contact_name="My friend", linked_user=self.friend
        )
        self.client = APIClient()
        self.client.force_authenticate(self.owner)
        self.base = "/api/v1/me/safety/"

    def user(self, alias):
        user = User.objects.create_user(email=f"{alias}@example.test")
        Profile.objects.create(
            user=user,
            alias=alias,
            cell=Point(36.824, -1.283, srid=4326),
            cell_updated_at=timezone.now(),
        )
        for kind in ("location", "sensitive_data"):
            ConsentRecord.objects.create(user=user, consent_type=kind, granted=True, version="test")
        return user

    def plan(self, **changes):
        fields = {
            "starts_at": timezone.now() - timedelta(minutes=5),
            "check_in_due_at": timezone.now() + timedelta(hours=3),
            "venue_label": "Public cafe",
            "share_approximate_location": False,
        }
        fields.update(changes)
        return save_plan(self.owner, fields)

    def panic(self):
        self.plan()
        return trigger_panic(self.owner, str(uuid.uuid4()))[0]

    def test_plan_is_shared_before_any_panic_and_bound_to_linked_recipient(self):
        plan = self.plan()
        self.assertEqual(plan.trusted_contact_user, self.friend)
        self.assertTrue(
            SafetyDelivery.objects.filter(session=plan, event_type="safety.plan_shared").exists()
        )
        self.client.force_authenticate(self.friend)
        response = self.client.get(self.base)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["shared_plan_count"], 1)
        self.assertEqual(response.data["shared_plans"][0]["venue_label"], "Public cafe")

    def test_broker_outage_keeps_one_durable_alert_and_recipient(self):
        self.plan()
        with patch(
            "apps.safety.tasks.dispatch_safety_delivery.delay", side_effect=RuntimeError("offline")
        ):
            with self.captureOnCommitCallbacks(execute=True):
                alert, created = trigger_panic(self.owner, "stable-key")
        self.assertTrue(created)
        self.assertEqual(alert.status, "stored")
        self.assertIsNone(alert.delivered_at)
        self.assertEqual(SafetyAlertRecipient.objects.filter(alert=alert).count(), 1)
        self.assertEqual(SafetyDelivery.objects.get(alert=alert).status, "queued")
        retry, created = trigger_panic(self.owner, "another-key")
        self.assertFalse(created)
        self.assertEqual(retry.pk, alert.pk)

    def test_panic_stays_in_overview_and_can_be_marked_safe_idempotently(self):
        alert = self.panic()
        self.assertEqual(self.client.get(self.base).data["active_date"]["status"], "panic")
        first = resolve_plan(self.owner, alert.date_session_id, safe=True)
        again = resolve_plan(self.owner, alert.date_session_id, safe=True)
        self.assertEqual(first.safe_at, again.safe_at)
        self.assertIsNone(self.client.get(self.base).data["active_date"])
        self.assertEqual(SafetyDelivery.objects.filter(event_type="safety.safe").count(), 1)
        self.client.force_authenticate(self.friend)
        self.assertEqual(
            self.client.get(self.base).data["incoming_alerts"][0]["session_status"], "safe"
        )

    def test_retry_key_recovers_alert_even_after_safe_resolution(self):
        self.plan()
        alert, _ = trigger_panic(self.owner, "stable")
        resolve_plan(self.owner, alert.date_session_id, safe=True)
        self.assertEqual(trigger_panic(self.owner, "stable")[0].pk, alert.pk)

    def test_acknowledgement_is_scoped_and_only_records_a_real_recipient_ack(self):
        alert = self.panic()
        recipient = alert.recipients.get()
        with self.assertRaisesMessage(ValueError, "safety_alert_not_found"):
            acknowledge_alert(self.stranger, recipient.pk)
        ack = acknowledge_alert(self.friend, recipient.pk)
        again = acknowledge_alert(self.friend, recipient.pk)
        self.assertEqual(ack.acknowledged_at, again.acknowledged_at)
        alert.refresh_from_db()
        self.assertEqual(alert.status, "acknowledged")
        self.assertEqual(SafetyDelivery.objects.filter(event_type="safety.acknowledged").count(), 1)

    def test_cannot_replace_linked_contact_or_unlink_an_open_plan(self):
        serializer = TrustedContactSerializer(
            self.contact, data={"contact_name": "New person"}, partial=True
        )
        self.assertTrue(serializer.is_valid())
        with self.assertRaises(Exception) as caught:
            serializer.save()
        self.assertIn("contact_replacement_requires_unlink", str(caught.exception))
        self.plan()
        with self.assertRaisesMessage(ValueError, "resolve_date_before_unlink"):
            unlink_contact(self.owner)
        self.contact.refresh_from_db()
        self.assertEqual(self.contact.linked_user_id, self.friend.pk)

    def test_unlink_revokes_historical_recipient_access(self):
        alert = self.panic()
        resolve_plan(self.owner, alert.date_session_id, safe=True)
        unlink_contact(self.owner)
        self.client.force_authenticate(self.friend)
        overview = self.client.get(self.base).data
        self.assertEqual(overview["incoming_alert_count"], 0)
        self.assertEqual(overview["shared_plan_count"], 0)

    def test_plan_with_a_removed_recipient_must_be_resolved_before_replacement(self):
        plan = self.plan()
        DateSession.objects.filter(pk=plan.pk).update(trusted_contact_user=None)
        with self.assertRaisesMessage(ValueError, "trusted_contact_changed"):
            save_plan(self.owner, {"venue_label": "New cafe"}, plan.pk)
        with self.assertRaisesMessage(ValueError, "trusted_contact_changed"):
            trigger_panic(self.owner, "replacement-key")
        resolve_plan(self.owner, plan.pk, safe=True)
        self.assertEqual(self.plan().trusted_contact_user_id, self.friend.pk)

    def test_invites_are_single_use_expiring_and_reject_self_link(self):
        self.contact.linked_user = None
        self.contact.save()
        code, _ = issue_invite(self.owner)
        self.assertEqual(len(code), 12)
        with self.assertRaisesMessage(ValueError, "invite_code_expired_or_invalid"):
            accept_invite(self.owner, code)
        accept_invite(self.friend, code)
        with self.assertRaisesMessage(ValueError, "invite_code_expired_or_invalid"):
            accept_invite(self.stranger, code)
        unlink_contact(self.owner)
        expired, _ = issue_invite(self.owner)
        TrustedContact.objects.filter(pk=self.contact.pk).update(
            invite_expires_at=timezone.now() - timedelta(seconds=1)
        )
        with self.assertRaisesMessage(ValueError, "invite_code_expired_or_invalid"):
            accept_invite(self.friend, expired)

    def test_open_panic_prevents_new_plan_and_cannot_be_cancelled(self):
        alert = self.panic()
        with self.assertRaisesMessage(ValueError, "active_date_already_exists"):
            self.plan()
        with self.assertRaisesMessage(ValueError, "mark_safe_to_resolve_panic"):
            resolve_plan(self.owner, alert.date_session_id, safe=False)

    @patch(
        "apps.safety.delivery.send_user_event",
        return_value=PushResult(unavailable_reason="push_unconfigured"),
    )
    def test_unconfigured_push_never_claims_sent_or_delivered(self, send):
        alert = self.panic()
        self.assertEqual(process_delivery(alert.push_delivery.pk), "unavailable")
        alert.refresh_from_db()
        self.assertEqual(alert.status, "stored")
        self.assertIsNone(alert.delivered_at)
        send.assert_called_once()

    @patch("apps.safety.delivery.send_user_event", return_value=PushResult(accepted=1))
    def test_push_acceptance_is_distinct_from_acknowledgement(self, send):
        alert = self.panic()
        self.assertEqual(process_delivery(alert.push_delivery.pk), "push_accepted")
        alert.refresh_from_db()
        self.assertEqual(alert.status, "push_accepted")
        self.assertIsNone(alert.delivered_at)
        self.assertEqual(process_delivery(alert.push_delivery.pk), "ignored")
        send.assert_called_once()

    @patch("apps.safety.delivery.send_user_event", side_effect=RuntimeError("temporary failure"))
    def test_transient_push_failure_has_backoff_and_a_bounded_retry_count(self, send):
        alert = self.panic()
        job = alert.push_delivery
        self.assertEqual(process_delivery(job.pk), "queued")
        job.refresh_from_db()
        self.assertEqual(job.attempts, 1)
        self.assertGreater(job.next_attempt_at, timezone.now())
        SafetyDelivery.objects.filter(pk=job.pk).update(attempts=7, next_attempt_at=timezone.now())
        self.assertEqual(process_delivery(job.pk), "failed")

    @patch("apps.safety.delivery.send_user_event")
    def test_safe_resolution_cancels_stale_panic_push(self, send):
        alert = self.panic()
        resolve_plan(self.owner, alert.date_session_id, safe=True)
        self.assertEqual(process_delivery(alert.push_delivery.pk), "cancelled")
        send.assert_not_called()

    @patch("apps.safety.tasks.dispatch_safety_delivery.delay")
    def test_expired_worker_lease_is_recovered(self, enqueue):
        alert = self.panic()
        SafetyDelivery.objects.filter(pk=alert.push_delivery.pk).update(
            status="processing", lease_until=timezone.now() - timedelta(seconds=1)
        )
        self.assertEqual(dispatch_pending(), 2)  # shared plan plus panic
        self.assertEqual(enqueue.call_count, 2)

    def test_checkin_reminder_and_overdue_are_idempotent_and_do_not_trigger_panic(self):
        plan = self.plan(check_in_due_at=timezone.now() + timedelta(minutes=10))
        process_due_checkins()
        process_due_checkins()
        self.assertEqual(SafetyDelivery.objects.filter(event_type="safety.checkin_due").count(), 1)
        DateSession.objects.filter(pk=plan.pk).update(
            check_in_due_at=timezone.now() - timedelta(minutes=16)
        )
        process_due_checkins()
        process_due_checkins()
        self.assertEqual(SafetyDelivery.objects.filter(event_type="safety.overdue").count(), 1)
        self.assertFalse(PanicAlert.objects.exists())

    def test_expiry_and_retention_only_remove_closed_plans(self):
        plan = self.plan()
        DateSession.objects.filter(pk=plan.pk).update(
            check_in_due_at=timezone.now() - timedelta(hours=25)
        )
        process_due_checkins()
        plan.refresh_from_db()
        self.assertEqual(plan.status, "expired")
        DateSession.objects.filter(pk=plan.pk).update(
            updated_at=timezone.now() - timedelta(days=91)
        )
        self.panic()
        purge_old_plans()
        self.assertFalse(DateSession.objects.filter(pk=plan.pk).exists())
        self.assertTrue(DateSession.objects.filter(status="panic").exists())

    def test_coarse_area_never_exposes_exact_location_and_respects_withdrawal(self):
        plan = self.plan(share_approximate_location=True)
        self.assertEqual(
            plan.approximate_area, {"latitude": -1.3, "longitude": 36.8, "radius_km": 12}
        )
        response = self.client.post(
            "/api/v1/me/consents/",
            {"type": "location", "granted": False, "version": "test"},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        plan.refresh_from_db()
        self.assertIsNone(plan.approximate_area)
        self.assertIsNone(DateSessionSerializer(plan).data["approximate_area"])

    def test_venue_update_preserves_reminder_state_but_new_deadline_resets_it(self):
        plan = self.plan()
        DateSession.objects.filter(pk=plan.pk).update(
            reminder_sent_at=timezone.now(), overdue_at=timezone.now()
        )
        same = save_plan(self.owner, {"venue_label": "Another public cafe"}, plan.pk)
        self.assertIsNotNone(same.reminder_sent_at)
        changed = save_plan(
            self.owner, {"check_in_due_at": timezone.now() + timedelta(hours=4)}, plan.pk
        )
        self.assertIsNone(changed.reminder_sent_at)
        self.assertIsNone(changed.overdue_at)

    def test_date_validation_rejects_past_due_dates_and_long_sessions(self):
        for due in [timezone.now() - timedelta(minutes=1), timezone.now() + timedelta(days=3)]:
            serializer = DateSessionWriteSerializer(
                data={
                    "starts_at": timezone.now().isoformat(),
                    "check_in_due_at": due.isoformat(),
                    "venue_label": "Cafe",
                }
            )
            self.assertFalse(serializer.is_valid())

    def test_masked_phone_uses_actual_phone_digits_and_never_hash_digits(self):
        serializer = TrustedContactSerializer(
            data={"contact_name": "Friend", "phone": "0712345678"}
        )
        self.assertTrue(serializer.is_valid())
        self.contact.delete()
        contact = serializer.save(user=self.owner)
        self.assertEqual(TrustedContactSerializer(contact).data["phone_masked"], "•••• 5678")

    @patch("apps.safety.delivery.send_user_event")
    def test_edited_deadline_cancels_the_old_queued_reminder(self, send):
        plan = self.plan(check_in_due_at=timezone.now() + timedelta(minutes=10))
        process_due_checkins()
        old_reminder = SafetyDelivery.objects.get(event_type="safety.checkin_due")
        save_plan(self.owner, {"check_in_due_at": timezone.now() + timedelta(hours=2)}, plan.pk)
        self.assertEqual(process_delivery(old_reminder.pk), "cancelled")
        send.assert_not_called()

    def test_handled_overdue_plans_cannot_starve_new_checkin_reminders(self):
        now = timezone.now()
        users = User.objects.bulk_create(
            [User(email=f"overdue-{i}@example.test") for i in range(500)]
        )
        DateSession.objects.bulk_create(
            [
                DateSession(
                    user=user,
                    starts_at=now - timedelta(hours=3),
                    check_in_due_at=now - timedelta(hours=1),
                    venue_label="Cafe",
                    trusted_contact_name="Friend",
                    overdue_at=now - timedelta(minutes=40),
                    reminder_sent_at=now - timedelta(hours=2),
                )
                for user in users
            ]
        )
        self.plan(check_in_due_at=now + timedelta(minutes=10))
        process_due_checkins()
        self.assertEqual(SafetyDelivery.objects.filter(event_type="safety.checkin_due").count(), 1)

    def test_pagination_reaches_records_after_100_and_is_viewer_scoped(self):
        DateSession.objects.bulk_create(
            [
                DateSession(
                    user=self.owner,
                    trusted_contact_user=self.friend,
                    trusted_contact_name="Friend",
                    starts_at=timezone.now(),
                    check_in_due_at=timezone.now() + timedelta(hours=2),
                    venue_label=f"Cafe {i}",
                    status="safe",
                )
                for i in range(105)
            ]
        )
        ids, cursor = [], None
        while True:
            response = self.client.get(
                self.base + "dates/", {"paged": "1", **({"cursor": cursor} if cursor else {})}
            )
            self.assertEqual(response.status_code, 200)
            ids.extend(row["id"] for row in response.data["items"])
            cursor = response.data["next_cursor"]
            if not cursor:
                break
        self.assertEqual(len(set(ids)), 105)
        first = self.client.get(self.base + "dates/", {"paged": "1"})
        self.client.force_authenticate(self.stranger)
        other = self.client.get(
            self.base + "dates/", {"paged": "1", "cursor": first.data["next_cursor"]}
        )
        self.assertEqual(other.status_code, 400)

    def test_cache_outage_does_not_prevent_a_durable_panic(self):
        self.plan()
        with patch(
            "rest_framework.throttling.SimpleRateThrottle.cache.get",
            side_effect=RedisConnectionError(),
        ):
            response = self.client.post(
                self.base + "panic/", {}, format="json", HTTP_IDEMPOTENCY_KEY="cache-outage"
            )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(PanicAlert.objects.count(), 1)
