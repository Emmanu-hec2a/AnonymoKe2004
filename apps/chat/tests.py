import uuid
from io import BytesIO
from unittest.mock import patch

from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.compliance.models import ConsentRecord
from apps.compliance.services import _media_keys_for_user
from apps.matching.models import Match
from apps.profiles.models import Profile
from apps.safety.models import Block

from .activity import peer_activity, update_activity
from .media import attachment_data, process_chat_attachment, sanitize_image
from .models import ChatAttachment, Message
from .services import mark_delivered, mark_read, moderate_message, send_message


def members():
    profiles = []
    for alias in ("Quiet Comet", "Velvet Echo", "Other Orbit"):
        user = User.objects.create_user(email=alias.replace(" ", "").lower() + "@example.test")
        profile = Profile.objects.create(
            user=user, alias=alias, age_years=27, gender="NB", verification_level="verified"
        )
        for kind in ("sensitive_data", "voice"):
            ConsentRecord.objects.create(user=user, consent_type=kind, granted=True, version="test")
        profiles.append(profile)
    return profiles


@override_settings(CHANNEL_LAYERS={"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}})
class ConversationTests(TestCase):
    def setUp(self):
        self.me, self.other, self.outsider = members()
        self.match = Match.objects.create(profile_a=self.me, profile_b=self.other)
        self.client = APIClient()
        self.client.force_authenticate(self.me.user)
        self.url = f"/api/v1/matches/{self.match.pk}"
        self.enterContext(patch("apps.safety.tasks.scan_content.delay"))
        self.enterContext(patch("apps.notifications.service.enqueue_user_event"))

    def message(self, **values):
        return Message.objects.create(
            match=self.match, sender=self.other, body="Hello", moderation_status="clear", **values
        )

    def asset(self, kind="audio", status="ready"):
        return ChatAttachment.objects.create(
            match=self.match,
            sender=self.me,
            kind=kind,
            content_type="audio/mp4" if kind == "audio" else "image/jpeg",
            size_bytes=10,
            incoming_key=f"chat/incoming/{uuid.uuid4()}",
            object_key=f"chat/processed/{uuid.uuid4()}",
            status=status,
        )

    def test_delivery_and_read_are_distinct_and_idempotent(self):
        message = self.message()
        self.assertEqual(mark_delivered(self.me, self.match.pk, [message.pk]), 1)
        message.refresh_from_db()
        first = message.delivered_at
        self.assertIsNone(message.read_at)
        self.assertEqual(mark_delivered(self.me, self.match.pk, [message.pk]), 0)
        mark_read(self.me, self.match.pk, message.pk)
        message.refresh_from_db()
        self.assertEqual(message.delivered_at, first)
        self.assertIsNotNone(message.read_at)

    def test_receipts_reject_other_matches_and_sender_acknowledgements(self):
        foreign = Match.objects.create(profile_a=self.me, profile_b=self.outsider)
        message = Message.objects.create(
            match=foreign, sender=self.outsider, body="private", moderation_status="clear"
        )
        with self.assertRaisesMessage(ValueError, "message_not_found"):
            mark_delivered(self.me, self.match.pk, [message.pk])
        with self.assertRaisesMessage(ValueError, "message_not_found"):
            mark_delivered(self.outsider, foreign.pk, [message.pk])

    def test_reply_is_match_scoped_and_moderation_safe(self):
        target = self.message()
        reply = send_message(self.me, self.match.pk, "Hello back", uuid.uuid4(), target.pk).message
        self.assertEqual(reply.reply_to_id, target.pk)
        target.moderation_status = "blocked"
        target.save(update_fields=["moderation_status"])
        timeline = self.client.get(self.url + "/messages/?paged=1").json()["items"]
        rendered_reply = next(item for item in timeline if item["message_id"] == str(reply.pk))
        self.assertEqual(rendered_reply["reply_to"]["body"], "Message unavailable")
        with self.assertRaisesMessage(ValueError, "reply_message_unavailable"):
            send_message(self.me, self.match.pk, "Again", uuid.uuid4(), target.pk)

    def test_reply_to_another_match_is_rejected(self):
        foreign = Match.objects.create(profile_a=self.me, profile_b=self.outsider)
        target = Message.objects.create(
            match=foreign, sender=self.outsider, body="Secret", moderation_status="clear"
        )
        with self.assertRaisesMessage(ValueError, "reply_message_unavailable"):
            send_message(self.me, self.match.pk, "Hi", uuid.uuid4(), target.pk)

    def test_retry_identity_includes_reply_and_attachment(self):
        first, second = self.message(), self.message()
        client_id = uuid.uuid4()
        original = send_message(self.me, self.match.pk, "Hi", client_id, first.pk).message
        self.assertEqual(
            send_message(self.me, self.match.pk, "Hi", client_id, first.pk).message.pk, original.pk
        )
        with self.assertRaisesMessage(ValueError, "client_message_id_conflict"):
            send_message(self.me, self.match.pk, "Hi", client_id, second.pk)

    def test_presence_is_conversation_scoped_and_supports_multiple_devices(self):
        update_activity(self.me, self.match.pk, "one", active=True, typing=True)
        update_activity(self.me, self.match.pk, "two", active=True, typing=False)
        self.assertTrue(peer_activity(self.other, self.match.pk)["typing"])
        update_activity(self.me, self.match.pk, "one", active=False, typing=False)
        self.assertTrue(peer_activity(self.other, self.match.pk)["active"])
        self.assertFalse(peer_activity(self.other, self.match.pk)["typing"])
        with self.assertRaises(ValueError):
            peer_activity(self.outsider, self.match.pk)

    def test_typing_and_presence_expire_without_last_seen_history(self):
        with patch("apps.chat.activity.time.time", return_value=1000):
            update_activity(self.me, self.match.pk, "one", active=True, typing=True)
        with patch("apps.chat.activity.time.time", return_value=1007):
            self.assertFalse(peer_activity(self.other, self.match.pk)["typing"])
            self.assertTrue(peer_activity(self.other, self.match.pk)["active"])
        with patch("apps.chat.activity.time.time", return_value=1046):
            self.assertFalse(peer_activity(self.other, self.match.pk)["active"])

    @patch("apps.chat.media_views.R2MediaStore")
    def test_photo_upload_is_locked_before_mutual_reveal(self, store):
        response = self.client.post(
            self.url + "/attachments/upload-url/",
            {"kind": "image", "content_type": "image/jpeg", "size_bytes": 100},
            format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(ChatAttachment.objects.count(), 0)
        store.assert_not_called()

    @patch("apps.chat.media_views.R2MediaStore")
    def test_voice_upload_before_reveal_requires_consent_and_disguise(self, store):
        store.return_value.presign_upload.return_value = "https://storage.test/upload"
        response = self.client.post(
            self.url + "/attachments/upload-url/",
            {"kind": "audio", "content_type": "audio/mp4", "size_bytes": 100},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertTrue(ChatAttachment.objects.get().disguise_voice)
        ConsentRecord.objects.filter(user=self.me.user, consent_type="voice").update(
            revoked_at=timezone.now()
        )
        self.assertEqual(
            self.client.post(
                self.url + "/attachments/upload-url/",
                {"kind": "audio", "content_type": "audio/mp4", "size_bytes": 100},
                format="json",
            ).status_code,
            403,
        )

    @patch("apps.chat.media.R2MediaStore")
    def test_shared_media_is_private_and_revoked_on_block(self, store):
        store.return_value.presign_private.return_value = "https://storage.test/private-signed"
        asset = self.asset()
        message = send_message(
            self.me, self.match.pk, "", uuid.uuid4(), attachment_id=asset.pk
        ).message
        moderate_message(message.pk)
        self.assertEqual(
            attachment_data(asset, self.other)["url"], "https://storage.test/private-signed"
        )
        store.return_value.presign_private.assert_called_with(asset.object_key, ttl_seconds=60)
        Block.objects.create(blocker=self.other, blocked=self.me)
        with self.assertRaises(ValueError):
            attachment_data(asset, self.other)

    @patch("apps.chat.media.R2MediaStore")
    def test_revoked_voice_consent_hides_media_and_held_messages_do_not_leak_urls(self, store):
        asset = self.asset()
        message = send_message(
            self.me, self.match.pk, "", uuid.uuid4(), attachment_id=asset.pk
        ).message
        with self.assertRaises(ValueError):
            attachment_data(asset, self.other)
        moderate_message(message.pk)
        ConsentRecord.objects.filter(user=self.me.user, consent_type="voice").update(
            revoked_at=timezone.now()
        )
        with self.assertRaisesMessage(ValueError, "voice_consent_required"):
            attachment_data(asset, self.other)
        store.return_value.presign_private.assert_not_called()

    @patch("apps.chat.media.process_audio", return_value=(b"clean audio", 1250))
    @patch("apps.chat.media.R2MediaStore")
    def test_voice_processing_uses_disguise_and_ready_message_is_released(self, store, transcode):
        store.return_value.download.return_value = b"source"
        asset = self.asset(status="processing")
        message = send_message(
            self.me, self.match.pk, "", uuid.uuid4(), attachment_id=asset.pk
        ).message
        process_chat_attachment(str(asset.pk))
        asset.refresh_from_db()
        message.refresh_from_db()
        self.assertEqual(asset.status, "ready")
        self.assertEqual(message.moderation_status, "clear")
        self.assertTrue(transcode.call_args.args[0].disguise_voice)
        self.assertEqual(transcode.call_args.kwargs["max_duration_ms"], 60000)
        self.assertIn(asset.incoming_key, _media_keys_for_user(self.me.user))
        self.assertIn(asset.object_key, _media_keys_for_user(self.me.user))

    def test_image_processing_strips_metadata_and_rejects_animation(self):
        output = BytesIO()
        exif = Image.Exif()
        exif[270] = "private GPS/name"
        Image.new("RGB", (2000, 1000), "teal").save(output, "JPEG", exif=exif)
        payload, width, height = sanitize_image(output.getvalue())
        self.assertEqual((width, height), (1600, 800))
        self.assertFalse(Image.open(BytesIO(payload)).getexif())
        with self.assertRaises(ValueError):
            sanitize_image(b"not an image")

    def test_attachment_cannot_be_reused_by_a_second_message(self):
        asset = self.asset()
        send_message(self.me, self.match.pk, "", uuid.uuid4(), attachment_id=asset.pk)
        with self.assertRaisesMessage(ValueError, "attachment_unavailable"):
            send_message(self.me, self.match.pk, "", uuid.uuid4(), attachment_id=asset.pk)


@override_settings(CHANNEL_LAYERS={"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}})
class RealtimeTests(TransactionTestCase):
    def test_header_auth_typing_and_disconnect_presence(self):
        from asgiref.sync import async_to_sync
        from channels.testing import WebsocketCommunicator

        from apps.accounts.authentication import AuthenticationService
        from config.asgi import application

        me, other, outsider = members()
        match = Match.objects.create(profile_a=me, profile_b=other)
        tokens = [
            AuthenticationService.issue_session(profile.user).access_token
            for profile in (me, other, outsider)
        ]

        async def scenario():
            url = f"/ws/v1/matches/{match.pk}/"
            a = WebsocketCommunicator(
                application, url, headers=[(b"authorization", f"Bearer {tokens[0]}".encode())]
            )
            b = WebsocketCommunicator(
                application, url, headers=[(b"authorization", f"Bearer {tokens[1]}".encode())]
            )
            stranger = WebsocketCommunicator(
                application, url, headers=[(b"authorization", f"Bearer {tokens[2]}".encode())]
            )
            self.assertTrue((await a.connect())[0])
            self.assertTrue((await b.connect())[0])
            self.assertFalse((await stranger.connect())[0])
            await a.send_json_to({"type": "activity", "active": True, "typing": True})
            found = False
            for _ in range(8):
                event = await b.receive_json_from(timeout=2)
                if event.get("typing"):
                    self.assertNotIn("body", event)
                    found = True
                    break
            self.assertTrue(found)
            await a.disconnect()
            await b.disconnect()
            await stranger.disconnect()

        async_to_sync(scenario)()
