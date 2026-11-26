from datetime import timedelta

from django.db.models import Count, F, IntegerField, OuterRef, Q, Subquery, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.chat.models import Message
from apps.safety.models import Block

from .models import Match


def inbox_queryset(profile):
    blocked = Block.objects.filter(blocker=profile).values("blocked_id")
    blockers = Block.objects.filter(blocked=profile).values("blocker_id")
    visible = Message.objects.filter(match_id=OuterRef("pk"), deleted_at__isnull=True).filter(
        Q(sender=profile) | Q(moderation_status="clear")
    )
    latest = visible.order_by("-created_at", "-pk")
    unread = visible.filter(read_at__isnull=True, moderation_status="clear").exclude(sender=profile)
    unread = unread.order_by().values("match_id").annotate(total=Count("pk")).values("total")
    return (
        Match.objects.filter(
            Q(profile_a=profile) | Q(profile_b=profile),
            state__in=["masked", "unmasked"],
            profile_a__user__status="active",
            profile_b__user__status="active",
        )
        .exclude(Q(profile_a_id__in=blocked) | Q(profile_b_id__in=blocked))
        .exclude(Q(profile_a_id__in=blockers) | Q(profile_b_id__in=blockers))
        .select_related("profile_a__user", "profile_b__user")
        .annotate(
            activity_at=Coalesce(Subquery(latest.values("created_at")[:1]), F("created_at")),
            last_body=Subquery(latest.values("body")[:1]),
            last_status=Subquery(latest.values("moderation_status")[:1]),
            last_attachment_kind=Subquery(latest.values("attachment__kind")[:1]),
            last_sender=Subquery(latest.values("sender_id")[:1]),
            unread_count=Coalesce(Subquery(unread[:1]), Value(0), output_field=IntegerField()),
        )
        .order_by("-activity_at", "-pk")
    )


def match_summary(match, profile, store=None):
    other = match.profile_b if match.profile_a_id == profile.id else match.profile_a
    side = "a" if match.profile_a_id == profile.pk else "b"
    other_side = "b" if side == "a" else "a"
    own_request = getattr(match, f"{side}_unmask_consent_at")
    incoming_request = getattr(match, f"{other_side}_unmask_consent_at")
    reveal = (
        "revealed"
        if match.state == "unmasked"
        else "incoming"
        if incoming_request
        else "outgoing"
        if own_request
        else "none"
    )
    declined = getattr(match, f"{side}_unmask_declined_at")
    cooldown = declined + timedelta(hours=24) if declined else None
    if cooldown and cooldown <= timezone.now():
        cooldown = None
    preview = getattr(match, "last_body", None)
    if not preview and getattr(match, "last_attachment_kind", None):
        preview = "Photo" if match.last_attachment_kind == "image" else "Voice note"
    status = getattr(match, "last_status", None)
    if status and status != "clear":
        preview = {
            "queued": "Checking your message…",
            "flagged": "Message under review",
            "blocked": "Message not delivered",
        }.get(status, "Message unavailable")
    elif preview and getattr(match, "last_sender", None) == profile.pk:
        preview = f"You: {preview}"
    return {
        "match_id": str(match.pk),
        "profile_id": str(other.public_id),
        "viewer_profile_id": str(profile.public_id),
        "alias": other.alias,
        "age_years": other.age_years,
        "state": match.state,
        "created_at": match.created_at,
        "activity_at": getattr(match, "activity_at", match.created_at),
        "last_message": preview[:180] if preview else None,
        "unread_count": getattr(match, "unread_count", 0),
        "reveal_status": reveal,
        "reveal_cooldown_until": cooldown,
        "blurred_avatar_url": store.presign_derived(other.blurred_avatar_key)
        if store and other.blurred_avatar_key
        else None,
        "is_verified": other.verification_level != "none",
    }
