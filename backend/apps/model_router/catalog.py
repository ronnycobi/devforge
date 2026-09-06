"""Model catalog — the metadata the router picks from.

One ModelProfile per (provider, model) the platform can route to, with the facts
routing needs: capability tier, context window, price, and speed. Prices are the
Anthropic first-party list rates (USD per 1M tokens); keep them in sync with the
provider's pricing. `is_fallback_only` marks models (the offline stub) that must
never be chosen over a real model — only when nothing real is usable.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelProfile:
    provider: str
    model: str
    tier: int  # 1 = basic, 2 = standard, 3 = advanced
    context_window: int
    input_cost_per_mtok: float
    output_cost_per_mtok: float
    speed: int  # 1 = slow .. 3 = fast
    is_fallback_only: bool = False

    @property
    def avg_cost_per_mtok(self) -> float:
        return (self.input_cost_per_mtok + self.output_cost_per_mtok) / 2


# Ordered advanced -> basic within a provider for readability; routing does not
# depend on catalog order.
MODEL_CATALOG: list[ModelProfile] = [
    ModelProfile("anthropic", "claude-opus-5", 3, 1_000_000, 5.0, 25.0, speed=1),
    ModelProfile("anthropic", "claude-sonnet-5", 2, 1_000_000, 2.0, 10.0, speed=2),
    ModelProfile("anthropic", "claude-haiku-4-5", 1, 200_000, 1.0, 5.0, speed=3),
    ModelProfile(
        "stub", "stub-1", 1, 1_000_000, 0.0, 0.0, speed=3, is_fallback_only=True
    ),
]


def profile_for(provider: str, model: str) -> ModelProfile | None:
    return next(
        (p for p in MODEL_CATALOG if p.provider == provider and p.model == model),
        None,
    )


def profile_by_model(model: str) -> ModelProfile | None:
    return next((p for p in MODEL_CATALOG if p.model == model), None)
