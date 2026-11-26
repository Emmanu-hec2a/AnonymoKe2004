import logging
from datetime import timedelta
from io import BytesIO
from types import SimpleNamespace

from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from PIL import Image, ImageOps

from apps.accounts.models import User
from apps.compliance.consent import has_active_consent
from apps.matching.services import participant_match
from apps.profiles.media import MediaRejected, process_audio
from apps.profiles.storage import MediaPayloadTooLarge, R2MediaStore

from .models import ChatAttachment, Message


def ensure_media_access(profile, match_id, kind):
    match = participant_match(profile, match_id)
    if kind == "image":
        if match.state != "unmasked":
            raise ValueError("photos_require_mutual_reveal")
        for member in (match.profile_a, match.profile_b):
            if not has_active_consent(member.user, "sensitive_data"):
                raise ValueError("sensitive_data_consent_required")
            if settings.REQUIRE_VERIFICATION_PRE_UNMASK and member.verification_level == "none":
                raise ValueError("verification_required_before_unmask")
    elif kind == "audio":
        if not has_active_consent(profile.user, "voice"):
            raise ValueError("voice_consent_required")
    else:
        raise ValueError("attachment_kind_invalid")
    return match


def attachment_data(asset, viewer, context=None, *, message=None):
    context = context if context is not None else {}
    key = ("chat_match", viewer.pk, asset.match_id)
    if key not in context:
        context[key] = participant_match(viewer, asset.match_id)
    match = context[key]
    if message is None:
        message = Message.objects.filter(
            attachment=asset, match=match, deleted_at__isnull=True
        ).first()
    elif message.match_id != match.pk or message.attachment_id != asset.pk or message.deleted_at:
        raise ValueError("attachment_not_found")
    if asset.sender_id != viewer.pk and (not message or message.moderation_status != "clear"):
        raise ValueError("attachment_not_found")
    access_key = ("chat_access", asset.sender_id, asset.match_id, asset.kind)
    if access_key not in context:
        ensure_media_access(asset.sender, asset.match_id, asset.kind)
        context[access_key] = True
    url = None
    if asset.status == "ready" and asset.object_key:
        if "chat_media_store" not in context:
            context["chat_media_store"] = R2MediaStore()
        url = context["chat_media_store"].presign_private(asset.object_key, ttl_seconds=60)
    return {
        "id": str(asset.pk),
        "kind": asset.kind,
        "status": asset.status,
        "url": url,
        "width": asset.width,
        "height": asset.height,
        "duration_ms": asset.duration_ms,
        "voice_disguised": asset.disguise_voice if asset.kind == "audio" else False,
        "error_code": asset.rejection_code or None,
    }


def sanitize_image(payload):
    try:
        with Image.open(BytesIO(payload)) as source:
            if source.format not in {"JPEG", "PNG", "WEBP"} or getattr(source, "n_frames", 1) != 1:
                raise MediaRejected("image_format_invalid")
            width, height = source.size
            if min(width, height) < 32 or max(width, height) > 8000 or width * height > 32000000:
                raise MediaRejected("image_dimensions_invalid")
            image = ImageOps.contain(ImageOps.exif_transpose(source).convert("RGB"), (1600, 1600))
            output = BytesIO()
            image.save(output, "JPEG", quality=82, optimize=True, exif=b"")
            return output.getvalue(), image.width, image.height
    except (OSError, ValueError, Image.DecompressionBombError) as error:
        raise MediaRejected("image_invalid") from error


@shared_task(queue="media")
def process_chat_attachment(asset_id):
    now = timezone.now()
    claim = (
        ChatAttachment.objects.filter(pk=asset_id, status="processing")
        .filter(
            Q(processing_started_at__isnull=True)
            | Q(processing_started_at__lt=now - timedelta(minutes=2))
        )
        .update(processing_started_at=now)
    )
    if not claim:
        return "pending"
    asset = ChatAttachment.objects.select_related("sender__user").filter(pk=asset_id).first()
    if not asset:
        return "removed"
    key = f"chat/processed/{asset.pk}.{'jpg' if asset.kind == 'image' else 'm4a'}"
    ChatAttachment.objects.filter(pk=asset.pk).update(object_key=key)
    try:
        ensure_media_access(asset.sender, asset.match_id, asset.kind)
        store = R2MediaStore()
        payload = store.download(
            asset.incoming_key, max_bytes=10485760 if asset.kind == "image" else 5242880
        )
        if asset.kind == "image":
            result, width, height = sanitize_image(payload)
            duration = 0
        else:
            result, duration = process_audio(
                SimpleNamespace(disguise_voice=asset.disguise_voice), payload, max_duration_ms=60000
            )
            width = height = 0
        with transaction.atomic():
            user = (
                User.objects.select_for_update()
                .filter(pk=asset.sender.user_id, status="active")
                .first()
            )
            if not user:
                return "removed"
            current = (
                ChatAttachment.objects.select_for_update(of=("self",))
                .filter(pk=asset.pk, status="processing", processing_started_at=now)
                .first()
            )
            if not current:
                return "superseded"
            ensure_media_access(asset.sender, asset.match_id, asset.kind)
            store.upload_private(
                key, result, "image/jpeg" if asset.kind == "image" else "audio/mp4"
            )
            current.status, current.width, current.height, current.duration_ms = (
                "ready",
                width,
                height,
                duration,
            )
            current.rejection_code = ""
            current.save()
    except (MediaRejected, MediaPayloadTooLarge, ValueError) as error:
        ChatAttachment.objects.filter(pk=asset.pk, processing_started_at=now).update(
            status="rejected", rejection_code=str(error)[:64]
        )
    except Exception as error:  # noqa: BLE001 - retain an intent for recovery, never log media URLs
        attempts = asset.attempts + 1
        ChatAttachment.objects.filter(pk=asset.pk, processing_started_at=now).update(
            attempts=attempts,
            status="rejected" if attempts >= 5 else "processing",
            rejection_code="media_processing_unavailable",
        )
        logging.getLogger("anonymoke.chat").warning(
            "chat_media_processing_unavailable (%s)", type(error).__name__
        )
    from .services import moderate_message

    for message_id in Message.objects.filter(
        attachment_id=asset.pk, moderation_status="queued"
    ).values_list("pk", flat=True):
        moderate_message(message_id)
    return "processed"


@shared_task(queue="media")
def recover_chat_attachments():
    cutoff = timezone.now() - timedelta(minutes=2)
    for asset_id in (
        ChatAttachment.objects.filter(status="processing")
        .filter(Q(processing_started_at__isnull=True) | Q(processing_started_at__lt=cutoff))
        .values_list("pk", flat=True)[:100]
    ):
        try:
            process_chat_attachment.apply_async(args=[str(asset_id)], retry=False)
        except Exception:  # noqa: BLE001
            break


@shared_task(queue="media")
def purge_unused_chat_uploads():
    from apps.compliance.services import default_object_storage

    # The account lock serializes deletion with media publication and erasure.
    for asset in ChatAttachment.objects.filter(
        message__isnull=True, created_at__lt=timezone.now() - timedelta(days=1)
    )[:100]:
        with transaction.atomic():
            if not User.objects.select_for_update().filter(pk=asset.sender.user_id).exists():
                continue
            current = (
                ChatAttachment.objects.select_for_update(of=("self",))
                .filter(pk=asset.pk, message__isnull=True)
                .first()
            )
            if current:
                try:
                    default_object_storage().delete_keys(
                        [key for key in (current.incoming_key, current.object_key) if key]
                    )
                except RuntimeError:
                    continue
                current.delete()
