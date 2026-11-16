from django.urls import path

from .views import BlockCreateView, BlockDeleteView, ReportCreateView

urlpatterns = [
    path("reports/", ReportCreateView.as_view(), name="report-create"),
    path("blocks/", BlockCreateView.as_view(), name="block-create"),
    path("blocks/<uuid:profile_id>/", BlockDeleteView.as_view(), name="block-delete"),
]
