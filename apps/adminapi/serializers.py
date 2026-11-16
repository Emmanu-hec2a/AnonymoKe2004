from rest_framework import serializers

from apps.safety.models import ModerationFlagRecord, Report
from apps.store.models import Purchase


class AdminReportSerializer(serializers.ModelSerializer):
    reported_profile_id = serializers.SerializerMethodField()

    class Meta:
        model = Report
        fields = [
            "id",
            "reported_profile_id",
            "reason",
            "note",
            "evidence_message_ids",
            "status",
            "created_at",
            "updated_at",
        ]

    def get_reported_profile_id(self, obj):
        profile = getattr(obj.reported, "profile", None)
        return str(profile.public_id) if profile else None


class ModerationFlagSerializer(serializers.ModelSerializer):
    subject_profile_id = serializers.SerializerMethodField()

    class Meta:
        model = ModerationFlagRecord
        fields = [
            "id",
            "subject_profile_id",
            "content_type",
            "content_id",
            "content_digest",
            "categories",
            "layer",
            "score",
            "status",
            "created_at",
        ]

    def get_subject_profile_id(self, obj):
        profile = getattr(obj.subject_user, "profile", None)
        return str(profile.public_id) if profile else None


class ModerationActionSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=["dismiss", "review", "resolve", "suspend", "ban"])
    reason = serializers.CharField(required=False, allow_blank=True, max_length=500)

    def validate(self, attrs):
        if attrs["action"] in {"dismiss", "suspend", "ban"} and not attrs.get("reason", "").strip():
            raise serializers.ValidationError({"reason": "required_for_action"})
        return attrs


class AdminPurchaseSerializer(serializers.ModelSerializer):
    product_code = serializers.CharField(source="product.code", read_only=True)
    profile_id = serializers.SerializerMethodField()

    class Meta:
        model = Purchase
        fields = [
            "id",
            "profile_id",
            "product_code",
            "amount_kes",
            "status",
            "mpesa_receipt",
            "result_code",
            "created_at",
            "completed_at",
        ]

    def get_profile_id(self, obj):
        profile = getattr(obj.user, "profile", None) if obj.user else None
        return str(profile.public_id) if profile else None
