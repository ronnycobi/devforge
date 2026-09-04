from django.contrib import admin

from apps.workspaces.models import Workspace


@admin.register(Workspace)
class WorkspaceAdmin(admin.ModelAdmin):
    list_display = ["name", "project", "environment", "is_default", "created_at"]
    list_filter = ["environment", "is_default"]
    search_fields = ["name", "slug", "project__name"]
    autocomplete_fields = ["project"]
    readonly_fields = ["slug", "created_at", "updated_at"]
