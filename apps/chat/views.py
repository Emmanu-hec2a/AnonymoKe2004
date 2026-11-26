from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.core.cursors import decode_cursor, encode_cursor
from apps.matching.services import participant_match
from apps.profiles.models import Profile

from .activity import peer_activity, update_activity
from .serializers import MessageSerializer, MessageWriteSerializer
from .services import list_messages, mark_delivered, mark_read, send_message, visible_messages


def _profile_for_user(user):
    return Profile.objects.get_or_create(user=user)[0]


class MessageListCreateView(APIView):
    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "no-store"
        return response

    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]

    def get_throttles(self):
        self.throttle_scope = "chat_send" if self.request.method == "POST" else "chat_read"
        return super().get_throttles()

    def get(self, request, match_id):
        profile = _profile_for_user(request.user)
        cursor = request.query_params.get("cursor")
        if request.query_params.get("paged") == "1" or cursor:
            try:
                match = participant_match(profile, match_id)
                queryset = visible_messages(profile, match)
                if cursor:
                    timestamp, message_id = decode_cursor(cursor, f"chat:{match_id}:{profile.pk}")
                    queryset = queryset.filter(
                        Q(created_at__lt=timestamp) | Q(created_at=timestamp, pk__lt=message_id)
                    )
                messages = list(queryset.order_by("-created_at", "-pk")[:51])
            except ValueError as exc:
                return Response(
                    {"error": {"code": str(exc)}},
                    status=400 if str(exc) == "cursor_invalid" else 404,
                )
            more = len(messages) > 50
            items = messages[:50]
            next_cursor = (
                encode_cursor(items[-1].created_at, items[-1].pk, f"chat:{match_id}:{profile.pk}")
                if more
                else None
            )
            return Response(
                {
                    "items": MessageSerializer(
                        items[::-1], many=True, context={"viewer": profile}
                    ).data,
                    "next_cursor": next_cursor,
                    "activity": peer_activity(profile, match_id),
                }
            )
        before_value = request.query_params.get("before")
        before = parse_datetime(before_value) if before_value else None
        if before_value and before is None:
            return Response({"error": {"code": "cursor_invalid"}}, status=400)
        if before and timezone.is_naive(before):
            before = timezone.make_aware(before)
        try:
            messages = list_messages(_profile_for_user(request.user), match_id, before)
        except ValueError as exc:
            return Response({"error": {"code": str(exc)}}, status=404)
        next_cursor = messages[0].created_at.isoformat() if messages else None
        return Response(
            {
                "items": MessageSerializer(messages, many=True, context={"viewer": profile}).data,
                "next_cursor": next_cursor,
                "activity": peer_activity(profile, match_id),
            }
        )

    def post(self, request, match_id):
        serializer = MessageWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            result = send_message(
                _profile_for_user(request.user),
                match_id,
                serializer.validated_data["body"],
                serializer.validated_data.get("client_message_id"),
                serializer.validated_data.get("reply_to_id"),
                serializer.validated_data.get("attachment_id"),
            )
        except ValueError as exc:
            return Response({"error": {"code": str(exc)}}, status=400)
        return Response(
            MessageSerializer(
                result.message, context={"viewer": _profile_for_user(request.user)}
            ).data,
            status=201,
        )


class MessageReadView(APIView):
    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "no-store"
        return response

    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "chat_read"

    def post(self, request, match_id):
        serializer = ReadAnchorSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            count = mark_read(
                _profile_for_user(request.user),
                match_id,
                serializer.validated_data.get("through_message_id"),
            )
        except ValueError as exc:
            return Response({"error": {"code": str(exc)}}, status=404)
        return Response({"marked_read": count})


class ReadAnchorSerializer(serializers.Serializer):
    through_message_id = serializers.UUIDField(required=False)


class DeliverySerializer(serializers.Serializer):
    message_ids = serializers.ListField(child=serializers.UUIDField(), max_length=100)


class MessageDeliveryView(MessageReadView):
    def post(self, request, match_id):
        serializer = DeliverySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            count = mark_delivered(
                _profile_for_user(request.user), match_id, serializer.validated_data["message_ids"]
            )
        except ValueError as error:
            return Response({"error": {"code": str(error)}}, status=404)
        return Response({"marked_delivered": count})


class ActivitySerializer(serializers.Serializer):
    session_id = serializers.UUIDField()
    active = serializers.BooleanField()
    typing = serializers.BooleanField(default=False)


class ChatActivityView(MessageReadView):
    throttle_scope = "chat_activity"

    def put(self, request, match_id):
        serializer = ActivitySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            activity = update_activity(
                _profile_for_user(request.user),
                match_id,
                str(serializer.validated_data["session_id"]),
                active=serializer.validated_data["active"],
                typing=serializer.validated_data["typing"],
            )
        except ValueError as error:
            return Response({"error": {"code": str(error)}}, status=404)
        return Response(activity)
