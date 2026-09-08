"""Credit accounting and budget protection.

Credits are a platform abstraction over cost: cost_usd is derived from the model's
list price, then converted to credits at CREDITS_PER_USD (config). Plans and their
allowances are config too (settings.DEVFORGE_PLANS) — never hard-coded in logic.

Cost note: usage is charged with a blended (avg of input+output) per-token rate,
because agents currently report total tokens only. Per-direction pricing is a
straightforward refinement once results carry the split; it does not change the
accounting model.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.db.models import Sum
from django.utils import timezone

from apps.credits.models import CreditAccount, UsageRecord
from apps.model_router.catalog import profile_by_model


@dataclass(frozen=True)
class GuardResult:
    """Whether agent work may run, with a human-readable reason when it may not.

    Truthy/falsy so existing `if not guard_can_run(org)` and boolean asserts keep
    working, while callers that want to explain the block read `.reason`.
    """

    ok: bool
    reason: str = ""

    def __bool__(self) -> bool:
        return self.ok

_DEFAULT_PLANS = {"free": 1000, "pro": 5000, "business": 25000}


def credits_per_usd() -> Decimal:
    return Decimal(str(getattr(settings, "DEVFORGE_CREDITS_PER_USD", 100)))


def plans() -> dict:
    return getattr(settings, "DEVFORGE_PLANS", _DEFAULT_PLANS)


def cost_usd_for(model: str, total_tokens: int) -> Decimal:
    profile = profile_by_model(model)
    if not profile or not total_tokens:
        return Decimal("0")
    rate = Decimal(str(profile.avg_cost_per_mtok))  # USD per 1M tokens (blended)
    return (Decimal(total_tokens) / Decimal(1_000_000)) * rate


def credits_for(cost_usd: Decimal) -> Decimal:
    return (cost_usd * credits_per_usd()).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )


def get_account(organization) -> CreditAccount | None:
    return CreditAccount.objects.filter(organization=organization).first()


def ensure_account(organization, plan: str = "free", grant: bool = True) -> CreditAccount:
    account, created = CreditAccount.objects.get_or_create(
        organization=organization, defaults={"plan": plan}
    )
    if created and grant:
        account.credit(plans().get(plan, 0))
    return account


def daily_usd_cap(account: CreditAccount) -> Decimal | None:
    """The effective per-day USD cap for an account: its own, else the platform
    default (settings.DEVFORGE_ORG_DAILY_USD_CAP), else None = unlimited."""
    if account.daily_usd_cap is not None:
        return account.daily_usd_cap
    default = getattr(settings, "DEVFORGE_ORG_DAILY_USD_CAP", None)
    return Decimal(str(default)) if default is not None else None


def spent_today(organization) -> Decimal:
    """Total model spend (USD) attributed to this org since local midnight."""
    start = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    agg = UsageRecord.objects.filter(
        organization=organization, created_at__gte=start
    ).aggregate(s=Sum("cost_usd"))
    return agg["s"] or Decimal("0")


def guard_can_run(organization) -> GuardResult:
    """Whether agent work may run. An org with no account is unlimited (dev).

    Two independent protections: the credit balance (a total ceiling per plan)
    and a hard daily USD cap (a velocity ceiling that stops a runaway loop from
    draining the whole balance in one session)."""
    account = get_account(organization)
    if account is None:
        return GuardResult(True)
    if account.balance <= 0:
        return GuardResult(False, "Insufficient credits — top up to run agent work.")
    cap = daily_usd_cap(account)
    if cap is not None and spent_today(organization) >= cap:
        return GuardResult(
            False,
            f"Daily budget cap of ${cap} reached for today — resets at midnight.",
        )
    return GuardResult(True)


def record_task_usage(task) -> UsageRecord | None:
    """Record a completed task's model usage and debit the org's account."""
    organization = task.project.organization
    total = task.tokens or 0
    profile = profile_by_model(task.model)
    cost = cost_usd_for(task.model, total)
    charged = credits_for(cost)

    record = UsageRecord.objects.create(
        organization=organization,
        project=task.project,
        task=task,
        agent_key=task.agent_key,
        provider=profile.provider if profile else "",
        model=task.model,
        total_tokens=total,
        cost_usd=cost,
        credits_charged=charged,
    )
    account = get_account(organization)
    if account and charged:
        account.debit(charged)
    return record


def generate_invoice(organization, *, year: int | None = None, month: int | None = None):
    """Build (or refresh) the usage statement for an org's month from UsageRecords.

    Idempotent per (org, month): re-running recomputes totals. Records only what is
    owed — it does not collect payment.
    """
    import calendar
    from datetime import date

    from django.db.models import Sum

    from apps.credits.models import Invoice, UsageRecord

    today = timezone.localdate()
    year = year or today.year
    month = month or today.month
    start = date(year, month, 1)
    end = date(year, month, calendar.monthrange(year, month)[1])

    records = UsageRecord.objects.filter(
        organization=organization, created_at__date__gte=start, created_at__date__lte=end
    )
    lines = [
        {
            "model": r["model"] or "unknown",
            "tokens": r["tokens"] or 0,
            "cost_usd": float(r["cost"] or 0),
            "credits": float(r["credits"] or 0),
        }
        for r in records.values("model").annotate(
            tokens=Sum("total_tokens"), cost=Sum("cost_usd"), credits=Sum("credits_charged")
        ).order_by("-cost")
    ]
    totals = records.aggregate(cost=Sum("cost_usd"), credits=Sum("credits_charged"))
    invoice, _ = Invoice.objects.update_or_create(
        organization=organization, period_start=start,
        defaults={
            "period_end": end,
            "subtotal_usd": totals["cost"] or Decimal("0"),
            "credits_used": totals["credits"] or Decimal("0"),
            "lines": lines,
        },
    )
    return invoice
