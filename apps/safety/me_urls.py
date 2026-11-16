from django.urls import path

from .me_views import (
    DateSessionDetailView,
    DateSessionListCreateView,
    DateSessionSafeView,
    PanicAlertDetailView,
    PanicAlertView,
    PanicRetryView,
    SafetyOverviewView,
    SharedPlansView,
    TrustedContactUnlinkView,
    TrustedContactView,
)

urlpatterns = [
    path("shared-plans/", SharedPlansView.as_view()),
    path("trusted-contact/unlink/", TrustedContactUnlinkView.as_view()),
    path("panic/<uuid:alert_id>/retry/", PanicRetryView.as_view()),
    path("", SafetyOverviewView.as_view(), name="safety-overview"),
    path("trusted-contact/", TrustedContactView.as_view(), name="trusted-contact"),
    path("dates/", DateSessionListCreateView.as_view(), name="date-session-list"),
    path("dates/<uuid:session_id>/", DateSessionDetailView.as_view(), name="date-session-detail"),
    path("dates/<uuid:session_id>/safe/", DateSessionSafeView.as_view(), name="date-session-safe"),
    path("panic/", PanicAlertView.as_view(), name="panic-alert"),
    path("panic/<uuid:alert_id>/", PanicAlertDetailView.as_view(), name="panic-alert-detail"),
]
