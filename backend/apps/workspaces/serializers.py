from rest_framework import serializers

from apps.workspaces.models import Workspace


class WorkspaceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Workspace
        fields = [
            "id",
            "project",
            "name",
            "slug",
            "environment",
            "is_default",
            "created_at",
            "updated_at",
        ]
        # project comes from the URL, slug is derived, is_default is managed
        # explicitly (a project keeps exactly one default).
        read_only_fields = [
            "project",
            "slug",
            "is_default",
            "created_at",
            "updated_at",
        ]
