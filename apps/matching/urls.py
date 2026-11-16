from django.urls import path

from .likes import IncomingLikesView
from .views import (
    MatchDetailView,
    MatchListView,
    RevealedIdentityView,
    SwipeView,
    UndoPassView,
    UnmaskRequestView,
    UnmaskRespondView,
    UnmaskWithdrawView,
)

urlpatterns = [
    path("likes/", IncomingLikesView.as_view()),
    path("swipes/", SwipeView.as_view()),
    path("swipes/undo/", UndoPassView.as_view()),
    path("matches/", MatchListView.as_view()),
    path("matches/<uuid:match_id>/", MatchDetailView.as_view()),
    path("matches/<uuid:match_id>/unmask/request/", UnmaskRequestView.as_view()),
    path("matches/<uuid:match_id>/unmask/respond/", UnmaskRespondView.as_view()),
    path("matches/<uuid:match_id>/unmask/withdraw/", UnmaskWithdrawView.as_view()),
    path("matches/<uuid:match_id>/revealed/", RevealedIdentityView.as_view()),
]
