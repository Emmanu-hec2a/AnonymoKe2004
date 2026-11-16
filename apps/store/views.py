import secrets

from django.conf import settings
from django.db.models import Q
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Entitlement, Product, Purchase
from .providers import PaymentProviderError
from .serializers import (
    EntitlementSerializer,
    ProductSerializer,
    PurchaseCreateSerializer,
    PurchaseSerializer,
)
from .services import create_purchase, process_daraja_callback


class ProductListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):  # noqa: ARG002
        products = Product.objects.filter(is_active=True).order_by("price_kes", "code")
        return Response(ProductSerializer(products, many=True).data)


class PurchaseCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = PurchaseCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        idempotency_key = request.headers.get("Idempotency-Key", "")
        try:
            purchase = create_purchase(
                user=request.user,
                product_code=serializer.validated_data["product_code"],
                phone=serializer.validated_data["phone"],
                idempotency_key=idempotency_key,
            )
        except ValueError as exc:
            return Response({"error": {"code": str(exc)}}, status=400)
        except PaymentProviderError as exc:
            return Response({"error": {"code": str(exc)}}, status=503)
        return Response(PurchaseSerializer(purchase).data, status=201)


class PurchaseDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, purchase_id):
        purchase = Purchase.objects.filter(id=purchase_id, user=request.user).first()
        if not purchase:
            return Response({"error": {"code": "purchase_not_found"}}, status=404)
        return Response(PurchaseSerializer(purchase).data)


class EntitlementListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        entitlements = Entitlement.objects.filter(user=request.user).filter(
            Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now()), quantity__gt=0
        )
        return Response(EntitlementSerializer(entitlements, many=True).data)


class DarajaCallbackView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request, callback_token):
        if not settings.DARAJA_CALLBACK_TOKEN or not secrets.compare_digest(
            callback_token, settings.DARAJA_CALLBACK_TOKEN
        ):
            return Response({"ResultCode": 1, "ResultDesc": "Rejected"}, status=403)
        if not isinstance(request.data, dict):
            return Response({"ResultCode": 1, "ResultDesc": "Invalid payload"}, status=400)
        try:
            process_daraja_callback(payload=request.data)
        except (ValueError, PaymentProviderError):
            return Response({"ResultCode": 1, "ResultDesc": "Rejected"}, status=400)
        return Response({"ResultCode": 0, "ResultDesc": "Accepted"})
