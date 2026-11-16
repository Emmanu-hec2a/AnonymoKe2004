import base64
import json
from datetime import UTC, datetime
from importlib.resources import files
from urllib import request
from urllib.parse import quote

from django.conf import settings
from django.template.loader import render_to_string


class EmailDeliveryProvider:
    def send_magic_link(self, email: str, token: str) -> str:
        raise NotImplementedError


class ResendEmailAdapter(EmailDeliveryProvider):
    def send_magic_link(self, email: str, token: str) -> str:
        if not settings.RESEND_API_KEY:
            raise RuntimeError("resend_not_configured")
        context = {
            "sign_in_url": f"{settings.MAGIC_LINK_BASE_URL}{quote(token, safe='')}",
            "ttl_minutes": settings.MAGIC_LINK_TTL_MINUTES,
            "year": datetime.now(UTC).year,
            "reply_to_email": settings.RESEND_REPLY_TO_EMAIL,
            "privacy_url": settings.EMAIL_PRIVACY_URL,
            "terms_url": settings.EMAIL_TERMS_URL,
        }
        logo = files("apps.accounts").joinpath("resources", "anonymoke-logo.jpeg").read_bytes()
        message = {
            "from": settings.RESEND_FROM_EMAIL,
            "to": [email],
            "subject": "Your AnonymoKE sign-in link",
            "html": render_to_string("accounts/emails/magic_link.html", context),
            "text": render_to_string("accounts/emails/magic_link.txt", context),
            "attachments": [
                {
                    "filename": "anonymoke-logo.jpeg",
                    "content": base64.b64encode(logo).decode("ascii"),
                    "content_type": "image/jpeg",
                    "content_id": "anonymoke-logo",
                }
            ],
        }
        if settings.RESEND_REPLY_TO_EMAIL:
            message["reply_to"] = settings.RESEND_REPLY_TO_EMAIL
        req = request.Request(
            "https://api.resend.com/emails",
            data=json.dumps(message).encode(),
            headers={
                "Authorization": f"Bearer {settings.RESEND_API_KEY}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with request.urlopen(req, timeout=10) as response:  # noqa: S310 - fixed HTTPS Resend endpoint
            payload = json.loads(response.read())
        return str(payload["id"])
