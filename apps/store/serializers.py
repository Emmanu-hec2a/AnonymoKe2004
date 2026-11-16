from rest_framework import serializers

from .models import Entitlement, Product, Purchase


class ProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = ["code", "name", "price_kes", "kind", "duration_days"]


class PurchaseCreateSerializer(serializers.Serializer):
    product_code = serializers.CharField(max_length=64)
    phone = serializers.CharField(max_length=20, write_only=True)


class PurchaseSerializer(serializers.ModelSerializer):
    product_code = serializers.CharField(source="product.code", read_only=True)

    class Meta:
        model = Purchase
        fields = [
            "id",
            "product_code",
            "amount_kes",
            "status",
            "result_code",
            "created_at",
            "completed_at",
        ]


class EntitlementSerializer(serializers.ModelSerializer):
    class Meta:
        model = Entitlement
        fields = ["kind", "quantity", "expires_at"]
