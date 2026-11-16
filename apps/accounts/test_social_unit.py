from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from .social import OIDCConfig, OIDCSocialProvider, provider_for


class SocialTokenValidationTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def setUp(self):
        self.provider = OIDCSocialProvider(
            "google", OIDCConfig("https://issuer.test", "web-client", "https://issuer.test/keys")
        )
        now = datetime.now(UTC)
        self.claims = {
            "iss": "https://issuer.test",
            "aud": "web-client",
            "sub": "provider-subject",
            "iat": now,
            "exp": now + timedelta(minutes=5),
            "email": "PERSON@example.test",
            "email_verified": True,
        }

    def token(self, claims=None):
        return jwt.encode(
            claims or self.claims, self.key, algorithm="RS256", headers={"kid": "test"}
        )

    def verify(self, token):
        with patch.object(self.provider, "_key_for_kid", return_value=self.key.public_key()):
            return self.provider.verify_credential(token)

    def test_signed_token_returns_only_a_verified_normalized_identity(self):
        result = self.verify(self.token())
        self.assertEqual(result.email, "person@example.test")
        self.assertEqual(result.subject, "provider-subject")
        self.assertTrue(result.email_verified)

    def test_wrong_audience_issuer_or_expiry_cannot_authenticate(self):
        for field, value in (
            ("aud", "another-app"),
            ("iss", "https://attacker.test"),
            ("exp", datetime.now(UTC) - timedelta(minutes=1)),
        ):
            with (
                self.subTest(field=field),
                self.assertRaisesRegex(ValueError, "social_token_invalid"),
            ):
                self.verify(self.token({**self.claims, field: value}))

    def test_required_claims_cannot_be_omitted_even_with_a_valid_signature(self):
        for field in ("exp", "iat", "iss", "aud", "sub"):
            claims = {key: value for key, value in self.claims.items() if key != field}
            with (
                self.subTest(field=field),
                self.assertRaisesRegex(ValueError, "social_token_invalid"),
            ):
                self.verify(self.token(claims))

    def test_unverified_or_malformed_email_is_never_used_for_account_linking(self):
        for values in (
            {"email_verified": False},
            {"email_verified": 1},
            {"email_verified": []},
            {"email": "not-an-email"},
            {"email": None},
            {"email": ["person@example.test"]},
        ):
            with (
                self.subTest(values=values),
                self.assertRaisesRegex(ValueError, "social_email_not_verified"),
            ):
                self.verify(self.token({**self.claims, **values}))

    def test_apple_string_email_verified_claim_is_supported(self):
        result = self.verify(self.token({**self.claims, "email_verified": "true"}))
        self.assertTrue(result.email_verified)

    def test_both_canonical_google_issuers_are_accepted_without_accepting_other_issuers(self):
        config = SimpleNamespace(
            GOOGLE_OIDC_CLIENT_ID="web-client",
            GOOGLE_OIDC_ISSUER="https://accounts.google.com",
            GOOGLE_OIDC_JWKS_URL="https://www.googleapis.com/oauth2/v3/certs",
        )
        with patch("apps.accounts.social.settings", config):
            provider = provider_for("google")
        with patch.object(provider, "_key_for_kid", return_value=self.key.public_key()):
            for issuer in ("accounts.google.com", "https://accounts.google.com"):
                self.assertEqual(
                    provider.verify_credential(self.token({**self.claims, "iss": issuer})).subject,
                    "provider-subject",
                )
            with self.assertRaisesRegex(ValueError, "social_token_invalid"):
                provider.verify_credential(
                    self.token({**self.claims, "iss": "https://attacker.test"})
                )

    def test_wrong_signing_algorithm_is_rejected_before_key_lookup(self):
        token = jwt.encode(self.claims, "test-secret-longer-than-32-characters", algorithm="HS256")
        with patch.object(self.provider, "_key_for_kid") as lookup:
            with self.assertRaisesRegex(ValueError, "social_token_invalid"):
                self.provider.verify_credential(token)
            lookup.assert_not_called()

    def test_native_apple_bundle_and_service_audiences_are_both_explicit(self):
        config = SimpleNamespace(
            GOOGLE_OIDC_CLIENT_ID="",
            APPLE_SERVICE_ID="web-service",
            APPLE_BUNDLE_ID="co.anonymoke.anonymoke",
            APPLE_OIDC_ISSUER="https://appleid.apple.com",
            APPLE_OIDC_JWKS_URL="https://appleid.apple.com/auth/keys",
        )
        with patch("apps.accounts.social.settings", config):
            self.assertEqual(
                provider_for("apple").config.audience,
                ("web-service", "co.anonymoke.anonymoke"),
            )
            with self.assertRaisesRegex(ValueError, "unsupported_provider"):
                provider_for("unknown")

    def test_unconfigured_providers_never_create_a_dummy_identity(self):
        with patch(
            "apps.accounts.social.settings",
            SimpleNamespace(GOOGLE_OIDC_CLIENT_ID="", APPLE_SERVICE_ID="", APPLE_BUNDLE_ID=""),
        ):
            for provider in ("google", "apple"):
                with self.assertRaisesRegex(RuntimeError, "provider_not_configured"):
                    provider_for(provider).verify_credential("untrusted")
