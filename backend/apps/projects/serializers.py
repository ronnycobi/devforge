from rest_framework import serializers

from apps.organizations.access import manageable_organizations_for
from apps.projects.models import Project


class ProjectSerializer(serializers.ModelSerializer):
    organization_slug = serializers.SlugField(
        source="organization.slug", read_only=True
    )
    workspace_count = serializers.IntegerField(
        source="workspaces.count", read_only=True
    )

    class Meta:
        model = Project
        fields = [
            "id",
            "organization",
            "organization_slug",
            "name",
            "slug",
            "description",
            "mode",
            "status",
            "technology",
            "created_by",
            "created_at",
            "updated_at",
            "workspace_count",
        ]
        read_only_fields = [
            "slug",
            "created_by",
            "created_at",
            "updated_at",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None:
            # A user may only create a project in an organization they manage.
            self.fields["organization"].queryset = manageable_organizations_for(
                request.user
            )
        # Organization is fixed at creation time.
        if self.instance is not None:
            self.fields["organization"].read_only = True
