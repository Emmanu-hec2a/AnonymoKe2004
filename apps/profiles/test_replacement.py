from unittest.mock import patch

from django.test import TestCase

from . import tests as fixtures
from .media import MediaRejected
from .models import MediaAsset, PrivateIdentity
from .tasks_media import process_media_asset


class PhotoReplacementTests(TestCase):
    setUp = fixtures.ProfileIntegrationTests.setUp
    asset = fixtures.ProfileIntegrationTests.asset

    @patch("apps.profiles.tasks_media.R2MediaStore")
    @patch("apps.profiles.tasks_media.process_avatar")
    def test_rejected_photo_does_not_poison_a_valid_replacement(self, process, storage):
        process.side_effect = [
            MediaRejected("exactly_one_face_required"),
            (b"new-original", b"new-blur"),
        ]
        bad = self.asset()
        self.assertEqual(process_media_asset(str(bad.pk)), "rejected")
        replacement = self.asset()
        self.assertEqual(process_media_asset(str(replacement.pk)), "ready")
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.blurred_avatar_key, f"media/derived/{replacement.pk}.jpg")
        self.assertEqual(
            PrivateIdentity.objects.get(user=self.user).real_avatar_key,
            f"media/original/{replacement.pk}.jpg",
        )
        self.assertEqual(MediaAsset.objects.get(pk=bad.pk).status, "rejected")
        response = self.client.patch(
            self.base + "profile/",
            {"onboarding_photo_upload_id": str(replacement.pk)},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)

    @patch("apps.profiles.views.R2MediaStore")
    def test_transport_validation_rejection_returns_a_useful_error_code(self, storage):
        bad = self.asset(status="pending")
        storage.return_value.head.return_value = {"ContentLength": 20, "ContentType": "image/gif"}
        response = self.client.post(
            self.base + "media/complete/", {"upload_id": str(bad.pk)}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"]["code"], "media_content_type_invalid")
