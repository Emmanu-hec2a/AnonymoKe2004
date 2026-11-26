from datetime import timedelta

from django.contrib.gis.db.models.functions import Distance
from django.db.models import Exists, OuterRef, Q, Subquery
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.core.cursors import decode_cursor, encode_cursor
from apps.discovery.services import candidate_queryset
from apps.profiles.models import Profile
from apps.store.models import Entitlement

from .models import Match, Swipe
from .services import LIKE_TTL_HOURS


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


class SentLikesView(APIView):
    """Likes you sent that are still waiting for an answer.

    Each item is the same masked card Discover shows, plus the swipe's
    client_swipe_id (pass it to POST /swipes/undo/ to withdraw the like) and
    the moment the like expires if it is never answered. Likes that already
    became a live match are not listed; those are closed from Matches.
    """

    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "matches"

    def get(self, request):
        from apps.discovery.views import card_data, media_store

        profile, _ = Profile.objects.get_or_create(user=request.user)
        live_match = Match.objects.exclude(state=Match.State.CLOSED).filter(
            Q(profile_a=profile, profile_b_id=OuterRef("to_profile_id"))
            | Q(profile_a_id=OuterRef("to_profile_id"), profile_b=profile)
        )
        sent = Swipe.objects.filter(
            from_profile=profile, action=Swipe.Action.LIKE, is_undone=False
        ).exclude(Exists(live_match))
        own_swipe = sent.filter(to_profile_id=OuterRef("pk"))
        liked = (
            Profile.objects.select_related("user")
            .filter(pk__in=sent.values("to_profile_id"))
            .annotate(
                liked_at=Subquery(own_swipe.values("created_at")[:1]),
                client_swipe_id=Subquery(own_swipe.values("client_swipe_id")[:1]),
            )
            .order_by("-liked_at", "-pk")
        )
        if profile.cell is not None:
            liked = liked.annotate(distance_m=Distance("cell", profile.cell))
        count = liked.count()
        try:
            if request.query_params.get("cursor"):
                stamp, profile_id = decode_cursor(
                    request.query_params["cursor"], f"likes-sent:{profile.pk}"
                )
                liked = liked.filter(Q(liked_at__lt=stamp) | Q(liked_at=stamp, pk__lt=profile_id))
        except ValueError as exc:
            return Response({"error": {"code": str(exc)}}, status=400)
        batch = list(liked[:21])
        items = batch[:20]
        cursor = (
            encode_cursor(items[-1].liked_at, items[-1].pk, f"likes-sent:{profile.pk}")
            if len(batch) > 20
            else None
        )
        store = media_store()
        return Response(
            {
                "count": count,
                "items": [
                    {
                        **card_data(item, store),
                        "client_swipe_id": str(item.client_swipe_id),
                        "liked_at": item.liked_at,
                        "expires_at": item.liked_at + timedelta(hours=LIKE_TTL_HOURS),
                    }
                    for item in items
                ],
                "next_cursor": cursor,
            }
        )
