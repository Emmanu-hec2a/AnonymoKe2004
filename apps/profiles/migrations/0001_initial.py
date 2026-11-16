import uuid

from django.conf import settings
from django.contrib.gis.db import models
import django.db.models.deletion
from django.db import migrations


class Migration(migrations.Migration):
    initial = True
    dependencies = [("accounts", "0001_initial")]

    operations = [
        migrations.CreateModel(
            name="Profile",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("public_id", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("alias", models.CharField(blank=True, max_length=40)),
                ("age_years", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("birth_date_ciphertext", models.BinaryField(blank=True, default=bytes)),
                ("bio", models.TextField(blank=True, max_length=300)),
                ("interests", models.JSONField(blank=True, default=list)),
                ("blurred_avatar_key", models.CharField(blank=True, max_length=255)),
                ("audio_key", models.CharField(blank=True, max_length=255)),
                ("audio_duration_ms", models.PositiveIntegerField(default=0)),
                ("cell", models.PointField(blank=True, geography=True, null=True, srid=4326)),
                ("cell_updated_at", models.DateTimeField(blank=True, null=True)),
                ("location_flagged", models.BooleanField(default=False)),
                ("verification_level", models.CharField(choices=[("none", "None"), ("age_verified", "Age verified"), ("verified", "Verified")], default="none", max_length=20)),
                ("is_discoverable", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="profile", to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name="PrivateIdentity",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("username", models.CharField(blank=True, max_length=20, null=True, unique=True)),
                ("real_first_name_ciphertext", models.BinaryField(blank=True, default=bytes)),
                ("real_avatar_key", models.CharField(blank=True, max_length=255)),
                ("social_handles_ciphertext", models.BinaryField(blank=True, default=bytes)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="private_identity", to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name="MatchingPreference",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("target_genders", models.JSONField(default=list)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("profile", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="matching_preference", to="profiles.profile")),
            ],
        ),
    ]
