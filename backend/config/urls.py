"""Root URL configuration for DevForge."""
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include("apps.core.urls")),
    path("api/v1/", include("apps.accounts.urls")),
    path("api/v1/", include("apps.projects.urls")),
    path("api/v1/", include("apps.agents.urls")),
    path("api/v1/", include("apps.orchestrator.urls")),
    path("api/v1/", include("apps.ai_providers.urls")),
    path("api/v1/", include("apps.model_router.urls")),
]
