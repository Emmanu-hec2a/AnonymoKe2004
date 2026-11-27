from datetime import timedelta
from unittest.mock import patch

from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from apps.accounts.models import RefreshSession, User
from apps.core.crypto import decrypt_text
from apps.profiles.models import Profile

from .models import DataSubjectRequest, WebDeletionRequest
from .web_erasure import confirm_deletion, process, recover, request_deletion


@override_settings(PUBLIC_BASE_URL="https://api.anonymoke.co.ke", RESEND_API_KEY="test-not-live")
class PublicDeletionTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(email="delete@example.test")
        self.profile = Profile.objects.create(user=self.user, alias="Quiet Comet")
        self.enqueue = self.enterContext(patch("apps.compliance.web_erasure.enqueue"))
        self.mail = self.enterContext(
            patch("apps.accounts.mail.ResendEmailAdapter.send_account_deletion")
        )

    def challenge(self):
        request_deletion(self.user.email)
        job = WebDeletionRequest.objects.latest("created_at")
        token = decrypt_text(bytes(job.token_ciphertext))
        self.assertNotEqual(job.token_hash, token)
        return job, token

    def test_public_pages_render_without_authentication_and_support_head(self):
        for path in ["/privacy-policy/", "/terms/", "/legal/privacy", "/delete-account/"]:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "AnonymoKe")
                self.assertIn("text/html", response["Content-Type"])
                self.assertEqual(self.client.head(path).status_code, 200)
        self.assertContains(self.client.get("/privacy-policy/"), "ANONYMOKE PRIVACY POLICY")

    def test_known_unknown_and_cooldown_responses_are_the_same(self):
        known = self.client.post("/delete-account/", {"email": self.user.email})
        unknown = self.client.post("/delete-account/", {"email": "unknown@example.test"})
        repeated = self.client.post("/delete-account/", {"email": self.user.email})
        for response in [known, unknown, repeated]:
            self.assertContains(response, "If this email belongs to an AnonymoKe account")
            self.assertEqual(response["Cache-Control"], "no-store")
        self.assertEqual(WebDeletionRequest.objects.count(), 1)
        self.assertNotContains(known, self.user.email)

    def test_public_request_does_not_wait_for_a_broker_or_email_provider(self):
        with self.captureOnCommitCallbacks(execute=True):
            request_deletion(self.user.email)
        self.enqueue.assert_not_called()
        self.mail.assert_not_called()
        self.assertEqual(WebDeletionRequest.objects.count(), 1)

    def test_confirmation_get_and_scanner_head_never_consume_or_delete(self):
        job, token = self.challenge()
        for method in [self.client.get, self.client.head]:
            response = method("/delete-account/verify/", {"token": token})
            self.assertEqual(response.status_code, 200)
            self.assertNotIn(token.encode(), response.content)
        job.refresh_from_db()
        self.assertIsNone(job.confirmed_at)
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())
        self.assertEqual(self.client.get("/delete-account/confirm/").status_code, 405)

    def test_explicit_confirmation_disables_account_and_is_idempotent(self):
        from apps.accounts.authentication import AuthenticationService

        access = AuthenticationService.issue_session(self.user).access_token
        job, token = self.challenge()
        refresh = RefreshSession.objects.create(
            user=self.user, jti_hash="a" * 64, expires_at=timezone.now() + timedelta(days=1)
        )
        payload = {"token": token, "confirm": "yes"}
        for _ in range(2):
            self.assertEqual(self.client.post("/delete-account/confirm/", payload).status_code, 200)
        job.refresh_from_db()
        self.user.refresh_from_db()
        refresh.refresh_from_db()
        self.assertEqual(self.user.status, "deletion_pending")
        self.assertEqual(job.status, "confirmed")
        self.assertIsNotNone(refresh.revoked_at)
        self.assertFalse(bytes(job.token_ciphertext))
        self.assertEqual(DataSubjectRequest.objects.count(), 1)
        self.mail.assert_not_called()
        response = self.client.get("/api/v1/me/profile/", HTTP_AUTHORIZATION=f"Bearer {access}")
        self.assertEqual(response.status_code, 401)

    def test_csrf_is_required_for_requests_and_destructive_confirmation(self):
        job, token = self.challenge()
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(
            client.post("/delete-account/", {"email": self.user.email}).status_code, 403
        )
        payload = {"token": token, "confirm": "yes"}
        self.assertEqual(client.post("/delete-account/confirm/", payload).status_code, 403)
        client.get("/delete-account/verify/")
        payload["csrfmiddlewaretoken"] = client.cookies["csrftoken"].value
        self.assertEqual(client.post("/delete-account/confirm/", payload).status_code, 200)

    def test_expiry_missing_checkbox_and_superseded_tokens_are_rejected(self):
        job, token = self.challenge()
        self.assertEqual(
            self.client.post("/delete-account/confirm/", {"token": token}).status_code, 400
        )
        request_deletion(self.user.email)
        with self.assertRaises(ValueError):
            confirm_deletion(token)
        job = WebDeletionRequest.objects.latest("created_at")
        token = decrypt_text(bytes(job.token_ciphertext))
        WebDeletionRequest.objects.filter(pk=job.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        with self.assertRaises(ValueError):
            confirm_deletion(token)
        self.user.refresh_from_db()
        self.assertEqual(self.user.status, "active")

    def test_email_delivery_receives_separate_purpose_token_then_clears_ciphertext(self):
        job, token = self.challenge()
        process(str(job.pk))
        self.mail.assert_called_once_with(self.user.email, token, str(job.pk))
        job.refresh_from_db()
        self.assertEqual(job.status, "sent")
        self.assertFalse(bytes(job.token_ciphertext))
        self.assertIsNone(job.confirmed_at)

    def test_email_failure_has_a_durable_retry_and_no_account_change(self):
        job, _ = self.challenge()
        self.mail.side_effect = RuntimeError("provider detail must not escape")
        process(str(job.pk))
        job.refresh_from_db()
        self.assertEqual(job.status, "pending")
        self.assertEqual(job.error_code, "email_unavailable")
        self.assertIsNone(job.lease_until)
        self.assertTrue(bytes(job.token_ciphertext))
        self.user.refresh_from_db()
        self.assertEqual(self.user.status, "active")

    def test_purge_failure_retries_without_reactivating_account(self):
        job, token = self.challenge()
        confirm_deletion(token)
        with patch(
            "apps.compliance.web_erasure.purge_user_data", side_effect=RuntimeError("r2 down")
        ):
            process(str(job.pk))
        job.refresh_from_db()
        self.user.refresh_from_db()
        self.assertEqual(job.status, "confirmed")
        self.assertEqual(self.user.status, "deletion_pending")
        self.assertEqual(job.error_code, "storage_temporarily_unavailable")
        self.assertGreater(job.next_attempt_at, timezone.now())

    def test_real_purge_removes_user_and_retains_completion_audit(self):
        job, token = self.challenge()
        confirm_deletion(token)
        from .storage import ObjectStorageDeletionAdapter

        with patch(
            "apps.compliance.services.default_object_storage",
            return_value=ObjectStorageDeletionAdapter(),
        ):
            process(str(job.pk))
        self.assertFalse(User.objects.filter(pk=self.user.pk).exists())
        job.refresh_from_db()
        self.assertIsNone(job.user_id)
        self.assertEqual(job.status, "completed")
        self.assertEqual(job.subject_request.status, "completed")
        self.assertIsNone(job.subject_request.user_id)

    def test_recovery_respects_active_lease_and_queues_only_due_work(self):
        first, _ = self.challenge()
        WebDeletionRequest.objects.filter(pk=first.pk).update(
            lease_until=timezone.now() + timedelta(minutes=1)
        )
        recover()
        self.enqueue.assert_not_called()
        WebDeletionRequest.objects.filter(pk=first.pk).update(
            lease_until=timezone.now() - timedelta(seconds=1)
        )
        recover()
        self.enqueue.assert_called_once_with(first.pk)

    def test_deleted_account_cannot_be_replaced_by_same_email_to_reuse_old_link(self):
        _, token = self.challenge()
        self.user.delete()
        replacement = User.objects.create_user(email="delete@example.test")
        with self.assertRaises(ValueError):
            confirm_deletion(token)
        replacement.refresh_from_db()
        self.assertEqual(replacement.status, "active")
