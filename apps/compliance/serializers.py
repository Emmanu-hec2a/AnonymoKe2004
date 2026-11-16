from rest_framework import serializers

from .models import ConsentRecord


class ConsentSerializer(serializers.ModelSerializer):
    type = serializers.CharField(source="consent_type")

    class Meta:
        model = ConsentRecord
        fields = ["type", "version", "granted", "granted_at", "revoked_at"]
        read_only_fields = ["granted_at", "revoked_at"]


class ConsentWriteSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=ConsentRecord.ConsentType.values)
    version = serializers.CharField(max_length=64)
    granted = serializers.BooleanField()


class ErasureRequestSerializer(serializers.Serializer):
    confirm = serializers.BooleanField()

    def validate_confirm(self, value):
        if not value:
            raise serializers.ValidationError("confirmation_required")
        return value
