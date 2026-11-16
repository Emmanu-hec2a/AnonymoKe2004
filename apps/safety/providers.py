import logging
from dataclasses import dataclass

from django.conf import settings

logger = logging.getLogger("anonymoke.safety")


class SafetyAlertProviderUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class SafetyAlertResult:
    provider_reference: str


class BaseSafetyAlertProvider:
    """Adapter boundary for SMS, WhatsApp, or another trusted-contact provider."""

    def send_panic_alert(
        self,
        *,
        alert_id: str,
        phone: str,
        contact_name: str,
        message: str,
    ) -> SafetyAlertResult:
        raise NotImplementedError


class LoggingSafetyAlertProvider(BaseSafetyAlertProvider):
    """Development provider; never use it to claim a real delivery in production."""

    def send_panic_alert(self, *, alert_id, phone, contact_name, message):  # noqa: ARG002
        logger.warning(
            "safety_alert_development_delivery alert_id=%s contact=%s phone_suffix=%s message=%s",
            alert_id,
            contact_name,
            phone[-4:],
            message,
        )
        return SafetyAlertResult(provider_reference=f"development:{alert_id}")


class UnconfiguredSafetyAlertProvider(BaseSafetyAlertProvider):
    def send_panic_alert(self, **kwargs):  # noqa: ARG002
        raise SafetyAlertProviderUnavailable("safety_alert_provider_unconfigured")


def default_safety_alert_provider() -> BaseSafetyAlertProvider:
    if settings.SAFETY_ALERT_PROVIDER.lower() == "logging":
        return LoggingSafetyAlertProvider()
    return UnconfiguredSafetyAlertProvider()
