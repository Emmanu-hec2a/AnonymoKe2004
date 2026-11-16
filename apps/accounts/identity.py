from dataclasses import dataclass


@dataclass(frozen=True)
class VerifiedExternalIdentity:
    provider: str
    subject: str
    email: str
    email_verified: bool
