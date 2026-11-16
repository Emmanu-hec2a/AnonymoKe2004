from django.urls import path

from .views import (
    VerificationStartView,
    VerificationStatusView,
    VerificationWebhookView,
    verification_return,
)

urlpatterns = [
    path("return/", verification_return),
    path("start/", VerificationStartView.as_view()),
    path("status/", VerificationStatusView.as_view()),
    path("webhook/<str:provider>/", VerificationWebhookView.as_view()),
]
