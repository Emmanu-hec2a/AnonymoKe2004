from rest_framework import serializers


class MagicLinkRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()


class MagicLinkVerifySerializer(serializers.Serializer):
    token = serializers.CharField(min_length=20, max_length=200)


class SocialVerifySerializer(serializers.Serializer):
    credential = serializers.CharField(min_length=20, max_length=10000)


class RefreshTokenSerializer(serializers.Serializer):
    refresh_token = serializers.CharField(min_length=20, max_length=10000)
