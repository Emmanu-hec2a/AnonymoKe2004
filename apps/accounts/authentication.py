import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone as django_timezone
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from .identity import VerifiedExternalIdentity
from .models import ExternalIdentity, MagicLinkToken, RefreshSession, User


@dataclass(frozen=True)
class SessionDTO:
    user_id: str
    access_token: str
    refresh_token: str
    access_expires_at: str
    refresh_expires_at: str
    is_onboarded: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "access_expires_at": self.access_expires_at,
            "refresh_expires_at": self.refresh_expires_at,
            "is_onboarded": self.is_onboarded,
        }


def _hash(value: str) -> str:
    return hmac.new(settings.JWT_SECRET.encode(), value.encode(), hashlib.sha256).hexdigest()


class AuthenticationService:
    @staticmethod
    def issue_session(user: User) -> SessionDTO:
        if user.status != User.Status.ACTIVE:
            raise ValueError("user_not_active")
        now = datetime.now(UTC)
        access_expiry = now + timedelta(minutes=settings.JWT_ACCESS_MINUTES)
        refresh_expiry = now + timedelta(days=settings.JWT_REFRESH_DAYS)
        access_jti = secrets.token_urlsafe(24)
        refresh_jti = secrets.token_urlsafe(24)
        access = jwt.encode(
            {
                "sub": str(user.id),
                "jti": access_jti,
                "typ": "access",
                "iat": now,
                "exp": access_expiry,
            },
            settings.JWT_SECRET,
            algorithm="HS256",
        )
        refresh = jwt.encode(
            {
                "sub": str(user.id),
                "jti": refresh_jti,
                "typ": "refresh",
                "iat": now,
                "exp": refresh_expiry,
            },
            settings.JWT_SECRET,
            algorithm="HS256",
        )
        RefreshSession.objects.create(
            user=user, jti_hash=_hash(refresh_jti), expires_at=refresh_expiry
        )
        return SessionDTO(
            user_id=str(user.id),
            access_token=access,
            refresh_token=refresh,
            access_expires_at=access_expiry.isoformat(),
            refresh_expires_at=refresh_expiry.isoformat(),
            is_onboarded=user.is_onboarded,
        )

    @staticmethod
    @transaction.atomic
    def authenticate_external(identity: VerifiedExternalIdentity) -> tuple[User, bool]:
        if not identity.email_verified:
            raise ValueError("external_email_not_verified")
        external = (
            ExternalIdentity.objects.select_for_update()
            .filter(provider=identity.provider, subject=identity.subject)
            .first()
        )
        if external:
            return external.user, False
        user, is_new = User.objects.get_or_create(email=identity.email.lower(), defaults={})
        linked, _ = ExternalIdentity.objects.get_or_create(
            provider=identity.provider,
            subject=identity.subject,
            defaults={"user": user, "email_verified": identity.email_verified},
        )
        return linked.user, is_new and linked.user_id == user.pk

    @staticmethod
    @transaction.atomic
    def rotate_refresh_token(raw_refresh_token: str) -> SessionDTO:
        try:
            claims = jwt.decode(raw_refresh_token, settings.JWT_SECRET, algorithms=["HS256"])
        except jwt.PyJWTError as exc:
            raise ValueError("refresh_token_invalid") from exc
        if claims.get("typ") != "refresh" or not claims.get("jti"):
            raise ValueError("refresh_token_invalid")
        session = (
            RefreshSession.objects.select_for_update().filter(jti_hash=_hash(claims["jti"])).first()
        )
        if (
            not session
            or session.revoked_at
            or session.expires_at <= django_timezone.now()
            or session.user.status != User.Status.ACTIVE
        ):
            raise ValueError("refresh_token_reused_or_expired")
        session.revoked_at = django_timezone.now()
        session.save(update_fields=["revoked_at"])
        payload = AuthenticationService.issue_session(session.user)
        new_claims = jwt.decode(payload.refresh_token, settings.JWT_SECRET, algorithms=["HS256"])
        session.replaced_by = RefreshSession.objects.get(jti_hash=_hash(new_claims["jti"])).id
        session.save(update_fields=["replaced_by"])
        return payload

    @staticmethod
    @transaction.atomic
    def revoke_refresh_token(raw_refresh_token: str) -> None:
        try:
            claims = jwt.decode(raw_refresh_token, settings.JWT_SECRET, algorithms=["HS256"])
        except jwt.PyJWTError as exc:
            raise ValueError("refresh_token_invalid") from exc
        if claims.get("typ") != "refresh" or not claims.get("jti"):
            raise ValueError("refresh_token_invalid")
        session = (
            RefreshSession.objects.select_for_update().filter(jti_hash=_hash(claims["jti"])).first()
        )
        if not session or session.revoked_at:
            raise ValueError("refresh_token_invalid")
        session.revoked_at = django_timezone.now()
        session.save(update_fields=["revoked_at"])


class JWTAuthentication(BaseAuthentication):
    def authenticate_header(self, request):
        return "Bearer"

    def authenticate(self, request):
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return None
        try:
            claims = jwt.decode(header[7:], settings.JWT_SECRET, algorithms=["HS256"])
        except jwt.PyJWTError as exc:
            raise AuthenticationFailed("invalid_access_token") from exc
        if claims.get("typ") != "access":
            raise AuthenticationFailed("invalid_access_token")
        try:
            user = User.objects.get(pk=claims["sub"], status=User.Status.ACTIVE)
        except (User.DoesNotExist, KeyError) as exc:
            raise AuthenticationFailed("user_not_active") from exc
        return user, claims


class MagicLinkService:
    @staticmethod
    @transaction.atomic
    def request(email: str) -> str | None:
        normalized = email.strip().lower()
        if connection.vendor == "postgresql":
            lock_key = int.from_bytes(hashlib.sha256(normalized.encode()).digest()[:8], signed=True)
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_xact_lock(%s)", [lock_key])
        now = django_timezone.now()
        recent = MagicLinkToken.objects.filter(
            email=normalized,
            requested_at__gte=now - timedelta(seconds=settings.MAGIC_LINK_RESEND_COOLDOWN_SECONDS),
        )
        if recent.exists():
            return None
        hourly = MagicLinkToken.objects.filter(
            email=normalized, requested_at__gte=now - timedelta(hours=1)
        ).count()
        if hourly >= settings.MAGIC_LINK_MAX_ATTEMPTS_PER_HOUR:
            return None
        raw_token = secrets.token_urlsafe(32)
        MagicLinkToken.objects.create(
            email=normalized,
            token_hash=_hash(raw_token),
            expires_at=now + timedelta(minutes=settings.MAGIC_LINK_TTL_MINUTES),
        )
        return raw_token

    @staticmethod
    def discard_undelivered(raw_token: str) -> None:
        MagicLinkToken.objects.filter(token_hash=_hash(raw_token), used_at__isnull=True).delete()

    @staticmethod
    @transaction.atomic
    def verify(raw_token: str) -> tuple[User, bool]:
        record = (
            MagicLinkToken.objects.select_for_update().filter(token_hash=_hash(raw_token)).first()
        )
        now = django_timezone.now()
        if not record or record.used_at or record.expires_at <= now:
            raise ValueError("magic_link_invalid")
        record.used_at = now
        record.save(update_fields=["used_at"])
        user, is_new = User.objects.get_or_create(email=record.email)
        return user, is_new
