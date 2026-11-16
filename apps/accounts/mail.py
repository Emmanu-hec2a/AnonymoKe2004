import json
from urllib import request
from urllib.parse import quote

from django.conf import settings


class EmailDeliveryProvider:
    def send_magic_link(self, email: str, token: str) -> str:
        raise NotImplementedError


class ResendEmailAdapter(EmailDeliveryProvider):
    def send_magic_link(self, email: str, token: str) -> str:
        if not settings.RESEND_API_KEY:
            raise RuntimeError("resend_not_configured")
        link = f"{settings.MAGIC_LINK_BASE_URL}{quote(token)}"
        body = json.dumps(
            {
                "from": settings.RESEND_FROM_EMAIL,
                "to": [email],
                "subject": "Your AnonymoKE sign-in link",
                "html": (
                    "<p>Use this one-time sign-in link to continue to AnonymoKE:</p>"
                    f'<p><a href="{link}">Sign in securely</a></p>'
                ),
            }
        ).encode()
        req = request.Request(
            "https://api.resend.com/emails",
            data=body,
            headers={
                "Authorization": f"Bearer {settings.RESEND_API_KEY}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with request.urlopen(req, timeout=10) as response:  # noqa: S310 - fixed HTTPS Resend endpoint
            payload = json.loads(response.read())
        return str(payload["id"])
