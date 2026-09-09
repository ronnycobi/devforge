"""Support center — tickets customers log and staff work (help desk).

A customer raises a SupportTicket (a question, bug, billing issue, logged call, …);
it carries a threaded conversation of TicketMessages. Staff see every tenant's
tickets in the Control Center and reply; internal notes stay staff-only.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone


class TicketStatus(models.TextChoices):
    OPEN = "open", "Open"
    IN_PROGRESS = "in_progress", "In progress"
    WAITING = "waiting", "Waiting on customer"
    RESOLVED = "resolved", "Resolved"
    CLOSED = "closed", "Closed"


OPEN_STATUSES = ("open", "in_progress", "waiting")


class SupportTicket(models.Model):
    CATEGORIES = [("question", "Question"), ("bug", "Problem / bug"),
                  ("billing", "Billing"), ("feature", "Feature request"),
                  ("call", "Logged call"), ("other", "Other")]
    PRIORITIES = [("low", "Low"), ("normal", "Normal"), ("high", "High"), ("urgent", "Urgent")]

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="support_tickets"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="support_tickets",
    )
    subject = models.CharField(max_length=200)
    category = models.CharField(max_length=16, choices=CATEGORIES, default="question")
    priority = models.CharField(max_length=8, choices=PRIORITIES, default="normal")
    status = models.CharField(max_length=16, choices=TicketStatus.choices, default=TicketStatus.OPEN)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="assigned_tickets",
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return f"{self.number} {self.subject}"

    @property
    def number(self) -> str:
        return f"DF-{self.pk:05d}"

    @property
    def is_open(self) -> bool:
        return self.status in OPEN_STATUSES


class TicketMessage(models.Model):
    ticket = models.ForeignKey(SupportTicket, on_delete=models.CASCADE, related_name="messages")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="ticket_messages",
    )
    body = models.TextField()
    internal = models.BooleanField(default=False)   # staff-only note; hidden from the customer
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"msg on {self.ticket_id}"
