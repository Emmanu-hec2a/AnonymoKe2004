from django.urls import path

from .views import BoostView, DiscoveryProfileView, DiscoveryView

urlpatterns = [
    path("discover/", DiscoveryView.as_view()),
    path("discover/<uuid:profile_id>/", DiscoveryProfileView.as_view()),
    path("me/boost/", BoostView.as_view()),
]
