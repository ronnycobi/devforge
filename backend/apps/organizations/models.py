"""Organizations — the tenant boundary for DevForge.

Every project, agent run, credit balance, and cost record will ultimately hang
off an Organization. Users join organizations through Membership, which carries
a role. This is the root of multi-tenant isolation, so keep the boundary clean:
downstream code scopes queries by organization, never by user alone.
"""
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.text import slugify

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


class Team(models.Model):
    """A named subgroup within an organization. Members must belong to the org."""

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="teams"
    )
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        through="organizations.TeamMembership",
        related_name="teams",
    )

    class Meta:
        ordering = ["organization", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "slug"], name="unique_team_slug_per_org"
            )
        ]

    def __str__(self):
        return f"{self.name} @ {self.organization}"

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name) or "team"
            slug, n = base, 2
            existing = Team.objects.filter(organization=self.organization)
            if self.pk:
                existing = existing.exclude(pk=self.pk)
            while existing.filter(slug=slug).exists():
                slug, n = f"{base}-{n}", n + 1
            self.slug = slug
        super().save(*args, **kwargs)

    def add_member(self, user):
        """Attach an org member to this team. Refuses non-members of the org."""
        if not Membership.objects.filter(organization=self.organization, user=user).exists():
            raise ValueError("User must be a member of the organization to join a team.")
        tm, _ = TeamMembership.objects.get_or_create(team=self, user=user)
        return tm


class TeamMembership(models.Model):
    team = models.ForeignKey(
        Team, on_delete=models.CASCADE, related_name="team_memberships"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="team_memberships"
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "user"], name="unique_team_membership"
            )
        ]
        ordering = ["team", "user"]

    def __str__(self):
        return f"{self.user} in {self.team}"


class InvitationStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    ACCEPTED = "accepted", "Accepted"
    REVOKED = "revoked", "Revoked"


def _new_token() -> str:
    return secrets.token_urlsafe(32)


def _default_expiry():
    return timezone.now() + timedelta(days=14)


class Invitation(models.Model):
    """An invite for an email to join an organization with a role (and optional team).

    The token is the secret that authorizes acceptance; acceptance additionally
    requires the accepting user's email to match, so a leaked link can't attach a
    stranger's account.
    """

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="invitations"
    )
    email = models.EmailField()
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.MEMBER)
    team = models.ForeignKey(
        Team, on_delete=models.SET_NULL, null=True, blank=True, related_name="invitations"
    )
    token = models.CharField(max_length=64, unique=True, default=_new_token)
    status = models.CharField(
        max_length=16, choices=InvitationStatus.choices, default=InvitationStatus.PENDING
    )
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="sent_invitations",
    )
    created_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField(default=_default_expiry)
    accepted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Invite {self.email} → {self.organization} ({self.status})"

    @property
    def is_expired(self) -> bool:
        return timezone.now() > self.expires_at

    @property
    def is_pending(self) -> bool:
        return self.status == InvitationStatus.PENDING and not self.is_expired
