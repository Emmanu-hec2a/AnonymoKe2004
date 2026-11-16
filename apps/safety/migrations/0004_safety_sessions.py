import uuid

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("safety", "0003_report_evidence")]

    operations = [
        migrations.CreateModel(
            name="TrustedContact",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("contact_name", models.CharField(max_length=80)),
                ("phone_hash", models.CharField(max_length=64)),
                ("phone_ciphertext", models.BinaryField(blank=True, default=bytes)),
                ("is_verified", models.BooleanField(default=False)),
                ("invite_code_hash", models.CharField(blank=True, max_length=64)),
                ("invite_expires_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.OneToOneField(on_delete=models.deletion.CASCADE, related_name="trusted_contact", to=settings.AUTH_USER_MODEL)),
                ("linked_user", models.ForeignKey(blank=True, null=True, on_delete=models.deletion.SET_NULL, related_name="trusted_safety_relationships", to=settings.AUTH_USER_MODEL)),
            ],
            options={"indexes": [models.Index(fields=["user", "updated_at"], name="safety_trust_user_id_3bd084_idx")]},
        ),
        migrations.CreateModel(
            name="DateSession",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("status", models.CharField(choices=[("active", "Active"), ("safe", "Safe"), ("panic", "Panic alert sent"), ("cancelled", "Cancelled"), ("expired", "Expired")], default="active", max_length=16)),
                ("starts_at", models.DateTimeField()),
                ("venue_label", models.CharField(max_length=120)),
                ("check_in_due_at", models.DateTimeField()),
                ("share_approximate_location", models.BooleanField(default=False)),
                ("trusted_contact_name", models.CharField(max_length=80)),
                ("trusted_contact_phone_ciphertext", models.BinaryField(blank=True, default=bytes)),
                ("safe_at", models.DateTimeField(blank=True, null=True)),
                ("panic_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="date_sessions", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "indexes": [models.Index(fields=["user", "status", "starts_at"], name="safety_dates_user_id_5fe3c6_idx")],
                "constraints": [models.UniqueConstraint(condition=models.Q(status="active"), fields=("user",), name="unique_active_date_session_per_user")],
            },
        ),
        migrations.CreateModel(
            name="PanicAlert",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("idempotency_key", models.CharField(max_length=128)),
                ("status", models.CharField(choices=[("queued", "Queued"), ("sent", "Sent"), ("failed", "Failed")], default="queued", max_length=16)),
                ("provider_reference", models.CharField(blank=True, max_length=128)),
                ("error_code", models.CharField(blank=True, max_length=64)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("triggered_at", models.DateTimeField(auto_now_add=True)),
                ("delivered_at", models.DateTimeField(blank=True, null=True)),
                ("date_session", models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="panic_alerts", to="safety.datesession")),
                ("user", models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="panic_alerts", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "indexes": [models.Index(fields=["user", "status", "triggered_at"], name="safety_panic_user_id_9c8dfc_idx")],
                "constraints": [models.UniqueConstraint(fields=("user", "idempotency_key"), name="unique_user_panic_idempotency")],
            },
        ),
        migrations.CreateModel(
            name="SafetyAlertRecipient",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("status", models.CharField(choices=[("unread", "Unread"), ("acknowledged", "Acknowledged")], default="unread", max_length=16)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("acknowledged_at", models.DateTimeField(blank=True, null=True)),
                ("alert", models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="recipients", to="safety.panicalert")),
                ("recipient_user", models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="received_safety_alerts", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "indexes": [models.Index(fields=["recipient_user", "status", "created_at"], name="safety_safet_recipien_2d6c10_idx")],
                "constraints": [models.UniqueConstraint(fields=("alert", "recipient_user"), name="unique_safety_alert_recipient")],
            },
        ),
    ]
