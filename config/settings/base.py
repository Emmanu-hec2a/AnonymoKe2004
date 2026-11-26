from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parents[2]
env = environ.Env(
    DEBUG=(bool, False),
    DJANGO_SECRET_KEY=(str, "unsafe-dev-only"),
    ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
)
ENV_FILE = BASE_DIR / ".env"
if ENV_FILE.exists():
    environ.Env.read_env(ENV_FILE)

SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")

INSTALLED_APPS = [
    "daphne",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.gis",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "drf_spectacular",
    "apps.core",
    "apps.accounts",
    "apps.compliance",
    "apps.profiles",
    "apps.discovery",
    "apps.matching",
    "apps.chat",
    "apps.verification",
    "apps.safety",
    "apps.adminapi",
    "apps.store",
    "apps.notifications",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
ASGI_APPLICATION = "config.asgi.application"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

DATABASES = {
    "default": env.db(
        "DATABASE_URL", default="postgis://anonymoke:anonymoke@localhost:5432/anonymoke"
    )
}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "accounts.User"

JWT_SECRET = env("JWT_SECRET", default=SECRET_KEY)
JWT_ACCESS_MINUTES = env.int("JWT_ACCESS_MINUTES", default=15)
JWT_REFRESH_DAYS = env.int("JWT_REFRESH_DAYS", default=30)
MAGIC_LINK_TTL_MINUTES = env.int("MAGIC_LINK_TTL_MINUTES", default=10)
MAGIC_LINK_RESEND_COOLDOWN_SECONDS = env.int("MAGIC_LINK_RESEND_COOLDOWN_SECONDS", default=60)
MAGIC_LINK_MAX_ATTEMPTS_PER_HOUR = env.int("MAGIC_LINK_MAX_ATTEMPTS_PER_HOUR", default=5)
REQUIRE_VERIFICATION_PRE_DISCOVERY = env.bool("REQUIRE_VERIFICATION_PRE_DISCOVERY", default=False)
REQUIRE_VERIFICATION_PRE_UNMASK = env.bool("REQUIRE_VERIFICATION_PRE_UNMASK", default=True)
VERIFICATION_PROVIDER = env("VERIFICATION_PROVIDER", default="dummy")
SMILE_ID_ENVIRONMENT = env("SMILE_ID_ENVIRONMENT", default="sandbox")
SMILE_ID_ADULT_POLICY_CONFIRMED = env.bool("SMILE_ID_ADULT_POLICY_CONFIRMED", default=False)
SMILE_ID_PARTNER_ID = env("SMILE_ID_PARTNER_ID", default="")
SMILE_ID_API_KEY = env("SMILE_ID_API_KEY", default="")
SMILE_ID_CALLBACK_URL = env("SMILE_ID_CALLBACK_URL", default="")
SMILE_ID_PRIVACY_URL = env("SMILE_ID_PRIVACY_URL", default="")
SMILE_ID_REDIRECT_URL = env("SMILE_ID_REDIRECT_URL", default="")
SMILE_ID_LINK_HOSTS = env.list(
    "SMILE_ID_LINK_HOSTS", default=["links.usesmileid.com", "links.smileidentity.com"]
)
VERIFICATION_WEBHOOK_SECRET = env("VERIFICATION_WEBHOOK_SECRET", default="")
RESEND_FROM_EMAIL = env("RESEND_FROM_EMAIL", default="AnonymoKE <noreply@anonymoke.co.ke>")
RESEND_REPLY_TO_EMAIL = env("RESEND_REPLY_TO_EMAIL", default="")
EMAIL_PRIVACY_URL = env("EMAIL_PRIVACY_URL", default="")
EMAIL_TERMS_URL = env("EMAIL_TERMS_URL", default="")
RESEND_API_KEY = env("RESEND_API_KEY", default="")
MAGIC_LINK_BASE_URL = env(
    "MAGIC_LINK_BASE_URL", default="https://api.anonymoke.co.ke/auth/magic-link#token="
)
# Public certificates for the currently registered Android signing configurations.
# Override this list when introducing a release/Play signing certificate.
ANDROID_APP_LINK_SHA256_FINGERPRINTS = env.list(
    "ANDROID_APP_LINK_SHA256_FINGERPRINTS",
    default=[
        (
            "86:8D:B1:46:27:F4:4F:94:AD:B2:61:95:5E:5A:2B:41:"
            "F2:83:7F:73:90:A0:EE:A4:FA:57:FF:BE:E9:90:01:6B"
        ),
        (
            "D6:D8:9F:61:38:46:F1:78:2B:81:78:3D:6D:C7:80:68:"
            "5B:64:1B:76:7C:DF:70:25:13:CA:AF:48:94:0F:E6:5F"
        ),
    ],
)
GOOGLE_OIDC_CLIENT_ID = env("GOOGLE_OIDC_CLIENT_ID", default="")
GOOGLE_OIDC_ISSUER = env("GOOGLE_OIDC_ISSUER", default="https://accounts.google.com")
GOOGLE_OIDC_JWKS_URL = env(
    "GOOGLE_OIDC_JWKS_URL", default="https://www.googleapis.com/oauth2/v3/certs"
)
APPLE_SERVICE_ID = env("APPLE_SERVICE_ID", default="")
APPLE_BUNDLE_ID = env("APPLE_BUNDLE_ID", default="")
APPLE_OIDC_ISSUER = env("APPLE_OIDC_ISSUER", default="https://appleid.apple.com")
APPLE_OIDC_JWKS_URL = env("APPLE_OIDC_JWKS_URL", default="https://appleid.apple.com/auth/keys")
LOCATION_HMAC_SECRET = env("LOCATION_HMAC_SECRET", default=SECRET_KEY)
FIELD_ENCRYPTION_KEY = env("FIELD_ENCRYPTION_KEY", default=SECRET_KEY)
R2_ENDPOINT_URL = env("R2_ENDPOINT_URL", default="")
R2_ACCESS_KEY_ID = env("R2_ACCESS_KEY_ID", default="")
R2_SECRET_ACCESS_KEY = env("R2_SECRET_ACCESS_KEY", default="")
R2_BUCKET_PRIVATE = env("R2_BUCKET_PRIVATE", default="")
R2_BUCKET_PUBLIC_DERIVED = env("R2_BUCKET_PUBLIC_DERIVED", default="")
PAYMENT_PROVIDER = env("PAYMENT_PROVIDER", default="dummy")
FIREBASE_SERVICE_ACCOUNT_JSON = env("FIREBASE_SERVICE_ACCOUNT_JSON", default="")
FIREBASE_PROJECT_ID = env("FIREBASE_PROJECT_ID", default="anonymoke-e038b")
DARAJA_BASE_URL = env("DARAJA_BASE_URL", default="https://sandbox.safaricom.co.ke")
DARAJA_CONSUMER_KEY = env("DARAJA_CONSUMER_KEY", default="")
DARAJA_CONSUMER_SECRET = env("DARAJA_CONSUMER_SECRET", default="")
# Daraja go-live store/head-office shortcode authenticates STK requests and queries.
DARAJA_SHORTCODE = env("DARAJA_SHORTCODE", default="")
# The customer-facing Buy Goods Till receives the payment (PartyB).
DARAJA_TILL_NUMBER = env("DARAJA_TILL_NUMBER", default="")
DARAJA_PASSKEY = env("DARAJA_PASSKEY", default="")
DARAJA_CALLBACK_BASE_URL = env("DARAJA_CALLBACK_BASE_URL", default="")
DARAJA_CALLBACK_TOKEN = env("DARAJA_CALLBACK_TOKEN", default="")
MEDIA_UPLOAD_URL_TTL_SECONDS = env.int("MEDIA_UPLOAD_URL_TTL_SECONDS", default=900)
MEDIA_AVATAR_MAX_BYTES = env.int("MEDIA_AVATAR_MAX_BYTES", default=10 * 1024 * 1024)
MEDIA_AUDIO_MAX_BYTES = env.int("MEDIA_AUDIO_MAX_BYTES", default=5 * 1024 * 1024)
MEDIA_AUDIO_MAX_DURATION_MS = env.int("MEDIA_AUDIO_MAX_DURATION_MS", default=15500)
MEDIA_REQUIRE_EXACTLY_ONE_FACE = env.bool("MEDIA_REQUIRE_EXACTLY_ONE_FACE", default=True)
AUTO_SUSPEND_SCAM_REPORTS = env.bool("AUTO_SUSPEND_SCAM_REPORTS", default=True)
AUTO_SUSPEND_REPORT_THRESHOLD = env.int("AUTO_SUSPEND_REPORT_THRESHOLD", default=3)
CHAT_MAX_MESSAGE_LENGTH = env.int("CHAT_MAX_MESSAGE_LENGTH", default=2000)
SAFETY_ALERT_PROVIDER = env("SAFETY_ALERT_PROVIDER", default="unconfigured")
SAFETY_RETENTION_DAYS = env.int("SAFETY_RETENTION_DAYS", default=90)

REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_AUTHENTICATION_CLASSES": ["apps.accounts.authentication.JWTAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_THROTTLE_RATES": {
        "auth_request": "20/min",
        "auth_verify": "60/min",
        "auth_social": "30/min",
        "auth_refresh": "120/min",
        "discovery": "60/min",
        "swipe": "120/min",
        "chat_read": "120/min",
        "chat_send": "60/min",
        "chat_activity": "120/min",
        "chat_media": "20/hour",
        "match_actions": "30/min",
        "matches": "120/min",
        "report": "30/hour",
        "block": "60/hour",
        "panic": "5/hour",
        "panic_retry": "10/hour",
        "safety_read": "120/min",
        "safety_write": "30/min",
        "safety_invite_issue": "5/hour",
        "safety_invite_accept": "10/hour",
        "safety_invite_ip": "30/hour",
        "verification_start": "5/hour",
        "verification_read": "60/min",
        "profile_read": "60/min",
        "profile_write": "30/min",
        "media_upload": "10/hour",
        "data_export": "3/hour",
        "account_erasure": "5/hour",
    },
}

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": env("REDIS_URL", default="redis://localhost:6379/0"),
    }
}

