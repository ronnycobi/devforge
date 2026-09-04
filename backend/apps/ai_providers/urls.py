from django.urls import path

from apps.ai_providers.api import ProviderListView

app_name = "ai_providers"

urlpatterns = [
    path("ai/providers/", ProviderListView.as_view(), name="provider-list"),
]
