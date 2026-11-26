import logging
from dataclasses import dataclass
from datetime import datetime

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.matching.services import _lock_pair, participant_match
from apps.safety.models import Block
from apps.safety.moderation import scan_text

from .models import Message

logger = logging.getLogger("anonymoke.chat")


@dataclass(frozen=True)
class MessageResult:
    message: Message
    flags: tuple[str, ...]


def _blocked(first, second) -> bool:
    return (
        Block.objects.filter(blocker=first, blocked=second).exists()
        or Block.objects.filter(blocker=second, blocked=first).exists()
    )


@transaction.atomic
def send_message(
    profile, match_id, body: str, client_message_id=None, reply_to_id=None, attachment_id=None
) -> MessageResult:
    match = participant_match(profile, match_id)
    if match.state == match.State.CLOSED:
        raise ValueError("match_closed")
    other = match.profile_b if match.profile_a_id == profile.id else match.profile_a
    if _blocked(profile, other):
        raise ValueError("messaging_blocked")
    normalized = body.strip()
    if not normalized and not attachment_id:
        raise ValueError("message_empty")
    if len(normalized) > settings.CHAT_MAX_MESSAGE_LENGTH:
        raise ValueError("message_too_long")
    _lock_pair(profile, other)
    if client_message_id:
        existing = Message.objects.filter(
            match=match, sender=profile, client_message_id=client_message_id
        ).first()
        if existing:
            if (
                existing.body != normalized
                or str(existing.reply_to_id or "") != str(reply_to_id or "")
                or str(existing.attachment_id or "") != str(attachment_id or "")
            ):
                raise ValueError("client_message_id_conflict")
            return MessageResult(message=existing, flags=())
    reply = None
    if reply_to_id:
        reply = Message.objects.filter(
            pk=reply_to_id, match=match, moderation_status="clear", deleted_at__isnull=True
        ).first()
        if not reply:
            raise ValueError("reply_message_unavailable")
    attachment = None
    if attachment_id:
        from .media import ensure_media_access
        from .models import ChatAttachment

        attachment = (
            ChatAttachment.objects.select_for_update(of=("self",))
            .filter(
                pk=attachment_id,
                sender=profile,
                match=match,
                status__in=["processing", "ready"],
                message__isnull=True,
            )
            .first()
        )
        if not attachment:
            raise ValueError("attachment_unavailable")
        ensure_media_access(profile, match_id, attachment.kind)
    flags = scan_text(normalized)
    categories = {flag.category for flag in flags}
    if match.state == match.State.MASKED and "contact_exchange" in categories:
        raise ValueError("contact_exchange_not_allowed")
    status = Message.ModerationStatus.QUEUED
    message = Message.objects.create(
        match=match,
        sender=profile,
        body=normalized,
        moderation_status=status,
        client_message_id=client_message_id,
        reply_to=reply,
        attachment=attachment,
    )
    from apps.safety.tasks import scan_content

    def enqueue_moderation():
        try:
            scan_content.delay(str(profile.user_id), "message", str(message.id), "")
            Message.objects.filter(pk=message.pk).update(moderation_queued_at=timezone.now())
        except Exception:  # noqa: BLE001 - queue outages must not lose the message
            logger.warning("message_moderation_queue_unavailable", exc_info=True)

    transaction.on_commit(enqueue_moderation)
    return MessageResult(message=message, flags=tuple(flag.category for flag in flags))


def publish_approved_message(message):
    try:
        participant_match(message.sender, message.match_id)
    except ValueError:
        return
    match = message.match
    profile = message.sender
    other = match.profile_b if match.profile_a_id == profile.id else match.profile_a

    def publish_realtime():
        try:
            _publish_message(message)
        except Exception:  # noqa: BLE001 - realtime delivery has polling fallback
            logger.warning("message_realtime_delivery_unavailable", exc_info=True)

    def enqueue_notification():
        try:
            from apps.notifications.service import enqueue_user_event

            enqueue_user_event(
                user_id=other.user_id,
                event_type="chat.message",
                match_id=match.id,
                actor_alias=profile.alias,
            )
        except Exception:  # noqa: BLE001 - push delivery must not break messaging
            logger.warning("message_notification_enqueue_unavailable", exc_info=True)

    transaction.on_commit(publish_realtime)
    transaction.on_commit(enqueue_notification)


@transaction.atomic
def moderate_message(message_id):
    import hashlib

    from apps.safety.models import ModerationFlagRecord

    message = (
        Message.objects.select_for_update(of=("self",))
        .select_related("match", "sender__user")
        .filter(pk=message_id)
        .first()
    )
    if not message or message.moderation_status != Message.ModerationStatus.QUEUED:
        return 0
    if message.attachment_id:
        asset = message.attachment
        if asset.status not in {"ready", "rejected"}:
            return 0
        if asset.status == "rejected":
            message.moderation_status = Message.ModerationStatus.BLOCKED
            message.save(update_fields=["moderation_status", "updated_at"])
            return 0
    try:
        participant_match(message.sender, message.match_id)
    except ValueError:
        message.moderation_status = Message.ModerationStatus.BLOCKED
        message.save(update_fields=["moderation_status", "updated_at"])
        return 0
    flags = scan_text(message.body)
    if message.match.state == message.match.State.UNMASKED:
        flags = [flag for flag in flags if flag.category != "contact_exchange"]
    message.moderation_status = (
        Message.ModerationStatus.FLAGGED if flags else Message.ModerationStatus.CLEAR
    )
    message.save(update_fields=["moderation_status", "updated_at"])
    if flags:
        ModerationFlagRecord.objects.create(
            subject_user_id=message.sender.user_id,
            content_type="message",
            content_id=message.id,
            content_digest=hashlib.sha256(message.body.encode()).hexdigest(),
            categories=[flag.category for flag in flags],
            layer=1,
            score=max(flag.score for flag in flags),
        )
    elif not message.deleted_at:
        publish_approved_message(message)
    return len(flags)


