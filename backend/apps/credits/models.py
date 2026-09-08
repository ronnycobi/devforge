"""Credits and usage.

A CreditAccount holds an organization's DevForge credit balance (credits are a
platform abstraction over raw tokens; docs/PRODUCT.md §20). Every agent run that
uses a model writes a UsageRecord attributable to org / project / task / provider
/ model, and debits the account. An org with no account is treated as unlimited
(development default) so nothing breaks before billing is provisioned.
"""
from __future__ import annotations

from decimal import Decimal

from django.db import models
from django.utils import timezone


class CreditAccount(models.Model):
    organization = models.OneToOneField(
        "organizations.Organization",
        on_delete=models.CASCADE,
        related_name="credit_account",
    )
    plan = models.CharField(max_length=32, default="free")
    balance = models.DecimalField(max_digits=14, decimal_places=4, default=0)
    # Hard velocity cap: max USD of model spend per calendar day for this org.
    # Null falls back to the platform default (settings.DEVFORGE_ORG_DAILY_USD_CAP,
    # itself null = unlimited). Protects against a runaway loop draining a balance.
    daily_usd_cap = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="Max USD of AI spend per day. Blank = use platform default / unlimited.",
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.organization.slug}: {self.balance} credits ({self.plan})"

    def credit(self, amount) -> None:
        self.balance = self.balance + Decimal(amount)
        self.save(update_fields=["balance", "updated_at"])

    def debit(self, amount) -> None:
        # Allowed to go negative: the last task isn't clawed back; the next one
        # is blocked by the pre-run guard.
        self.balance = self.balance - Decimal(amount)
        self.save(update_fields=["balance", "updated_at"])


class UsageRecord(models.Model):
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.CASCADE,
        related_name="usage_records",
    )
    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="usage_records",
    )
    task = models.ForeignKey(
        "orchestrator.AgentTask",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="usage_records",
    )
    agent_key = models.CharField(max_length=64, blank=True)
    provider = models.CharField(max_length=64, blank=True)
    model = models.CharField(max_length=100, blank=True)
    total_tokens = models.PositiveIntegerField(default=0)
    cost_usd = models.DecimalField(max_digits=14, decimal_places=6, default=0)
    credits_charged = models.DecimalField(max_digits=14, decimal_places=4, default=0)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["organization", "created_at"])]

    def __str__(self):
        return f"{self.agent_key} {self.model} {self.credits_charged}cr"


class Invoice(models.Model):
    """A usage statement for an organization over a billing period.

    Generated from real UsageRecords — the amount owed for AI work. Payment
    COLLECTION (a gateway like Stripe/PayFast) is a separate integration and is
    intentionally not modelled here; an invoice records what is owed, not a charge.
    """

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        ISSUED = "issued", "Issued"

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="invoices"
    )
    period_start = models.DateField()
    period_end = models.DateField()
    currency = models.CharField(max_length=8, default="USD")
    subtotal_usd = models.DecimalField(max_digits=14, decimal_places=6, default=0)
    credits_used = models.DecimalField(max_digits=14, decimal_places=4, default=0)
    lines = models.JSONField(default=list, blank=True)  # [{model, tokens, cost_usd, credits}]
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-period_start"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "period_start"], name="uniq_invoice_period_per_org"
            )
        ]

    def __str__(self):
        return f"{self.organization} {self.period_start:%Y-%m} — {self.subtotal_usd} {self.currency}"
