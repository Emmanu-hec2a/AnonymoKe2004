import json

from django.db.models import Q, Sum
from django.utils import timezone
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.compliance.models import AuditLog
from apps.core.crypto import decrypt_text
from apps.core.cursors import decode_cursor, encode_cursor
from apps.profiles.models import Profile
from apps.profiles.storage import MediaStorageUnavailable, R2MediaStore

from .inbox import inbox_queryset, match_summary
from .models import Match
from .serializers import SwipeWriteSerializer, UnmaskResponseSerializer
from .services import (
    close_match,
    participant_match,
    record_swipe,
    request_unmask,
    respond_unmask,
    revealed_identity,
    undo_pass,
    withdraw_unmask,
)


def _profile_for_user(user):
    return Profile.objects.get_or_create(user=user)[0]


def _other(match: Match, profile: Profile) -> Profile:
    return match.profile_b if match.profile_a_id == profile.id else match.profile_a


def _store():
    try:
        return R2MediaStore()
    except MediaStorageUnavailable:
        return None


def _summary(match: Match, profile: Profile) -> dict:
    return match_summary(match, profile, _store())


class SwipeView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "swipe"

    def post(self, request):
        serializer = SwipeWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            result = record_swipe(
                _profile_for_user(request.user),
                serializer.validated_data["profile_id"],
                serializer.validated_data["action"],
                serializer.validated_data["client_swipe_id"],
            )
        except ValueError as exc:
            return Response({"error": {"code": str(exc)}}, status=400)
        return Response(
            {
                "is_match": result.match is not None,
                "match_id": str(result.match.id) if result.match else None,
                "client_swipe_id": str(result.swipe.client_swipe_id),
            }
        )


class UndoPassSerializer(serializers.Serializer):
    client_swipe_id = serializers.UUIDField()


class UndoPassView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "swipe"

    def post(self, request):
        serializer = UndoPassSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            swipe = undo_pass(
                _profile_for_user(request.user), serializer.validated_data["client_swipe_id"]
            )
        except ValueError as exc:
            return Response({"error": {"code": str(exc)}}, status=400)
        return Response({"profile_id": str(swipe.to_profile.public_id)})


class MatchListView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "matches"

    def get(self, request):
        profile = _profile_for_user(request.user)
        matches = inbox_queryset(profile)
        store = _store()
        if request.query_params.get("paged") != "1":
            return Response([match_summary(match, profile, store) for match in matches[:50]])
        count = matches.count()
        unread = matches.aggregate(total=Sum("unread_count"))["total"] or 0
        cursor = request.query_params.get("cursor")
        try:
            if cursor:
                timestamp, match_id = decode_cursor(cursor, f"matches:{profile.pk}")
                matches = matches.filter(
                    Q(activity_at__lt=timestamp) | Q(activity_at=timestamp, pk__lt=match_id)
                )
        except ValueError as exc:
            return Response({"error": {"code": str(exc)}}, status=400)
        batch = list(matches[:31])
        items = batch[:30]
        next_cursor = (
            encode_cursor(items[-1].activity_at, items[-1].pk, f"matches:{profile.pk}")
            if len(batch) > 30
            else None
        )
        return Response(
            {
                "items": [match_summary(match, profile, store) for match in items],
                "next_cursor": next_cursor,
                "total_count": count,
                "unread_count": unread,
            }
        )


class MatchDetailView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "matches"

    def get(self, request, match_id):
        try:
            match = participant_match(_profile_for_user(request.user), match_id)
        except ValueError as exc:
            return Response({"error": {"code": str(exc)}}, status=404)
        profile = _profile_for_user(request.user)
        current = inbox_queryset(profile).filter(pk=match.pk).first()
        if not current:
            return Response({"error": {"code": "match_not_found"}}, status=404)
        return Response(_summary(current, profile))

    def delete(self, request, match_id):
        try:
            close_match(_profile_for_user(request.user), match_id)
        except ValueError as exc:
            return Response({"error": {"code": str(exc)}}, status=404)
        return Response(status=204)


class UnmaskRequestView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "match_actions"

    def post(self, request, match_id):
        try:
            match = request_unmask(_profile_for_user(request.user), match_id)
        except ValueError as exc:
            status = 403 if str(exc) == "verification_required_before_unmask" else 400
            return Response({"error": {"code": str(exc)}}, status=status)
        return Response({"match_id": str(match.id), "state": match.state})


class UnmaskRespondView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "match_actions"

    def post(self, request, match_id):
        serializer = UnmaskResponseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            match = respond_unmask(
                _profile_for_user(request.user), match_id, serializer.validated_data["accept"]
            )
        except ValueError as exc:
            status = 403 if str(exc) == "verification_required_before_unmask" else 400
            return Response({"error": {"code": str(exc)}}, status=status)
        return Response({"match_id": str(match.id), "state": match.state})


class UnmaskWithdrawView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "match_actions"

    def post(self, request, match_id):
        try:
            match = withdraw_unmask(_profile_for_user(request.user), match_id)
        except ValueError as exc:
            return Response({"error": {"code": str(exc)}}, status=400)
        return Response({"match_id": str(match.id), "state": match.state})


class RevealedIdentityView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, match_id):
        profile = _profile_for_user(request.user)
        try:
            result = revealed_identity(profile, match_id)
        except ValueError as exc:
            return Response({"error": {"code": str(exc)}}, status=403)
        other = result.get("profile")
        identity = result.get("identity")
        if not other or not identity:
            return Response(
                {
                    "profile_id": str(other.public_id) if other else None,
                    "real_first_name": None,
                    "username": None,
                    "real_avatar_url": None,
                    "social_handles": [],
                }
            )
        try:
            real_first_name = (
                decrypt_text(bytes(identity.real_first_name_ciphertext))
                if identity.real_first_name_ciphertext
                else None
            )
            handles_text = (
                decrypt_text(bytes(identity.social_handles_ciphertext))
                if identity.social_handles_ciphertext
                else "[]"
            )
            social_handles = json.loads(handles_text)
            avatar_url = (
                R2MediaStore().presign_private(identity.real_avatar_key, ttl_seconds=300)
                if identity.real_avatar_key
                else None
            )
        except (ValueError, json.JSONDecodeError):
            real_first_name = None
            social_handles = []
            avatar_url = None
        except MediaStorageUnavailable:
            return Response({"error": {"code": "media_storage_unavailable"}}, status=503)
        AuditLog.objects.create(
            actor_user_id=request.user.id,
            action="revealed_identity_viewed",
            object_type="match",
            object_id=match_id,
            metadata={"viewed_at": timezone.now().isoformat()},
        )
        return Response(
            {
                "profile_id": str(other.public_id),
                "real_first_name": real_first_name,
                "username": identity.username,
                "real_avatar_url": avatar_url,
                "social_handles": social_handles if isinstance(social_handles, list) else [],
            }
        )
