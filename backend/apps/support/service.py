"""Support ticket orchestration.

Creating a ticket opens it with the customer's first message and (best-effort)
emails a confirmation + a staff notification. Staff/customer replies thread onto it
and move the status sensibly. Email is best-effort — a delivery failure never loses
a ticket or a message.
"""
from __future__ import annotations

from django.conf import settings

from apps.audit.service import record as audit
from apps.support.models import SupportTicket, TicketMessage, TicketStatus


def create_ticket(*, organization, user, subject, body, category="question",
                  priority="normal") -> SupportTicket:
    ticket = SupportTicket.objects.create(
        organization=organization, created_by=user,
        subject=(subject or "").strip()[:200] or "(no subject)",
        category=category if category in dict(SupportTicket.CATEGORIES) else "question",
        priority=priority if priority in dict(SupportTicket.PRIORITIES) else "normal",
        status=TicketStatus.OPEN,
    )
    if (body or "").strip():
        TicketMessage.objects.create(ticket=ticket, author=user, body=body.strip())
    audit("support.ticket", actor=user, organization=organization,
          target=f"ticket:{ticket.id}", summary=ticket.subject)
    _email(getattr(user, "email", ""),
           f"[{ticket.number}] We received your request",
           f"Thanks — your support request \"{ticket.subject}\" is logged as "
           f"{ticket.number}. We'll reply here and by email.")
    inbox = getattr(settings, "DEVFORGE_SUPPORT_EMAIL", "")
    if inbox:
        _email(inbox, f"[{ticket.number}] New {ticket.get_category_display()} — {organization.name}",
               f"{ticket.subject}\n\n{body}")
    return ticket


def add_message(ticket: SupportTicket, *, author, body, internal=False, from_staff=False) -> TicketMessage:
    msg = TicketMessage.objects.create(
        ticket=ticket, author=author, body=(body or "").strip(), internal=internal)
    # Status moves: a staff reply waits on the customer; a customer reply reopens.
    if not internal:
        if from_staff and ticket.status in ("open", "in_progress"):
            ticket.status = TicketStatus.WAITING
        elif not from_staff and ticket.status in ("waiting", "resolved"):
            ticket.status = TicketStatus.OPEN
    ticket.save(update_fields=["status", "updated_at"])
    audit("support.reply", actor=author, organization=ticket.organization,
          target=f"ticket:{ticket.id}", summary="internal" if internal else "reply")
    # A public staff reply emails the customer; internal notes never leave the desk.
    if from_staff and not internal and ticket.created_by and ticket.created_by.email:
        _email(ticket.created_by.email, f"[{ticket.number}] Reply to your request",
               f"{body}\n\n— Support")
    return msg


def set_status(ticket: SupportTicket, *, status, user) -> SupportTicket:
    if status in TicketStatus.values:
        ticket.status = status
        ticket.save(update_fields=["status", "updated_at"])
        audit("support.status", actor=user, organization=ticket.organization,
              target=f"ticket:{ticket.id}", summary=status)
    return ticket


def assign(ticket: SupportTicket, *, staff, user) -> SupportTicket:
    ticket.assigned_to = staff
    if ticket.status == TicketStatus.OPEN:
        ticket.status = TicketStatus.IN_PROGRESS
    ticket.save(update_fields=["assigned_to", "status", "updated_at"])
    audit("support.assign", actor=user, organization=ticket.organization,
          target=f"ticket:{ticket.id}", summary=getattr(staff, "email", ""))
    return ticket


def _email(to, subject, text):
    if not to:
        return
    try:
        from apps.notifications.email import send_email
        send_email(subject=subject, to=to, text=text)
    except Exception:
        pass
