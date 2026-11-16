import json
import logging
import re
import uuid

from django.conf import settings
from django.db import transaction
from django.http import Http404, HttpResponse
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .models import VerificationAttempt, VerificationResultCheck
from .serializers import VerificationStartSerializer
from .services import VerificationService, verification_available
from .smile import valid_signature


class VerificationStartView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "verification_start"

    def post(self, request):
        serializer = VerificationStartSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            result = VerificationService.start(request.user, serializer.validated_data["purpose"])
        except RuntimeError:
            return Response({"error": {"code": "verification_provider_unavailable"}}, status=503)
        except ValueError as exc:
            return Response({"error": {"code": str(exc)}}, status=409)
        return Response(
            {
                "verification_id": str(result.attempt.pk),
                "status": result.attempt.status,
                "launch_url": result.launch_url,
                "expires_at": result.attempt.expires_at,
            },
            status=201,
        )


class VerificationStatusView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "verification_read"

    def get(self, request):
        attempts = VerificationAttempt.objects.filter(user=request.user).order_by("-created_at")[
            :10
        ]
        return Response(
            {
                "available": verification_available(),
                "privacy_url": settings.SMILE_ID_PRIVACY_URL,
                "verification_level": getattr(
                    getattr(request.user, "profile", None), "verification_level", "none"
                ),
                "attempts": [
                    {
                        "verification_id": str(item.pk),
                        "purpose": item.purpose,
                        "provider": item.provider,
                        "status": item.status,
                        "reason_code": item.reason_code,
                        "expires_at": item.expires_at,
                        "created_at": item.created_at,
                    }
                    for item in attempts
                ],
            }
        )


class VerificationWebhookView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request, provider):
        if provider != "smile_id" or not valid_signature(
            request.headers.get("Response-Signature", ""),
            request.headers.get("Response-Timestamp", ""),
        ):
            raise Http404
        if len(request.body) > 256_000:
            return Response(status=413)
        try:
            data = json.loads(request.body)
            params = data.get("partner_params") or {}
            reference = uuid.UUID(
                str(
                    params.get("anonymoke_attempt_id")
                    or params.get("user_id")
                    or data.get("user_id")
                )
            )
            job_id = data.get("job_id") or request.headers.get("job_id") or params.get("job_id")
            if not isinstance(job_id, str) or not re.fullmatch(
                r"job_[0-9a-hjkmnp-tv-z]{26}", job_id
            ):
                raise ValueError("verification_job_invalid")
            attempt = VerificationAttempt.objects.filter(pk=reference, provider="smile_id").first()
            if attempt and attempt.status not in {"passed", "failed"}:
                # Persist only a hint, never callback identity data or its claimed result.
                # A user-bound provider lookup remains the sole source of a badge.
                with transaction.atomic():
                    check, _ = VerificationResultCheck.objects.get_or_create(
                        attempt=attempt, job_id=job_id
                    )

                    def enqueue():
                        from .tasks import check_verification_result

                        try:
                            check_verification_result.delay(check.pk)
                        except Exception:  # noqa: BLE001 - beat recovers the saved hint
                            logging.getLogger("anonymoke.verification").warning(
                                "verification_check_pending"
                            )

                    transaction.on_commit(enqueue)
        except (ValueError, TypeError, AttributeError, json.JSONDecodeError):
            return Response({"error": {"code": "invalid_verification_callback"}}, status=400)
        return Response({"accepted": True})


def verification_return(request):  # noqa: ARG001
    response = HttpResponse(
        '<!doctype html><html lang="en"><meta name="viewport" '
        'content="width=device-width, initial-scale=1"><title>AnonymoKE verification</title>'
        '<body style="background:#0f1115;color:#f2f4f8;font:18px system-ui;padding:32px">'
        "<h1>Return to AnonymoKE</h1><p>Open the app to check your verification status. "
        "Closing this page does not change the verification result.</p></body></html>"
    )
    response["Cache-Control"] = "no-store"
    response["Content-Security-Policy"] = (
        "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'"
    )
    return response
