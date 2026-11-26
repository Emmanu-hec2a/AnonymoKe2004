from datetime import timedelta

from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.measure import D
from django.db.models import Exists, F, OuterRef, Q
from django.utils import timezone

from apps.accounts.models import User
from apps.matching.models import Match, Swipe
from apps.profiles.eligibility import consented_profiles, ensure_discovery_access
from apps.profiles.models import MatchingPreference, Profile
from apps.safety.models import Block

from .models import ProfileBoost


def candidate_queryset(
    me: Profile,
    max_distance_km: int | None = None,
    min_age: int | None = None,
    max_age: int | None = None,
    ranking_at=None,
):
    ensure_discovery_access(me)
    try:
        target_genders = list(me.matching_preference.target_genders)
    except MatchingPreference.DoesNotExist:
        raise ValueError("matching_preferences_required") from None
    if not target_genders:
        return Profile.objects.none()
    distance_limit = min(max_distance_km or me.max_distance_km, me.max_distance_km)
    minimum_age = max(min_age or me.min_age_pref, me.min_age_pref)
    maximum_age = min(max_age or me.max_age_pref, me.max_age_pref)
    if minimum_age > maximum_age:
        return Profile.objects.none()
    seen = Swipe.objects.filter(from_profile=me, is_undone=False).values("to_profile_id")
    blocked = Block.objects.filter(Q(blocker=me) | Q(blocked=me)).values_list(
        "blocker_id", "blocked_id"
    )
    blocked_ids = set()
    for blocker_id, blocked_id in blocked:
        blocked_ids.add(blocker_id if blocked_id == me.id else blocked_id)
    matched = Match.objects.filter(Q(profile_a=me) | Q(profile_b=me)).exclude(
        state=Match.State.CLOSED
    )
    gender_filter = Q(matching_preference__target_genders__contains=[me.gender]) | Q(
        matching_preference__target_genders__contains=["ALL"]
    )
    ranked_at = ranking_at or timezone.now()
    candidates = (
        consented_profiles(Profile.objects.select_related("user", "matching_preference"))
        .filter(
            is_discoverable=True,
            location_flagged=False,
            user__status=User.Status.ACTIVE,
            gender__in=target_genders if "ALL" not in target_genders else ["M", "W", "NB"],
            age_years__gte=minimum_age,
            age_years__lte=maximum_age,
            min_age_pref__lte=me.age_years,
            max_age_pref__gte=me.age_years,
            cell__isnull=False,
            cell_updated_at__gte=timezone.now() - timedelta(days=7),
        )
        .filter(gender_filter)
        .filter(cell__dwithin=(me.cell, D(km=distance_limit)))
        .exclude(id=me.id)
        .exclude(id__in=seen)
        .exclude(id__in=blocked_ids)
        .exclude(id__in=matched.values("profile_a_id"))
        .exclude(id__in=matched.values("profile_b_id"))
        .annotate(
            distance_m=Distance("cell", me.cell),
            boost_active=Exists(
                ProfileBoost.objects.filter(
                    profile_id=OuterRef("pk"),
                    expires_at__gt=ranked_at,
                    activated_at__lte=ranked_at,
                )
            ),
            # People who already liked you come first: one like from you makes a match.
            # This never reaches the client; "who liked you" stays a premium list.
            liked_me=Exists(
                Swipe.objects.filter(
                    from_profile_id=OuterRef("pk"),
                    to_profile=me,
                    action=Swipe.Action.LIKE,
                    is_undone=False,
                    created_at__lte=ranked_at,
                )
            ),
        )
        .filter(distance_m__lte=F("max_distance_km") * 1000)
        .order_by(
            "-liked_me",
            "-boost_active",
            "distance_m",
            "-verification_level",
            "-updated_at",
            "id",
        )
    )
    return candidates


def candidate_feed(me, limit=20, max_distance_km=None, min_age=None, max_age=None):
    return list(candidate_queryset(me, max_distance_km, min_age, max_age)[:limit])
