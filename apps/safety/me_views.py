import logging
from datetime import timedelta

from django.core.cache.backends.locmem import LocMemCache
from django.db import transaction
from django.db.models import Case, CharField, IntegerField, Q, Value, When
from django.shortcuts import get_object_or_404
from django.utils import timezone
from redis.exceptions import RedisError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle, SimpleRateThrottle
from rest_framework.views import APIView

from .lifecycle import (
    OPEN_STATES,
    accept_invite,
    acknowledge_alert,
    issue_invite,
    lock_owner,
    resolve_plan,
    save_plan,
    trigger_panic,
    trusted_contact,
    unlink_contact,
)
from .models import DateSession, PanicAlert, SafetyAlertRecipient, SafetyDelivery, TrustedContact
from .pagination import page_response
from .serializers import (
    DateSessionSerializer,
    DateSessionWriteSerializer,
    PanicAlertSerializer,
    SafetyAlertRecipientSerializer,
    SafetyHistorySerializer,
    TrustedContactSerializer,
)

_fallback_cache = LocMemCache("safety-throttle-fallback", {})


class SafetyThrottle(ScopedRateThrottle):
    def allow_request(self, request, view):
        if getattr(view, "throttle_scope", "") == "panic":
            key = str(request.headers.get("Idempotency-Key", ""))
            if key and PanicAlert.objects.filter(user=request.user, idempotency_key=key).exists():
                return True
        try:
            return super().allow_request(request, view)
        except (RedisError, ConnectionError, TimeoutError, OSError):
            if "invite" in getattr(view, "throttle_scope", ""):
                self.history = [self.timer()]
                self.now = self.timer()
                return False
            self.cache = _fallback_cache
            return super().allow_request(request, view)


class SafetyView(APIView):
    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "no-store"
        return response

    permission_classes = [IsAuthenticated]
    throttle_classes = [SafetyThrottle]
    throttle_scope = "safety_read"

    def get_throttles(self):
        if self.throttle_scope == "safety_read" and self.request.method not in (
            "GET",
            "HEAD",
            "OPTIONS",
        ):
            self.throttle_scope = "safety_write"
        return super().get_throttles()

    def handle_exception(self, exc):
        if isinstance(exc, ValueError):
            code = str(exc)
            status = (
                429 if code.endswith("rate_limited") else 404 if code.endswith("not_found") else 409
            )
            return Response({"error": {"code": code}}, status=status)
        return super().handle_exception(exc)


def incoming(user):
    return SafetyAlertRecipient.objects.filter(
        recipient_user=user,
        alert__user__trusted_contact__linked_user=user,
        alert__user__status="active",
    ).select_related("alert__user__profile", "alert__date_session")


def shared_plans(user):
    return DateSession.objects.filter(
        trusted_contact_user=user, user__trusted_contact__linked_user=user, user__status="active"
    ).select_related("user__profile")


def completed_plans(user):
    """One record per completed plan; shared history remains tied to the current link."""
    return (
        DateSession.objects.filter(
            Q(user=user)
            | Q(
                trusted_contact_user=user,
                user__trusted_contact__linked_user=user,
                user__status="active",
            ),
            status__in=["safe", "cancelled", "expired"],
        )
        .select_related("user__profile")
        .annotate(
            viewer_role=Case(
                When(user=user, then=Value("owner")),
                default=Value("trusted_contact"),
                output_field=CharField(),
            )
        )
    )


class SafetyHistoryView(SafetyView):
    def get(self, request):
        return page_response(
            request,
            completed_plans(request.user),
            SafetyHistorySerializer,
            "completed-history-v1",
            size=20,
            timestamp_field="updated_at",
        )


