from django.contrib import admin

from apps.deployments.models import Deployment


@admin.register(Deployment)
class DeploymentAdmin(admin.ModelAdmin):
    list_display = [
        "id", "project", "environment", "provider", "status", "approved", "created_at",
    ]
    list_filter = ["environment", "provider", "status", "approved"]
    search_fields = ["project__name", "url"]
    autocomplete_fields = ["project", "created_by", "approved_by"]
    readonly_fields = ["created_at", "completed_at", "approved_at"]
