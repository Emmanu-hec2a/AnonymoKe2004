import logging
import uuid

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.compliance.consent import has_active_consent

from .models import MatchingPreference, MediaAsset, PrivateIdentity, Profile
from .serializers import (
    LocationUpdateSerializer,
    MatchingPreferenceWriteSerializer,
    MediaCompleteSerializer,
    MediaStatusSerializer,
    MediaUploadSerializer,
    ProfileSerializer,
)
from .services import update_snapped_location
from .storage import MediaStorageUnavailable, R2MediaStore
from .tasks_media import process_media_asset


class ProfileAPI(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "profile_read"

    def get_throttles(self):
        if (
            self.request.method not in ("GET", "HEAD", "OPTIONS")
            and self.throttle_scope == "profile_read"
        ):
            self.throttle_scope = "profile_write"
        return super().get_throttles()

    def handle_exception(self, exc):
        if isinstance(exc, ObjectDoesNotExist):
            return Response({"error": {"code": "resource_not_found"}}, status=404)
        if isinstance(exc, ValidationError):
            detail = exc.detail
            while isinstance(detail, (dict, list)):
                detail = next(iter(detail.values())) if isinstance(detail, dict) else detail[0]
            return Response({"error": {"code": str(detail), "fields": exc.detail}}, status=400)
        return super().handle_exception(exc)


class ProfileView(ProfileAPI):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile, _ = Profile.objects.get_or_create(user=request.user)
        return Response(ProfileSerializer(profile).data)

    @transaction.atomic
    def patch(self, request):
        type(request.user).objects.select_for_update().get(pk=request.user.pk, status="active")
        if "onboarding_photo_upload_id" in request.data:
            for kind in ("terms", "privacy", "location", "sensitive_data"):
                if not has_active_consent(request.user, kind):
                    return Response({"error": {"code": f"{kind}_consent_required"}}, status=403)
        if {"gender", "birth_date", "min_age_pref", "max_age_pref", "target_genders"}.intersection(
            request.data
        ) and not has_active_consent(request.user, "sensitive_data"):
            return Response({"error": {"code": "sensitive_data_consent_required"}}, status=403)
        if "max_distance_km" in request.data and not has_active_consent(request.user, "location"):
            return Response({"error": {"code": "location_consent_required"}}, status=403)
        profile, _ = Profile.objects.get_or_create(user=request.user)
        serializer = ProfileSerializer(profile, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        has_photo = (
            bool(profile.blurred_avatar_key)
            and PrivateIdentity.objects.filter(user=request.user)
            .exclude(real_avatar_key="")
            .exists()
        )
        request.user.is_onboarded = bool(
            profile.alias
            and profile.gender
            and profile.age_years
            and has_photo
            and MatchingPreference.objects.filter(profile=profile)
            .exclude(target_genders=[])
            .exists()
            and all(
                has_active_consent(request.user, kind)
                for kind in ("terms", "privacy", "location", "sensitive_data")
            )
        )
        request.user.save(update_fields=["is_onboarded"])
        return Response(serializer.data)


class PreferencesView(ProfileAPI):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not has_active_consent(request.user, "sensitive_data"):
            return Response({"target_genders": []})
        preference = MatchingPreference.objects.filter(profile__user=request.user).first()
        return Response({"target_genders": preference.target_genders if preference else []})

    @transaction.atomic
    def put(self, request):
        type(request.user).objects.select_for_update().get(pk=request.user.pk, status="active")
        if not has_active_consent(request.user, "sensitive_data"):
            return Response({"error": {"code": "sensitive_data_consent_required"}}, status=403)
        serializer = MatchingPreferenceWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        profile, _ = Profile.objects.get_or_create(user=request.user)
        preference, _ = MatchingPreference.objects.get_or_create(profile=profile)
        preference.target_genders = serializer.validated_data["target_genders"]
        preference.save(update_fields=["target_genders", "updated_at"])
        return Response(status=204)


class LocationUpdateView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def put(self, request):
        type(request.user).objects.select_for_update().get(pk=request.user.pk, status="active")
        if not has_active_consent(request.user, "location"):
            return Response({"error": {"code": "location_consent_required"}}, status=403)
        serializer = LocationUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        profile, _ = Profile.objects.get_or_create(user=request.user)
        try:
            update_snapped_location(
                profile,
                latitude=serializer.validated_data["lat"],
                longitude=serializer.validated_data["lon"],
                accuracy_m=serializer.validated_data["accuracy_m"],
                is_mock=serializer.validated_data["is_mock"],
                captured_at=serializer.validated_data["captured_at"],
            )
        except ValueError as exc:
            return Response({"error": {"code": str(exc)}}, status=400)
        return Response(status=204)


class MediaUploadURLView(ProfileAPI):
    permission_classes = [IsAuthenticated]
    throttle_scope = "media_upload"

    def post(self, request):
        serializer = MediaUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if data["kind"] == MediaAsset.Kind.AVATAR:
            for kind in ("privacy", "sensitive_data"):
                if not has_active_consent(request.user, kind):
                    return Response({"error": {"code": f"{kind}_consent_required"}}, status=403)
        if data["kind"] == MediaAsset.Kind.AUDIO and not has_active_consent(request.user, "voice"):
            return Response({"error": {"code": "voice_consent_required"}}, status=403)
        asset = MediaAsset.objects.create(
            user=request.user,
            kind=data["kind"],
            content_type=data["content_type"],
            size_bytes=data["size_bytes"],
            incoming_key=f"incoming/{uuid.uuid4()}",
            disguise_voice=data["disguise_voice"],
        )
        try:
            upload_url = R2MediaStore().presign_upload(asset.incoming_key, data["content_type"])
        except Exception:  # noqa: BLE001 - storage providers expose varied client errors
            asset.delete()
            return Response(
                {"error": {"code": "media_storage_unavailable"}},
                status=503,
            )
        return Response(
            {
                "upload_id": asset.id,
                "method": "PUT",
                "upload_url": upload_url,
                "headers": {"Content-Type": data["content_type"]},
                "expires_in_seconds": 900,
            },
            status=201,
        )


class MediaCompleteView(ProfileAPI):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = MediaCompleteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            asset = MediaAsset.objects.get(
                id=serializer.validated_data["upload_id"], user=request.user
            )
        except MediaAsset.DoesNotExist:
            return Response({"error": {"code": "media_upload_not_found"}}, status=404)
        if asset.status != MediaAsset.Status.PENDING:
            return Response(MediaStatusSerializer(asset).data, status=202)
        try:
            metadata = R2MediaStore().head(asset.incoming_key)
        except MediaStorageUnavailable:
            return Response({"error": {"code": "media_storage_unavailable"}}, status=503)
        except Exception:  # noqa: BLE001 - storage providers use varied missing-object errors
            return Response({"error": {"code": "media_upload_missing"}}, status=400)
        actual_size = int(metadata.get("ContentLength", 0))
        actual_content_type = metadata.get("ContentType")
        maximum = (
            settings.MEDIA_AVATAR_MAX_BYTES
            if asset.kind == MediaAsset.Kind.AVATAR
            else settings.MEDIA_AUDIO_MAX_BYTES
        )
        if (
            actual_size <= 0
            or actual_size > maximum
            or actual_content_type not in {asset.content_type, None}
        ):
            asset.status = MediaAsset.Status.REJECTED
            asset.rejection_code = (
                "media_content_type_invalid"
                if actual_content_type not in {asset.content_type, None}
                else "media_size_invalid"
            )
            asset.save(update_fields=["status", "rejection_code", "updated_at"])
            return Response(MediaStatusSerializer(asset).data, status=400)
        with transaction.atomic():
            type(request.user).objects.select_for_update().get(pk=request.user.pk, status="active")
            asset = MediaAsset.objects.select_for_update().get(pk=asset.pk, user=request.user)
            if asset.status != MediaAsset.Status.PENDING:
                return Response(MediaStatusSerializer(asset).data, status=202)
            if asset.kind == "audio" and not has_active_consent(request.user, "voice"):
                return Response({"error": {"code": "voice_consent_required"}}, status=403)
            if asset.kind == "avatar":
                for kind in ("privacy", "sensitive_data"):
                    if not has_active_consent(request.user, kind):
                        return Response({"error": {"code": f"{kind}_consent_required"}}, status=403)
            asset.status = MediaAsset.Status.PROCESSING
            asset.size_bytes = actual_size
            asset.save(update_fields=["status", "size_bytes", "updated_at"])

            def dispatch():
                try:
                    process_media_asset.delay(str(asset.id))
                except Exception:  # noqa: BLE001 - beat recovers durable processing intents
                    logging.getLogger("anonymoke.media").warning("media_dispatch_pending")

            transaction.on_commit(dispatch)
        return Response(MediaStatusSerializer(asset).data, status=202)


class MediaStatusView(ProfileAPI):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        assets = MediaAsset.objects.filter(user=request.user).order_by("-created_at")[:20]
        return Response(MediaStatusSerializer(assets, many=True).data)


class MediaAssetStatusView(ProfileAPI):
    def get(self, request, upload_id):
        asset = MediaAsset.objects.filter(pk=upload_id, user=request.user).first()
        if asset is None:
            return Response({"error": {"code": "media_upload_not_found"}}, status=404)
        response = Response(MediaStatusSerializer(asset).data)
        response["Cache-Control"] = "no-store"
        return response


class MediaDeleteView(ProfileAPI):
    @transaction.atomic
    def delete(self, request, kind):
        from apps.compliance.services import default_object_storage

        if kind not in {"avatar", "audio"}:
            return Response(status=404)
        type(request.user).objects.select_for_update().get(pk=request.user.pk)
        assets = MediaAsset.objects.filter(user=request.user, kind=kind)
        keys = [
            key
            for asset in assets
            for key in [asset.incoming_key, asset.original_key, asset.derived_key]
            if key
        ]
        profile = Profile.objects.filter(user=request.user).first()
        identity = getattr(request.user, "private_identity", None)
        if kind == "avatar":
            keys.extend(
                [
                    profile.blurred_avatar_key if profile else "",
                    identity.real_avatar_key if identity else "",
                ]
            )
        else:
            keys.append(profile.audio_key if profile else "")
        keys = list(dict.fromkeys(key for key in keys if key))
        try:
            if keys:
                default_object_storage().delete_keys(keys)
        except RuntimeError:
            return Response({"error": {"code": "media_storage_unavailable"}}, status=503)
        if profile:
            if kind == "audio":
                profile.audio_key, profile.audio_duration_ms, profile.audio_disguised = "", 0, False
            else:
                profile.blurred_avatar_key = ""
            profile.save()
        if identity and kind == "avatar":
            identity.real_avatar_key = ""
            identity.save(update_fields=["real_avatar_key", "updated_at"])
        assets.delete()
        return Response(status=204)
