import hashlib
import hmac

from django.conf import settings
from django.shortcuts import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.profiles.models import Profile

from .models import (
    Block,
    Report,
)
from .pagination import page_response
from .serializers import (
    BlockedProfileSerializer,
    BlockWriteSerializer,
    MyReportSerializer,
    ReportWriteSerializer,
)
from .services import block_profile, register_report


def _invite_hash(code):
    return hmac.new(settings.JWT_SECRET.encode(), code.encode(), hashlib.sha256).hexdigest()


def _profile_for_user(user):
    return Profile.objects.get_or_create(user=user)[0]


class ReportCreateView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "report"

    def get_throttles(self):
        self.throttle_scope = "safety_read" if self.request.method == "GET" else "report"
        return super().get_throttles()

    def get(self, request):
        reports = (
            Report.objects.filter(reporter=request.user)
            .select_related("reported__profile")
            .order_by("-created_at")
        )
        return page_response(request, reports, MyReportSerializer, "reports")

    def post(self, request):
        serializer = ReportWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        target = get_object_or_404(Profile, public_id=data["profile_id"])
        try:
            report = register_report(
                reporter=request.user,
                reported=target.user,
                reason=data["reason"],
                note=data.get("note", ""),
                evidence_message_ids=[str(value) for value in data.get("message_ids", [])],
            )
        except ValueError as exc:
            return Response({"error": {"code": str(exc)}}, status=400)
        return Response(
            {
                "report_id": str(report.id),
                "status": report.status,
            },
            status=201,
        )


class BlockCreateView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "block"

    def get_throttles(self):
        self.throttle_scope = "safety_read" if self.request.method == "GET" else "block"
        return super().get_throttles()

    def get(self, request):
        profile = _profile_for_user(request.user)
        blocks = (
            Block.objects.filter(blocker=profile).select_related("blocked").order_by("-created_at")
        )
        return page_response(request, blocks, BlockedProfileSerializer, "blocks")

    def post(self, request):
        serializer = BlockWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        blocker = _profile_for_user(request.user)
        blocked = get_object_or_404(Profile, public_id=serializer.validated_data["profile_id"])
        try:
            block = block_profile(blocker=blocker, blocked=blocked)
        except ValueError as exc:
            return Response({"error": {"code": str(exc)}}, status=400)
        return Response(
            {"block_id": str(block.id), "profile_id": str(blocked.public_id)}, status=201
        )


class BlockDeleteView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "block"

    def delete(self, request, profile_id):
        blocker = _profile_for_user(request.user)
        deleted, _ = Block.objects.filter(blocker=blocker, blocked__public_id=profile_id).delete()
        return Response(status=204)
