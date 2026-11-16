import base64
import hashlib
import hmac
import json
from datetime import timedelta
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.compliance.models import ConsentRecord
from apps.core.crypto import decrypt_text
from apps.profiles.models import Profile

from .models import VerificationAttempt, VerificationResultCheck
from .services import VerificationService, reconcile_attempt
from .tasks import check_verification_result
from .test_smile_unit import SMILE_SETTINGS


@override_settings(
    **SMILE_SETTINGS,
    VERIFICATION_PROVIDER="smile_id",
    SMILE_ID_ADULT_POLICY_CONFIRMED=True,
    DEBUG=True,
)
class VerificationIntegrationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(email="verification@example.test")
        self.profile = Profile.objects.create(user=self.user, alias="Quiet Comet")
        ConsentRecord.objects.create(
            user=self.user, consent_type="sensitive_data", granted=True, version="test"
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.base = "/api/v1/me/verification/"
        self.job = "job_" + "0" * 26

    def attempt(self):
        return VerificationAttempt.objects.create(
            user=self.user, provider="smile_id", purpose="identity_check"
        )

    def result(self, attempt, status="clear"):
        return {"user_id": str(attempt.pk), "job_id": self.job, "status": status}

    def callback(self, attempt, **changes):
        stamp = timezone.now().isoformat()
        signature = base64.b64encode(
            hmac.new(
                b"unit-key", f"{stamp}partner-testsid_request".encode(), hashlib.sha256
            ).digest()
        ).decode()
        payload = {"user_id": str(attempt.pk), "job_id": self.job, "status": "clear"}
        payload.update(changes)
        return self.client.post(
            self.base + "webhook/smile_id/",
            json.dumps(payload),
            content_type="application/json",
            HTTP_RESPONSE_SIGNATURE=signature,
            HTTP_RESPONSE_TIMESTAMP=stamp,
        )

    def test_explicit_verification_consent_is_required(self):
        response = self.client.post(
            self.base + "start/", {"purpose": "identity_check"}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(VerificationAttempt.objects.exists())

    @override_settings(SMILE_ID_API_KEY="")
    def test_missing_credentials_disables_start_without_creating_dummy_attempt(self):
        self.assertFalse(self.client.get(self.base + "status/").data["available"])
        response = self.client.post(
            self.base + "start/", {"purpose": "identity_check", "consent": True}, format="json"
        )
        self.assertEqual(response.status_code, 503)
        self.assertFalse(VerificationAttempt.objects.exists())

    @override_settings(SMILE_ID_ADULT_POLICY_CONFIRMED=False)
    def test_unconfirmed_adult_policy_disables_verification(self):
        with self.assertRaisesMessage(RuntimeError, "verification_provider_unavailable"):
            VerificationService.start(self.user, "identity_check")

    @patch("apps.verification.services.SmileID")
    def test_hosted_link_is_encrypted_and_reused_instead_of_duplicated(self, provider):
        url = "https://links.usesmileid.com/private-session"
        provider.return_value.create_session.return_value = (
            "reference",
            url,
            timezone.now() + timedelta(minutes=30),
        )
        first = VerificationService.start(self.user, "identity_check")
        again = VerificationService.start(self.user, "identity_check")
        self.assertEqual(first.attempt.pk, again.attempt.pk)
        self.assertEqual(again.launch_url, url)
        first.attempt.refresh_from_db()
        self.assertNotIn(url.encode(), bytes(first.attempt.launch_url_ciphertext))
        self.assertEqual(decrypt_text(bytes(first.attempt.launch_url_ciphertext)), url)
        provider.return_value.create_session.assert_called_once()

    @patch("apps.verification.services.SmileID")
    def test_clear_result_requires_an_authoritative_user_bound_lookup(self, provider):
        attempt = self.attempt()
        provider.return_value.result.return_value = self.result(attempt)
        reconcile_attempt(attempt.pk, job_id=self.job)
        provider.return_value.result.assert_called_once_with(str(attempt.pk), self.job)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.verification_level, "verified")
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, "passed")
        self.assertEqual(bytes(attempt.launch_url_ciphertext), b"")

    @patch("apps.verification.services.SmileID")
    def test_foreign_result_cannot_verify_or_reserve_a_job_id(self, provider):
        attempt = self.attempt()
        provider.return_value.result.return_value = {
            **self.result(attempt),
            "user_id": "another-user",
        }
        with self.assertRaisesMessage(ValueError, "verification_reference_mismatch"):
            reconcile_attempt(attempt.pk, job_id=self.job)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.verification_level, "none")
        attempt.refresh_from_db()
        self.assertEqual(attempt.provider_job_id, "")

    @override_settings(DEBUG=False, SMILE_ID_ENVIRONMENT="sandbox")
    @patch("apps.verification.services.SmileID")
    def test_sandbox_result_cannot_grant_a_production_badge(self, provider):
        attempt = self.attempt()
        provider.return_value.result.return_value = self.result(attempt)
        with self.assertRaisesMessage(ValueError, "verification_environment_invalid"):
            reconcile_attempt(attempt.pk, job_id=self.job)

    @patch("apps.verification.services.SmileID")
    def test_withdrawn_sensitive_consent_prevents_verification(self, provider):
        attempt = self.attempt()
        response = self.client.post(
            "/api/v1/me/consents/",
            {"type": "sensitive_data", "granted": False, "version": "test"},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        provider.return_value.result.return_value = self.result(attempt)
        with self.assertRaisesMessage(ValueError, "sensitive_data_consent_required"):
            reconcile_attempt(attempt.pk, job_id=self.job)

    @patch("apps.verification.services.SmileID")
    def test_attention_requires_review_and_never_grants_a_badge(self, provider):
        attempt = self.attempt()
        provider.return_value.result.return_value = self.result(attempt, "attention")
        reconcile_attempt(attempt.pk, job_id=self.job)
        attempt.refresh_from_db()
        self.profile.refresh_from_db()
        self.assertEqual(attempt.status, "review")
        self.assertEqual(self.profile.verification_level, "none")

    @patch(
        "apps.verification.tasks.check_verification_result.delay",
        side_effect=RuntimeError("broker offline"),
    )
    def test_webhook_is_durable_and_does_not_trust_claimed_result(self, enqueue):
        attempt = self.attempt()
        with self.captureOnCommitCallbacks(execute=True):
            response = self.callback(attempt)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            VerificationResultCheck.objects.filter(attempt=attempt, job_id=self.job).exists()
        )
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.verification_level, "none")
        self.callback(attempt)
        self.assertEqual(VerificationResultCheck.objects.count(), 1)

    def test_invalid_webhook_signature_cannot_create_a_job(self):
        response = self.client.post(
            self.base + "webhook/smile_id/", {"status": "clear"}, format="json"
        )
        self.assertEqual(response.status_code, 404)
        self.assertFalse(VerificationResultCheck.objects.exists())

    @patch(
        "apps.verification.tasks.reconcile_attempt", side_effect=RuntimeError("provider offline")
    )
    def test_provider_outage_keeps_callback_for_retry(self, reconcile):
        check = VerificationResultCheck.objects.create(attempt=self.attempt(), job_id=self.job)
        check_verification_result(check.pk)
        check.refresh_from_db()
        self.assertIsNone(check.completed_at)
        self.assertEqual(check.attempts, 1)
        self.assertGreater(check.next_attempt_at, timezone.now())

    @patch(
        "apps.verification.tasks.reconcile_attempt",
        side_effect=ValueError("verification_reference_mismatch"),
    )
    def test_mismatched_callback_is_discarded_without_blocking_real_callback(self, reconcile):
        attempt = self.attempt()
        check = VerificationResultCheck.objects.create(attempt=attempt, job_id=self.job)
        check_verification_result(check.pk)
        check.refresh_from_db()
        self.assertIsNotNone(check.completed_at)
        attempt.refresh_from_db()
        self.assertEqual(attempt.provider_job_id, "")
