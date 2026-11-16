from datetime import timedelta

from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from apps.profiles.eligibility import ensure_discovery_access
from apps.profiles.models import Profile
from apps.store.models import Entitlement

from .models import ProfileBoost


def available_boosts(user):
    return Entitlement.objects.filter(user=user, kind="boost", quantity__gt=0).filter(
        Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now())
    )


def boost_status(profile):
    active = (
        ProfileBoost.objects.filter(
            profile=profile,
            expires_at__gt=timezone.now(),
        )
        .order_by("-expires_at")
        .first()
    )
    return {
        "active_until": active.expires_at if active else None,
        "available_boosts": available_boosts(profile.user).aggregate(total=Sum("quantity"))["total"]
        or 0,
    }


@transaction.atomic
def activate_boost(profile, client_activation_id):
    profile = Profile.objects.select_for_update().select_related("user").get(pk=profile.pk)
    ensure_discovery_access(profile)
    duplicate = ProfileBoost.objects.filter(
        profile=profile,
        client_activation_id=client_activation_id,
    ).first()
    if duplicate:
        return duplicate
    now = timezone.now()
    active = ProfileBoost.objects.filter(profile=profile, expires_at__gt=now).first()
    if active:
        return active
    entitlement = available_boosts(profile.user).select_for_update().order_by("created_at").first()
    if not entitlement:
        raise ValueError("boost_required")
    entitlement.quantity -= 1
    entitlement.save(update_fields=["quantity", "updated_at"])
    return ProfileBoost.objects.create(
        profile=profile,
        source_entitlement=entitlement,
        client_activation_id=client_activation_id,
        activated_at=now,
        expires_at=now + timedelta(minutes=30),
    )
