import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from threading import Lock
from time import monotonic
from urllib import request

import jwt
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_email

from .identity import VerifiedExternalIdentity


class BaseSocialProvider(ABC):
    @abstractmethod
    def verify_credential(self, credential: str) -> VerifiedExternalIdentity:
        raise NotImplementedError


class ProviderNotConfigured(BaseSocialProvider):
    def verify_credential(self, credential: str) -> VerifiedExternalIdentity:  # noqa: ARG002
        raise RuntimeError("provider_not_configured")


@dataclass(frozen=True)
class OIDCConfig:
    issuer: str | tuple[str, ...]
    audience: str | tuple[str, ...]
    jwks_url: str


class OIDCSocialProvider(BaseSocialProvider):
    _jwks_cache: dict[str, tuple[float, dict]] = {}
    _cache_lock = Lock()

    def __init__(self, provider: str, config: OIDCConfig):
        self.provider = provider
        self.config = config

    def verify_credential(self, credential: str) -> VerifiedExternalIdentity:
        try:
            header = jwt.get_unverified_header(credential)
            if header.get("alg") != "RS256" or not header.get("kid"):
                raise ValueError("social_token_algorithm_invalid")
            key = self._key_for_kid(header["kid"])
            claims = jwt.decode(
                credential,
                key=key,
                algorithms=["RS256"],
                audience=self.config.audience,
                issuer=self.config.issuer,
                options={"require": ["exp", "iat", "sub", "iss", "aud"]},
            )
        except (jwt.PyJWTError, KeyError, ValueError) as exc:
            raise ValueError("social_token_invalid") from exc
        email = claims.get("email")
        subject = claims.get("sub")
        verified = claims.get("email_verified") is True or claims.get("email_verified") == "true"
        if (
            not isinstance(email, str)
            or not isinstance(subject, str)
            or not subject
            or not verified
        ):
            raise ValueError("social_email_not_verified")
        try:
            validate_email(email)
        except ValidationError as exc:
            raise ValueError("social_email_not_verified") from exc
        return VerifiedExternalIdentity(
            provider=self.provider,
            subject=str(subject),
            email=str(email).lower(),
            email_verified=True,
        )

    def _key_for_kid(self, kid: str):
        now = monotonic()
        with self._cache_lock:
            cached = self._jwks_cache.get(self.config.jwks_url)
            if not cached or cached[0] <= now:
                cached = (now + 3600, self._fetch_jwks())
                self._jwks_cache[self.config.jwks_url] = cached
        for jwk in cached[1].get("keys", []):
            if jwk.get("kid") == kid:
                return jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(jwk))
        raise ValueError("social_signing_key_not_found")

    def _fetch_jwks(self) -> dict:
        if not self.config.jwks_url.startswith("https://"):
            raise ValueError("social_jwks_url_invalid")
        req = request.Request(  # noqa: S310 - provider URL is HTTPS-validated below
            self.config.jwks_url,
            headers={"Accept": "application/json"},
        )
        with request.urlopen(req, timeout=10) as response:  # noqa: S310 - HTTPS-only provider URL
            return json.loads(response.read())


def provider_for(name: str) -> BaseSocialProvider:
    if name == "google" and settings.GOOGLE_OIDC_CLIENT_ID:
        return OIDCSocialProvider(
            "google",
            OIDCConfig(
                issuer=("https://accounts.google.com", "accounts.google.com")
                if settings.GOOGLE_OIDC_ISSUER
                in {"https://accounts.google.com", "accounts.google.com"}
                else settings.GOOGLE_OIDC_ISSUER,
                audience=settings.GOOGLE_OIDC_CLIENT_ID,
                jwks_url=settings.GOOGLE_OIDC_JWKS_URL,
            ),
        )
    apple_audiences = tuple(
        value for value in (settings.APPLE_SERVICE_ID, settings.APPLE_BUNDLE_ID) if value
    )
    if name == "apple" and apple_audiences:
        return OIDCSocialProvider(
            "apple",
            OIDCConfig(
                issuer=settings.APPLE_OIDC_ISSUER,
                audience=apple_audiences,
                jwks_url=settings.APPLE_OIDC_JWKS_URL,
            ),
        )
    if name in {"google", "apple"}:
        return ProviderNotConfigured()
    raise ValueError("unsupported_provider")
