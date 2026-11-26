from django.urls import path

from .media_views import ChatMediaCompleteView, ChatMediaView, ChatUploadView
from .views import ChatActivityView, MessageDeliveryView, MessageListCreateView, MessageReadView

urlpatterns = [
    path("matches/<uuid:match_id>/messages/", MessageListCreateView.as_view()),
    path("matches/<uuid:match_id>/read/", MessageReadView.as_view()),
    path("matches/<uuid:match_id>/delivered/", MessageDeliveryView.as_view()),
    path("matches/<uuid:match_id>/activity/", ChatActivityView.as_view()),
    path("matches/<uuid:match_id>/attachments/upload-url/", ChatUploadView.as_view()),
    path(
        "matches/<uuid:match_id>/attachments/<uuid:asset_id>/complete/",
        ChatMediaCompleteView.as_view(),
    ),
    path("matches/<uuid:match_id>/attachments/<uuid:asset_id>/", ChatMediaView.as_view()),
]
