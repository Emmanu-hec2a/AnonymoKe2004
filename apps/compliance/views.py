from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.profiles.models import MatchingPreference, Profile

from .models import ConsentRecord, DataSubjectRequest
from .serializers import ConsentSerializer, ConsentWriteSerializer, ErasureRequestSerializer
from .services import purge_user_data


class ConsentListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "no-store"
        return response

    def get(self, request):
        records = ConsentRecord.objects.filter(user=request.user).order_by(
            "consent_type", "-granted_at", "-id"
        )
        latest: dict[str, ConsentRecord] = {}
        for record in records:
            latest.setdefault(record.consent_type, record)
        return Response(ConsentSerializer(latest.values(), many=True).data)

    @transaction.atomic
    def post(self, request):
        # Serialize grant/revoke operations for the same account.
        type(request.user).objects.select_for_update().get(pk=request.user.pk)
        serializer = ConsentWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        latest = (
            ConsentRecord.objects.filter(user=request.user, consent_type=data["type"])
            .order_by("-granted_at", "-id")
            .first()
        )
        if (
            latest
            and latest.version == data["version"]
            and latest.granted == data["granted"]
            and (latest.revoked_at is None) == data["granted"]
        ):
            # Retrying a partial onboarding save must not create duplicate grants.
            return Response(ConsentSerializer(latest).data, status=201)
        ConsentRecord.objects.filter(
            user=request.user,
            consent_type=data["type"],
            revoked_at__isnull=True,
        ).update(revoked_at=timezone.now())
        record = ConsentRecord.objects.create(
            user=request.user,
            consent_type=data["type"],
            version=data["version"],
            granted=data["granted"],
            revoked_at=None if data["granted"] else timezone.now(),
        )
        if not data["granted"]:
            profile = Profile.objects.filter(user=request.user).first()
            if profile and data["type"] == "location":
                profile.cell = None
                profile.cell_updated_at = None
                profile.save(update_fields=["cell", "cell_updated_at", "updated_at"])
                from apps.safety.models import DateSession

                DateSession.objects.filter(user=request.user).update(
                    approximate_area=None, share_approximate_location=False
                )
            if profile and data["type"] == "sensitive_data":
                MatchingPreference.objects.filter(profile=profile).delete()
        return Response(ConsentSerializer(record).data, status=201)


class AccountErasureView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "account_erasure"

    def delete(self, request):
        serializer = ErasureRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        subject_request = DataSubjectRequest.objects.create(
            user=request.user,
            kind=DataSubjectRequest.Kind.ERASURE,
            status=DataSubjectRequest.Status.PROCESSING,
        )
        try:
            result = purge_user_data(str(request.user.id))
        except RuntimeError:
            subject_request.status = DataSubjectRequest.Status.FAILED
            subject_request.completion_proof = {"error": "erasure_storage_unavailable"}
            subject_request.save(update_fields=["status", "completion_proof"])
            return Response(
                {"error": {"code": "erasure_temporarily_unavailable"}},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        subject_request.status = DataSubjectRequest.Status.COMPLETED
        subject_request.completed_at = timezone.now()
        subject_request.completion_proof = {
            "deleted_objects": result.deleted_objects,
            "retained_financial_transactions": result.retained_financial_transactions,
        }
        subject_request.save(update_fields=["status", "completed_at", "completion_proof"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class DataExportView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "data_export"

    def post(self, request):
        from .exporting import export_user_data

        payload = export_user_data(request.user)
        subject_request = DataSubjectRequest.objects.create(
            user=request.user,
            kind=DataSubjectRequest.Kind.EXPORT,
            status=DataSubjectRequest.Status.COMPLETED,
            completed_at=timezone.now(),
        )
        payload["export_request_id"] = str(subject_request.pk)
        response = Response(payload)
        response["Cache-Control"] = "no-store"
        response["Content-Disposition"] = 'attachment; filename="anonymoke-data.json"'
        return response
