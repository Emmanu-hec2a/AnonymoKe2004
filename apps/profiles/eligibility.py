from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from apps.compliance.consent import has_active_consent
from apps.compliance.models import ConsentRecord

from .models import Profile


def active_consent_users(kind):
    return ConsentRecord.objects.filter(
        consent_type=kind,
        granted=True,
        revoked_at__isnull=True,
        granted_at__lte=timezone.now(),
    ).values("user_id")


def consented_profiles(queryset):
    for kind in ("location", "sensitive_data"):
        queryset = queryset.filter(user_id__in=active_consent_users(kind))
    return queryset


def ensure_discovery_access(profile: Profile):
    for kind in ("location", "sensitive_data"):
        if not has_active_consent(profile.user, kind):
            raise ValueError(f"{kind}_consent_required")
    if profile.user.status != profile.user.Status.ACTIVE:
        raise ValueError("account_not_active")
    if not profile.is_discoverable:
        raise ValueError("profile_paused")
    if not profile.age_years or profile.age_years < 18 or not profile.gender:
        raise ValueError("profile_incomplete")
    if profile.location_flagged:
        raise ValueError("location_flagged")
    if profile.cell is None:
        raise ValueError("location_required")
    if not profile.cell_updated_at or profile.cell_updated_at < timezone.now() - timedelta(days=7):
        raise ValueError("location_stale")
    if settings.REQUIRE_VERIFICATION_PRE_DISCOVERY and profile.verification_level == "none":
        raise ValueError("verification_required_before_discovery")
