import logging
import uuid

from django.db import transaction
from rest_framework import serializers
from rest_framework.response import Response

from apps.accounts.models import User
from apps.profiles.storage import R2MediaStore

from .media import attachment_data, ensure_media_access, process_chat_attachment
from .models import ChatAttachment
from .views import MessageReadView, _profile_for_user


class UploadSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=["image", "audio"])
    content_type = serializers.ChoiceField(
        choices=["image/jpeg", "image/png", "image/webp", "audio/mp4", "audio/x-m4a"]
    )
    size_bytes = serializers.IntegerField(min_value=1, max_value=10485760)

    def validate(self, values):
        if (values["kind"] == "image") != values["content_type"].startswith("image/"):
            raise serializers.ValidationError("media_content_type_invalid")
        if values["kind"] == "audio" and values["size_bytes"] > 5242880:
            raise serializers.ValidationError("media_too_large")
        return values


class ChatUploadView(MessageReadView):
    throttle_scope = "chat_media"

    def post(self, request, match_id):
        serializer = UploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        profile = _profile_for_user(request.user)
        try:
            with transaction.atomic():
                User.objects.select_for_update().get(pk=request.user.pk, status="active")
                match = ensure_media_access(profile, match_id, serializer.validated_data["kind"])
                asset = ChatAttachment.objects.create(
                    match=match,
                    sender=profile,
                    incoming_key=f"chat/incoming/{uuid.uuid4()}",
                    disguise_voice=match.state != "unmasked",
                    **serializer.validated_data,
                )
                url = R2MediaStore().presign_upload(asset.incoming_key, asset.content_type)
        except ValueError as error:
            return Response({"error": {"code": str(error)}}, status=403)
        except Exception:  # noqa: BLE001
            return Response({"error": {"code": "media_storage_unavailable"}}, status=503)
        return Response(
            {
                "upload_id": asset.pk,
                "upload_url": url,
                "method": "PUT",
                "headers": {"Content-Type": asset.content_type},
                "expires_in_seconds": 900,
            },
            status=201,
        )


class ChatMediaCompleteView(MessageReadView):
    throttle_scope = "chat_media"

    def post(self, request, match_id, asset_id):
        asset = ChatAttachment.objects.filter(
            pk=asset_id, match_id=match_id, sender__user=request.user
        ).first()
        if not asset:
            return Response({"error": {"code": "attachment_not_found"}}, status=404)
        try:
            ensure_media_access(asset.sender, match_id, asset.kind)
            if asset.status == "pending":
                head = R2MediaStore().head(asset.incoming_key)
                maximum = 10485760 if asset.kind == "image" else 5242880
                if (
                    not 0 < int(head.get("ContentLength", 0)) <= maximum
                    or head.get("ContentType") != asset.content_type
                ):
                    raise ValueError("media_size_or_type_invalid")
                with transaction.atomic():
                    User.objects.select_for_update().get(pk=request.user.pk, status="active")
                    ensure_media_access(asset.sender, match_id, asset.kind)
                    changed = ChatAttachment.objects.filter(pk=asset.pk, status="pending").update(
                        status="processing"
                    )
                    if changed:

                        def queue():
                            try:
                                process_chat_attachment.apply_async(
                                    args=[str(asset.pk)], retry=False
                                )
                            except Exception:  # noqa: BLE001 - periodic recovery retries the durable intent
                                logging.getLogger("anonymoke.chat").warning(
                                    "chat_media_queue_pending_recovery"
                                )

                        transaction.on_commit(queue)
                asset.refresh_from_db()
            return Response(attachment_data(asset, asset.sender), status=202)
        except ValueError as error:
            return Response({"error": {"code": str(error)}}, status=400)
        except Exception:  # noqa: BLE001
            return Response({"error": {"code": "media_storage_unavailable"}}, status=503)


class ChatMediaView(MessageReadView):
    def get(self, request, match_id, asset_id):
        asset = (
            ChatAttachment.objects.select_related("sender__user")
            .filter(pk=asset_id, match_id=match_id)
            .first()
        )
        if not asset:
            return Response(status=404)
        try:
            data = attachment_data(asset, _profile_for_user(request.user))
        except ValueError:
            return Response({"error": {"code": "attachment_not_found"}}, status=404)
        except Exception:  # noqa: BLE001
            return Response({"error": {"code": "media_storage_unavailable"}}, status=503)
        response = Response(data)
        response["Cache-Control"] = "no-store"
        return response
