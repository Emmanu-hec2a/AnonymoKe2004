from django.urls import path

from .views import AccountErasureView, ConsentListCreateView, DataExportView

urlpatterns = [
    path("consents/", ConsentListCreateView.as_view()),
    path("account/", AccountErasureView.as_view()),
    path("data-export/", DataExportView.as_view()),
]
