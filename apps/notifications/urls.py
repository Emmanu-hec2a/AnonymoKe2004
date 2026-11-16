from django.urls import path

from .views import DeviceTokenView

urlpatterns = [
    path("notifications/devices/", DeviceTokenView.as_view()),
]
