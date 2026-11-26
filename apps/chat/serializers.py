from django.conf import settings
from rest_framework import serializers


class MessageWriteSerializer(serializers.Serializer):
    body = serializers.CharField(
        max_length=settings.CHAT_MAX_MESSAGE_LENGTH,
        trim_whitespace=True,
        allow_blank=True,
        default="",
    )
    client_message_id = serializers.UUIDField(required=False)
    reply_to_id = serializers.UUIDField(required=False, allow_null=True)
    attachment_id = serializers.UUIDField(required=False, allow_null=True)


class MessageSerializer(serializers.Serializer):
    message_id = serializers.UUIDField(source="id")
    sender_profile_id = serializers.UUIDField(source="sender.public_id")
    body = serializers.CharField()
    moderation_status = serializers.CharField()
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()
    read_at = serializers.DateTimeField(allow_null=True)
    client_message_id = serializers.UUIDField(allow_null=True)
    delivered_at = serializers.DateTimeField(allow_null=True)
    reply_to = serializers.SerializerMethodField()
    attachment = serializers.SerializerMethodField()

    def get_reply_to(self, message):
        reply = message.reply_to
        if not reply:
            return None
        available = (
            reply.match_id == message.match_id
            and reply.deleted_at is None
            and reply.moderation_status == "clear"
        )
        return {
            "message_id": str(reply.pk),
            "sender_profile_id": str(reply.sender.public_id),
            "body": reply.body[:140] if available else "Message unavailable",
            "kind": reply.attachment.kind if available and reply.attachment_id else "text",
            "available": available,
        }

    def get_attachment(self, message):
        if not message.attachment_id:
            return None
        from .media import attachment_data

        viewer = self.context.get("viewer")
        if viewer is None:
            return {
                "id": str(message.attachment_id),
                "kind": message.attachment.kind,
                "status": "unavailable",
                "url": None,
            }
        try:
            return attachment_data(message.attachment, viewer, self.context, message=message)
        except Exception:  # noqa: BLE001 - access loss must not expose media or break a timeline
            return {
                "id": str(message.attachment_id),
                "kind": message.attachment.kind,
                "status": "unavailable",
                "url": None,
            }
