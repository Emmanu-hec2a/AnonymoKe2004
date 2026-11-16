from rest_framework import serializers


class VerificationStartSerializer(serializers.Serializer):
    purpose = serializers.ChoiceField(choices=["age_check", "identity_check"])
    consent = serializers.BooleanField()

    def validate_consent(self, value):
        if not value:
            raise serializers.ValidationError("verification_consent_required")
        return value


class VerificationWebhookSerializer(serializers.Serializer):
    reference = serializers.CharField(min_length=1, max_length=512)
    status = serializers.ChoiceField(choices=["passed", "failed", "review"])
    verification_level = serializers.ChoiceField(
        choices=["none", "age_verified", "verified"], default="none"
    )
    reason_code = serializers.CharField(max_length=64, required=False, default="")
