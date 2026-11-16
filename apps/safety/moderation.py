import re
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class ModerationFlag:
    category: str
    matched_terms: tuple[str, ...]
    score: float


class BaseManagedModerationProvider(ABC):
    @abstractmethod
    def classify(self, text: str) -> ModerationFlag:
        raise NotImplementedError


class NotConfiguredManagedModerationProvider(BaseManagedModerationProvider):
    def classify(self, text: str) -> ModerationFlag:  # noqa: ARG002
        raise RuntimeError("managed_moderation_not_configured")


# Layer 1 is deliberately conservative: it flags for review and never bans by itself.
PATTERNS: dict[str, tuple[str, ...]] = {
    "money_request": (
        r"\bmpesa\b",
        r"\btuma\b",
        r"\bsend\b",
        r"\bfare\b",
        r"\bairtime\b",
        r"\bloan\b",
    ),
    "contact_exchange": (
        r"\+?254\d{9}\b",
        r"\b0[17]\d{8}\b",
        r"@[a-z0-9_.]{3,30}",
        r"\bwhatsapp\b",
        r"(?:https?://|www\.|t\.me/|wa\.me/)",
    ),
    "commercial_sexual": (r"\bescort\b", r"\bsex for money\b", r"\bmalaya\b"),
}


def scan_text(text: str) -> list[ModerationFlag]:
    flags: list[ModerationFlag] = []
    lowered = text.casefold()
    for category, patterns in PATTERNS.items():
        matches = tuple(pattern for pattern in patterns if re.search(pattern, lowered))
        if matches:
            flags.append(ModerationFlag(category=category, matched_terms=matches, score=0.5))
    return flags
