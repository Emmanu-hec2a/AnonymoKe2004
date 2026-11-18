from datetime import date
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import timezone
from rest_framework import serializers

from apps.core.crypto import encrypt_text
from apps.safety.moderation import scan_text

from .models import MatchingPreference, MediaAsset, Profile
from .storage import R2MediaStore
from .validation import (
    age_on,
    validate_age_preferences,
    validate_alias,
    validate_birth_date,
    validate_distance_preference,
    validate_target_genders,
)


def _validate_target_genders(value):
    try:
        return validate_target_genders(value)
    except ValueError as exc:
        raise serializers.ValidationError(str(exc)) from exc


class ProfileSerializer(serializers.ModelSerializer):
    birth_date = serializers.DateField(write_only=True, required=False)
    onboarding_photo_upload_id = serializers.UUIDField(write_only=True, required=False)
    language = serializers.ChoiceField(choices=["en", "sw"], required=False)
    target_genders = serializers.ListField(
        source="matching_preference.target_genders",
        child=serializers.ChoiceField(choices=["M", "W", "NB", "ALL"]),
        required=False,
        allow_empty=False,
        max_length=3,
    )
    avatar_url = serializers.SerializerMethodField()
    avatar_thumbnail_url = serializers.SerializerMethodField()
    has_avatar = serializers.SerializerMethodField()
    blurred_avatar_url = serializers.SerializerMethodField()
    audio_url = serializers.SerializerMethodField()
    audio_disguised = serializers.BooleanField(read_only=True)
    audio_duration_ms = serializers.IntegerField(read_only=True)

    class Meta:
        model = Profile
        fields = [
            "public_id",
            "alias",
            "gender",
            "birth_date",
            "onboarding_photo_upload_id",
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
            "target_genders",
            "avatar_url",
            "avatar_thumbnail_url",
            "has_avatar",
            "blurred_avatar_url",
            "audio_url",
            "audio_disguised",
            "audio_duration_ms",
        ]
        read_only_fields = ["public_id", "age_years", "verification_level"]

    def validate_birth_date(self, value: date) -> date:
        try:
            today = timezone.localdate(timezone=ZoneInfo("Africa/Nairobi"))
            return validate_birth_date(value, today)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc

    def update(self, instance, validated_data):
        validated_data.pop("onboarding_photo_upload_id", None)
        preference = validated_data.pop("matching_preference", None)
        birth_date = validated_data.pop("birth_date", None)
        if birth_date:
            today = timezone.localdate(timezone=ZoneInfo("Africa/Nairobi"))
            instance.birth_date_ciphertext = encrypt_text(birth_date.isoformat())
            instance.age_years = age_on(birth_date, today)
        result = super().update(instance, validated_data)
        if preference is not None:
            MatchingPreference.objects.update_or_create(profile=instance, defaults=preference)
            instance._state.fields_cache.pop("matching_preference", None)
        return result

    def validate_onboarding_photo_upload_id(self, value):
        if self.instance is None:
            raise serializers.ValidationError("photo_not_ready")
        asset = MediaAsset.objects.filter(
            pk=value, user_id=self.instance.user_id, kind="avatar", status="ready"
        ).first()
        identity = getattr(self.instance.user, "private_identity", None)
        if not (
            asset
            and asset.original_key
            and asset.derived_key
            and identity
            and identity.real_avatar_key == asset.original_key
            and self.instance.blurred_avatar_key == asset.derived_key
        ):
            raise serializers.ValidationError("photo_not_ready")
        return value

    def validate_alias(self, value):
        try:
            return validate_alias(value)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc

    def validate_height_cm(self, value):
        if value is not None and not 100 <= value <= 250:
            raise serializers.ValidationError("height_invalid")
        return value

    def validate_interests(self, value):
        if not isinstance(value, list) or len(value) > 10:
            raise serializers.ValidationError("interests_invalid")
        normalized = []
        for item in value:
            if not isinstance(item, str) or not 2 <= len(item.strip()) <= 24:
                raise serializers.ValidationError("interests_invalid")
            item = item.strip()
            if item.casefold() in {old.casefold() for old in normalized}:
                raise serializers.ValidationError("interests_duplicate")
            normalized.append(item)
        return normalized

    def validate_target_genders(self, value):
        return _validate_target_genders(value)

    def _url(self, key, *, private=False):
        if not key:
            return None
        try:
            store = self.context.setdefault("media_store", None)
            if store is None:
                store = self.context["media_store"] = R2MediaStore()
            return store.presign_private(key) if private else store.presign_derived(key)
        except Exception:  # noqa: BLE001 - unavailable media must not hide profile controls
            return None

    def get_avatar_url(self, obj):
        identity = getattr(obj.user, "private_identity", None)
        return self._url(identity.real_avatar_key if identity else "", private=True)

    def get_has_avatar(self, obj):
        identity = getattr(obj.user, "private_identity", None)
        return bool(identity and identity.real_avatar_key)

    def get_avatar_thumbnail_url(self, obj):
        identity = getattr(obj.user, "private_identity", None)
        if not identity or not identity.real_avatar_key:
            return None
        asset = (
            MediaAsset.objects.filter(
                user_id=obj.user_id,
                kind="avatar",
                status="ready",
                original_key=identity.real_avatar_key,
            )
            .exclude(thumbnail_key="")
            .only("thumbnail_key")
            .first()
        )
        return self._url(asset.thumbnail_key, private=True) if asset else None

    def get_blurred_avatar_url(self, obj):
        return self._url(obj.blurred_avatar_key)

    def get_audio_url(self, obj):
        from apps.compliance.consent import has_active_consent

        return (
            self._url(obj.audio_key, private=True)
            if has_active_consent(obj.user, "voice")
            else None
        )

    def validate(self, attrs):
        for key in ("alias", "bio", "interests"):
            if key in attrs:
                text = " ".join(attrs[key]) if key == "interests" else attrs[key]
                if any(
                    flag.category in {"contact_exchange", "commercial_sexual"}
                    or len(flag.matched_terms) >= 2
                    for flag in scan_text(text)
                ):
                    raise serializers.ValidationError("profile_content_not_allowed")
        min_age = attrs.get("min_age_pref", self.instance.min_age_pref if self.instance else 18)
        max_age = attrs.get("max_age_pref", self.instance.max_age_pref if self.instance else 35)
        distance = attrs.get(
            "max_distance_km", self.instance.max_distance_km if self.instance else 15
        )
        try:
            validate_age_preferences(min_age, max_age)
            validate_distance_preference(distance)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc
        return attrs


