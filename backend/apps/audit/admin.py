from django.contrib import admin

from apps.audit.models import AuditEvent


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ["created_at", "action", "actor", "organization", "target", "summary"]
    list_filter = ["action"]
    search_fields = ["action", "target", "summary", "actor__email", "organization__name"]
    readonly_fields = [f.name for f in AuditEvent._meta.fields]
