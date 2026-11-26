import time
import uuid

import jwt
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.conf import settings

from apps.accounts.models import User
from apps.matching.services import participant_match
from apps.profiles.models import Profile

from .activity import peer_activity, update_activity
from .models import Message
from .serializers import MessageSerializer
from .services import mark_delivered, mark_read, send_message


class ChatConsumer(AsyncJsonWebsocketConsumer):
    async def receive(self, text_data=None, bytes_data=None, **kwargs):
        if bytes_data is not None or (text_data is not None and len(text_data) > 16384):
            await self.close(code=1009)
            return
        try:
            await super().receive(text_data=text_data, bytes_data=bytes_data, **kwargs)
        except (ValueError, TypeError):
            await self.close(code=4400)

    async def connect(self):
        self.match_id = self.scope["url_route"]["kwargs"]["match_id"]
        token = None  # Bearer headers keep session credentials out of access logs.
        headers = dict(self.scope.get("headers", []))
        authorization = headers.get(b"authorization", b"").decode()
        if authorization.startswith("Bearer "):
            token = authorization[7:]
        self.token = token
        self.profile = await self._authenticate(token, self.match_id)
        if not self.profile:
            await self.close(code=4401)
            return
        self.group_name = f"match-{self.match_id}"
        self.message_times = []
        self.event_times = []
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        await self.send_json({"type": "activity", **await self._activity(True, False)})

    async def disconnect(self, close_code):  # noqa: ARG002
        if hasattr(self, "group_name"):
            try:
                await self._activity(False, False)
            except ValueError:
                pass
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive_json(self, content, **kwargs):  # noqa: ARG002
        now = time.monotonic()
        self.event_times = [stamp for stamp in self.event_times if now - stamp < 10]
        if len(self.event_times) >= 20:
            await self.send_json({"type": "error", "code": "event_rate_limited"})
            return
        self.event_times.append(now)
        if not await self._authenticate(self.token, self.match_id):
            await self.close(code=4403)
            return
        if not isinstance(content, dict):
            await self.send_json({"type": "error", "code": "event_invalid"})
            return
        message_type = content.get("type")
        if message_type == "ping":
            await self.send_json({"type": "pong", **await self._activity(True, False)})
            return
        if message_type == "activity":
            active, typing = content.get("active"), content.get("typing", False)
            if not isinstance(active, bool) or not isinstance(typing, bool):
                await self.send_json({"type": "error", "code": "event_invalid"})
                return
            await self.send_json({"type": "activity", **await self._activity(active, typing)})
            return
        if message_type == "delivered":
            try:
                ids = content.get("message_ids", [])
                if not isinstance(ids, list) or len(ids) > 100:
                    raise ValueError("event_invalid")
                await self._delivered([uuid.UUID(value) for value in ids])
            except (ValueError, TypeError, AttributeError):
                await self.send_json({"type": "error", "code": "event_invalid"})
            return
        if message_type == "read":
            try:
                anchor = content.get("through_message_id")
                await self._mark_read(
                    self.profile, self.match_id, uuid.UUID(anchor) if anchor else None
                )
            except (ValueError, TypeError, AttributeError):
                await self.send_json({"type": "error", "code": "match_not_found"})
            return
        if message_type != "message" or not isinstance(content.get("body"), str):
            await self.send_json({"type": "error", "code": "event_invalid"})
            return
        now = time.monotonic()
        self.message_times = [timestamp for timestamp in self.message_times if now - timestamp < 10]
        if len(self.message_times) >= 10:
            await self.send_json({"type": "error", "code": "message_rate_limited"})
            return
        self.message_times.append(now)
        try:
            client_id = content.get("client_message_id")
            payload = await self._send_message(
                self.profile,
                self.match_id,
                content["body"],
                uuid.UUID(client_id) if client_id else None,
                uuid.UUID(content["reply_to_id"]) if content.get("reply_to_id") else None,
                uuid.UUID(content["attachment_id"]) if content.get("attachment_id") else None,
            )
            await self.send_json({"type": "message.ack", **payload})
        except (ValueError, TypeError, AttributeError) as exc:
            await self.send_json(
                {
                    "type": "error",
                    "code": str(exc) if isinstance(exc, ValueError) else "event_invalid",
                }
            )

    async def chat_message(self, event):
        if not await self._authenticate(self.token, self.match_id):
            await self.close(code=4403)
            return
        payload = await self._approved_payload(event.get("message_id"))
        if payload:
            await self.send_json({"type": "message.new", **payload})

    @database_sync_to_async
    def _approved_payload(self, message_id):
        message = (
            Message.objects.select_related("sender")
            .filter(
                pk=message_id,
                match_id=self.match_id,
                moderation_status="clear",
                deleted_at__isnull=True,
            )
            .first()
        )
        return (
            dict(MessageSerializer(message, context={"viewer": self.profile}).data)
            if message
            else None
        )

    @database_sync_to_async
    def _authenticate(self, raw_token, match_id):
        if not raw_token:
            return None
        try:
            claims = jwt.decode(
                raw_token,
                settings.JWT_SECRET,
                algorithms=["HS256"],
                options={"require": ["exp", "sub", "typ"]},
            )
            if claims.get("typ") != "access":
                return None
            user = User.objects.get(pk=claims["sub"], status=User.Status.ACTIVE)
            profile = Profile.objects.get(user=user)
            participant_match(profile, match_id)
            return profile
        except (jwt.PyJWTError, KeyError, User.DoesNotExist, Profile.DoesNotExist, ValueError):
            return None

    @database_sync_to_async
    def _send_message(self, profile, match_id, body, client_id, reply_to=None, attachment=None):
        return dict(
            MessageSerializer(
                send_message(profile, match_id, body, client_id, reply_to, attachment).message,
                context={"viewer": profile},
            ).data
        )

    @database_sync_to_async
    def _mark_read(self, profile, match_id, anchor):
        mark_read(profile, match_id, anchor)

    @database_sync_to_async
    def _activity(self, active, typing):
        return update_activity(
            self.profile, self.match_id, self.channel_name, active=active, typing=typing
        )

    @database_sync_to_async
    def _peer(self):
        return peer_activity(self.profile, self.match_id)

    @database_sync_to_async
    def _delivered(self, ids):
        return mark_delivered(self.profile, self.match_id, ids)

    async def chat_activity(self, event):
        if not await self._authenticate(self.token, self.match_id):
            await self.close(code=4403)
            return
        await self.send_json({"type": "activity", **await self._peer()})

    async def chat_receipts(self, event):
        if not await self._authenticate(self.token, self.match_id):
            await self.close(code=4403)
            return
        await self.send_json({"type": "receipts.changed"})
