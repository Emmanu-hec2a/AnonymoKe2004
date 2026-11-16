from django.urls import path

from .views import (
    AdminMessageReviewView,
    AdminModerationFlagListView,
    AdminPurchaseListView,
    AdminReportActionView,
    AdminReportListView,
)

urlpatterns = [
    path(
        "moderation/messages/<uuid:message_id>/",
        AdminMessageReviewView.as_view(),
        name="admin-message-review",
    ),
    path("reports/", AdminReportListView.as_view(), name="admin-report-list"),
    path(
        "reports/<uuid:report_id>/action/",
        AdminReportActionView.as_view(),
        name="admin-report-action",
    ),
    path("moderation/flags/", AdminModerationFlagListView.as_view(), name="admin-moderation-flags"),
    path("purchases/", AdminPurchaseListView.as_view(), name="admin-purchase-list"),
]
