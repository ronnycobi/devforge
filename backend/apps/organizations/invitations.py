"""Invitation flow: invite an email to an org, accept via token, or revoke.

Kept as a service (not in the model) so the rules live in one place: acceptance
needs both the secret token AND a matching user email, is idempotent-safe, and
respects expiry/revocation. Sending the invite email is the notifications layer's
job — this only creates and resolves the record.
"""
from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.organizations.models import (
    Invitation,
    InvitationStatus,
    Membership,
    Organization,
    Role,
)


class InvitationError(Exception):
    pass


def _norm(email: str) -> str:
    # Emails are matched case-insensitively (Django's normalize_email only lowercases
    # the domain), so invitations store and compare the full address in lowercase.
    return User.objects.normalize_email(email or "").lower()


def create_invitation(organization: Organization, email: str, *, role=Role.MEMBER,
                      team=None, invited_by=None) -> Invitation:
    email = _norm(email)
    if not email:
        raise InvitationError("An email is required.")
    if Membership.objects.filter(organization=organization, user__email__iexact=email).exists():
        raise InvitationError("That user is already a member of the organization.")
    if team is not None and team.organization_id != organization.id:
        raise InvitationError("Team does not belong to this organization.")
    # Supersede any earlier pending invite for the same email/org.
    Invitation.objects.filter(
        organization=organization, email=email, status=InvitationStatus.PENDING
    ).update(status=InvitationStatus.REVOKED)
    return Invitation.objects.create(
        organization=organization, email=email, role=role, team=team,
        invited_by=invited_by,
    )


@transaction.atomic
def accept_invitation(token: str, user) -> Membership:
    try:
        inv = Invitation.objects.select_for_update().get(token=token)
    except Invitation.DoesNotExist:
        raise InvitationError("Invalid invitation.")
    if inv.status == InvitationStatus.REVOKED:
        raise InvitationError("This invitation was revoked.")
    if inv.status == InvitationStatus.ACCEPTED:
        raise InvitationError("This invitation was already accepted.")
    if inv.is_expired:
        inv.status = InvitationStatus.REVOKED
        inv.save(update_fields=["status"])
        raise InvitationError("This invitation has expired.")
    if _norm(user.email) != inv.email:
        raise InvitationError("This invitation was issued to a different email.")

    membership = inv.organization.add_member(user, role=inv.role)
    if inv.role != membership.role:  # existing membership? keep the higher intent
        membership.role = inv.role
        membership.save(update_fields=["role"])
    if inv.team_id:
        inv.team.add_member(user)
    inv.status = InvitationStatus.ACCEPTED
    inv.accepted_at = timezone.now()
    inv.save(update_fields=["status", "accepted_at"])
    from apps.audit.service import record
    record("member.joined", actor=user, organization=inv.organization,
           target=f"user:{user.id}", summary=f"{user.email} joined as {inv.role}")
    return membership


def revoke_invitation(inv: Invitation) -> Invitation:
    if inv.status == InvitationStatus.PENDING:
        inv.status = InvitationStatus.REVOKED
        inv.save(update_fields=["status"])
    return inv
