from datetime import UTC, date, datetime, timedelta
from unittest.mock import Mock, patch

from django.core.cache import cache
from django.db import IntegrityError
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.compliance.models import ConsentRecord
from apps.compliance.services import (
    R2ObjectStorageDeletionAdapter,
    _media_keys_for_user,
    purge_user_data,
)
from apps.core.crypto import decrypt_text

from .models import MatchingPreference, MediaAsset, PrivateIdentity, Profile
from .storage import MediaPayloadTooLarge
from .tasks_media import process_media_asset, recover_media_processing, refresh_avatar_preview


class ProfileIntegrationTests(TestCase):
    def setUp(self):
        self.enterContext(
            patch("apps.profiles.tasks_media.avatar_thumbnail", return_value=b"thumbnail")
        )
        cache.clear()
        self.user = User.objects.create_user(email="profile@example.test")
        self.profile = Profile.objects.create(
            user=self.user, alias="Quiet Comet", gender="NB", age_years=27
        )
        MatchingPreference.objects.create(profile=self.profile, target_genders=["ALL"])
        for kind in ["location", "sensitive_data", "voice", "terms", "privacy"]:
            ConsentRecord.objects.create(
                user=self.user, consent_type=kind, granted=True, version="test"
            )
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.base = "/api/v1/me/"

    def asset(self, kind="avatar", status="processing", **kwargs):
        return MediaAsset.objects.create(
            user=self.user,
            kind=kind,
            status=status,
            content_type="image/jpeg" if kind == "avatar" else "audio/mp4",
            size_bytes=100,
            incoming_key=f"incoming/{MediaAsset.objects.count()}",
            **kwargs,
        )

    def ready_photo(self):
        asset = self.asset(
            status="ready", original_key="private-photo.jpg", derived_key="blurred-photo.jpg"
        )
        PrivateIdentity.objects.update_or_create(
            user=self.user, defaults={"real_avatar_key": asset.original_key}
        )
        self.profile.blurred_avatar_key = asset.derived_key
        self.profile.save(update_fields=["blurred_avatar_key"])
        return asset

    def test_profile_fields_alone_do_not_mark_an_account_onboarded_without_a_photo(self):
        response = self.client.patch(
            self.base + "profile/", {"alias": "Custom alias"}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_onboarded)

    def test_final_photo_receipt_is_owner_scoped_ready_active_and_write_only(self):
        asset = self.ready_photo()
        response = self.client.patch(
            self.base + "profile/", {"onboarding_photo_upload_id": str(asset.pk)}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("onboarding_photo_upload_id", response.data)
        self.assertNotIn("original_key", response.data)
        self.assertNotIn("derived_key", response.data)
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_onboarded)

    def test_final_save_requires_every_required_consent_and_remains_atomic(self):
        asset = self.ready_photo()
        for kind in ("terms", "privacy", "location", "sensitive_data"):
            with self.subTest(kind=kind):
                self.client.post(
                    self.base + "consents/",
                    {"type": kind, "version": "test", "granted": False},
                    format="json",
                )
                response = self.client.patch(
                    self.base + "profile/",
                    {"alias": "Must not save", "onboarding_photo_upload_id": str(asset.pk)},
                    format="json",
                )
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.data["error"]["code"], f"{kind}_consent_required")
                self.profile.refresh_from_db()
                self.user.refresh_from_db()
                self.assertEqual(self.profile.alias, "Quiet Comet")
                self.assertFalse(self.user.is_onboarded)
                self.client.post(
                    self.base + "consents/",
                    {"type": kind, "version": "test", "granted": True},
                    format="json",
                )

    def test_an_ordinary_profile_patch_cannot_bypass_missing_terms(self):
        self.ready_photo()
        self.client.post(
            self.base + "consents/",
            {"type": "terms", "version": "test", "granted": False},
            format="json",
        )
        self.assertEqual(
            self.client.patch(self.base + "profile/", {"alias": "Updated alias"}).status_code,
            200,
        )
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_onboarded)

    def test_empty_matching_preferences_do_not_complete_onboarding(self):
        self.ready_photo()
        MatchingPreference.objects.filter(profile=self.profile).update(target_genders=[])
        self.assertEqual(
            self.client.patch(self.base + "profile/", {"alias": "Updated alias"}).status_code,
            200,
        )
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_onboarded)
        self.assertEqual(
            self.client.patch(
                self.base + "profile/", {"target_genders": ["NB"]}, format="json"
            ).status_code,
            200,
        )
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_onboarded)

    def test_identical_consent_retries_do_not_duplicate_grants_and_responses_never_cache(self):
        for granted in (True, False):
            payload = {"type": "voice", "version": "onboarding-test", "granted": granted}
            first = self.client.post(self.base + "consents/", payload, format="json")
            count = ConsentRecord.objects.filter(user=self.user, consent_type="voice").count()
            again = self.client.post(self.base + "consents/", payload, format="json")
            self.assertEqual(first.status_code, 201)
            self.assertEqual(first.data, again.data)
            self.assertEqual(first["Cache-Control"], "no-store")
            self.assertEqual(again["Cache-Control"], "no-store")
            self.assertEqual(
                ConsentRecord.objects.filter(user=self.user, consent_type="voice").count(), count
            )
        response = self.client.get(self.base + "consents/")
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertFalse(next(c for c in response.data if c["type"] == "voice")["granted"])

    def test_a_different_consent_version_is_recorded_as_a_new_decision(self):
        count = ConsentRecord.objects.filter(user=self.user, consent_type="terms").count()
        self.client.post(
            self.base + "consents/",
            {"type": "terms", "version": "new-version", "granted": True},
            format="json",
        )
        self.assertEqual(
            ConsentRecord.objects.filter(user=self.user, consent_type="terms").count(), count + 1
        )
        self.assertEqual(
            ConsentRecord.objects.filter(user=self.user, consent_type="terms", revoked_at=None)
            .get()
            .version,
            "new-version",
        )

    def test_photo_receipts_reject_unready_wrong_kind_and_another_accounts_upload(self):
        assets = [self.asset(status=status) for status in ["pending", "processing", "rejected"]]
        assets.append(self.asset(kind="audio", status="ready"))
        foreign = self.asset(status="ready")
        foreign.user = User.objects.create_user(email="photo-owner@example.test")
        foreign.save(update_fields=["user"])
        assets.append(foreign)
        for asset in assets:
            with self.subTest(status=asset.status, kind=asset.kind):
                response = self.client.patch(
                    self.base + "profile/",
                    {"alias": "Changed alias", "onboarding_photo_upload_id": str(asset.pk)},
                    format="json",
                )
                self.assertEqual(response.status_code, 400)
                self.profile.refresh_from_db()
                self.assertEqual(self.profile.alias, "Quiet Comet")

    def test_a_stale_ready_photo_receipt_cannot_finalize_a_newer_photo(self):
        old = self.ready_photo()
        newer = self.asset(
            status="ready", original_key="new-private.jpg", derived_key="new-blur.jpg"
        )
        PrivateIdentity.objects.filter(user=self.user).update(real_avatar_key=newer.original_key)
        self.profile.blurred_avatar_key = newer.derived_key
        self.profile.save(update_fields=["blurred_avatar_key"])
        response = self.client.patch(
            self.base + "profile/", {"onboarding_photo_upload_id": str(old.pk)}, format="json"
        )
        self.assertEqual(response.status_code, 400)

    def test_specific_media_status_returns_only_owned_metadata_and_never_caches(self):
        asset = self.ready_photo()
        response = self.client.get(self.base + f"media/status/{asset.pk}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(str(response.data["upload_id"]), str(asset.pk))
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertNotIn("original_key", response.data)
        self.client.force_authenticate(
            User.objects.create_user(email="unrelated-photo-owner@example.test")
        )
        self.assertEqual(self.client.get(self.base + f"media/status/{asset.pk}/").status_code, 404)

    @patch("apps.profiles.views.R2MediaStore")
    def test_avatar_upload_requires_privacy_and_sensitive_data_consent(self, store):
        for kind in ["privacy", "sensitive_data"]:
            with self.subTest(kind=kind):
                ConsentRecord.objects.filter(user=self.user, consent_type=kind).update(
                    revoked_at=timezone.now()
                )
                response = self.client.post(
                    self.base + "media/upload-url/",
                    {"kind": "avatar", "content_type": "image/png", "size_bytes": 100},
                    format="json",
                )
                self.assertEqual(response.status_code, 403)
                ConsentRecord.objects.filter(user=self.user, consent_type=kind).update(
                    revoked_at=None
                )
        store.assert_not_called()
        self.assertFalse(MediaAsset.objects.exists())

    @patch("apps.profiles.tasks_media.process_avatar", return_value=(b"original", b"blurred"))
    @patch("apps.profiles.tasks_media.R2MediaStore")
    def test_photo_consent_revoked_before_publication_prevents_storage_writes(self, store, process):
        asset = self.asset()
        ConsentRecord.objects.filter(user=self.user, consent_type="privacy").update(
            revoked_at=timezone.now()
        )
        self.assertEqual(process_media_asset(str(asset.pk)), "rejected")
        store.return_value.upload_private.assert_not_called()
        store.return_value.upload_derived.assert_not_called()
        asset.refresh_from_db()
        self.assertEqual(asset.rejection_code, "privacy_consent_required")

    @patch("apps.profiles.tasks_media.R2MediaStore")
    def test_object_replacement_beyond_the_byte_limit_is_rejected_without_decoder_or_retry(
        self, store
    ):
        asset = self.asset()
        store.return_value.download.side_effect = MediaPayloadTooLarge("media_size_invalid")
        self.assertEqual(process_media_asset(str(asset.pk)), "rejected")
        asset.refresh_from_db()
        self.assertEqual(asset.rejection_code, "media_size_invalid")
        store.return_value.upload_private.assert_not_called()

    def test_birth_date_requires_matching_consent_before_storage(self):
        self.client.post(
            self.base + "consents/",
            {"type": "sensitive_data", "granted": False, "version": "test"},
            format="json",
        )
        before = bytes(self.profile.birth_date_ciphertext)
        response = self.client.patch(
            self.base + "profile/", {"birth_date": "1999-03-14"}, format="json"
        )
        self.assertEqual(response.status_code, 403)
        self.profile.refresh_from_db()
        self.assertEqual(bytes(self.profile.birth_date_ciphertext), before)

    @patch("apps.profiles.serializers.timezone")
    def test_birth_date_uses_kenya_birthday_and_is_encrypted_and_write_only(self, clock):
        # Already 15 November in Kenya, still 14 November in UTC.
        # Freeze only the DOB clock; consent timestamps still use the real clock.
        moment = datetime(2026, 11, 14, 21, 30, tzinfo=UTC)
        clock.localdate.side_effect = lambda *, timezone: moment.astimezone(timezone).date()
        response = self.client.patch(
            self.base + "profile/",
            {"alias": "My own alias", "birth_date": "2008-11-15", "height_cm": None},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["age_years"], 18)
        self.assertNotIn("birth_date", response.data)
        self.assertNotIn("birth_date_ciphertext", response.data)
        self.profile.refresh_from_db()
        self.assertEqual(decrypt_text(bytes(self.profile.birth_date_ciphertext)), "2008-11-15")
        self.assertNotEqual(bytes(self.profile.birth_date_ciphertext), b"2008-11-15")
        self.assertIsNone(self.profile.height_cm)
        owner = self.client.get(self.base + "profile/")
        self.assertNotIn("birth_date", owner.data)
        self.assertNotIn("birth_date_ciphertext", owner.data)

    @patch("apps.profiles.serializers.timezone.localdate", return_value=date(2026, 11, 15))
    def test_invalid_birth_dates_cannot_partially_change_the_profile(self, today):
        for birth_date in ["1999-02-31", "2008-11-16", "2027-01-01", "1925-11-15"]:
            with self.subTest(birth_date=birth_date):
                response = self.client.patch(
                    self.base + "profile/",
                    {"alias": "Changed alias", "birth_date": birth_date},
                    format="json",
                )
                self.assertEqual(response.status_code, 400)
                self.profile.refresh_from_db()
                self.assertEqual(self.profile.alias, "Quiet Comet")
                self.assertFalse(self.profile.birth_date_ciphertext)

    def test_alias_controls_and_invalid_height_cannot_partially_change_the_profile(self):
        for values in [
            {"alias": "a"},
            {"alias": "Too\nMany Lines"},
            {"alias": "Bad\x00Name"},
            {"alias": "a" * 41},
            {"alias": "Different alias", "height_cm": 99},
            {"alias": "Different alias", "height_cm": 251},
        ]:
            with self.subTest(values=values):
                response = self.client.patch(self.base + "profile/", values, format="json")
                self.assertEqual(response.status_code, 400)
                self.profile.refresh_from_db()
                self.assertEqual(self.profile.alias, "Quiet Comet")

    def test_optional_height_can_be_cleared(self):
        self.profile.height_cm = 168
        self.profile.save(update_fields=["height_cm"])
        response = self.client.patch(self.base + "profile/", {"height_cm": None}, format="json")
        self.assertEqual(response.status_code, 200)
        self.profile.refresh_from_db()
        self.assertIsNone(self.profile.height_cm)

    def test_preferences_are_updated_together_and_returned_to_the_owner(self):
        response = self.client.patch(
            self.base + "profile/",
            {
                "target_genders": ["W", "NB"],
                "min_age_pref": 24,
                "max_age_pref": 85,
                "max_distance_km": 9,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["target_genders"], ["W", "NB"])
        self.assertEqual(response.data["max_age_pref"], 85)
        self.assertEqual(
            MatchingPreference.objects.get(profile=self.profile).target_genders, ["W", "NB"]
        )

    def test_invalid_preferences_cannot_partially_update_the_profile(self):
        response = self.client.patch(
            self.base + "profile/",
            {"alias": "Different alias", "target_genders": ["ALL", "W"]},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.alias, "Quiet Comet")
        legacy = self.client.put(
            self.base + "preferences/", {"target_genders": ["ALL", "W"]}, format="json"
        )
        self.assertEqual(legacy.status_code, 400)

    def test_matching_preferences_are_saved_with_profile_at_full_age_and_distance_bounds(self):
        for targets, minimum, maximum, distance in [
            (["NB"], 18, 100, 1),
            (["W", "NB"], 45, 85, 50),
            (["ALL"], 100, 100, 15),
        ]:
            with self.subTest(targets=targets):
                response = self.client.patch(
                    self.base + "profile/",
                    {
                        "target_genders": targets,
                        "min_age_pref": minimum,
                        "max_age_pref": maximum,
                        "max_distance_km": distance,
                    },
                    format="json",
                )
                self.assertEqual(response.status_code, 200)
                saved = self.client.get(self.base + "profile/").data
                self.assertEqual(saved["target_genders"], targets)
                self.assertEqual(saved["min_age_pref"], minimum)
                self.assertEqual(saved["max_age_pref"], maximum)
                self.assertEqual(saved["max_distance_km"], distance)

    def test_invalid_matching_fields_do_not_change_profile_or_previous_preferences(self):
        for invalid in [
            {"target_genders": []},
            {"target_genders": ["M", "M"]},
            {"target_genders": ["unknown"]},
            {"target_genders": "M"},
            {"target_genders": [["M"]]},
            {"min_age_pref": 17},
            {"min_age_pref": 36, "max_age_pref": 35},
            {"max_age_pref": 101},
            {"max_distance_km": 0},
            {"max_distance_km": 51},
        ]:
            with self.subTest(invalid=invalid):
                response = self.client.patch(
                    self.base + "profile/", {"alias": "Changed alias", **invalid}, format="json"
                )
                self.assertEqual(response.status_code, 400)
                self.profile.refresh_from_db()
                self.assertEqual(self.profile.alias, "Quiet Comet")
                self.assertEqual(self.profile.min_age_pref, 18)
                self.assertEqual(self.profile.max_age_pref, 35)
                self.assertEqual(self.profile.max_distance_km, 15)
                self.assertEqual(
                    MatchingPreference.objects.get(profile=self.profile).target_genders, ["ALL"]
                )

    @patch("apps.profiles.serializers.MatchingPreference.objects.update_or_create")
    def test_matching_database_failure_rolls_back_the_whole_profile_save(self, update):
        update.side_effect = IntegrityError("test failure")
        self.client.raise_request_exception = False
        response = self.client.patch(
            self.base + "profile/",
            {"alias": "Changed alias", "target_genders": ["M"], "max_age_pref": 80},
            format="json",
        )
        self.assertEqual(response.status_code, 500)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.alias, "Quiet Comet")
        self.assertEqual(self.profile.max_age_pref, 35)
        self.assertEqual(
            MatchingPreference.objects.get(profile=self.profile).target_genders, ["ALL"]
        )

    def test_distance_change_requires_location_consent_without_changing_matching_preferences(self):
        self.client.post(
            self.base + "consents/",
            {"type": "location", "granted": False, "version": "test"},
            format="json",
        )
        response = self.client.patch(
            self.base + "profile/",
            {"target_genders": ["M"], "max_distance_km": 50, "max_age_pref": 80},
            format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            MatchingPreference.objects.get(profile=self.profile).target_genders, ["ALL"]
        )

    def test_withdrawn_matching_consent_prevents_preference_changes(self):
        self.client.post(
            self.base + "consents/",
            {"type": "sensitive_data", "granted": False, "version": "test"},
            format="json",
        )
        response = self.client.patch(
            self.base + "profile/", {"target_genders": ["W"], "min_age_pref": 25}, format="json"
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(MatchingPreference.objects.filter(profile=self.profile).exists())

    def test_pause_remains_available_after_matching_consent_is_withdrawn(self):
        self.client.post(
            self.base + "consents/",
            {"type": "sensitive_data", "granted": False, "version": "test"},
            format="json",
        )
        self.assertEqual(
            self.client.patch(
                self.base + "profile/", {"is_discoverable": False}, format="json"
            ).status_code,
            200,
        )
        self.profile.refresh_from_db()
        self.assertFalse(self.profile.is_discoverable)

    def test_interest_shape_and_duplicates_are_validated(self):
        for interests in [{"Tech": True}, ["a"], ["Tech", "tech"], ["Tech"] * 11, [123]]:
            response = self.client.patch(
                self.base + "profile/", {"interests": interests}, format="json"
            )
            self.assertEqual(response.status_code, 400)
        good = self.client.patch(
            self.base + "profile/", {"interests": [" Live music ", "Tech"]}, format="json"
        )
        self.assertEqual(good.data["interests"], ["Live music", "Tech"])

    def test_profile_text_moderation_rejects_contact_or_payment_solicitation(self):
        for body in ["Call 0712345678", "Send mpesa fare", "An escort for you"]:
            response = self.client.patch(self.base + "profile/", {"bio": body}, format="json")
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.data["error"]["code"], "profile_content_not_allowed")
        self.assertEqual(
            self.client.patch(
                self.base + "profile/", {"bio": "Send good vibes"}, format="json"
            ).status_code,
            200,
        )

    def test_verification_badge_cannot_be_self_assigned(self):
        self.client.patch(
            self.base + "profile/",
            {"verification_level": "verified", "age_years": 30},
            format="json",
        )
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.verification_level, "none")
        self.assertEqual(self.profile.age_years, 27)

    @patch("apps.profiles.serializers.R2MediaStore")
    def test_owner_gets_distinct_private_and_blurred_urls_without_exposing_keys(self, store):
        PrivateIdentity.objects.create(user=self.user, real_avatar_key="private-owner.jpg")
        self.profile.blurred_avatar_key = "blurred-owner.jpg"
        self.profile.save()
        store.return_value.presign_private.return_value = "https://storage.test/private"
        store.return_value.presign_derived.return_value = "https://storage.test/blurred"
        response = self.client.get(self.base + "profile/")
        self.assertEqual(response.data["avatar_url"], "https://storage.test/private")
        self.assertEqual(response.data["blurred_avatar_url"], "https://storage.test/blurred")
        self.assertNotIn("real_avatar_key", response.data)
        other = User.objects.create_user(email="another@example.test")
        self.client.force_authenticate(other)
        self.assertIsNone(self.client.get(self.base + "profile/").data["avatar_url"])

    @patch("apps.profiles.serializers.R2MediaStore", side_effect=RuntimeError("offline"))
    def test_storage_outage_does_not_hide_account_controls(self, store):
        self.profile.blurred_avatar_key = "stored.jpg"
        self.profile.save()
        response = self.client.get(self.base + "profile/")
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data["blurred_avatar_url"])

    @patch("apps.profiles.views.R2MediaStore")
    def test_voice_upload_requires_explicit_consent(self, store):
        self.client.post(
            self.base + "consents/",
            {"type": "voice", "granted": False, "version": "test"},
            format="json",
        )
        response = self.client.post(
            self.base + "media/upload-url/",
            {"kind": "audio", "content_type": "audio/mp4", "size_bytes": 100},
            format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(MediaAsset.objects.exists())
        store.assert_not_called()

    @patch("apps.profiles.views.R2MediaStore")
    def test_audio_upload_retains_the_explicit_disguise_choice(self, store):
        store.return_value.presign_upload.return_value = "https://storage.test/upload"
        response = self.client.post(
            self.base + "media/upload-url/",
            {
                "kind": "audio",
                "content_type": "audio/mp4",
                "size_bytes": 32,
                "disguise_voice": False,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertFalse(MediaAsset.objects.get(pk=response.data["upload_id"]).disguise_voice)

    @patch("apps.profiles.tasks_media.process_audio", return_value=(b"processed capsule", 12000))
    @patch("apps.profiles.tasks_media.R2MediaStore")
    def test_audio_worker_publishes_only_processed_audio_with_correct_metadata(
        self, store, process
    ):
        asset = self.asset(kind="audio", disguise_voice=False)
        store.return_value.download.return_value = b"original capsule"
        self.assertEqual(process_media_asset(str(asset.pk)), "ready")
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.audio_key, f"media/audio/{asset.pk}.m4a")
        self.assertEqual(self.profile.audio_duration_ms, 12000)
        self.assertFalse(self.profile.audio_disguised)
        store.return_value.upload_private.assert_called_once_with(
            self.profile.audio_key, b"processed capsule", "audio/mp4"
        )
        store.return_value.upload_derived.assert_not_called()

    @patch("apps.profiles.tasks_media.process_audio", return_value=(b"processed capsule", 12000))
    @patch("apps.profiles.tasks_media.R2MediaStore")
    def test_voice_consent_revoked_before_publication_prevents_any_audio_upload(
        self, store, process
    ):
        asset = self.asset(kind="audio")
        ConsentRecord.objects.filter(user=self.user, consent_type="voice").update(
            revoked_at=timezone.now()
        )
        self.assertEqual(process_media_asset(str(asset.pk)), "rejected")
        asset.refresh_from_db()
        self.assertEqual(asset.rejection_code, "voice_consent_required")
        store.return_value.upload_private.assert_not_called()
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.audio_key, "")

    def test_other_accounts_cannot_complete_an_audio_upload(self):
        asset = self.asset(kind="audio", status="pending")
        other = User.objects.create_user(email="not-the-audio-owner@example.test")
        self.client.force_authenticate(other)
        response = self.client.post(
            self.base + "media/complete/", {"upload_id": str(asset.pk)}, format="json"
        )
        self.assertEqual(response.status_code, 404)
        asset.refresh_from_db()
        self.assertEqual(asset.status, "pending")

    @patch(
        "apps.profiles.tasks_media.process_audio", return_value=(b"old processed capsule", 12000)
    )
    @patch("apps.profiles.tasks_media.R2MediaStore")
    def test_a_late_audio_worker_cannot_replace_a_newer_ready_capsule(self, store, process):
        old = self.asset(kind="audio")
        self.asset(kind="audio", status="ready")
        self.profile.audio_key = "newer-capsule.m4a"
        self.profile.audio_duration_ms = 3000
        self.profile.audio_disguised = False
        self.profile.save()
        process_media_asset(str(old.pk))
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.audio_key, "newer-capsule.m4a")
        self.assertEqual(self.profile.audio_duration_ms, 3000)
        self.assertFalse(self.profile.audio_disguised)

    @patch("apps.profiles.views.R2MediaStore")
    @patch(
        "apps.profiles.views.process_media_asset.delay", side_effect=RuntimeError("broker offline")
    )
    def test_media_completion_keeps_processing_intent_through_broker_failure(self, enqueue, store):
        asset = self.asset(status="pending")
        store.return_value.head.return_value = {"ContentLength": 100, "ContentType": "image/jpeg"}
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                self.base + "media/complete/", {"upload_id": str(asset.pk)}, format="json"
            )
        self.assertEqual(response.status_code, 202)
        asset.refresh_from_db()
        self.assertEqual(asset.status, "processing")
        again = self.client.post(
            self.base + "media/complete/", {"upload_id": str(asset.pk)}, format="json"
        )
        self.assertEqual(again.status_code, 202)
        self.assertEqual(MediaAsset.objects.count(), 1)

    @patch("apps.profiles.tasks_media.process_avatar", return_value=(b"original", b"blurred"))
    @patch("apps.profiles.tasks_media.R2MediaStore")
    def test_photo_processing_publishes_a_private_original_and_separate_blur(self, store, process):
        asset = self.asset()
        self.assertEqual(process_media_asset(str(asset.pk)), "ready")
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.blurred_avatar_key, f"media/derived/{asset.pk}.jpg")
        self.assertEqual(
            PrivateIdentity.objects.get(user=self.user).real_avatar_key,
            f"media/original/{asset.pk}.jpg",
        )
        self.assertEqual(store.return_value.upload_private.call_count, 2)
        asset.refresh_from_db()
        self.assertEqual(asset.thumbnail_key, f"media/thumbnails/{asset.pk}.jpg")
        store.return_value.upload_derived.assert_called_once()

    @patch("apps.profiles.tasks_media.R2MediaStore")
    def test_transient_processing_failure_is_recoverable_and_tracks_possible_objects(self, store):
        asset = self.asset()
        store.return_value.download.side_effect = RuntimeError("offline")
        self.assertEqual(process_media_asset(str(asset.pk)), "retry_pending")
        asset.refresh_from_db()
        self.assertEqual(asset.status, "processing")
        self.assertEqual(asset.processing_attempts, 1)
        self.assertTrue(asset.original_key)
        MediaAsset.objects.filter(pk=asset.pk).update(
            processing_queued_at=timezone.now() - timedelta(minutes=3)
        )
        with patch("apps.profiles.tasks_media.process_media_asset.delay") as enqueue:
            recover_media_processing()
        enqueue.assert_called_once_with(str(asset.pk))

    @patch("apps.profiles.tasks_media.process_avatar", return_value=(b"original", b"blurred"))
    @patch("apps.profiles.tasks_media.R2MediaStore")
    def test_old_upload_cannot_replace_a_newer_accepted_photo(self, store, process):
        old = self.asset()
        self.asset(status="ready")
        self.profile.blurred_avatar_key = "newer-photo.jpg"
        self.profile.save()
        process_media_asset(str(old.pk))
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.blurred_avatar_key, "newer-photo.jpg")

    @patch("apps.profiles.tasks_media.process_audio", return_value=(b"audio", 12000))
    @patch("apps.profiles.tasks_media.R2MediaStore")
    def test_voice_disguise_state_reflects_actual_processing_option(self, store, process):
        asset = self.asset(kind="audio", disguise_voice=False)
        process_media_asset(str(asset.pk))
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.audio_duration_ms, 12000)
        self.assertFalse(self.profile.audio_disguised)

    @patch("apps.compliance.services.default_object_storage")
    def test_media_deletion_is_scoped_and_clears_active_voice(self, storage):
        self.asset(kind="audio", status="ready", original_key="voice.m4a")
        self.profile.audio_key, self.profile.audio_duration_ms = "voice.m4a", 12000
        self.profile.save()
        response = self.client.delete(self.base + "media/audio/")
        self.assertEqual(response.status_code, 204)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.audio_key, "")
        self.assertFalse(MediaAsset.objects.filter(user=self.user, kind="audio").exists())
        self.assertEqual(self.client.delete(self.base + "media/audio/").status_code, 204)

    def test_export_contains_owned_records_and_omits_credentials(self):
        self.asset(status="ready")
        response = self.client.post(self.base + "data-export/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["account"]["email"], self.user.email)
        self.assertEqual(len(response.data["media"]), 1)
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertNotIn("password", str(response.data))
        self.assertNotIn("launch_url", str(response.data))

    def test_purge_collects_private_identity_even_without_a_profile(self):
        PrivateIdentity.objects.create(user=self.user, real_avatar_key="private.jpg")
        self.assertIn("private.jpg", _media_keys_for_user(self.user))
        self.profile.delete()
        self.assertIn("private.jpg", _media_keys_for_user(User.objects.get(pk=self.user.pk)))

    def test_failed_storage_purge_keeps_account_available_for_retry(self):
        self.asset(status="ready", original_key="private.jpg")
        storage = Mock()
        storage.delete_keys.side_effect = RuntimeError("erasure_storage_unavailable")
        with self.assertRaisesMessage(RuntimeError, "erasure_storage_unavailable"):
            purge_user_data(str(self.user.pk), storage=storage)
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())

    @override_settings(R2_BUCKET_PRIVATE="private", R2_BUCKET_PUBLIC_DERIVED="derived")
    def test_storage_purge_chunks_large_batches_and_rejects_partial_failure(self):
        adapter = R2ObjectStorageDeletionAdapter.__new__(R2ObjectStorageDeletionAdapter)
        adapter.client = Mock()
        adapter.client.delete_objects.return_value = {}
        self.assertEqual(adapter.delete_keys([f"key-{i}" for i in range(1001)]), 2002)
        self.assertEqual(adapter.client.delete_objects.call_count, 4)
        adapter.client.delete_objects.return_value = {"Errors": [{"Code": "AccessDenied"}]}
        with self.assertRaisesMessage(RuntimeError, "erasure_storage_unavailable"):
            adapter.delete_keys(["private-key"])

    @patch(
        "apps.profiles.tasks_media.process_avatar", return_value=(b"private-copy", b"softer-blur")
    )
    @patch("apps.profiles.tasks_media.R2MediaStore")
    def test_refresh_ready_preview_preserves_private_identity(self, store, process):
        asset = self.ready_photo()
        store.return_value.download.return_value = b"approved original"
        self.profile.is_discoverable = False
        self.profile.save(update_fields=["is_discoverable"])
        self.assertEqual(refresh_avatar_preview(str(asset.pk)), "refreshed")
        asset.refresh_from_db()
        self.profile.refresh_from_db()
        self.assertEqual(asset.status, "ready")
        self.assertFalse(self.profile.is_discoverable)
        self.assertEqual(
            PrivateIdentity.objects.get(user=self.user).real_avatar_key, "private-photo.jpg"
        )
        self.assertEqual(self.profile.blurred_avatar_key, "blurred-photo.jpg")
        store.return_value.upload_private.assert_called_once_with(
            asset.thumbnail_key, b"thumbnail", "image/jpeg"
        )
        store.return_value.upload_derived.assert_called_once_with(
            "blurred-photo.jpg", b"softer-blur", "image/jpeg"
        )

    @patch("apps.profiles.tasks_media.R2MediaStore")
    def test_refresh_does_not_process_an_unapproved_photo(self, store):
        asset = self.asset()
        self.assertEqual(refresh_avatar_preview(str(asset.pk)), "skipped")
        store.assert_not_called()

    @patch("apps.profiles.tasks_media.process_avatar", return_value=(b"private", b"preview"))
    @patch("apps.profiles.tasks_media.R2MediaStore")
    def test_refresh_does_not_publish_after_owner_is_deactivated(self, store, process):
        asset = self.ready_photo()

        def deactivate(*args, **kwargs):
            User.objects.filter(pk=self.user.pk).update(status="suspended")
            return b"approved original"

        store.return_value.download.side_effect = deactivate
        self.assertEqual(refresh_avatar_preview(str(asset.pk)), "removed")
        store.return_value.upload_derived.assert_not_called()

    @patch("apps.profiles.serializers.R2MediaStore")
    def test_header_thumbnail_is_owner_scoped_and_presigned_privately(self, store):
        asset = self.ready_photo()
        asset.thumbnail_key = "media/thumbnails/header.jpg"
        asset.save(update_fields=["thumbnail_key"])
        store.return_value.presign_private.side_effect = lambda key: "private:" + key
        response = self.client.get(self.base + "profile/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data["avatar_thumbnail_url"], "private:media/thumbnails/header.jpg"
        )
        other = User.objects.create_user(email="thumbnail-other@example.test")
        Profile.objects.create(user=other)
        self.client.force_authenticate(other)
        self.assertIsNone(self.client.get(self.base + "profile/").data["avatar_thumbnail_url"])

    def test_erasure_includes_thumbnails_even_after_a_partial_refresh_failure(self):
        asset = self.ready_photo()
        self.assertIn(f"media/thumbnails/{asset.pk}.jpg", _media_keys_for_user(self.user))

    @patch("apps.profiles.tasks_media.process_avatar", return_value=(b"private", b"preview"))
    @patch("apps.profiles.tasks_media.R2MediaStore")
    def test_refresh_does_not_publish_after_privacy_consent_is_revoked(self, store, process):
        asset = self.ready_photo()

        def revoke(*args, **kwargs):
            ConsentRecord.objects.filter(user=self.user, consent_type="privacy").update(
                revoked_at=timezone.now()
            )
            return b"approved original"

        store.return_value.download.side_effect = revoke
        self.assertEqual(refresh_avatar_preview(str(asset.pk)), "consent_required")
        store.return_value.upload_derived.assert_not_called()
