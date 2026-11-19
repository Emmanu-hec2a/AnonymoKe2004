import hashlib
import logging
import struct
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.contrib.gis.measure import D
from django.db import connection, transaction
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

from apps.compliance.consent import has_active_consent
from apps.profiles.eligibility import consented_profiles, ensure_discovery_access
from apps.profiles.models import MatchingPreference, PrivateIdentity, Profile
from apps.safety.models import Block

from .models import Match, Swipe

STALE_LOCATION_DAYS = 7
UNMASK_COOLDOWN_HOURS = 24
LIKE_TTL_HOURS = 24
logger = logging.getLogger("anonymoke.matching")


@dataclass(frozen=True)
class SwipeResult:
    swipe: Swipe
    match: Match | None


def _queue_event(*, user_id: int, event_type: str, match_id=None, actor_alias=None) -> None:
    from apps.notifications.service import enqueue_user_event

    def dispatch():
        try:
            enqueue_user_event(
                user_id=user_id,
                event_type=event_type,
                match_id=str(match_id) if match_id else None,
                actor_alias=actor_alias,
            )
        except Exception:  # noqa: BLE001 - push delivery must not break core actions
            logger.warning("notification_enqueue_failed", exc_info=True)

    transaction.on_commit(dispatch)


def _pair_key(first_id, second_id) -> int:
    values = sorted([str(first_id), str(second_id)])
    digest = hashlib.blake2b(f"{values[0]}:{values[1]}".encode(), digest_size=8).digest()
    return struct.unpack(">q", digest)[0]


def _lock_pair(first: Profile, second: Profile) -> None:
    if connection.vendor != "postgresql":
        return
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [_pair_key(first.id, second.id)])


def _stale(profile: Profile) -> bool:
    return not profile.cell_updated_at or profile.cell_updated_at < timezone.now() - timedelta(
        days=STALE_LOCATION_DAYS
    )


def _gender_allowed(preference: list, gender: str) -> bool:
    return "ALL" in preference or gender in preference


def _preference(profile: Profile) -> list:
    try:
        return list(profile.matching_preference.target_genders)
    except MatchingPreference.DoesNotExist:
        return []


def _blocked(first: Profile, second: Profile) -> bool:
    return Block.objects.filter(
        Q(blocker=first, blocked=second) | Q(blocker=second, blocked=first)
    ).exists()


def eligible_target(me: Profile, public_id) -> Profile:
    ensure_discovery_access(me)
    try:
        target = consented_profiles(
            Profile.objects.select_related("user", "matching_preference")
        ).get(public_id=public_id)
    except Profile.DoesNotExist as exc:
        raise ValueError("profile_not_found") from exc
    if target.id == me.id:
        raise ValueError("cannot_target_self")
    if (
        target.user.status != target.user.Status.ACTIVE
        or not target.is_discoverable
        or target.location_flagged
        or target.cell is None
        or _stale(target)
        or me.cell is None
        or me.location_flagged
        or _stale(me)
    ):
        raise ValueError("profile_not_eligible")
    if not me.gender or not target.gender or not _gender_allowed(_preference(me), target.gender):
        raise ValueError("profile_not_eligible")
    if not _gender_allowed(_preference(target), me.gender):
        raise ValueError("profile_not_eligible")
    if target.age_years is None or me.age_years is None:
        raise ValueError("profile_not_eligible")
    if not (
        me.min_age_pref <= target.age_years <= me.max_age_pref
        and target.min_age_pref <= me.age_years <= target.max_age_pref
    ):
        raise ValueError("profile_not_eligible")
    if _blocked(me, target):
        raise ValueError("profile_not_eligible")
    if not Profile.objects.filter(
        pk=target.pk,
        cell__dwithin=(me.cell, D(km=min(me.max_distance_km, target.max_distance_km))),
    ).exists():
        raise ValueError("profile_not_eligible")
    return target