class SafetyOverviewView(SafetyView):
    def get(self, request):
        focused = request.query_params.get("view") == "active"
        active = (
            DateSession.objects.filter(user=request.user, status__in=OPEN_STATES)
            .order_by("-created_at")
            .first()
        )
        contact = trusted_contact(request.user)
        own_alerts = PanicAlert.objects.filter(user=request.user)
        if focused:
            own_alerts = own_alerts.filter(date_session__status__in=OPEN_STATES)
        alerts = (
            own_alerts.select_related("date_session", "push_delivery")
            .prefetch_related("recipients")
            .order_by("-triggered_at")[:5]
        )
        received = incoming(request.user)
        if focused:
            received = received.filter(alert__date_session__status__in=OPEN_STATES)
        received = received.annotate(
            priority=Case(
                When(status="unread", alert__date_session__status="panic", then=Value(0)),
                default=Value(1),
                output_field=IntegerField(),
            )
        ).order_by("priority", "-created_at")
        plans = shared_plans(request.user)
        if focused:
            plans = plans.filter(status__in=OPEN_STATES).exclude(
                pk__in=received.values("alert__date_session_id")
            )
        else:
            plans = plans.filter(updated_at__gte=timezone.now() - timedelta(days=30))
        plans = plans.order_by("-updated_at")
        history = completed_plans(request.user)
        now = timezone.now()
        latest_safe = (
            history.filter(status="safe", safe_at__gte=now - timedelta(minutes=5))
            .order_by("-safe_at", "-pk")
            .first()
        )
        recent_completion = None
        if latest_safe:
            recent_completion = {
                "session": SafetyHistorySerializer(latest_safe).data,
                "expires_in_seconds": max(
                    0, int((latest_safe.safe_at + timedelta(minutes=5) - now).total_seconds())
                ),
            }
        return Response(
            {
                "trusted_contact": TrustedContactSerializer(contact).data if contact else None,
                "active_date": DateSessionSerializer(active).data if active else None,
                "panic_alerts": PanicAlertSerializer(alerts, many=True).data,
                "incoming_alerts": SafetyAlertRecipientSerializer(received[:20], many=True).data,
                "incoming_alert_count": received.count(),
                "shared_plans": DateSessionSerializer(plans[:20], many=True).data,
                "shared_plan_count": plans.count(),
                "history_count": history.count(),
                "recent_completion": recent_completion,
            }
        )


class TrustedContactView(SafetyView):
    def get(self, request):
        contact = trusted_contact(request.user)
        return Response(TrustedContactSerializer(contact).data if contact else None)

    @transaction.atomic
    def put(self, request):
        lock_owner(request.user.pk)
        contact = trusted_contact(request.user, lock=True)
        serializer = TrustedContactSerializer(
            contact, data=request.data, partial=contact is not None
        )
        serializer.is_valid(raise_exception=True)
        result = serializer.save(user=request.user) if not contact else serializer.save()
        return Response(TrustedContactSerializer(result).data)

    @transaction.atomic
    def delete(self, request):
        unlink_contact(request.user)
        TrustedContact.objects.filter(user=request.user).delete()
        return Response(status=204)


class TrustedContactUnlinkView(SafetyView):
    def post(self, request):
        unlink_contact(request.user)
        return Response(status=204)


class InviteIPThrottle(SimpleRateThrottle):
    scope = "safety_invite_ip"

    def allow_request(self, request, view):
        try:
            return super().allow_request(request, view)
        except (RedisError, ConnectionError, TimeoutError, OSError):
            self.history = [self.timer()]
            self.now = self.timer()
            return False

    def get_cache_key(self, request, view):  # noqa: ARG002
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class TrustedContactInviteView(SafetyView):
    throttle_scope = "safety_invite_issue"

    def post(self, request):
        code, expires = issue_invite(request.user)
        return Response({"invite_code": code, "expires_at": expires}, status=201)


class TrustedContactAcceptView(SafetyView):
    throttle_classes = [SafetyThrottle, InviteIPThrottle]
    throttle_scope = "safety_invite_accept"

    def post(self, request):
        contact = accept_invite(request.user, request.data.get("invite_code", ""))
        return Response({"linked": True, "contact_name": contact.contact_name})


