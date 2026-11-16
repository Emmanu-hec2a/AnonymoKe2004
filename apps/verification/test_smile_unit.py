"""Provider contract checks, runnable without GDAL or a database via unittest."""

import base64
import hashlib
import hmac
import json
import os
from datetime import timedelta
from unittest import TestCase
from unittest.mock import MagicMock, patch
from urllib.error import URLError

from django.conf import settings
from django.test import override_settings
from django.utils import timezone

if not settings.configured and not os.getenv("DJANGO_SETTINGS_MODULE"):
    settings.configure(SECRET_KEY="unit-tests", USE_TZ=True)

from .smile import NoRedirects, SmileID, allowed_launch_url, configured, valid_signature  # noqa: E402

SMILE_SETTINGS = {
    "SMILE_ID_ENVIRONMENT": "sandbox",
    "SMILE_ID_PARTNER_ID": "partner-test",
    "SMILE_ID_API_KEY": "unit-key",
    "SMILE_ID_CALLBACK_URL": "https://api.example.test/callback/",
    "SMILE_ID_PRIVACY_URL": "https://example.test/privacy",
    "SMILE_ID_REDIRECT_URL": "https://api.example.test/return/",
    "SMILE_ID_LINK_HOSTS": ["links.usesmileid.com"],
}


class SmileContractTests(TestCase):
    def setUp(self):
        self.enterContext(override_settings(**SMILE_SETTINGS))

    def test_missing_credentials_and_unknown_environment_are_unavailable(self):
        for values in [{"SMILE_ID_API_KEY": ""}, {"SMILE_ID_ENVIRONMENT": "prod-typo"}]:
            with override_settings(**values):
                self.assertFalse(configured())
                with self.assertRaisesRegex(RuntimeError, "provider_unavailable"):
                    SmileID()

    def test_launch_url_rejects_other_hosts_credentials_ports_and_bad_uris(self):
        self.assertTrue(allowed_launch_url("https://links.usesmileid.com/session"))
        for url in [
            "http://links.usesmileid.com/x",
            "https://evil.test/x",
            "https://links.usesmileid.com.evil.test/x",
            "https://user@links.usesmileid.com/x",
            "https://links.usesmileid.com:444/x",
            "https://links.usesmileid.com:bad/x",
            "https://[invalid",
        ]:
            with self.subTest(url=url):
                self.assertFalse(allowed_launch_url(url))

    def test_provider_redirects_cannot_forward_secrets(self):
        self.assertIsNone(
            NoRedirects().redirect_request(None, None, 302, "", {}, "https://evil.test")
        )

    @patch("apps.verification.smile.build_opener")
    def test_token_uses_multipart_and_provider_headers(self, opener):
        response = MagicMock()
        response.read.return_value = json.dumps({"token": "session-token"}).encode()
        opener.return_value.open.return_value.__enter__.return_value = response
        self.assertEqual(SmileID().token("attempt-id"), "session-token")
        request = opener.return_value.open.call_args.args[0]
        self.assertEqual(request.full_url, "https://testapi.smileidentity.com/v3/token")
        self.assertIn(b'name="user_id"\r\n\r\nattempt-id', request.data)
        self.assertEqual(request.get_header("Smileid-api-key"), "unit-key")
        self.assertEqual(opener.return_value.open.call_args.kwargs["timeout"], 12)

    @patch.object(SmileID, "request")
    def test_link_has_single_use_expiry_document_check_and_callback_reference(self, request):
        request.side_effect = [
            ({"token": "token"}, {}),
            (
                {
                    "user_id": "attempt",
                    "ref_id": "ref",
                    "link": "https://links.usesmileid.com/session",
                },
                {},
            ),
        ]
        reference, _, expires = SmileID().create_session("attempt")
        self.assertEqual(reference, "ref")
        self.assertLess(abs((expires - timezone.now()).total_seconds() - 1800), 2)
        fields = request.call_args.kwargs["fields"]
        self.assertTrue(fields["is_single_use"])
        self.assertEqual(fields["id_types"][0]["verification_method"], "document_verification")
        self.assertEqual(fields["partner_params"]["anonymoke_attempt_id"], "attempt")
        self.assertEqual(
            fields["notice_privacy_policy_url"], SMILE_SETTINGS["SMILE_ID_PRIVACY_URL"]
        )

    @patch.object(SmileID, "request")
    def test_result_uses_user_bound_token_and_rejects_path_injection(self, request):
        request.side_effect = [({"token": "bound-token"}, {}), ({"status": "clear"}, {})]
        job = "job_" + "0" * 26
        self.assertEqual(SmileID().result("attempt", job)["status"], "clear")
        self.assertEqual(request.call_args_list[0].kwargs["fields"], {"user_id": "attempt"})
        self.assertEqual(request.call_args.kwargs["token"], "bound-token")
        for invalid in ["../other", "job_short", {}, None]:
            with self.assertRaisesRegex(ValueError, "job_invalid"):
                SmileID().result("attempt", invalid)

    @patch("apps.verification.smile.build_opener")
    def test_network_failure_is_sanitized(self, opener):
        opener.return_value.open.side_effect = URLError("private upstream details")
        with self.assertRaisesRegex(RuntimeError, "^verification_provider_unavailable$"):
            SmileID().token()

    def test_webhook_signature_requires_fresh_exact_timestamp(self):
        def sign(stamp):
            return base64.b64encode(
                hmac.new(
                    b"unit-key", f"{stamp}partner-testsid_request".encode(), hashlib.sha256
                ).digest()
            ).decode()

        stamp = timezone.now().isoformat()
        self.assertTrue(valid_signature(sign(stamp), stamp))
        self.assertFalse(valid_signature("wrong", stamp))
        stale = (timezone.now() - timedelta(minutes=11)).isoformat()
        self.assertFalse(valid_signature(sign(stale), stale))
        self.assertFalse(valid_signature(sign(stamp), "2026-11-14T10:00:00"))

    def test_malformed_signature_is_rejected_without_a_server_error(self):
        for signature in ["not-base64", "é", None, {}]:
            self.assertFalse(valid_signature(signature, timezone.now().isoformat()))