@transaction.atomic
def record_swipe(me: Profile, public_id, action: str, client_swipe_id) -> SwipeResult:
    if action not in Swipe.Action.values:
        raise ValueError("swipe_action_invalid")
    ensure_discovery_access(me)
    _lock_pair(me, me)
    duplicate = Swipe.objects.filter(from_profile=me, client_swipe_id=client_swipe_id).first()
    if duplicate:
        if str(duplicate.to_profile.public_id) != str(public_id) or duplicate.action != action:
            raise ValueError("client_swipe_id_conflict")
        if duplicate.is_undone:
            raise ValueError("swipe_undone")
        match = _match_for_pair(me, duplicate.to_profile)
        return SwipeResult(swipe=duplicate, match=match)
    target = eligible_target(me, public_id)
    _lock_pair(me, target)
    swipe, created = Swipe.objects.get_or_create(
        from_profile=me,
        to_profile=target,
        defaults={"action": action, "client_swipe_id": client_swipe_id},
    )
    new_like = created and action == Swipe.Action.LIKE
    if not created and swipe.is_undone:
        swipe.action = action
        swipe.client_swipe_id = client_swipe_id
        swipe.is_undone = False
        swipe.created_at = timezone.now()
        swipe.save(
            update_fields=["action", "client_swipe_id", "is_undone", "created_at", "updated_at"]
        )
        new_like = action == Swipe.Action.LIKE
    if not created and swipe.action != action:
        raise ValueError("swipe_already_recorded")
    match = None
    match_created = False
    if swipe.action == Swipe.Action.LIKE:
        reciprocal = Swipe.objects.filter(
            from_profile=target,
            to_profile=me,
            action=Swipe.Action.LIKE,
            is_undone=False,
        ).exists()
        if reciprocal:
            profile_a, profile_b = sorted([me, target], key=lambda item: str(item.id))
            match, match_created = Match.objects.get_or_create(
                profile_a=profile_a,
                profile_b=profile_b,
                defaults={"state": Match.State.MASKED},
            )
            if match.state == Match.State.CLOSED:
                match = None
    if new_like:
        if match is not None and match_created:
            _queue_event(
                user_id=me.user_id,
                event_type="match.created",
                match_id=match.id,
                actor_alias=target.alias,
            )
            _queue_event(
                user_id=target.user_id,
                event_type="match.created",
                match_id=match.id,
                actor_alias=me.alias,
            )
        elif match is None:
            _queue_event(user_id=target.user_id, event_type="like.received")
    return SwipeResult(swipe=swipe, match=match)


@transaction.atomic
def undo_pass(me: Profile, client_swipe_id):
    from apps.store.models import Entitlement

    ensure_discovery_access(me)
    _lock_pair(me, me)
    swipe = (
        Swipe.objects.select_related("to_profile")
        .filter(
            from_profile=me,
            client_swipe_id=client_swipe_id,
        )
        .first()
    )
    if not swipe:
        raise ValueError("swipe_not_found")
    if swipe.action == Swipe.Action.LIKE:
        return _undo_like(me, swipe)
    if (
        not Entitlement.objects.filter(user=me.user, kind="premium", quantity__gt=0)
        .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now()))
        .exists()
    ):
        raise ValueError("premium_required")
    _lock_pair(me, swipe.to_profile)
    swipe = Swipe.objects.select_for_update().get(pk=swipe.pk)
    if swipe.is_undone:
        return swipe
    latest = (
        Swipe.objects.filter(from_profile=me, is_undone=False)
        .order_by("-created_at", "-pk")
        .first()
    )
    if not latest or latest.pk != swipe.pk:
        raise ValueError("only_latest_pass_can_be_undone")
    eligible_target(me, swipe.to_profile.public_id)
    swipe.is_undone = True
    swipe.save(update_fields=["is_undone", "updated_at"])
    return swipe


def _undo_like(me: Profile, swipe: Swipe) -> Swipe:
    # Withdrawing a like is free and not limited to the latest swipe, but a like that
    # already became a match is withdrawn by closing the match instead.
    _lock_pair(me, swipe.to_profile)
    swipe = Swipe.objects.select_for_update().select_related("to_profile").get(pk=swipe.pk)
    if swipe.is_undone:
        return swipe
    if _match_for_pair(me, swipe.to_profile) is not None:
        raise ValueError("like_already_matched")
    swipe.is_undone = True
    swipe.save(update_fields=["is_undone", "updated_at"])
    return swipe


