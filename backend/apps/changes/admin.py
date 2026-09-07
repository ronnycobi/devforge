from django.contrib import admin

from apps.changes.models import ChangeRequest


@admin.register(ChangeRequest)
class ChangeRequestAdmin(admin.ModelAdmin):
    list_display = ["id", "project", "status", "requires_approval", "approved", "created_at"]
    list_filter = ["status", "requires_approval", "approved"]
    search_fields = ["description", "project__name"]
    autocomplete_fields = ["project", "created_by", "approved_by"]
    readonly_fields = ["created_at", "updated_at", "plan", "estimate", "task_ids"]
