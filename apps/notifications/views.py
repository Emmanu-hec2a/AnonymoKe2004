from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import DeviceToken
from .serializers import DeviceTokenSerializer


class DeviceTokenView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = DeviceTokenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        device, created = DeviceToken.objects.update_or_create(
            token=data["token"],
            defaults={
                "user": request.user,
                "platform": data["platform"],
                "app_version": data.get("app_version", ""),
                "is_enabled": True,
                "last_seen_at": timezone.now(),
            },
        )
        return Response(
            {"registered": True, "device_id": device.id}, status=201 if created else 200
        )

    def delete(self, request):
        token = request.data.get("token")
        if isinstance(token, str) and token:
            DeviceToken.objects.filter(user=request.user, token=token).update(is_enabled=False)
        return Response(status=204)
