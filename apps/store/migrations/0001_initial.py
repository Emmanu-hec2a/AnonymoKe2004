import uuid

from django.conf import settings
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = [("accounts", "0001_initial")]

    operations = [
        migrations.CreateModel(
            name="FinancialTransaction",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("account_reference_hash", models.CharField(max_length=64)),
                ("amount_kes", models.PositiveIntegerField()),
                ("provider", models.CharField(max_length=32)),
                ("provider_reference", models.CharField(max_length=128, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("retained_until", models.DateTimeField()),
                ("user", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
            options={"indexes": [models.Index(fields=["retained_until"], name="store_fina_retained_9dce99_idx")]},
        ),
    ]
