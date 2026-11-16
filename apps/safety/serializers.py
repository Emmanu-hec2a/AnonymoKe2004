import hashlib
import hmac
from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from rest_framework import serializers

from apps.compliance.consent import has_active_consent
from apps.core.crypto import decrypt_text, encrypt_text
from apps.store.services import normalize_kenyan_phone

from .models import Block, DateSession, PanicAlert, Report, SafetyAlertRecipient, TrustedContact


class ReportWriteSerializer(serializers.Serializer):
    profile_id = serializers.UUIDField()
    reason = serializers.ChoiceField(choices=Report.Reason.values)
    note = serializers.CharField(required=False, allow_blank=True, max_length=1000)
    message_ids = serializers.ListField(
        child=serializers.UUIDField(), required=False, allow_empty=True, max_length=20
    )


class BlockWriteSerializer(serializers.Serializer):
    profile_id = serializers.UUIDField()


class BlockedProfileSerializer(serializers.ModelSerializer):
    profile_id = serializers.UUIDField(source="blocked.public_id", read_only=True)
    alias = serializers.CharField(source="blocked.alias", read_only=True)

    class Meta:
        model = Block
        fields = ["id", "profile_id", "alias", "created_at"]
        read_only_fields = fields


class MyReportSerializer(serializers.ModelSerializer):
    report_id = serializers.UUIDField(source="id", read_only=True)
    reported_profile_id = serializers.UUIDField(source="reported.profile.public_id", read_only=True)
    reported_alias = serializers.CharField(source="reported.profile.alias", read_only=True)

    class Meta:
        model = Report
        fields = [
            "report_id",
            "reported_profile_id",
            "reported_alias",
            "reason",
            "note",
            "status",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class TrustedContactSerializer(serializers.ModelSerializer):
    phone = serializers.CharField(write_only=True, required=False, allow_blank=True, max_length=24)
    phone_masked = serializers.SerializerMethodField()
    is_linked = serializers.SerializerMethodField()
    linked_alias = serializers.SerializerMethodField()

    class Meta:
        model = TrustedContact
        fields = [
            "contact_name",
            "phone",
            "phone_masked",
            "is_verified",
            "is_linked",
            "linked_alias",
            "updated_at",
        ]
        read_only_fields = [
            "phone_masked",
            "is_verified",
            "is_linked",
            "linked_alias",
            "updated_at",
        ]

    def validate_phone(self, value):
        if not value:
            return ""
        try:
            return normalize_kenyan_phone(value)
        except ValueError as exc:
            raise serializers.ValidationError("invalid_kenyan_phone") from exc

    def validate_contact_name(self, value):
        value = value.strip()
        if len(value) < 2:
            raise serializers.ValidationError("contact_name_invalid")
        return value

    def create(self, validated_data):
        phone = validated_data.pop("phone", "")
        return TrustedContact.objects.create(
            phone_hash=(
                hmac.new(settings.JWT_SECRET.encode(), phone.encode(), hashlib.sha256).hexdigest()
                if phone
                else ""
            ),
            phone_ciphertext=encrypt_text(phone) if phone else b"",
            **validated_data,
        )

    def update(self, instance, validated_data):
        if instance.linked_user_id and any(
            key in validated_data
            and (key == "phone" or validated_data[key] != getattr(instance, key))
            for key in ("contact_name", "phone")
        ):
            raise serializers.ValidationError(
                {"error": {"code": "contact_replacement_requires_unlink"}}
            )
        phone = validated_data.pop("phone", None)
        for key, value in validated_data.items():
            setattr(instance, key, value)
        if phone is not None:
            instance.phone_hash = (
                hmac.new(settings.JWT_SECRET.encode(), phone.encode(), hashlib.sha256).hexdigest()
                if phone
                else ""
            )
            instance.phone_ciphertext = encrypt_text(phone) if phone else b""
            instance.is_verified = False
        instance.save()
        return instance

    def get_phone_masked(self, obj):
        if not obj.phone_ciphertext:
            return ""
        try:
            phone = decrypt_text(bytes(obj.phone_ciphertext))
        except ValueError:
            return ""
        return f"•••• {phone[-4:]}" if phone else ""

    def get_is_linked(self, obj):
        return obj.linked_user_id is not None and obj.linked_user.status == "active"

    def get_linked_alias(self, obj):
        if not obj.linked_user_id:
            return None
        return getattr(getattr(obj.linked_user, "profile", None), "alias", "Linked account")


class DateSessionWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = DateSession
        fields = [
            "starts_at",
            "venue_label",
            "check_in_due_at",
            "share_approximate_location",
        ]

    def validate_venue_label(self, value):
        value = value.strip()
        if len(value) < 2:
            raise serializers.ValidationError("venue_label_invalid")
        return value

    def validate(self, attrs):
        starts_at = attrs.get("starts_at", getattr(self.instance, "starts_at", None))
        check_in_due_at = attrs.get(
            "check_in_due_at", getattr(self.instance, "check_in_due_at", None)
        )
        if starts_at and check_in_due_at and check_in_due_at <= starts_at:
            raise serializers.ValidationError("check_in_due_at_must_follow_start")
        if starts_at and check_in_due_at and check_in_due_at - starts_at > timedelta(hours=24):
            raise serializers.ValidationError("date_duration_exceeds_24_hours")
        if (
            (not self.instance or "check_in_due_at" in attrs)
            and check_in_due_at
            and check_in_due_at <= timezone.now()
        ):
            raise serializers.ValidationError("check_in_due_at_must_be_future")
        if (
            starts_at
            and (
                not self.instance
                or ("starts_at" in attrs and attrs["starts_at"] != self.instance.starts_at)
            )
            and not timezone.now() - timedelta(minutes=15)
            <= starts_at
            <= timezone.now() + timedelta(days=365)
        ):
            raise serializers.ValidationError("date_start_out_of_range")
        return attrs


class DateSessionSerializer(serializers.ModelSerializer):
    approximate_area = serializers.SerializerMethodField()
    owner_alias = serializers.CharField(
        source="user.profile.alias", read_only=True, default="Someone you trust"
    )

    class Meta:
        model = DateSession
        fields = [
            "id",
            "status",
            "starts_at",
            "venue_label",
            "check_in_due_at",
            "share_approximate_location",
            "trusted_contact_name",
            "created_at",
            "updated_at",
            "safe_at",
            "panic_at",
            "approximate_area",
            "owner_alias",
            "overdue_at",
        ]
        read_only_fields = [
            "id",
            "status",
            "trusted_contact_name",
            "created_at",
            "updated_at",
            "safe_at",
            "panic_at",
        ]

    def get_approximate_area(self, obj):
        return (
            obj.approximate_area
            if obj.share_approximate_location and has_active_consent(obj.user, "location")
            else None
        )


class PanicAlertSerializer(serializers.ModelSerializer):
    push_status = serializers.SerializerMethodField()
    acknowledged_at = serializers.SerializerMethodField()
    session_status = serializers.CharField(source="date_session.status", read_only=True)

    class Meta:
        model = PanicAlert
        fields = [
            "id",
            "date_session",
            "status",
            "error_code",
            "triggered_at",
            "delivered_at",
            "push_status",
            "acknowledged_at",
            "session_status",
        ]
        read_only_fields = fields

    def get_push_status(self, obj):
        delivery = getattr(obj, "push_delivery", None)
        return delivery.status if delivery else "unavailable"

    def get_acknowledged_at(self, obj):
        recipient = obj.recipients.filter(status="acknowledged").first()
        return recipient.acknowledged_at if recipient else None


class SafetyAlertRecipientSerializer(serializers.ModelSerializer):
    session_status = serializers.CharField(source="alert.date_session.status", read_only=True)
    safe_at = serializers.DateTimeField(source="alert.date_session.safe_at", read_only=True)
    approximate_area = serializers.SerializerMethodField()
    alert_id = serializers.UUIDField(source="alert.id", read_only=True)
    owner_alias = serializers.SerializerMethodField()
    venue_label = serializers.CharField(source="alert.date_session.venue_label", read_only=True)
    starts_at = serializers.DateTimeField(source="alert.date_session.starts_at", read_only=True)
    check_in_due_at = serializers.DateTimeField(
        source="alert.date_session.check_in_due_at", read_only=True
    )
    share_approximate_location = serializers.BooleanField(
        source="alert.date_session.share_approximate_location", read_only=True
    )

    class Meta:
        model = SafetyAlertRecipient
        fields = [
            "id",
            "alert_id",
            "status",
            "owner_alias",
            "venue_label",
            "starts_at",
            "check_in_due_at",
            "share_approximate_location",
            "created_at",
            "acknowledged_at",
            "session_status",
            "safe_at",
            "approximate_area",
        ]
        read_only_fields = fields

    def get_owner_alias(self, obj):
        return getattr(getattr(obj.alert.user, "profile", None), "alias", "Someone")

    def get_approximate_area(self, obj):
        session = obj.alert.date_session
        return (
            session.approximate_area
            if session.share_approximate_location and has_active_consent(obj.alert.user, "location")
            else None
        )