def expire_unanswered_likes(now=None) -> int:
    """Withdraw likes older than LIKE_TTL_HOURS that never became a match.

    The liked profile returns to the liker's Discover feed and leaves the other
    person's "likes you" list. Likes that produced a live match are kept.
    """
    now = now or timezone.now()
    cutoff = now - timedelta(hours=LIKE_TTL_HOURS)
    live_match = Match.objects.exclude(state=Match.State.CLOSED).filter(
        Q(profile_a_id=OuterRef("from_profile_id"), profile_b_id=OuterRef("to_profile_id"))
        | Q(profile_a_id=OuterRef("to_profile_id"), profile_b_id=OuterRef("from_profile_id"))
    )
    return (
        Swipe.objects.filter(
            action=Swipe.Action.LIKE,
            is_undone=False,
            created_at__lt=cutoff,
        )
        .exclude(Exists(live_match))
        .update(is_undone=True, updated_at=now)
    )


def _match_for_pair(first: Profile, second: Profile) -> Match | None:
    profile_a, profile_b = sorted([first, second], key=lambda item: str(item.id))
    return (
        Match.objects.filter(profile_a=profile_a, profile_b=profile_b)
        .exclude(state=Match.State.CLOSED)
        .first()
    )


def participant_match(user_profile: Profile, match_id) -> Match:
    match = (
        Match.objects.select_related("profile_a__user", "profile_b__user")
        .filter(
            id=match_id,
            state__in=[Match.State.MASKED, Match.State.UNMASKED],
            profile_a__user__status="active",
            profile_b__user__status="active",
        )
        .first()
    )
    if not match or user_profile.id not in {match.profile_a_id, match.profile_b_id}:
        raise ValueError("match_not_found")
    if _blocked(match.profile_a, match.profile_b):
        raise ValueError("match_not_found")
    return match


@transaction.atomic
def close_match(profile: Profile, match_id):
    match = (
        Match.objects.select_for_update()
        .filter(
            Q(profile_a=profile) | Q(profile_b=profile),
            id=match_id,
        )
        .first()
    )
    if not match:
        raise ValueError("match_not_found")
    if match.state != Match.State.CLOSED:
        match.state = Match.State.CLOSED
        match.closed_by = profile
        match.a_unmask_consent_at = None
        match.b_unmask_consent_at = None
        match.save(
            update_fields=[
                "state",
                "closed_by",
                "a_unmask_consent_at",
                "b_unmask_consent_at",
                "updated_at",
            ]
        )
        other = match.profile_b if match.profile_a_id == profile.pk else match.profile_a
        _queue_event(user_id=other.user_id, event_type="match.closed", match_id=match.pk)
    return match


def _side(match: Match, profile: Profile) -> str:
    return "a" if match.profile_a_id == profile.id else "b"


def _verified(profile: Profile) -> bool:
    return profile.verification_level in {
        Profile.VerificationLevel.AGE_VERIFIED,
        Profile.VerificationLevel.VERIFIED,
    }


def _set_unmasked_if_ready(match: Match) -> None:
    if match.a_unmask_consent_at and match.b_unmask_consent_at:
        _ensure_reveal_consent(match)
        if settings.REQUIRE_VERIFICATION_PRE_UNMASK and not (
            _verified(match.profile_a) and _verified(match.profile_b)
        ):
            raise ValueError("verification_required_before_unmask")
        match.state = Match.State.UNMASKED
        match.unmasked_at = match.unmasked_at or timezone.now()


def _ensure_reveal_consent(match):
    if not all(
        has_active_consent(profile.user, "sensitive_data")
        for profile in (match.profile_a, match.profile_b)
    ):
        raise ValueError("sensitive_data_consent_required")


@transaction.atomic
def request_unmask(profile: Profile, match_id) -> Match:
    match = participant_match(profile, match_id)
    match = Match.objects.select_for_update().get(pk=match.pk)
    if match.state == Match.State.UNMASKED:
        return match
    if match.state != Match.State.MASKED:
        raise ValueError("match_not_masked")
    _ensure_reveal_consent(match)
    if settings.REQUIRE_VERIFICATION_PRE_UNMASK and not _verified(profile):
        raise ValueError("verification_required_before_unmask")
    side = _side(match, profile)
    if getattr(match, f"{side}_unmask_consent_at"):
        return match
    declined_at = getattr(match, f"{side}_unmask_declined_at")
    if declined_at and declined_at > timezone.now() - timedelta(hours=UNMASK_COOLDOWN_HOURS):
        raise ValueError("unmask_cooldown")
    setattr(match, f"{side}_unmask_consent_at", timezone.now())
    setattr(match, f"{side}_unmask_declined_at", None)
    _set_unmasked_if_ready(match)
    match.save(
        update_fields=[
            f"{side}_unmask_consent_at",
            f"{side}_unmask_declined_at",
            "state",
            "unmasked_at",
            "updated_at",
        ]
    )
    other = match.profile_b if match.profile_a_id == profile.id else match.profile_a
    if match.state == Match.State.UNMASKED:
        _queue_event(
            user_id=profile.user_id,
            event_type="reveal.accepted",
            match_id=match.id,
            actor_alias=other.alias,
        )
        _queue_event(
            user_id=other.user_id,
            event_type="reveal.accepted",
            match_id=match.id,
            actor_alias=profile.alias,
        )
    else:
        _queue_event(
            user_id=other.user_id,
            event_type="reveal.requested",
            match_id=match.id,
            actor_alias=profile.alias,
        )
    return match


