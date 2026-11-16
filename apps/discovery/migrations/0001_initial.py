import uuid

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True
    dependencies = [("profiles", "0003_mediaasset"), ("store", "0002_store_checkout")]
    operations = [migrations.CreateModel(
        name="ProfileBoost",
        fields=[
            ("id", models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
            ("client_activation_id", models.UUIDField()),
            ("activated_at", models.DateTimeField()),
            ("expires_at", models.DateTimeField(db_index=True)),
            ("profile", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="boosts", to="profiles.profile")),
            ("source_entitlement", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to="store.entitlement")),
        ],
        options={
            "constraints": [models.UniqueConstraint(fields=["profile", "client_activation_id"], name="unique_boost_activation")],
            "indexes": [models.Index(fields=["profile", "expires_at"], name="boost_profile_expiry_idx")],
        },
    )]
