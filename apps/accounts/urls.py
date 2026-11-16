from django.urls import path

from .views import (
    LogoutView,
    MagicLinkRequestView,
    MagicLinkVerifyView,
    RefreshTokenView,
    SocialVerifyView,
)

urlpatterns = [
    path("magic-link/request/", MagicLinkRequestView.as_view()),
    path("magic-link/verify/", MagicLinkVerifyView.as_view()),
    path("social/<str:provider>/verify/", SocialVerifyView.as_view()),
    path("token/refresh/", RefreshTokenView.as_view()),
    path("logout/", LogoutView.as_view()),
]
