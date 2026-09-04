from django.contrib import admin

from apps.projects.models import Project
from apps.workspaces.models import Workspace


class WorkspaceInline(admin.TabularInline):
    model = Workspace
    extra = 0
    fields = ["name", "slug", "environment", "is_default"]
    readonly_fields = ["slug"]


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ["name", "organization", "mode", "status", "created_at"]
    list_filter = ["mode", "status"]
    search_fields = ["name", "slug", "organization__name"]
    autocomplete_fields = ["organization", "created_by"]
    readonly_fields = ["slug", "created_at", "updated_at"]
    inlines = [WorkspaceInline]
