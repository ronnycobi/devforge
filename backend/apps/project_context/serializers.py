from rest_framework import serializers

from apps.project_context.models import ContextEntry


class ContextEntrySerializer(serializers.ModelSerializer):
    # Optional on create: omit to auto-generate a unique key from the title.
    key = serializers.CharField(required=False, allow_blank=True)

    class Meta:
        model = ContextEntry
        fields = [
            "id",
            "project",
            "kind",
            "key",
            "title",
            "content",
            "data",
            "source",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "project",
            "created_by",
            "created_at",
            "updated_at",
        ]
