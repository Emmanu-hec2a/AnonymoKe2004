from django.urls import path

from .views import (
    DarajaCallbackView,
    EntitlementListView,
    ProductListView,
    PurchaseCreateView,
    PurchaseDetailView,
)

urlpatterns = [
    path("store/products/", ProductListView.as_view(), name="store-products"),
    path("purchases/", PurchaseCreateView.as_view(), name="purchase-create"),
    path("purchases/<uuid:purchase_id>/", PurchaseDetailView.as_view(), name="purchase-detail"),
    path("me/entitlements/", EntitlementListView.as_view(), name="entitlements"),
    path(
        "payments/daraja/callback/<str:callback_token>/",
        DarajaCallbackView.as_view(),
        name="daraja-callback",
    ),
]
