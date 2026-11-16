from django.conf import settings
from rest_framework import serializers


class MessageWriteSerializer(serializers.Serializer):
    body = serializers.CharField(max_length=settings.CHAT_MAX_MESSAGE_LENGTH, trim_whitespace=True)
    client_message_id = serializers.UUIDField(required=False)


class MessageSerializer(serializers.Serializer):
    message_id = serializers.UUIDField(source="id")
    sender_profile_id = serializers.UUIDField(source="sender.public_id")
    body = serializers.CharField()
    moderation_status = serializers.CharField()
    created_at = serializers.DateTimeField()
    read_at = serializers.DateTimeField(allow_null=True)
    client_message_id = serializers.UUIDField(allow_null=True)
