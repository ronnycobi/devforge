"""Tenant-access helpers.

The single source of truth for "which organizations can this user see / manage".
Every tenant-scoped API must derive its queryset from these so isolation stays
consistent — never hand-roll membership filters in individual views.
"""
from apps.organizations.models import Organization, Role


def organizations_for(user):
    """Organizations the user is a member of (any role)."""
    if not user or not user.is_authenticated:
        return Organization.objects.none()
    return Organization.objects.filter(memberships__user=user)


def manageable_organizations_for(user):
    """Organizations where the user is an owner or admin (can_manage)."""
    if not user or not user.is_authenticated:
        return Organization.objects.none()
    return Organization.objects.filter(
        memberships__user=user,
        memberships__role__in=[Role.OWNER, Role.ADMIN],
    )
