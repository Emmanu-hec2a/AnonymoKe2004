import uuid
from datetime import timedelta
from unittest.mock import patch

from django.contrib.gis.geos import Point
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.chat.models import Message
from apps.chat.services import mark_read, moderate_message, send_message
from apps.chat.tasks import retry_pending_moderation
from apps.compliance.models import ConsentRecord
from apps.core.cursors import decode_cursor, encode_cursor
from apps.profiles.models import MatchingPreference, Profile
from apps.safety.services import block_profile
from apps.store.models import Entitlement, Product, Purchase

from .inbox import inbox_queryset, match_summary
from .models import Match, Swipe
from .services import (
    close_match,
    participant_match,
    request_unmask,
    respond_unmask,
    revealed_identity,
    withdraw_unmask,
)


@override_settings(REQUIRE_VERIFICATION_PRE_DISCOVERY=False, REQUIRE_VERIFICATION_PRE_UNMASK=True)
class MatchesIntegrationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.me = self.profile("me")
        self.other = self.profile("other")
        self.match = Match.objects.create(profile_a=self.me, profile_b=self.other)
        self.client = APIClient()
        self.client.force_authenticate(user=self.me.user)
        self.url = f"/api/v1/matches/{self.match.pk}"

    def profile(self, name):
        user = User.objects.create_user(email=f"{name}@example.test")
        profile = Profile.objects.create(
            user=user,
            alias=name,
            age_years=27,
            gender="NB",
            verification_level="verified",
            cell=Point(36.82, -1.28, srid=4326),
            cell_updated_at=timezone.now(),
            min_age_pref=18,
            max_age_pref=40,
            max_distance_km=15,
        )
        MatchingPreference.objects.create(profile=profile, target_genders=["ALL"])
        for kind in ("location", "sensitive_data"):
            ConsentRecord.objects.create(user=user, consent_type=kind, version="test", granted=True)
        return profile

    def message(self, body="Hello there", status="clear", sender=None):
        return Message.objects.create(
            match=self.match, sender=sender or self.other, body=body, moderation_status=status
        )

    def test_inbox_real_preview_unread_and_reveal_status(self):
        self.message()
        self.message(body="Held text", status="flagged")
        request_unmask(self.other, self.match.pk)
        response = self.client.get("/api/v1/matches/?paged=1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["total_count"], 1)
        self.assertEqual(response.data["unread_count"], 1)
        item = response.data["items"][0]
        self.assertEqual(item["last_message"], "Hello there")
        self.assertEqual(item["reveal_status"], "incoming")
        self.assertNotIn("real_avatar_url", item)
        self.assertEqual(item["viewer_profile_id"], str(self.me.public_id))

    def test_own_pending_message_is_visible_only_to_sender(self):
        own = self.message(status="queued", sender=self.me)
        self.message(body="Hidden from me", status="flagged")
        response = self.client.get(f"{self.url}/messages/?paged=1")
        self.assertEqual([item["message_id"] for item in response.data["items"]], [str(own.pk)])
        summary = match_summary(inbox_queryset(self.me).get(), self.me)
        self.assertNotIn("Hidden from me", summary["last_message"])

    def test_retry_creates_one_message_and_rejects_changed_body(self):
        client_id = uuid.uuid4()
        first = send_message(self.me, self.match.pk, "A kind hello", client_id).message
        second = send_message(self.me, self.match.pk, "A kind hello", client_id).message
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(Message.objects.count(), 1)
        with self.assertRaisesMessage(ValueError, "client_message_id_conflict"):
            send_message(self.me, self.match.pk, "Different", client_id)

    def test_contact_details_are_rejected_before_mutual_reveal(self):
        with self.assertRaisesMessage(ValueError, "contact_exchange_not_allowed"):
            send_message(self.me, self.match.pk, "WhatsApp me on 0712345678", uuid.uuid4())
        self.assertFalse(Message.objects.exists())

    @patch("apps.chat.services.publish_approved_message")
    def test_moderation_publishes_clear_message_once(self, publish):
        message = self.message(status="queued")
        moderate_message(message.pk)
        moderate_message(message.pk)
        message.refresh_from_db()
        self.assertEqual(message.moderation_status, "clear")
        publish.assert_called_once()

    @patch("apps.chat.services.publish_approved_message")
    def test_flagged_message_is_held_and_never_published(self, publish):
        message = self.message(body="Send mpesa fare", status="queued")
        moderate_message(message.pk)
        message.refresh_from_db()
        self.assertEqual(message.moderation_status, "flagged")
        publish.assert_not_called()
        response = self.client.get(f"{self.url}/messages/?paged=1")
        self.assertEqual(response.data["items"], [])

    @patch("apps.safety.tasks.scan_content.delay")
    def test_pending_moderation_is_requeued_after_queue_outage(self, enqueue):
        message = self.message(status="queued")
        self.assertEqual(retry_pending_moderation(), 1)
        enqueue.assert_called_once_with(str(self.other.user_id), "message", str(message.pk), "")
        message.refresh_from_db()
        self.assertIsNotNone(message.moderation_queued_at)
        self.assertEqual(retry_pending_moderation(), 0)

    def test_read_anchor_leaves_later_messages_unread(self):
        first = self.message()
        later = self.message()
        self.assertEqual(mark_read(self.me, self.match.pk, first.pk), 1)
        later.refresh_from_db()
        self.assertIsNone(later.read_at)
        self.assertEqual(self.client.get("/api/v1/matches/?paged=1").data["unread_count"], 1)

    def test_message_pagination_handles_identical_timestamps(self):
        messages = [self.message() for _ in range(55)]
        Message.objects.update(created_at=timezone.now())
        first = self.client.get(f"{self.url}/messages/?paged=1")
        second = self.client.get(
            f"{self.url}/messages/", {"paged": "1", "cursor": first.data["next_cursor"]}
        )
        ids = [item["message_id"] for item in first.data["items"] + second.data["items"]]
        self.assertEqual(set(ids), {str(message.pk) for message in messages})
        self.assertEqual(len(ids), 55)
        self.assertIsNone(second.data["next_cursor"])

    def test_signed_cursors_are_scoped_and_tamper_resistant(self):
        token = encode_cursor(timezone.now(), uuid.uuid4(), "scope-a")
        self.assertIsNotNone(decode_cursor(token, "scope-a"))
        for raw, salt in [(token, "scope-b"), (token + "tampered", "scope-a")]:
            with self.assertRaisesMessage(ValueError, "cursor_invalid"):
                decode_cursor(raw, salt)

    def test_outsider_cannot_access_match_chat_or_identity(self):
        self.client.force_authenticate(user=self.profile("outsider").user)
        self.assertEqual(self.client.get(f"{self.url}/").status_code, 404)
        self.assertEqual(self.client.get(f"{self.url}/messages/?paged=1").status_code, 404)
        self.assertEqual(self.client.get(f"{self.url}/revealed/").status_code, 403)

    def test_closed_match_disappears_and_all_access_is_denied(self):
        close_match(self.me, self.match.pk)
        close_match(self.me, self.match.pk)
        self.assertEqual(self.client.get("/api/v1/matches/?paged=1").data["total_count"], 0)
        self.assertEqual(self.client.get(f"{self.url}/messages/?paged=1").status_code, 404)
        with self.assertRaisesMessage(ValueError, "match_not_found"):
            send_message(self.other, self.match.pk, "Hello", uuid.uuid4())

    def test_block_closes_match_and_revokes_reveal(self):
        request_unmask(self.me, self.match.pk)
        respond_unmask(self.other, self.match.pk, True)
        block_profile(blocker=self.other, blocked=self.me)
        with self.assertRaisesMessage(ValueError, "match_not_found"):
            revealed_identity(self.me, self.match.pk)
        self.assertFalse(inbox_queryset(self.me).exists())

    def test_suspended_participant_cannot_be_accessed(self):
        self.other.user.status = "suspended"
        self.other.user.save()
        with self.assertRaisesMessage(ValueError, "match_not_found"):
            participant_match(self.me, self.match.pk)

    def test_self_accept_is_rejected_and_repeat_request_is_idempotent(self):
        request_unmask(self.me, self.match.pk)
        self.match.refresh_from_db()
        original = self.match.a_unmask_consent_at
        request_unmask(self.me, self.match.pk)
        self.match.refresh_from_db()
        self.assertEqual(original, self.match.a_unmask_consent_at)
        with self.assertRaisesMessage(ValueError, "cannot_respond_to_own_reveal"):
            respond_unmask(self.me, self.match.pk, True)

    def test_mutual_consent_and_both_verifications_are_required(self):
        request_unmask(self.me, self.match.pk)
        self.other.verification_level = "none"
        self.other.save()
        with self.assertRaisesMessage(ValueError, "verification_required_before_unmask"):
            respond_unmask(self.other, self.match.pk, True)
        self.other.verification_level = "verified"
        self.other.save()
        self.assertEqual(respond_unmask(self.other, self.match.pk, True).state, "unmasked")
        self.assertIsNotNone(revealed_identity(self.me, self.match.pk)["profile"])

    def test_revoked_sensitive_consent_denies_revealed_identity(self):
        request_unmask(self.me, self.match.pk)
        respond_unmask(self.other, self.match.pk, True)
        ConsentRecord.objects.filter(user=self.other.user, consent_type="sensitive_data").update(
            revoked_at=timezone.now()
        )
        with self.assertRaisesMessage(ValueError, "sensitive_data_consent_required"):
            revealed_identity(self.me, self.match.pk)

    def test_decline_enforces_cooldown_and_withdraw_clears_request(self):
        request_unmask(self.me, self.match.pk)
        respond_unmask(self.other, self.match.pk, False)
        with self.assertRaisesMessage(ValueError, "unmask_cooldown"):
            request_unmask(self.me, self.match.pk)
        Match.objects.filter(pk=self.match.pk).update(
            a_unmask_declined_at=timezone.now() - timedelta(hours=25)
        )
        request_unmask(self.me, self.match.pk)
        withdraw_unmask(self.me, self.match.pk)
        self.match.refresh_from_db()
        self.assertIsNone(self.match.a_unmask_consent_at)

    def test_likes_count_does_not_expose_identities_without_premium(self):
        # An incoming like is not a match until the recipient likes back.
        liker = self.profile("liker")
        Swipe.objects.create(
            from_profile=liker, to_profile=self.me, action="like", client_swipe_id=uuid.uuid4()
        )
        response = self.client.get("/api/v1/likes/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertFalse(response.data["can_view"])
        self.assertEqual(response.data["items"], [])
        product = Product.objects.create(
            code="test-premium", name="Premium", price_kes=150, kind="premium"
        )
        purchase = Purchase.objects.create(
            user=self.me.user,
            product=product,
            amount_kes=150,
            phone_hash="0" * 64,
            idempotency_key=str(uuid.uuid4()),
            status="completed",
        )
        Entitlement.objects.create(
            user=self.me.user,
            kind="premium",
            quantity=1,
            source_purchase=purchase,
            expires_at=timezone.now() + timedelta(days=7),
        )
        response = self.client.get("/api/v1/likes/")
        self.assertEqual(response.data["items"][0]["profile_id"], str(liker.public_id))
        self.assertNotIn("real_avatar_url", response.data["items"][0])

    @patch("apps.chat.services.publish_approved_message")
    def test_only_staff_can_review_messages_and_approval_is_idempotent(self, publish):
        message = self.message(status="flagged")
        url = f"/api/v1/admin/moderation/messages/{message.pk}/"
        self.assertEqual(self.client.get(url).status_code, 403)
        self.me.user.is_staff = True
        self.me.user.role = "moderator"
        self.me.user.save()
        self.assertEqual(self.client.get(url).status_code, 200)
        payload = {"action": "approve", "reason": "Reviewed in context; no solicitation"}
        self.assertEqual(self.client.post(url, payload, format="json").status_code, 200)
        self.assertEqual(self.client.post(url, payload, format="json").status_code, 200)
        publish.assert_called_once()
        message.refresh_from_db()
        self.assertEqual(message.moderation_status, "clear")

    def test_queued_message_becomes_undeliverable_after_unmatch(self):
        message = self.message(status="queued")
        close_match(self.me, self.match.pk)
        moderate_message(message.pk)
        message.refresh_from_db()
        self.assertEqual(message.moderation_status, "blocked")

    @patch("apps.notifications.service._firebase_app")
    def test_stale_chat_push_is_discarded_after_unmatch(self, firebase):
        from apps.notifications.service import send_user_event

        close_match(self.me, self.match.pk)
        send_user_event(
            user_id=self.other.user_id, event_type="chat.message", match_id=self.match.pk
        )
        firebase.assert_not_called()
