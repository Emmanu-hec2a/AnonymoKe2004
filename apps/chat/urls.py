from django.urls import path

from .views import MessageListCreateView, MessageReadView

urlpatterns = [
    path("matches/<uuid:match_id>/messages/", MessageListCreateView.as_view()),
    path("matches/<uuid:match_id>/read/", MessageReadView.as_view()),
]
