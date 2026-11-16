import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("store", "0001_initial")]

    operations = [
        migrations.CreateModel(
            name="Product",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("code", models.CharField(max_length=64, unique=True)),
                ("name", models.CharField(max_length=120)),
                ("price_kes", models.PositiveIntegerField()),
                ("kind", models.CharField(choices=[("boost", "Boost"), ("premium", "Premium"), ("unmask_fast_track", "Fast-track unmask"), ("voucher", "Voucher")], max_length=32)),
                ("duration_days", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"indexes": [models.Index(fields=["is_active", "kind"])]},
        ),
        migrations.CreateModel(
            name="Purchase",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("amount_kes", models.PositiveIntegerField()),
                ("phone_hash", models.CharField(max_length=64)),
                ("phone_ciphertext", models.BinaryField(blank=True, default=bytes)),
                ("idempotency_key", models.CharField(max_length=128)),
                ("checkout_request_id", models.CharField(blank=True, max_length=128, null=True, unique=True)),
                ("merchant_request_id", models.CharField(blank=True, max_length=128)),
                ("status", models.CharField(choices=[("pending", "Pending"), ("completed", "Completed"), ("failed", "Failed"), ("cancelled", "Cancelled"), ("expired", "Expired")], default="pending", max_length=16)),
                ("mpesa_receipt", models.CharField(blank=True, max_length=64, null=True, unique=True)),
                ("result_code", models.IntegerField(blank=True, null=True)),
                ("raw_callback", models.JSONField(blank=True, default=dict)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("product", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="purchases", to="store.product")),
                ("user", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="purchases", to=settings.AUTH_USER_MODEL)),
            ],
            options={"indexes": [models.Index(fields=["user", "status", "created_at"])], "constraints": [models.UniqueConstraint(fields=("user", "idempotency_key"), name="unique_user_purchase_idempotency")]},
        ),
        migrations.CreateModel(
            name="PaymentCallbackLog",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("checkout_request_id", models.CharField(max_length=128, unique=True)),
                ("payload", models.JSONField(blank=True, default=dict)),
                ("received_at", models.DateTimeField(auto_now_add=True)),
                ("processed_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={"indexes": [models.Index(fields=["received_at", "processed_at"])]},
        ),
        migrations.CreateModel(
            name="Entitlement",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("kind", models.CharField(choices=[("boost", "Boost"), ("premium", "Premium"), ("unmask_fast_track", "Fast-track unmask"), ("voucher", "Voucher")], max_length=32)),
                ("quantity", models.PositiveIntegerField(default=0)),
                ("expires_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("source_purchase", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="entitlements", to="store.purchase")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="entitlements", to=settings.AUTH_USER_MODEL)),
            ],
            options={"indexes": [models.Index(fields=["user", "kind", "expires_at"])], "constraints": [models.UniqueConstraint(fields=("source_purchase", "kind"), name="unique_source_entitlement_kind")]},
        ),
    ]