def _publish_message(message: Message) -> None:
    if message.moderation_status != Message.ModerationStatus.CLEAR or message.deleted_at:
        return
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return
    async_to_sync(channel_layer.group_send)(
        f"match-{message.match_id}",
        {
            "type": "chat.message",
            "message_id": str(message.id),
            "sender_profile_id": str(message.sender.public_id),
            "body": message.body,
            "moderation_status": message.moderation_status,
            "created_at": message.created_at.isoformat(),
            "read_at": message.read_at.isoformat() if message.read_at else None,
        },
    )


def list_messages(profile, match_id, before: datetime | None, limit: int = 50):
    match = participant_match(profile, match_id)
    queryset = visible_messages(profile, match)
    if before:
        queryset = queryset.filter(created_at__lt=before)
    return list(queryset.order_by("-created_at", "-id")[: min(limit, 100)])[::-1]


def visible_messages(profile, match):
    return (
        Message.objects.filter(match=match, deleted_at__isnull=True)
        .filter(Q(sender=profile) | Q(moderation_status=Message.ModerationStatus.CLEAR))
        .select_related(
            "sender", "attachment__sender__user", "reply_to__sender", "reply_to__attachment"
        )
    )


@transaction.atomic
def mark_read(profile, match_id, through_message_id=None) -> int:
    match = participant_match(profile, match_id)
    queryset = Message.objects.filter(
        match=match,
        read_at__isnull=True,
        deleted_at__isnull=True,
        moderation_status=Message.ModerationStatus.CLEAR,
    ).exclude(sender=profile)
    if through_message_id:
        anchor = visible_messages(profile, match).filter(pk=through_message_id).first()
        if not anchor:
            raise ValueError("message_not_found")
        queryset = queryset.filter(
            Q(created_at__lt=anchor.created_at) | Q(created_at=anchor.created_at, pk__lte=anchor.pk)
        )
    now = timezone.now()
    count = queryset.update(read_at=now, delivered_at=Coalesce("delivered_at", now), updated_at=now)
    if count:
        _publish_receipts(match_id)
    return count


def _publish_receipts(match_id):
    def publish():
        try:
            layer = get_channel_layer()
            if layer:
                async_to_sync(layer.group_send)(f"match-{match_id}", {"type": "chat.receipts"})
        except Exception:  # noqa: BLE001
            logger.debug("chat_receipt_realtime_unavailable")

    transaction.on_commit(publish)


@transaction.atomic
def mark_delivered(profile, match_id, message_ids):
    match = participant_match(profile, match_id)
    if not message_ids or len(message_ids) > 100:
        return 0
    messages = Message.objects.filter(
        pk__in=message_ids, match=match, moderation_status="clear", deleted_at__isnull=True
    ).exclude(sender=profile)
    if messages.count() != len(set(message_ids)):
        raise ValueError("message_not_found")
    now = timezone.now()
    count = messages.filter(delivered_at__isnull=True).update(delivered_at=now, updated_at=now)
    if count:
        _publish_receipts(match_id)
    return count


@transaction.atomic
def review_message(message_id, *, approve, actor, reason):
    from apps.compliance.models import AuditLog
    from apps.safety.models import ModerationFlagRecord

    message = (
        Message.objects.select_for_update(of=("self",))
        .select_related("sender__user", "match")
        .filter(pk=message_id, deleted_at__isnull=True)
        .first()
    )
    if not message:
        raise ValueError("message_not_found")
    desired = Message.ModerationStatus.CLEAR if approve else Message.ModerationStatus.BLOCKED
    if message.moderation_status == desired:
        return message
    if message.moderation_status not in {
        Message.ModerationStatus.FLAGGED,
        Message.ModerationStatus.BLOCKED,
    }:
        raise ValueError("message_review_unavailable")
    if approve:
        participant_match(message.sender, message.match_id)
    previous = message.moderation_status
    message.moderation_status = desired
    message.save(update_fields=["moderation_status", "updated_at"])
    ModerationFlagRecord.objects.filter(content_type="message", content_id=message.pk).update(
        status="dismissed" if approve else "confirmed"
    )
    AuditLog.objects.create(
        actor_user_id=actor.pk,
        action="message_moderation_reviewed",
        object_type="message",
        object_id=message.pk,
        metadata={"previous_status": previous, "status": desired, "reason": reason},
    )
    if approve:
        publish_approved_message(message)
    return message