class MatchingPreferenceWriteSerializer(serializers.Serializer):
    target_genders = serializers.ListField(
        child=serializers.ChoiceField(choices=["M", "W", "NB", "ALL"]),
        allow_empty=False,
        max_length=3,
    )

    def validate_target_genders(self, value):
        return _validate_target_genders(value)


class LocationUpdateSerializer(serializers.Serializer):
    lat = serializers.FloatField()
    lon = serializers.FloatField()
    accuracy_m = serializers.FloatField(min_value=0)
    is_mock = serializers.BooleanField(default=False)
    captured_at = serializers.DateTimeField()


class MediaUploadSerializer(serializers.Serializer):
    disguise_voice = serializers.BooleanField(default=True)
    kind = serializers.ChoiceField(choices=MediaAsset.Kind.values)
    content_type = serializers.ChoiceField(
        choices=[
            "image/jpeg",
            "image/png",
            "image/webp",
            "audio/mp4",
            "audio/x-m4a",
        ]
    )
    size_bytes = serializers.IntegerField(min_value=1)

    def validate(self, attrs):
        maximum = (
            settings.MEDIA_AVATAR_MAX_BYTES
            if attrs["kind"] == MediaAsset.Kind.AVATAR
            else settings.MEDIA_AUDIO_MAX_BYTES
        )
        if attrs["size_bytes"] > maximum:
            raise serializers.ValidationError("media_too_large")
        if attrs["kind"] == MediaAsset.Kind.AVATAR and not attrs["content_type"].startswith(
            "image/"
        ):
            raise serializers.ValidationError("avatar_content_type_invalid")
        if attrs["kind"] == MediaAsset.Kind.AUDIO and not attrs["content_type"].startswith(
            "audio/"
        ):
            raise serializers.ValidationError("audio_content_type_invalid")
        return attrs


class MediaCompleteSerializer(serializers.Serializer):
    upload_id = serializers.UUIDField()


class MediaStatusSerializer(serializers.ModelSerializer):
    upload_id = serializers.UUIDField(source="id")

    class Meta:
        model = MediaAsset
        fields = ["upload_id", "kind", "status", "duration_ms", "rejection_code", "created_at"]
        read_only_fields = fields
