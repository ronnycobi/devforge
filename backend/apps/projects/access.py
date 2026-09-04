"""Shared project-scoping helpers for tenant-safe API views.

Any view acting on a single project should derive it through these, so the
"member can read / manager can write, and a foreign project is invisible (404)"
rule stays identical everywhere.
"""
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import PermissionDenied

from apps.organizations.access import (
    manageable_organizations_for,
    organizations_for,
)
from apps.projects.models import Project


def project_for_read(user, project_pk):
    """The project if the user is a member of its org, else 404 (no existence leak)."""
    return get_object_or_404(
        Project.objects.filter(organization__in=organizations_for(user)),
        pk=project_pk,
    )


def require_manageable_project(user, project_pk):
    """As project_for_read, but requires owner/admin — else 403."""
    project = project_for_read(user, project_pk)
    if project.organization not in manageable_organizations_for(user):
        raise PermissionDenied("You must be an owner or admin for this action.")
    return project
