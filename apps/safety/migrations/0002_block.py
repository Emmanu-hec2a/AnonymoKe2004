import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("profiles", "0003_mediaasset"), ("safety", "0001_initial")]

    operations = [
        migrations.CreateModel(
            name="Block",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("blocked", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="blocks_received", to="profiles.profile")),
                ("blocker", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="blocks_made", to="profiles.profile")),
            ],
            options={
                "indexes": [models.Index(fields=["blocked", "created_at"], name="safety_blo_blocked_0a4d55_idx")],
                "constraints": [models.UniqueConstraint(fields=("blocker", "blocked"), name="unique_profile_block"), models.CheckConstraint(condition=models.Q(("blocker", models.F("blocked")), _negated=True), name="block_cannot_target_self")],
            },
        ),
    ]
