import base64
import hashlib
import hmac
import json
import re
import secrets
from datetime import timedelta
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime


def configured():
    return bool(
        settings.SMILE_ID_ENVIRONMENT in {"sandbox", "production"}
        and settings.SMILE_ID_PARTNER_ID
        and settings.SMILE_ID_API_KEY
        and settings.SMILE_ID_CALLBACK_URL
        and settings.SMILE_ID_PRIVACY_URL
    )


def allowed_launch_url(url):
    try:
        parsed = urlparse(url)
        return (
            parsed.scheme == "https"
            and not parsed.username
            and not parsed.password
            and parsed.port in (None, 443)
            and parsed.hostname in settings.SMILE_ID_LINK_HOSTS
        )
    except ValueError:
        return False


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ARG002
        # Never forward API keys or user-bound tokens to a redirected origin.
        return None


class SmileID:
    def __init__(self):
        if not configured():
            raise RuntimeError("verification_provider_unavailable")
        self.base = (
            "https://api.smileidentity.com"
            if settings.SMILE_ID_ENVIRONMENT == "production"
            else "https://testapi.smileidentity.com"
        )

    def request(self, path, *, token=None, fields=None, method="POST"):
        headers = {"Accept": "application/json", "SmileID-Partner-ID": settings.SMILE_ID_PARTNER_ID}
        if token:
            headers["SmileID-Token"] = token
        else:
            headers["SmileID-API-Key"] = settings.SMILE_ID_API_KEY
        data = None
        if fields is not None:
            boundary = secrets.token_hex(20)
            parts = []
            for name, value in fields.items():
                encoded = (
                    json.dumps(value, separators=(",", ":"))
                    if isinstance(value, (dict, list, bool))
                    else str(value)
                )
                parts.append(
                    f"--{boundary}\r\nContent-Disposition: form-data; "
                    f'name="{name}"\r\n\r\n{encoded}\r\n'
                )
            data = ("".join(parts) + f"--{boundary}--\r\n").encode()
            headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        request = Request(self.base + path, data=data, headers=headers, method=method)  # noqa: S310
        try:
            with build_opener(NoRedirects()).open(request, timeout=12) as response:
                payload = json.loads(response.read(2_000_000))
                if not isinstance(payload, dict):
                    raise ValueError("invalid_response")
                return payload, dict(response.headers)
        except (HTTPError, URLError, TimeoutError, ValueError, OSError) as exc:
            raise RuntimeError("verification_provider_unavailable") from exc

    def token(self, reference=None):
        fields = {"user_id": reference} if reference else {}
        payload, _ = self.request("/v3/token", fields=fields)
        token = payload.get("token")
        if not isinstance(token, str) or not token:
            raise RuntimeError("verification_provider_unavailable")
        return token

    def create_session(self, reference):
        expires = timezone.now() + timedelta(minutes=30)
        fields = {
            "name": "AnonymoKE verification",
            "user_id": reference,
            "id_types": [
                {
                    "country": "KE",
                    "id_type": "NATIONAL_ID",
                    "verification_method": "document_verification",
                }
            ],
            "notice_privacy_policy_url": settings.SMILE_ID_PRIVACY_URL,
            "is_single_use": True,
            "expires_at": expires.isoformat(),
            "callback_url": settings.SMILE_ID_CALLBACK_URL,
            "theme_color": "#6A4AF0",
            "partner_params": {"anonymoke_attempt_id": reference},
        }
        if settings.SMILE_ID_REDIRECT_URL:
            fields["redirect_url"] = settings.SMILE_ID_REDIRECT_URL
        payload, _ = self.request("/v3/smile_links", token=self.token(), fields=fields)
        url = payload.get("link", "")
        if (
            not isinstance(url, str)
            or not allowed_launch_url(url)
            or payload.get("user_id") != reference
        ):
            raise RuntimeError("verification_provider_unavailable")
        return payload.get("ref_id", ""), url, expires

    def result(self, reference, job_id):
        if not isinstance(job_id, str) or not re.fullmatch(r"job_[0-9a-hjkmnp-tv-z]{26}", job_id):
            raise ValueError("verification_job_invalid")
        return self.request(f"/v3/status/{job_id}", token=self.token(reference), method="GET")[0]


def valid_signature(signature, timestamp):
    if (
        not configured()
        or not isinstance(signature, str)
        or not signature
        or not signature.isascii()
        or not timestamp
    ):
        return False
    try:
        when = parse_datetime(timestamp)
        if (
            when is None
            or timezone.is_naive(when)
            or abs((timezone.now() - when).total_seconds()) > 600
        ):
            return False
    except (ValueError, TypeError):
        return False
    expected = base64.b64encode(
        hmac.new(
            settings.SMILE_ID_API_KEY.encode(),
            f"{timestamp}{settings.SMILE_ID_PARTNER_ID}sid_request".encode(),
            hashlib.sha256,
        ).digest()
    ).decode()
    return hmac.compare_digest(signature, expected)
