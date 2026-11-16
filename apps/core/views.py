from django.conf import settings
from django.db import connection
from rest_framework.response import Response
from rest_framework.views import APIView


class HealthView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):  # noqa: ARG002
        return Response({"status": "ok"})


class ReadinessView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):  # noqa: ARG002
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
        except Exception:
            return Response({"status": "not_ready"}, status=503)
        return Response({"status": "ready"})


class ConfigView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):  # noqa: ARG002
        return Response(
            {
                "api_version": "v1",
                "min_supported_version": "0.1.0",
                "maintenance_mode": False,
                "features": {
                    "signups": True,
                    "discovery": True,
                    "chat": False,
                    "purchases": settings.PAYMENT_PROVIDER == "daraja",
                    "unmask": True,
                },
                "legal_document_versions": {},
                "distance_bucket_labels": [
                    "<1 km",
                    "1-2 km",
                    "2-5 km",
                    "5-10 km",
                    "10-25 km",
                    "25+ km",
                ],
            }
        )
