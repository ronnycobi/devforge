"""Organizations — the tenant boundary for DevForge.

Every project, agent run, credit balance, and cost record will ultimately hang
off an Organization. Users join organizations through Membership, which carries
a role. This is the root of multi-tenant isolation, so keep the boundary clean:
downstream code scopes queries by organization, never by user alone.
"""
from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.slugs import unique_slug


class Role(models.TextChoices):
    OWNER = "owner", "Owner"
    ADMIN = "admin", "Admin"
    MEMBER = "member", "Member"


class Organization(models.Model):
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="organizations_created",
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        through="organizations.Membership",
        related_name="organizations",
    )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(
                Organization, self.name, instance=self, fallback="org"
            )
        super().save(*args, **kwargs)

    def add_member(self, user, role=Role.MEMBER):
        """Idempotently attach a user; returns the Membership."""
        membership, _ = Membership.objects.get_or_create(
            organization=self, user=user, defaults={"role": role}
        )
        return membership


class Membership(models.Model):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="memberships"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    role = models.CharField(
        max_length=20, choices=Role.choices, default=Role.MEMBER
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "user"],
                name="unique_membership_per_org",
            )
        ]
        ordering = ["organization", "user"]

    def __str__(self):
        return f"{self.user} @ {self.organization} ({self.role})"

    @property
    def is_owner(self):
        return self.role == Role.OWNER

    @property
    def can_manage(self):
        """Owners and admins may manage the organization."""
        return self.role in {Role.OWNER, Role.ADMIN}
