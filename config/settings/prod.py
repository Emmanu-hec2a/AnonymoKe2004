import os

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403

_required_production_env = (
    "DJANGO_SECRET_KEY",
    "JWT_SECRET",
    "LOCATION_HMAC_SECRET",
    "FIELD_ENCRYPTION_KEY",
    "DATABASE_URL",
    "REDIS_URL",
    "RESEND_API_KEY",
    "GOOGLE_OIDC_CLIENT_ID",
    "APPLE_SERVICE_ID",
    "VERIFICATION_PROVIDER",
    "R2_ENDPOINT_URL",
    "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY",
    "R2_BUCKET_PRIVATE",
    "R2_BUCKET_PUBLIC_DERIVED",
    "DARAJA_CONSUMER_KEY",
    "DARAJA_CONSUMER_SECRET",
    "DARAJA_SHORTCODE",
    "DARAJA_PASSKEY",
    "DARAJA_CALLBACK_BASE_URL",
    "DARAJA_CALLBACK_TOKEN",
    "PAYMENT_PROVIDER",
)
_missing_production_env = [name for name in _required_production_env if not os.getenv(name)]
if _missing_production_env:
    raise ImproperlyConfigured(
        "Missing required production settings: " + ", ".join(_missing_production_env)
    )

if os.getenv("PAYMENT_PROVIDER") != "daraja":
    raise ImproperlyConfigured("PAYMENT_PROVIDER must be daraja in production")

DEBUG = False
_allow_smile_sandbox = os.getenv("ALLOW_SMILE_ID_SANDBOX", "").lower() == "true"
_allowed_smile_environments = {"production"} | ({"sandbox"} if _allow_smile_sandbox else set())
if VERIFICATION_PROVIDER != "smile_id" or SMILE_ID_ENVIRONMENT not in _allowed_smile_environments:  # noqa: F405
    raise ImproperlyConfigured(
        "Production verification requires Smile ID production credentials "
        "(set ALLOW_SMILE_ID_SANDBOX=true to permit the sandbox environment)"
    )
SECURE_SSL_REDIRECT = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
X_FRAME_OPTIONS = "DENY"
