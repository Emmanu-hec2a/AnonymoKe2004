from django.urls import path

from .views import (
    LocationUpdateView,
    MediaAssetStatusView,
    MediaCompleteView,
    MediaDeleteView,
    MediaStatusView,
    MediaUploadURLView,
    PreferencesView,
    ProfileView,
)

urlpatterns = [
    path("profile/", ProfileView.as_view()),
    path("preferences/", PreferencesView.as_view()),
    path("location/", LocationUpdateView.as_view()),
    path("media/upload-url/", MediaUploadURLView.as_view()),
    path("media/complete/", MediaCompleteView.as_view()),
    path("media/status/", MediaStatusView.as_view()),
    path("media/status/<uuid:upload_id>/", MediaAssetStatusView.as_view()),
    path("media/<str:kind>/", MediaDeleteView.as_view()),
]
