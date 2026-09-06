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

from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings

from apps.credits.models import CreditAccount, UsageRecord
from apps.model_router.catalog import profile_by_model

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


def guard_can_run(organization) -> bool:
    """True if agent work may run. An org with no account is unlimited (dev)."""
    account = get_account(organization)
    if account is None:
        return True
    return account.balance > 0


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