@transaction.atomic
def respond_unmask(profile: Profile, match_id, accept: bool) -> Match:
    match = participant_match(profile, match_id)
    match = Match.objects.select_for_update().get(pk=match.pk)
    if accept and match.state == Match.State.UNMASKED:
        return match
    if match.state != Match.State.MASKED:
        raise ValueError("match_not_masked")
    requester_side = (
        "a" if match.a_unmask_consent_at else "b" if match.b_unmask_consent_at else None
    )
    if not requester_side:
        raise ValueError("unmask_request_not_found")
    if requester_side == _side(match, profile):
        raise ValueError("cannot_respond_to_own_reveal")
    if not accept:
        setattr(match, f"{requester_side}_unmask_consent_at", None)
        setattr(match, f"{requester_side}_unmask_declined_at", timezone.now())
        match.save(
            update_fields=[
                f"{requester_side}_unmask_consent_at",
                f"{requester_side}_unmask_declined_at",
                "updated_at",
            ]
        )
        requester = match.profile_a if requester_side == "a" else match.profile_b
        _queue_event(
            user_id=requester.user_id,
            event_type="reveal.declined",
            match_id=match.id,
            actor_alias=profile.alias,
        )
        return match
    if settings.REQUIRE_VERIFICATION_PRE_UNMASK and not _verified(profile):
        raise ValueError("verification_required_before_unmask")
    side = _side(match, profile)
    setattr(match, f"{side}_unmask_consent_at", timezone.now())
    _set_unmasked_if_ready(match)
    match.save(update_fields=[f"{side}_unmask_consent_at", "state", "unmasked_at", "updated_at"])
    other = match.profile_b if match.profile_a_id == profile.id else match.profile_a
    if match.state == Match.State.UNMASKED:
        _queue_event(
            user_id=profile.user_id,
            event_type="reveal.accepted",
            match_id=match.id,
            actor_alias=other.alias,
        )
        _queue_event(
            user_id=other.user_id,
            event_type="reveal.accepted",
            match_id=match.id,
            actor_alias=profile.alias,
        )
    return match


@transaction.atomic
def withdraw_unmask(profile: Profile, match_id) -> Match:
    match = participant_match(profile, match_id)
    match = Match.objects.select_for_update().get(pk=match.pk)
    if match.state != Match.State.MASKED:
        raise ValueError("unmask_withdrawal_unavailable")
    side = _side(match, profile)
    if not getattr(match, f"{side}_unmask_consent_at"):
        raise ValueError("unmask_request_not_found")
    setattr(match, f"{side}_unmask_consent_at", None)
    match.save(update_fields=[f"{side}_unmask_consent_at", "updated_at"])
    other = match.profile_b if side == "a" else match.profile_a
    _queue_event(user_id=other.user_id, event_type="reveal.withdrawn", match_id=match.id)
    return match


def revealed_identity(profile: Profile, match_id) -> dict:
    match = participant_match(profile, match_id)
    _ensure_reveal_consent(match)
    if match.state != Match.State.UNMASKED or not (
        match.a_unmask_consent_at and match.b_unmask_consent_at
    ):
        raise ValueError("unmask_not_consented")
    if settings.REQUIRE_VERIFICATION_PRE_UNMASK and not (
        _verified(match.profile_a) and _verified(match.profile_b)
    ):
        raise ValueError("verification_required_before_unmask")
    other = match.profile_b if match.profile_a_id == profile.id else match.profile_a
    identity = PrivateIdentity.objects.filter(user=other.user).first()
    if not identity:
        return {"profile": other, "identity": None}
    return {"profile": other, "identity": identity}
