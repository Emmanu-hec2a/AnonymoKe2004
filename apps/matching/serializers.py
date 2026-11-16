from rest_framework import serializers

from .models import Swipe


class SwipeWriteSerializer(serializers.Serializer):
    profile_id = serializers.UUIDField()
    action = serializers.ChoiceField(choices=Swipe.Action.values)
    client_swipe_id = serializers.UUIDField()


class UnmaskResponseSerializer(serializers.Serializer):
    accept = serializers.BooleanField()
