from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="DeviceToken",
            fields=[
                (
                    "id",
                    models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID"),
                ),
                (
                    "token",
                    models.CharField(max_length=4096, unique=True),
                ),
                (
                    "platform",
                    models.CharField(
                        choices=[("android", "Android"), ("ios", "iOS")],
                        max_length=16,
                    ),
                ),
                ("app_version", models.CharField(blank=True, max_length=32)),
                ("is_enabled", models.BooleanField(default=True)),
                ("last_seen_at", models.DateTimeField(auto_now=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="notification_devices",
                        to="accounts.user",
                    ),
                ),
            ],
            options={
                "indexes": [models.Index(fields=["user", "is_enabled"], name="notificati_user_id_3f3e1b_idx")],
            },
        ),
    ]
