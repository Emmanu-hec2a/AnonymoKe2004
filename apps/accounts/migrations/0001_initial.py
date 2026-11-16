import uuid

import django.utils.timezone
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = [("auth", "0012_alter_user_first_name_max_length")]

    operations = [
        migrations.CreateModel(
            name="User",
            fields=[
                ("password", models.CharField(max_length=128, verbose_name="password")),
                ("last_login", models.DateTimeField(blank=True, null=True, verbose_name="last login")),
                ("is_superuser", models.BooleanField(default=False, help_text="Designates that this user has all permissions without explicitly assigning them.", verbose_name="superuser status")),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("email", models.EmailField(max_length=254, unique=True)),
                ("status", models.CharField(choices=[("active", "Active"), ("suspended", "Suspended"), ("banned", "Banned"), ("deletion_pending", "Deletion pending")], default="active", max_length=32)),
                ("role", models.CharField(choices=[("user", "User"), ("moderator", "Moderator"), ("support", "Support"), ("finance", "Finance"), ("admin", "Admin"), ("superadmin", "Superadmin")], default="user", max_length=32)),
                ("is_onboarded", models.BooleanField(default=False)),
                ("is_staff", models.BooleanField(default=False)),
                ("date_joined", models.DateTimeField(default=django.utils.timezone.now)),
                ("groups", models.ManyToManyField(blank=True, help_text="The groups this user belongs to. A user will get all permissions granted to each of their groups.", related_name="user_set", related_query_name="user", to="auth.group", verbose_name="groups")),
                ("user_permissions", models.ManyToManyField(blank=True, help_text="Specific permissions for this user.", related_name="user_set", related_query_name="user", to="auth.permission", verbose_name="user permissions")),
            ],
            options={"swappable": "AUTH_USER_MODEL"},
        ),
        migrations.CreateModel(
            name="ExternalIdentity",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("provider", models.CharField(max_length=20)),
                ("subject", models.CharField(max_length=255)),
                ("email_verified", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="external_identities", to="accounts.user")),
            ],
            options={
                "constraints": [models.UniqueConstraint(fields=("provider", "subject"), name="unique_external_identity")],
                "indexes": [models.Index(fields=["user", "provider"], name="accounts_ex_user_id_9a4f30_idx")],
            },
        ),
        migrations.CreateModel(
            name="MagicLinkToken",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("email", models.EmailField(max_length=254)),
                ("token_hash", models.CharField(max_length=64, unique=True)),
                ("requested_at", models.DateTimeField(auto_now_add=True)),
                ("expires_at", models.DateTimeField()),
                ("used_at", models.DateTimeField(blank=True, null=True)),
                ("failed_attempts", models.PositiveSmallIntegerField(default=0)),
            ],
            options={
                "indexes": [
                    models.Index(fields=["email", "requested_at"], name="accounts_ma_email_4ca2dc_idx"),
                    models.Index(fields=["expires_at"], name="accounts_ma_expires_4aaaf5_idx"),
                ]
            },
        ),
        migrations.CreateModel(
            name="RefreshSession",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("jti_hash", models.CharField(max_length=64, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("expires_at", models.DateTimeField()),
                ("revoked_at", models.DateTimeField(blank=True, null=True)),
                ("replaced_by", models.UUIDField(blank=True, null=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="refresh_sessions", to="accounts.user")),
            ],
            options={"indexes": [models.Index(fields=["user", "expires_at"], name="accounts_re_user_id_0a413b_idx")]},
        ),
    ]
