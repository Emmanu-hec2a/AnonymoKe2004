import secrets
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class VerificationResult:
    accepted: bool
    verification_level: str = "none"
    provider_reference: str | None = None
    reason_code: str | None = None


class BaseVerificationProvider(ABC):
    """Stable boundary for email, WhatsApp, Daraja, or ID-check providers."""

    @abstractmethod
    def send_verification(self, user, purpose: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def verify_code(self, user, code: str, purpose: str) -> VerificationResult:
        raise NotImplementedError


class DummyEmailAdapter(BaseVerificationProvider):
    def send_verification(self, user, purpose: str) -> str:  # noqa: ARG002
        return f"dummy-email-verification:{secrets.token_urlsafe(16)}"

    def verify_code(self, user, code: str, purpose: str) -> VerificationResult:  # noqa: ARG002
        return VerificationResult(accepted=code == "000000", verification_level="age_verified")
