"""Customer-facing support (in the dashboard) and staff support desk (Control Center)."""
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from apps.console.access import staff_required
from apps.organizations.access import organizations_for
from apps.support import service
from apps.support.models import SupportTicket, TicketStatus


# ---------------------------------------------------------------- customer side
@login_required
def my_tickets(request):
    orgs = list(organizations_for(request.user))
    if request.method == "POST":
        org = next((o for o in orgs), None)
        if org is None:
            messages.error(request, "Join or create an organization first.")
            return redirect("support:mine")
        subject = (request.POST.get("subject") or "").strip()
        if not subject:
            messages.error(request, "A subject is required.")
            return redirect("support:mine")
        t = service.create_ticket(
            organization=org, user=request.user, subject=subject,
            body=request.POST.get("body", ""), category=request.POST.get("category", "question"),
            priority=request.POST.get("priority", "normal"))
        messages.success(request, f"Logged your request as {t.number}.")
        return redirect("support:ticket", pk=t.id)

    tickets = SupportTicket.objects.filter(organization__in=orgs).select_related("organization")
    return render(request, "support/mine.html", {
        "active": "support", "tickets": tickets,
        "categories": SupportTicket.CATEGORIES, "priorities": SupportTicket.PRIORITIES,
    })


@login_required
def ticket(request, pk):
    t = get_object_or_404(
        SupportTicket.objects.filter(organization__in=organizations_for(request.user)), pk=pk)
    if request.method == "POST":
        body = (request.POST.get("body") or "").strip()
        if body:
            service.add_message(t, author=request.user, body=body, from_staff=False)
            messages.success(request, "Reply sent.")
        return redirect("support:ticket", pk=pk)
    return render(request, "support/ticket.html", {
        "active": "support", "ticket": t,
        "messages_list": t.messages.filter(internal=False).select_related("author"),
    })


# ------------------------------------------------------------------- staff side
@staff_required
def desk(request):
    status = request.GET.get("status") or ""
    qs = SupportTicket.objects.select_related("organization", "created_by", "assigned_to")
    if status:
        qs = qs.filter(status=status)
    return render(request, "console/support_desk.html", {
        "active": "support", "tickets": qs[:300], "current": status,
        "statuses": TicketStatus.choices,
        "open_count": SupportTicket.objects.filter(status__in=["open", "in_progress", "waiting"]).count(),
    })


@staff_required
def desk_ticket(request, pk):
    from apps.accounts.models import User
    t = get_object_or_404(SupportTicket, pk=pk)
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "reply":
            body = (request.POST.get("body") or "").strip()
            if body:
                service.add_message(t, author=request.user, body=body,
                                    internal=bool(request.POST.get("internal")), from_staff=True)
                messages.success(request, "Posted.")
        elif action == "status":
            service.set_status(t, status=request.POST.get("status"), user=request.user)
            messages.success(request, "Status updated.")
        elif action == "assign":
            service.assign(t, staff=request.user, user=request.user)
            messages.success(request, "Assigned to you.")
        return redirect("support:desk_ticket", pk=pk)
    return render(request, "console/support_ticket.html", {
        "active": "support", "ticket": t,
        "messages_list": t.messages.select_related("author"),
        "statuses": TicketStatus.choices,
    })
