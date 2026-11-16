from django.conf import settings
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .authentication import AuthenticationService, MagicLinkService
from .mail import ResendEmailAdapter
from .serializers import (
    MagicLinkRequestSerializer,
    MagicLinkVerifySerializer,
    RefreshTokenSerializer,
    SocialVerifySerializer,
)
from .social import provider_for


class AuthAPIView(APIView):
    authentication_classes = []
    permission_classes = []
    throttle_classes = [ScopedRateThrottle]
    validation_code = "auth_request_invalid"

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "no-store"
        return response

    def handle_exception(self, exc):
        if isinstance(exc, ValidationError):
            return Response({"error": {"code": self.validation_code}}, status=400)
        return super().handle_exception(exc)


class MagicLinkRequestView(AuthAPIView):
    throttle_scope = "auth_request"
    validation_code = "email_invalid"

    def post(self, request):
        serializer = MagicLinkRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if not settings.RESEND_API_KEY:
            return Response({"error": {"code": "email_delivery_unavailable"}}, status=503)
        token = MagicLinkService.request(serializer.validated_data["email"])
        # Enumeration-safe: production sends the token through Resend; the API does not return it.
        if token:
            try:
                ResendEmailAdapter().send_magic_link(serializer.validated_data["email"], token)
            except (RuntimeError, OSError, TimeoutError, ValueError, KeyError):
                MagicLinkService.discard_undelivered(token)
                return Response({"error": {"code": "email_delivery_unavailable"}}, status=503)
        return Response(
            {
                "accepted": True,
                "resend_after_seconds": settings.MAGIC_LINK_RESEND_COOLDOWN_SECONDS,
                "expires_in_seconds": settings.MAGIC_LINK_TTL_MINUTES * 60,
            },
            status=status.HTTP_202_ACCEPTED,
        )


class MagicLinkVerifyView(AuthAPIView):
    throttle_scope = "auth_verify"
    validation_code = "magic_link_invalid"

    def post(self, request):
        serializer = MagicLinkVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            user, is_new = MagicLinkService.verify(serializer.validated_data["token"])
        except ValueError:
            return Response({"error": {"code": "magic_link_invalid"}}, status=400)
        try:
            payload = AuthenticationService.issue_session(user).as_dict()
        except ValueError:
            return Response({"error": {"code": "user_not_active"}}, status=403)
        payload["is_new_user"] = is_new
        return Response(payload)


class SocialVerifyView(AuthAPIView):
    throttle_scope = "auth_social"
    validation_code = "social_token_invalid"

    def post(self, request, provider):
        serializer = SocialVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            identity = provider_for(provider).verify_credential(
                serializer.validated_data["credential"]
            )
            user, is_new = AuthenticationService.authenticate_external(identity)
        except (RuntimeError, OSError, TimeoutError):
            return Response(
                {"error": {"code": "provider_not_configured", "provider": provider}},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except ValueError as exc:
            return Response({"error": {"code": str(exc)}}, status=status.HTTP_400_BAD_REQUEST)
        try:
            payload = AuthenticationService.issue_session(user).as_dict()
        except ValueError:
            return Response({"error": {"code": "user_not_active"}}, status=403)
        payload["is_new_user"] = is_new
        return Response(payload)


class RefreshTokenView(AuthAPIView):
    throttle_scope = "auth_refresh"
    validation_code = "refresh_token_invalid"

    def post(self, request):
        serializer = RefreshTokenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            payload = AuthenticationService.rotate_refresh_token(
                serializer.validated_data["refresh_token"]
            )
        except ValueError:
            return Response({"error": {"code": "refresh_token_invalid"}}, status=401)
        return Response(payload.as_dict())


class LogoutView(AuthAPIView):
    throttle_scope = "auth_refresh"

    def post(self, request):
        serializer = RefreshTokenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            AuthenticationService.revoke_refresh_token(serializer.validated_data["refresh_token"])
        except ValueError:
            # Logout is idempotent and must not reveal whether a token was valid.
            pass
        return Response(status=status.HTTP_204_NO_CONTENT)
