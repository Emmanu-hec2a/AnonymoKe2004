from datetime import timedelta
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from .authentication import AuthenticationService, MagicLinkService
from .identity import VerifiedExternalIdentity
from .models import ExternalIdentity, MagicLinkToken, User


@override_settings(RESEND_API_KEY="test-configured")
class AuthIntegrationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.base = "/api/v1/auth/"

    @override_settings(RESEND_API_KEY="")
    def test_missing_delivery_configuration_fails_without_a_token_or_false_success(self):
        response = self.client.post(
            self.base + "magic-link/request/", {"email": "person@example.test"}, format="json"
        )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data["error"]["code"], "email_delivery_unavailable")
        self.assertFalse(MagicLinkToken.objects.exists())
        self.assertEqual(response["Cache-Control"], "no-store")

    @patch("apps.accounts.views.ResendEmailAdapter.send_magic_link")
    def test_requests_are_enumeration_safe_and_timing_metadata_matches_server_settings(self, send):
        User.objects.create_user(email="existing@example.test")
        bodies = []
        for email in ("existing@example.test", "new@example.test"):
            response = self.client.post(
                self.base + "magic-link/request/", {"email": email}, format="json"
            )
            self.assertEqual(response.status_code, 202)
            self.assertEqual(response["Cache-Control"], "no-store")
            self.assertNotIn("token", response.data)
            bodies.append(response.data)
        self.assertEqual(bodies[0], bodies[1])
        self.assertEqual(bodies[0]["resend_after_seconds"], 60)
        self.assertEqual(bodies[0]["expires_in_seconds"], 600)
        self.assertEqual(send.call_count, 2)

    @patch("apps.accounts.views.ResendEmailAdapter.send_magic_link", side_effect=OSError("offline"))
    def test_failed_delivery_discards_the_unusable_token_and_allows_retry(self, send):
        response = self.client.post(
            self.base + "magic-link/request/", {"email": "person@example.test"}, format="json"
        )
        self.assertEqual(response.status_code, 503)
        self.assertFalse(MagicLinkToken.objects.exists())
        send.side_effect = None
        self.assertEqual(
            self.client.post(
                self.base + "magic-link/request/", {"email": "person@example.test"}, format="json"
            ).status_code,
            202,
        )
        self.assertEqual(send.call_count, 2)

    @override_settings(MAGIC_LINK_RESEND_COOLDOWN_SECONDS=90)
    def test_configured_cooldown_and_hourly_limit_apply_to_normalized_email(self):
        self.assertIsNotNone(MagicLinkService.request("PERSON@example.test"))
        MagicLinkToken.objects.update(requested_at=timezone.now() - timedelta(seconds=70))
        self.assertIsNone(MagicLinkService.request("person@example.test"))
        for _attempt in range(4):
            MagicLinkToken.objects.update(requested_at=timezone.now() - timedelta(seconds=100))
            self.assertIsNotNone(MagicLinkService.request("person@example.test"))
        MagicLinkToken.objects.update(requested_at=timezone.now() - timedelta(seconds=100))
        self.assertIsNone(MagicLinkService.request("person@example.test"))

    def test_magic_link_is_single_use_and_returns_the_unified_session(self):
        token = MagicLinkService.request("person@example.test")
        response = self.client.post(
            self.base + "magic-link/verify/", {"token": token}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertTrue(
            {
                "user_id",
                "access_token",
                "refresh_token",
                "is_onboarded",
                "access_expires_at",
                "refresh_expires_at",
            }.issubset(response.data)
        )
        again = self.client.post(self.base + "magic-link/verify/", {"token": token}, format="json")
        self.assertEqual(again.status_code, 400)
        self.assertEqual(again.data["error"]["code"], "magic_link_invalid")
        self.assertEqual(User.objects.count(), 1)

    def test_expired_or_malformed_tokens_have_a_consistent_safe_error(self):
        token = MagicLinkService.request("person@example.test")
        MagicLinkToken.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        for value in (token, "short", "x" * 201):
            response = self.client.post(
                self.base + "magic-link/verify/", {"token": value}, format="json"
            )
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.data["error"]["code"], "magic_link_invalid")
        self.assertFalse(User.objects.exists())

    def test_validation_and_refresh_errors_remain_safe_and_uncached(self):
        invalid_email = self.client.post(
            self.base + "magic-link/request/", {"email": "not-an-email"}, format="json"
        )
        self.assertEqual(invalid_email.data["error"]["code"], "email_invalid")
        invalid_refresh = self.client.post(
            self.base + "token/refresh/", {"refresh_token": "x" * 30}, format="json"
        )
        self.assertEqual(invalid_refresh.status_code, 401)
        self.assertEqual(invalid_refresh["Cache-Control"], "no-store")

    def test_social_link_insert_recovers_if_another_request_created_the_identity(self):
        identity = VerifiedExternalIdentity("google", "same-subject", "person@example.test", True)
        user, created = AuthenticationService.authenticate_external(identity)
        self.assertTrue(created)
        with patch.object(ExternalIdentity.objects, "select_for_update") as lookup:
            lookup.return_value.filter.return_value.first.return_value = None
            again, created = AuthenticationService.authenticate_external(identity)
        self.assertEqual(again.pk, user.pk)
        self.assertFalse(created)
        self.assertEqual(ExternalIdentity.objects.count(), 1)
