from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.chat.models import Message
from apps.chat.serializers import MessageSerializer
from apps.chat.services import review_message
from apps.compliance.models import AuditLog
from apps.safety.models import ModerationFlagRecord, Report
from apps.store.models import Purchase

from .permissions import IsFinanceStaff, IsModerationStaff
from .serializers import (
    AdminPurchaseSerializer,
    AdminReportSerializer,
    ModerationActionSerializer,
    ModerationFlagSerializer,
)


class StaffBaseView(APIView):
    permission_classes = [IsAuthenticated, IsModerationStaff]


class MessageReviewSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=["approve", "block"])
    reason = serializers.CharField(max_length=500)


class AdminMessageReviewView(StaffBaseView):
    def get(self, request, message_id):
        message = get_object_or_404(
            Message.objects.select_related("sender"),
            pk=message_id,
            deleted_at__isnull=True,
            moderation_status__in=["flagged", "blocked"],
        )
        AuditLog.objects.create(
            actor_user_id=request.user.pk,
            action="message_review_viewed",
            object_type="message",
            object_id=message_id,
        )
        return Response(MessageSerializer(message).data)

    def post(self, request, message_id):
        serializer = MessageReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            message = review_message(
                message_id,
                approve=serializer.validated_data["action"] == "approve",
                actor=request.user,
                reason=serializer.validated_data["reason"],
            )
        except ValueError as exc:
            return Response({"error": {"code": str(exc)}}, status=400)
        return Response(MessageSerializer(message).data)


class AdminReportListView(StaffBaseView):
    def get(self, request):
        queryset = Report.objects.select_related("reported__profile").order_by("created_at")
        status = request.query_params.get("status")
        if status:
            allowed = {choice for choice, _ in Report.Status.choices}
            if status not in allowed:
                return Response({"error": {"code": "invalid_report_status"}}, status=400)
            queryset = queryset.filter(status=status)
        else:
            queryset = queryset.filter(status__in=[Report.Status.OPEN, Report.Status.REVIEW])
        try:
            limit = min(max(int(request.query_params.get("limit", 50)), 1), 100)
            offset = max(int(request.query_params.get("offset", 0)), 0)
        except ValueError:
            return Response({"error": {"code": "invalid_pagination"}}, status=400)
        items = list(queryset[offset : offset + limit])
        return Response(
            {
                "items": AdminReportSerializer(items, many=True).data,
                "next_offset": offset + limit if len(items) == limit else None,
            }
        )


class AdminReportActionView(StaffBaseView):
    @transaction.atomic
    def post(self, request, report_id):
        serializer = ModerationActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        report = get_object_or_404(Report.objects.select_for_update(), id=report_id)
        action = serializer.validated_data["action"]
        reason = serializer.validated_data.get("reason", "").strip()
        previous_status = report.status
        target_status = {
            "dismiss": Report.Status.DISMISSED,
            "review": Report.Status.REVIEW,
            "resolve": Report.Status.RESOLVED,
            "suspend": Report.Status.RESOLVED,
            "ban": Report.Status.RESOLVED,
        }[action]
        report.status = target_status
        report.save(update_fields=["status", "updated_at"])
        target_user_status = None
        if action == "suspend":
            User.objects.filter(pk=report.reported_id).update(status=User.Status.SUSPENDED)
            target_user_status = User.Status.SUSPENDED
        elif action == "ban":
            User.objects.filter(pk=report.reported_id).update(status=User.Status.BANNED)
            target_user_status = User.Status.BANNED
        AuditLog.objects.create(
            actor_user_id=request.user.id,
            action=f"moderation_report_{action}",
            object_type="report",
            object_id=report.id,
            reason=reason,
            metadata={
                "previous_status": previous_status,
                "new_status": report.status,
                "target_user_status": target_user_status,
            },
        )
        return Response(
            {
                "report_id": str(report.id),
                "status": report.status,
                "action": action,
            }
        )


class AdminModerationFlagListView(StaffBaseView):
    def get(self, request):
        queryset = ModerationFlagRecord.objects.select_related("subject_user__profile")
        status = request.query_params.get("status")
        if status:
            queryset = queryset.filter(status=status)
        try:
            limit = min(max(int(request.query_params.get("limit", 50)), 1), 100)
            offset = max(int(request.query_params.get("offset", 0)), 0)
        except ValueError:
            return Response({"error": {"code": "invalid_pagination"}}, status=400)
        items = list(queryset.order_by("created_at")[offset : offset + limit])
        return Response(
            {
                "items": ModerationFlagSerializer(items, many=True).data,
                "next_offset": offset + limit if len(items) == limit else None,
            }
        )


class FinanceBaseView(APIView):
    permission_classes = [IsAuthenticated, IsFinanceStaff]


class AdminPurchaseListView(FinanceBaseView):
    def get(self, request):
        queryset = Purchase.objects.select_related("product", "user__profile").order_by(
            "-created_at"
        )
        status = request.query_params.get("status")
        if status:
            allowed = {choice for choice, _ in Purchase.Status.choices}
            if status not in allowed:
                return Response({"error": {"code": "invalid_purchase_status"}}, status=400)
            queryset = queryset.filter(status=status)
        try:
            limit = min(max(int(request.query_params.get("limit", 50)), 1), 100)
            offset = max(int(request.query_params.get("offset", 0)), 0)
        except ValueError:
            return Response({"error": {"code": "invalid_pagination"}}, status=400)
        items = list(queryset[offset : offset + limit])
        return Response(
            {
                "items": AdminPurchaseSerializer(items, many=True).data,
                "next_offset": offset + limit if len(items) == limit else None,
            }
        )
