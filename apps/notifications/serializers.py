from rest_framework import serializers

from .models import DeviceToken


class DeviceTokenSerializer(serializers.Serializer):
    token = serializers.CharField(min_length=20, max_length=4096)
    platform = serializers.ChoiceField(choices=DeviceToken.Platform.values)
    app_version = serializers.CharField(max_length=32, required=False, allow_blank=True)
