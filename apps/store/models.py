import uuid

from django.conf import settings
from django.db import models


class FinancialTransaction(models.Model):
    """Minimal retained financial record; intentionally survives account erasure."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    account_reference_hash = models.CharField(max_length=64)
    amount_kes = models.PositiveIntegerField()
    provider = models.CharField(max_length=32)
    provider_reference = models.CharField(max_length=128, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    retained_until = models.DateTimeField()

    class Meta:
        indexes = [models.Index(fields=["retained_until"])]


class Product(models.Model):
    class Kind(models.TextChoices):
        BOOST = "boost", "Boost"
        PREMIUM = "premium", "Premium"
        UNMASK_FAST_TRACK = "unmask_fast_track", "Fast-track unmask"
        VOUCHER = "voucher", "Voucher"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=120)
    price_kes = models.PositiveIntegerField()
    kind = models.CharField(max_length=32, choices=Kind.choices)
    duration_days = models.PositiveSmallIntegerField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["is_active", "kind"])]


class Purchase(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"
        EXPIRED = "expired", "Expired"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="purchases",
    )
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="purchases")
    amount_kes = models.PositiveIntegerField()
    phone_hash = models.CharField(max_length=64)
    phone_ciphertext = models.BinaryField(blank=True, default=bytes)
    idempotency_key = models.CharField(max_length=128)
    checkout_request_id = models.CharField(max_length=128, unique=True, null=True, blank=True)
    merchant_request_id = models.CharField(max_length=128, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    mpesa_receipt = models.CharField(max_length=64, unique=True, null=True, blank=True)
    result_code = models.IntegerField(null=True, blank=True)
    raw_callback = models.JSONField(default=dict, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "idempotency_key"], name="unique_user_purchase_idempotency"
            )
        ]
        indexes = [models.Index(fields=["user", "status", "created_at"])]


class Entitlement(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="entitlements"
    )
    kind = models.CharField(max_length=32, choices=Product.Kind.choices)
    quantity = models.PositiveIntegerField(default=0)
    expires_at = models.DateTimeField(null=True, blank=True)
    source_purchase = models.ForeignKey(
        Purchase, on_delete=models.PROTECT, related_name="entitlements"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["source_purchase", "kind"], name="unique_source_entitlement_kind"
            )
        ]
        indexes = [models.Index(fields=["user", "kind", "expires_at"])]


class PaymentCallbackLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    checkout_request_id = models.CharField(max_length=128, unique=True)
    payload = models.JSONField(default=dict)
    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["received_at", "processed_at"])]