SPECTACULAR_SETTINGS = {
    "TITLE": "AnonymoKE API",
    "DESCRIPTION": "Privacy-first discovery and matching API for Kenya.",
    "VERSION": "0.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "SCHEMA_PATH_PREFIX": r"/api/v1",
}

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {"hosts": [env("REDIS_URL", default="redis://localhost:6379/0")]},
    }
}

CELERY_BROKER_URL = env("REDIS_URL", default="redis://localhost:6379/0")
CELERY_RESULT_BACKEND = env("REDIS_URL", default="redis://localhost:6379/0")
# Railway may expose the host CPU count rather than the service's allocation.
CELERY_WORKER_CONCURRENCY = env.int("CELERY_WORKER_CONCURRENCY", default=2)
CELERY_WORKER_PREFETCH_MULTIPLIER = env.int("CELERY_WORKER_PREFETCH_MULTIPLIER", default=1)
CELERY_TASK_DEFAULT_QUEUE = "default"
CELERY_TASK_ROUTES = {
    "apps.safety.tasks.scan_content": {"queue": "moderation"},
    "apps.profiles.tasks_media.process_media_asset": {"queue": "media"},
    "apps.safety.tasks.dispatch_panic_alert": {"queue": "safety"},
}
CELERY_BEAT_SCHEDULE = {
    "recover-chat-attachments": {
        "task": "apps.chat.media.recover_chat_attachments",
        "schedule": 60,
    },
    "purge-unused-chat-uploads": {
        "task": "apps.chat.media.purge_unused_chat_uploads",
        "schedule": 3600,
    },
    "recover-media-processing": {
        "task": "apps.profiles.tasks_media.recover_media_processing",
        "schedule": 60,
    },
    "reconcile-verifications": {
        "task": "apps.verification.tasks.reconcile_verifications",
        "schedule": 120,
    },
    "recover-safety-outbox": {
        "task": "apps.safety.tasks.recover_safety_deliveries",
        "schedule": 30,
    },
    "process-safety-checkins": {
        "task": "apps.safety.tasks.process_safety_checkins",
        "schedule": 60,
    },
    "purge-safety-history": {"task": "apps.safety.tasks.purge_safety_history", "schedule": 86400},
    "retry-pending-message-moderation": {
        "task": "apps.chat.tasks.retry_pending_moderation",
        "schedule": 60,
    },
    "expire-unanswered-likes": {
        "task": "apps.matching.tasks.expire_likes",
        "schedule": 600,
    },
    "purge-stale-locations-daily": {
        "task": "apps.profiles.tasks.purge_stale_locations",
        "schedule": 86400,
    },
    "purge-expired-auth-records-hourly": {
        "task": "apps.accounts.tasks.purge_expired_auth_records",
        "schedule": 3600,
    },
    "expire-stale-purchases-every-10-minutes": {
        "task": "apps.store.tasks.expire_stale_purchases",
        "schedule": 600,
    },
}

ROOT_LOGGER_NAME = "anonymoke"
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {"require_debug_false": {"()": "django.utils.log.RequireDebugFalse"}},
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {"anonymoke": {"handlers": ["console"], "level": "INFO"}},
}
