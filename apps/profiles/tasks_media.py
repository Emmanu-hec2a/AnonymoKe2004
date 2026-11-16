import logging
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.accounts.models import User
from apps.compliance.consent import has_active_consent

from .media import MediaRejected, process_audio, process_avatar
from .models import MediaAsset, PrivateIdentity, Profile
from .storage import MediaPayloadTooLarge, R2MediaStore


@shared_task(queue="media")
def process_media_asset(asset_id: str) -> str:
    # Claim briefly; decoding runs without holding account locks.
    now = timezone.now()
    claimed = (
        MediaAsset.objects.filter(pk=asset_id, status="processing")
        .filter(
            Q(processing_queued_at__isnull=True)
            | Q(processing_queued_at__lt=now - timedelta(minutes=2))
        )
        .update(processing_queued_at=now)
    )
    if not claimed:
        return "pending"
    asset = MediaAsset.objects.filter(pk=asset_id).first()
    if not asset:
        return "removed"
    try:
        original_key = (
            f"media/original/{asset.pk}.jpg"
            if asset.kind == "avatar"
            else f"media/audio/{asset.pk}.m4a"
        )
        derived_key = f"media/derived/{asset.pk}.jpg" if asset.kind == "avatar" else ""
        # Record every possible object before any upload, including partial failures.
        MediaAsset.objects.filter(pk=asset.pk, processing_queued_at=now).update(
            original_key=original_key, derived_key=derived_key
        )
        store = R2MediaStore()
        try:
            payload = store.download(
                asset.incoming_key,
                max_bytes=(
                    settings.MEDIA_AVATAR_MAX_BYTES
                    if asset.kind == "avatar"
                    else settings.MEDIA_AUDIO_MAX_BYTES
                ),
            )
        except MediaPayloadTooLarge as exc:
            raise MediaRejected("media_size_invalid") from exc
        if asset.kind == "avatar":
            original, derived = process_avatar(asset, payload)
            original_key, derived_key = (
                f"media/original/{asset.pk}.jpg",
                f"media/derived/{asset.pk}.jpg",
            )
        else:
            original, duration = process_audio(asset, payload)
            original_key, derived_key = f"media/audio/{asset.pk}.m4a", ""
        with transaction.atomic():
            # Erasure and media publication take the same account lock first.
            user = (
                User.objects.select_for_update().filter(pk=asset.user_id, status="active").first()
            )
            if not user:
                return "removed"
            current = (
                MediaAsset.objects.select_for_update()
                .filter(pk=asset.pk, status="processing", processing_queued_at=now)
                .first()
            )
            if not current:
                return "superseded"
            if asset.kind == "audio" and not has_active_consent(user, "voice"):
                raise MediaRejected("voice_consent_required")
            if asset.kind == "avatar":
                for kind in ("privacy", "sensitive_data"):
                    if not has_active_consent(user, kind):
                        raise MediaRejected(f"{kind}_consent_required")
            store.upload_private(
                original_key, original, "image/jpeg" if asset.kind == "avatar" else "audio/mp4"
            )
            if derived_key:
                store.upload_derived(derived_key, derived, "image/jpeg")
            newer = MediaAsset.objects.filter(
                user=user, kind=asset.kind, status="ready", created_at__gt=asset.created_at
            ).exists()
            profile, _ = Profile.objects.get_or_create(user=user)
            if asset.kind == "avatar" and not newer:
                identity, _ = PrivateIdentity.objects.get_or_create(user=user)
                identity.real_avatar_key = original_key
                identity.save(update_fields=["real_avatar_key", "updated_at"])
                profile.blurred_avatar_key = derived_key
            elif asset.kind == "audio":
                current.duration_ms = duration
                if not newer:
                    profile.audio_key = original_key
                    profile.audio_duration_ms = duration
                    profile.audio_disguised = asset.disguise_voice
            profile.save()
            current.status = "ready"
            current.original_key, current.derived_key = original_key, derived_key
            current.rejection_code = ""
            current.save()
            return "ready"
    except MediaRejected as exc:
        MediaAsset.objects.filter(pk=asset.pk, processing_queued_at=now).update(
            status="rejected", rejection_code=str(exc)
        )
        return "rejected"
    except Exception:  # noqa: BLE001 - beat retries sanitized infrastructure failures
        attempts = asset.processing_attempts + 1
        MediaAsset.objects.filter(pk=asset.pk, processing_queued_at=now).update(
            processing_attempts=attempts,
            rejection_code="media_processing_unavailable",
            status="rejected" if attempts >= 5 else "processing",
        )
        return "retry_pending"


@shared_task(queue="media")
def recover_media_processing():
    ids = (
        MediaAsset.objects.filter(status="processing")
        .filter(
            Q(processing_queued_at__isnull=True)
            | Q(processing_queued_at__lt=timezone.now() - timedelta(minutes=2))
        )
        .values_list("pk", flat=True)[:100]
    )
    for asset_id in ids:
        try:
            process_media_asset.delay(str(asset_id))
        except Exception:  # noqa: BLE001 - next beat retains the processing intent
            logging.getLogger("anonymoke.media").warning("media_dispatch_pending")
            break
