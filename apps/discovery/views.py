from datetime import timedelta

from django.contrib.gis.db.models.functions import Distance
from django.utils import timezone
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.compliance.consent import has_active_consent
from apps.matching.services import eligible_target
from apps.profiles.models import Profile
from apps.profiles.services import distance_bucket
from apps.profiles.storage import MediaStorageUnavailable, R2MediaStore

from .boosts import activate_boost, boost_status
from .pagination import candidate_page


def discovery_error(exc):
    code = str(exc)
    forbidden = code.endswith("consent_required") or code in {
        "verification_required_before_discovery",
        "account_not_active",
        "location_flagged",
    }
    return Response({"error": {"code": code}}, status=403 if forbidden else 400)


def card_data(profile, store):
    voice_allowed = has_active_consent(profile.user, "voice")
    return {
        "profile_id": str(profile.public_id),
        "alias": profile.alias,
        "age_years": profile.age_years,
        "height_cm": profile.height_cm,
        "bio": profile.bio,
        "distance_bucket": distance_bucket(profile.distance_m.m / 1000)
        if getattr(profile, "distance_m", None) is not None
        else None,
        "interests": profile.interests,
        "blurred_avatar_url": store.presign_derived(profile.blurred_avatar_key)
        if store and profile.blurred_avatar_key
        else None,
        "audio_url": store.presign_private(profile.audio_key)
        if store and profile.audio_key and voice_allowed
        else None,
        "audio_duration_s": round(profile.audio_duration_ms / 1000, 1)
        if profile.audio_duration_ms and voice_allowed
        else None,
        "media_expires_at": timezone.now() + timedelta(seconds=300),
        "is_verified": profile.verification_level != "none",
        "is_boosted": bool(getattr(profile, "boost_active", False)),
    }


def media_store():
    try:
        return R2MediaStore()
    except MediaStorageUnavailable:
        return None


class DiscoveryFilterSerializer(serializers.Serializer):
    max_distance_km = serializers.IntegerField(min_value=1, max_value=50, required=False)
    min_age = serializers.IntegerField(min_value=18, max_value=100, required=False)
    max_age = serializers.IntegerField(min_value=18, max_value=100, required=False)

    def validate(self, attrs):
        if (
            attrs.get("min_age") is not None
            and attrs.get("max_age") is not None
            and attrs["min_age"] > attrs["max_age"]
        ):
            raise serializers.ValidationError("min_age_must_not_exceed_max_age")
        return attrs


class DiscoveryView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "discovery"

    def get(self, request):
        filters = DiscoveryFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        try:
            profile, _ = Profile.objects.get_or_create(user=request.user)
            profiles, next_cursor = candidate_page(
                profile, cursor=request.query_params.get("cursor"), **filters.validated_data
            )
        except ValueError as exc:
            return discovery_error(exc)
        store = media_store()
        cards = [card_data(profile, store) for profile in profiles]
        response = Response({"items": cards, "next_cursor": next_cursor})
        response["Cache-Control"] = "no-store"
        return response


class DiscoveryProfileView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "discovery"

    def get(self, request, profile_id):
        me, _ = Profile.objects.get_or_create(user=request.user)
        try:
            target = eligible_target(me, profile_id)
        except ValueError as exc:
            return discovery_error(exc)
        target = (
            Profile.objects.select_related("user")
            .annotate(
                distance_m=Distance("cell", me.cell),
            )
            .get(pk=target.pk)
        )
        return Response(card_data(target, media_store()))


class BoostActivationSerializer(serializers.Serializer):
    client_activation_id = serializers.UUIDField()


class BoostView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "discovery"

    def get(self, request):
        profile, _ = Profile.objects.get_or_create(user=request.user)
        return Response(boost_status(profile))

    def post(self, request):
        serializer = BoostActivationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        profile, _ = Profile.objects.get_or_create(user=request.user)
        try:
            activate_boost(profile, serializer.validated_data["client_activation_id"])
        except ValueError as exc:
            return discovery_error(exc)
        return Response(boost_status(profile))
