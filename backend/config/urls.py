"""Root URL configuration for DevForge."""
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include("apps.core.urls")),
    path("api/v1/", include("apps.accounts.urls")),
    path("api/v1/", include("apps.projects.urls")),
    path("api/v1/", include("apps.technology.urls")),
    path("api/v1/", include("apps.agents.urls")),
    path("api/v1/", include("apps.orchestrator.urls")),
    path("api/v1/", include("apps.ai_providers.urls")),
    path("api/v1/", include("apps.model_router.urls")),
    path("api/v1/", include("apps.project_context.urls")),
    path("api/v1/", include("apps.exporter.urls")),
    path("api/v1/", include("apps.credits.urls")),
    path("api/v1/", include("apps.costs.urls")),
    path("api/v1/", include("apps.deployments.urls")),
    # Customer dashboard (the app) under /app/; public marketing site at the root.
    path("app/", include("apps.dashboard.urls")),
    path("", include("apps.marketing.urls")),
]
