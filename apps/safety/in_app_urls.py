from django.urls import path

from .me_views import (
    SafetyAlertAcknowledgeView,
    SafetyIncomingAlertsView,
    TrustedContactAcceptView,
    TrustedContactInviteView,
)

urlpatterns = [
    path("trusted-contact/invite/", TrustedContactInviteView.as_view()),
    path("trusted-contact/accept/", TrustedContactAcceptView.as_view()),
    path("alerts/", SafetyIncomingAlertsView.as_view()),
    path("alerts/<uuid:recipient_id>/ack/", SafetyAlertAcknowledgeView.as_view()),
]
