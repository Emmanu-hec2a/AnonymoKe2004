from django.utils import timezone

from apps.chat.models import Message
from apps.core.crypto import decrypt_text
from apps.matching.models import Match, Swipe
from apps.profiles.models import MediaAsset, PrivateIdentity, Profile
from apps.safety.models import Block, DateSession, Report, TrustedContact
from apps.store.models import FinancialTransaction, Purchase
from apps.verification.models import VerificationAttempt

from .models import ConsentRecord


def _decrypt(value):
    if not value:
        return None
    try:
        return decrypt_text(bytes(value))
    except ValueError:
        return None


def export_user_data(user):
    """Export the account owner's records without credentials or another user's identity."""
    profile = Profile.objects.filter(user=user).first()
    identity = PrivateIdentity.objects.filter(user=user).first()
    contact = TrustedContact.objects.filter(user=user).first()
    return {
        "format_version": 1,
        "generated_at": timezone.now(),
        "account": {"id": user.pk, "email": user.email, "date_joined": user.date_joined},
        "profile": (
            {
                **{
                    name: getattr(profile, name)
                    for name in [
                        "public_id",
                        "alias",
                        "gender",
                        "age_years",
                        "height_cm",
                        "bio",
                        "interests",
                        "language",
                        "is_discoverable",
                        "max_distance_km",
                        "min_age_pref",
                        "max_age_pref",
                        "verification_level",
                    ]
                },
                "birth_date": _decrypt(profile.birth_date_ciphertext),
            }
            if profile
            else None
        ),
        "private_identity": (
            {
                "username": identity.username,
                "first_name": _decrypt(identity.real_first_name_ciphertext),
                "social_handles": _decrypt(identity.social_handles_ciphertext),
            }
            if identity
            else None
        ),
        "matching_preferences": {
            "target_genders": getattr(
                getattr(profile, "matching_preference", None), "target_genders", []
            )
        },
        "consents": list(
            ConsentRecord.objects.filter(user=user).values(
                "consent_type", "version", "granted", "granted_at", "revoked_at"
            )
        ),
        "media": list(
            MediaAsset.objects.filter(user=user).values(
                "id", "kind", "status", "duration_ms", "created_at"
            )
        ),
        "media_note": (
            "Media entries are metadata. This JSON file does not contain photo or audio binaries."
        ),
        "authored_messages": list(
            Message.objects.filter(sender__user=user).values(
                "id", "match_id", "body", "moderation_status", "created_at"
            )
        ),
        "swipes": list(
            Swipe.objects.filter(from_profile__user=user).values(
                "id", "to_profile__public_id", "action", "created_at"
            )
        ),
        "matches": list(Match.objects.filter(profile_a=profile).values("id", "state", "created_at"))
        + list(Match.objects.filter(profile_b=profile).values("id", "state", "created_at"))
        if profile
        else [],
        "reports": list(
            Report.objects.filter(reporter=user).values(
                "id", "reason", "note", "status", "created_at"
            )
        ),
        "blocks": list(
            Block.objects.filter(blocker=profile).values("blocked__public_id", "created_at")
        )
        if profile
        else [],
        "date_plans": list(
            DateSession.objects.filter(user=user).values(
                "id", "status", "venue_label", "starts_at", "check_in_due_at", "safe_at", "panic_at"
            )
        ),
        "trusted_contact": {
            "name": contact.contact_name,
            "phone": _decrypt(contact.phone_ciphertext),
        }
        if contact
        else None,
        "purchases": list(
            Purchase.objects.filter(user=user).values(
                "id", "product_id", "status", "amount_kes", "created_at"
            )
        ),
        "financial_transactions": list(
            FinancialTransaction.objects.filter(user=user).values(
                "id", "amount_kes", "provider", "provider_reference", "created_at", "retained_until"
            )
        ),
        "verification": list(
            VerificationAttempt.objects.filter(user=user).values(
                "id", "provider", "purpose", "status", "created_at"
            )
        ),
    }
