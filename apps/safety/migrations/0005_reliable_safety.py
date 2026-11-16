import uuid

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


def upgrade_existing(apps, schema_editor):
    Plan = apps.get_model("safety", "DateSession")
    Contact = apps.get_model("safety", "TrustedContact")
    Alert = apps.get_model("safety", "PanicAlert")
    Recipient = apps.get_model("safety", "SafetyAlertRecipient")
    Delivery = apps.get_model("safety", "SafetyDelivery")
    alias = schema_editor.connection.alias
    for plan in Plan.objects.using(alias).filter(status__in=["active", "panic"]).iterator():
        recipient = Recipient.objects.using(alias).filter(alert__date_session_id=plan.pk).order_by("-created_at").first()
        contact = Contact.objects.using(alias).filter(user_id=plan.user_id).first()
        plan.trusted_contact_user_id = recipient.recipient_user_id if recipient else contact.linked_user_id if contact else None
        plan.save(using=alias, update_fields=["trusted_contact_user"])
    for alert in Alert.objects.using(alias).all().iterator():
        recipient = Recipient.objects.using(alias).filter(alert_id=alert.pk).first()
        alert.status = "acknowledged" if recipient and recipient.status == "acknowledged" else "stored"
        alert.delivered_at = recipient.acknowledged_at if recipient and recipient.status == "acknowledged" else None
        alert.save(using=alias, update_fields=["status", "delivered_at"])
        if recipient:
            Delivery.objects.using(alias).get_or_create(dedupe_key=f"panic:{alert.pk}", defaults={"session_id": alert.date_session_id, "recipient_id": recipient.recipient_user_id, "alert_id": alert.pk, "event_type": "safety.panic", "status": "queued" if alert.date_session.status == "panic" else "cancelled"})


class Migration(migrations.Migration):
    dependencies = [("safety", "0004_safety_sessions"), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.AddField(model_name="datesession", name="trusted_contact_user", field=models.ForeignKey(to=settings.AUTH_USER_MODEL, on_delete=django.db.models.deletion.SET_NULL, null=True, blank=True, related_name="shared_date_plans")),
        migrations.AddField(model_name="datesession", name="approximate_area", field=models.JSONField(null=True, blank=True)),
        migrations.AddField(model_name="datesession", name="reminder_sent_at", field=models.DateTimeField(null=True, blank=True)),
        migrations.AddField(model_name="datesession", name="overdue_at", field=models.DateTimeField(null=True, blank=True)),
        migrations.AlterField(model_name="panicalert", name="status", field=models.CharField(max_length=16, choices=[("queued", "Queued"), ("sent", "Sent"), ("failed", "Failed"), ("stored", "Saved in app"), ("push_accepted", "Push accepted"), ("acknowledged", "Contact acknowledged")], default="stored")),
        migrations.CreateModel(name="SafetyDelivery", fields=[
            ("id", models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
            ("event_type", models.CharField(max_length=48)),
            ("dedupe_key", models.CharField(max_length=160, unique=True)),
            ("status", models.CharField(max_length=24, default="queued")),
            ("attempts", models.PositiveSmallIntegerField(default=0)),
            ("next_attempt_at", models.DateTimeField(default=django.utils.timezone.now)),
            ("lease_until", models.DateTimeField(null=True, blank=True)),
            ("error_code", models.CharField(max_length=64, blank=True)),
            ("accepted_at", models.DateTimeField(null=True, blank=True)),
            ("created_at", models.DateTimeField(auto_now_add=True)),
            ("updated_at", models.DateTimeField(auto_now=True)),
            ("session", models.ForeignKey(to="safety.datesession", on_delete=django.db.models.deletion.CASCADE, related_name="deliveries")),
            ("recipient", models.ForeignKey(to=settings.AUTH_USER_MODEL, on_delete=django.db.models.deletion.CASCADE)),
            ("alert", models.OneToOneField(to="safety.panicalert", on_delete=django.db.models.deletion.CASCADE, null=True, blank=True, related_name="push_delivery")),
        ], options={"indexes": [models.Index(fields=["status", "next_attempt_at"], name="safety_delivery_pending")]}),
        migrations.RunPython(upgrade_existing, migrations.RunPython.noop),
    ]
