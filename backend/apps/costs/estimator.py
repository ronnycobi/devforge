"""Project cost analyzer.

Estimates what building a project will cost — in credits and USD — as RANGES,
never false-precision point numbers (docs/PRODUCT.md §22). It estimates against
real catalog pricing for the model each agent would use (cheapest-sufficient for
its complexity, ignoring live availability and never the free stub), so the
estimate is meaningful even when running offline. It also reads a risk level and
recommends the cheapest plan whose allowance covers the high estimate.
"""
from __future__ import annotations

from decimal import Decimal

from apps.costs.profiles import AGENT_COMPLEXITY, AGENT_TOKEN_ESTIMATE, DEFAULT_PIPELINE
from apps.credits.services import credits_for, plans
from apps.model_router.catalog import MODEL_CATALOG, ModelProfile
from apps.model_router.router import TaskComplexity

_REQUIRED_TIER = {TaskComplexity.LOW: 1, TaskComplexity.MEDIUM: 2, TaskComplexity.HIGH: 3}


def model_for_complexity(complexity: TaskComplexity) -> ModelProfile | None:
    """Cheapest real (non-stub) model whose tier meets the complexity."""
    required = _REQUIRED_TIER[complexity]
    real = [p for p in MODEL_CATALOG if not p.is_fallback_only]
    sufficient = [p for p in real if p.tier >= required]
    pool = sufficient or real  # degrade to most capable real model if none suffice
    if not pool:
        return None
    if sufficient:
        return min(pool, key=lambda p: (p.avg_cost_per_mtok, p.tier))
    return max(pool, key=lambda p: p.tier)


def _round2(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01")))


def estimate_project(agents=None, *, iterations: int = 1, spread: float = 0.4) -> dict:
    agents = agents or list(DEFAULT_PIPELINE)
    iterations = max(1, int(iterations))
    lo = Decimal(str(1 - spread))
    hi = Decimal(str(1 + spread))

    per_agent = []
    cost_low = cost_high = Decimal("0")
    high_complexity_count = 0

    for agent in agents:
        complexity = AGENT_COMPLEXITY.get(agent, TaskComplexity.MEDIUM)
        if complexity == TaskComplexity.HIGH:
            high_complexity_count += 1
        tokens = AGENT_TOKEN_ESTIMATE.get(agent, 4000) * iterations
        profile = model_for_complexity(complexity)
        rate = Decimal(str(profile.avg_cost_per_mtok)) if profile else Decimal("0")
        expected = (Decimal(tokens) / Decimal(1_000_000)) * rate
        a_low, a_high = expected * lo, expected * hi
        cost_low += a_low
        cost_high += a_high
        per_agent.append(
            {
                "agent": agent,
                "complexity": complexity.value,
                "model": profile.model if profile else None,
                "est_tokens": tokens,
                "cost_usd": [_round2(a_low), _round2(a_high)],
                "credits": [float(credits_for(a_low)), float(credits_for(a_high))],
            }
        )

    credits_low = credits_for(cost_low)
    credits_high = credits_for(cost_high)

    return {
        "agents": agents,
        "iterations": iterations,
        "cost_usd": [_round2(cost_low), _round2(cost_high)],
        "credits": [float(credits_low), float(credits_high)],
        "risk": _risk(high_complexity_count, iterations),
        "recommended_plan": _recommend_plan(credits_high),
        "per_agent": per_agent,
    }


def _risk(high_complexity_count: int, iterations: int) -> str:
    score = high_complexity_count + (iterations - 1)
    if score >= 4:
        return "high"
    if score >= 2:
        return "medium"
    return "low"


def _recommend_plan(credits_high: Decimal) -> str:
    for name, allowance in sorted(plans().items(), key=lambda kv: kv[1]):
        if Decimal(allowance) >= credits_high:
            return name
    return "enterprise"  # exceeds every configured plan -> custom
