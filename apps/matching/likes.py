from django.db.models import OuterRef, Q, Subquery
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.core.cursors import decode_cursor, encode_cursor
from apps.discovery.services import candidate_queryset
from apps.profiles.models import Profile
from apps.store.models import Entitlement

from .models import Swipe


class IncomingLikesView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "matches"

    def get(self, request):
        from apps.discovery.views import card_data, media_store

        profile, _ = Profile.objects.get_or_create(user=request.user)
        premium = (
            Entitlement.objects.filter(user=request.user, kind="premium", quantity__gt=0)
            .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now()))
            .exists()
        )
        incoming = Swipe.objects.filter(to_profile=profile, action="like", is_undone=False)
        try:
            candidates = candidate_queryset(profile).filter(
                pk__in=incoming.values("from_profile_id")
            )
        except ValueError as exc:
            return Response(
                {
                    "count": 0,
                    "can_view": premium,
                    "items": [],
                    "next_cursor": None,
                    "unavailable_reason": str(exc),
                }
            )
        count = candidates.count()
        if not premium:
            return Response({"count": count, "can_view": False, "items": [], "next_cursor": None})
        candidates = candidates.annotate(
            liked_at=Subquery(
                incoming.filter(from_profile_id=OuterRef("pk")).values("created_at")[:1]
            )
        ).order_by("-liked_at", "-pk")
        try:
            if request.query_params.get("cursor"):
                stamp, profile_id = decode_cursor(
                    request.query_params["cursor"], f"likes:{profile.pk}"
                )
                candidates = candidates.filter(
                    Q(liked_at__lt=stamp) | Q(liked_at=stamp, pk__lt=profile_id)
                )
        except ValueError as exc:
            return Response({"error": {"code": str(exc)}}, status=400)
        batch = list(candidates[:21])
        items = batch[:20]
        cursor = (
            encode_cursor(items[-1].liked_at, items[-1].pk, f"likes:{profile.pk}")
            if len(batch) > 20
            else None
        )
        store = media_store()
        return Response(
            {
                "count": count,
                "can_view": True,
                "items": [card_data(item, store) for item in items],
                "next_cursor": cursor,
            }
        )
