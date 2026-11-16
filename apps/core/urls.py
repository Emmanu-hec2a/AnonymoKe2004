from django.urls import path

from .views import ConfigView, HealthView, ReadinessView

urlpatterns = [
    path("healthz", HealthView.as_view(), name="healthz"),
    path("readyz", ReadinessView.as_view(), name="readyz"),
    path("api/v1/config/", ConfigView.as_view(), name="config"),
]
