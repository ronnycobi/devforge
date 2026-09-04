from rest_framework import serializers

from apps.agents.definitions import registry
from apps.orchestrator.models import AgentTask


class AgentTaskSerializer(serializers.ModelSerializer):
    class Meta:
        model = AgentTask
        fields = [
            "id",
            "project",
            "workspace",
            "agent_key",
            "parent_task",
            "depends_on",
            "status",
            "priority",
            "input",
            "output",
            "error",
            "messages",
            "attempts",
            "max_attempts",
            "approval_required",
            "approved",
            "model",
            "tokens",
            "credits",
            "cost",
            "created_by",
            "created_at",
            "started_at",
            "completed_at",
        ]
        read_only_fields = [
            "project",
            "status",
            "output",
            "error",
            "messages",
            "attempts",
            "approved",
            "model",
            "tokens",
            "credits",
            "cost",
            "created_by",
            "created_at",
            "started_at",
            "completed_at",
        ]

    def validate_agent_key(self, value):
        if value not in registry:
            raise serializers.ValidationError(f"Unknown agent '{value}'.")
        return value
