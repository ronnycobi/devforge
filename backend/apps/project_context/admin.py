from django.contrib import admin

from apps.project_context.models import ContextEntry


@admin.register(ContextEntry)
class ContextEntryAdmin(admin.ModelAdmin):
    list_display = ["kind", "key", "title", "project", "source", "updated_at"]
    list_filter = ["kind"]
    search_fields = ["key", "title", "content", "project__name"]
    autocomplete_fields = ["project", "created_by"]
    readonly_fields = ["created_at", "updated_at"]
