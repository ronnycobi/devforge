from django.contrib import admin

from apps.orchestrator.models import AgentTask


@admin.register(AgentTask)
class AgentTaskAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "agent_key",
        "project",
        "status",
        "priority",
        "attempts",
        "approval_required",
        "created_at",
    ]
    list_filter = ["status", "agent_key", "approval_required"]
    search_fields = ["agent_key", "project__name"]
    autocomplete_fields = ["project", "created_by", "approved_by"]
    readonly_fields = [
        "created_at",
        "started_at",
        "completed_at",
        "approved_at",
        "attempts",
    ]
    raw_id_fields = ["parent_task"]
    filter_horizontal = ["depends_on"]