class SafetyIncomingAlertsView(SafetyView):
    def get(self, request):
        query = incoming(request.user)
        active = request.query_params.get("active") == "1"
        if active:
            query = query.filter(alert__date_session__status__in=OPEN_STATES)
        return page_response(
            request,
            query,
            SafetyAlertRecipientSerializer,
            "incoming-active" if active else "incoming",
        )


class SharedPlansView(SafetyView):
    def get(self, request):
        query = shared_plans(request.user)
        active = request.query_params.get("active") == "1"
        if active:
            query = query.filter(status__in=OPEN_STATES).exclude(
                pk__in=incoming(request.user)
                .filter(alert__date_session__status__in=OPEN_STATES)
                .values("alert__date_session_id")
            )
        return page_response(
            request, query, DateSessionSerializer, "shared-active" if active else "shared"
        )


class SafetyAlertAcknowledgeView(SafetyView):
    def post(self, request, recipient_id):
        return Response(
            SafetyAlertRecipientSerializer(acknowledge_alert(request.user, recipient_id)).data
        )


class DateSessionListCreateView(SafetyView):
    def get(self, request):
        return page_response(
            request, DateSession.objects.filter(user=request.user), DateSessionSerializer, "plans"
        )

    def post(self, request):
        serializer = DateSessionWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            DateSessionSerializer(save_plan(request.user, serializer.validated_data)).data,
            status=201,
        )


class DateSessionDetailView(SafetyView):
    def patch(self, request, session_id):
        session = get_object_or_404(DateSession, pk=session_id, user=request.user)
        serializer = DateSessionWriteSerializer(session, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        return Response(
            DateSessionSerializer(
                save_plan(request.user, serializer.validated_data, session_id)
            ).data
        )

    def delete(self, request, session_id):
        resolve_plan(request.user, session_id, safe=False)
        return Response(status=204)


class DateSessionSafeView(SafetyView):
    def post(self, request, session_id):
        return Response(
            DateSessionSerializer(resolve_plan(request.user, session_id, safe=True)).data
        )


class PanicAlertView(SafetyView):
    throttle_scope = "panic"

    def post(self, request):
        key = str(request.headers.get("Idempotency-Key", "")).strip()
        if not key or len(key) > 128:
            return Response({"error": {"code": "idempotency_key_required"}}, status=400)
        alert, created = trigger_panic(request.user, key)
        return Response(PanicAlertSerializer(alert).data, status=202 if created else 200)


class PanicAlertDetailView(SafetyView):
    def get(self, request, alert_id):
        return Response(
            PanicAlertSerializer(get_object_or_404(PanicAlert, pk=alert_id, user=request.user)).data
        )


class PanicRetryView(SafetyView):
    throttle_scope = "panic_retry"

    @transaction.atomic
    def post(self, request, alert_id):
        lock_owner(request.user.pk)
        alert = get_object_or_404(PanicAlert, pk=alert_id, user=request.user)
        if alert.date_session.status != "panic":
            raise ValueError("date_session_not_active")
        delivery = get_object_or_404(SafetyDelivery.objects.select_for_update(), alert=alert)
        if delivery.status in {"failed", "unavailable"}:
            delivery.status = "queued"
            delivery.attempts = 0
            delivery.next_attempt_at = timezone.now()
            delivery.save(update_fields=["status", "attempts", "next_attempt_at", "updated_at"])
            from .tasks import dispatch_safety_delivery

            def enqueue():
                try:
                    dispatch_safety_delivery.delay(str(delivery.pk))
                except Exception:  # noqa: BLE001 - beat retries the saved job
                    logging.getLogger("anonymoke.safety").warning(
                        "safety_retry_pending_broker_recovery"
                    )

            transaction.on_commit(enqueue)
        return Response(PanicAlertSerializer(alert).data)
