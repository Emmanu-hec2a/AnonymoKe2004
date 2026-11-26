from dataclasses import dataclass, field

from django.conf import settings
from django.db import transaction

from apps.accounts.models import User
from apps.profiles.models import MediaAsset, PrivateIdentity, Profile
from apps.store.models import FinancialTransaction, Purchase

from .storage import ObjectStorageDeletionAdapter, R2ObjectStorageDeletionAdapter


@dataclass
class PurgeResult:
    user_id: str
    deleted_objects: list[str] = field(default_factory=list)
    retained_financial_transactions: int = 0


def default_object_storage() -> ObjectStorageDeletionAdapter:
    if settings.R2_ENDPOINT_URL:
        return R2ObjectStorageDeletionAdapter()
    if not settings.DEBUG:
        raise RuntimeError("r2_not_configured")
    return ObjectStorageDeletionAdapter()


@transaction.atomic
def purge_user_data(
    user_id: str, storage: ObjectStorageDeletionAdapter | None = None
) -> PurgeResult:
    user = User.objects.select_for_update().get(pk=user_id)
    keys = list(dict.fromkeys(_media_keys_for_user(user)))
    if keys:
        (storage or default_object_storage()).delete_keys(keys)
    financial_count = FinancialTransaction.objects.filter(user=user).count()
    FinancialTransaction.objects.filter(user=user).update(
        user=None, account_reference_hash="purged"
    )
    Purchase.objects.filter(user=user).update(user=None, phone_hash="purged", phone_ciphertext=b"")
    result = PurgeResult(
        user_id=str(user.id),
        deleted_objects=["user_cascade", "media_objects"],
        retained_financial_transactions=financial_count,
    )
    user.delete()
    return result


def _media_keys_for_user(user: User) -> list[str]:
    keys: list[str] = []
    from apps.chat.models import ChatAttachment

    for asset in ChatAttachment.objects.filter(sender__user=user).only(
        "incoming_key", "object_key"
    ):
        keys.extend([asset.incoming_key, asset.object_key])
    for asset in MediaAsset.objects.filter(user=user).only(
        "kind", "incoming_key", "original_key", "derived_key", "thumbnail_key"
    ):
        keys.extend(
            [asset.incoming_key, asset.original_key, asset.derived_key, asset.thumbnail_key]
        )
        if asset.kind == "avatar":
            keys.append(f"media/thumbnails/{asset.pk}.jpg")
    identity = PrivateIdentity.objects.filter(user=user).first()
    if identity:
        keys.append(identity.real_avatar_key)
    try:
        profile = user.profile
    except Profile.DoesNotExist:
        return [key for key in keys if key]
    keys.extend([profile.blurred_avatar_key, profile.audio_key])
    return [key for key in keys if key]
