from django.urls import include, path

urlpatterns = [
    path("", include("apps.core.urls")),
    path("api/v1/auth/", include("apps.accounts.urls")),
    path("api/v1/me/verification/", include("apps.verification.urls")),
    path("api/v1/me/", include("apps.compliance.urls")),
    path("api/v1/me/", include("apps.profiles.urls")),
    path("api/v1/", include("apps.discovery.urls")),
    path("api/v1/", include("apps.matching.urls")),
    path("api/v1/", include("apps.chat.urls")),
    path("api/v1/", include("apps.safety.urls")),
    path("api/v1/admin/", include("apps.adminapi.urls")),
    path("api/v1/", include("apps.store.urls")),
    path("api/v1/me/", include("apps.notifications.urls")),
    path("api/v1/me/safety/", include("apps.safety.me_urls")),
    path("api/v1/me/safety/", include("apps.safety.in_app_urls")),
]
