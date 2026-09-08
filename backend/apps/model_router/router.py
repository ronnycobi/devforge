"""The Model Router.

Chooses a provider+model for a piece of work from the task's shape — complexity,
context size, budget, customer preference — subject to what's actually available,
then executes with failover down an ordered candidate list (docs/PRODUCT.md §3).

Two standing policies:
- **Quality-first by default.** DevForge optimizes for the best output, so for a
  given complexity the router picks the *most capable* model whose tier meets it.
  A task may opt into economy (`prefer_quality=False`) or a hard `max_cost_per_mtok`
  ceiling. The default is configurable via settings.DEVFORGE_PREFER_QUALITY.
- **Real models beat the stub.** The offline stub is chosen only when no real
  model is usable (e.g. no API key), so the platform still runs offline.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from apps.ai_providers.base import CompletionRequest, ProviderUnavailable
from apps.ai_providers.registry import complete as gateway_complete
from apps.ai_providers.registry import registry
from apps.model_router.catalog import MODEL_CATALOG, ModelProfile


class TaskComplexity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


_REQUIRED_TIER = {TaskComplexity.LOW: 1, TaskComplexity.MEDIUM: 2, TaskComplexity.HIGH: 3}


def _default_prefer_quality() -> bool:
    # Platform posture: best model by default. Configurable, evaluated per request
    # so tests and deployments can override it.
    from django.conf import settings

    return getattr(settings, "DEVFORGE_PREFER_QUALITY", True)


@dataclass
class RoutingRequest:
    complexity: TaskComplexity = TaskComplexity.MEDIUM
    required_context_tokens: int = 0
    max_cost_per_mtok: float | None = None  # budget ceiling on avg cost
    prefer_quality: bool = field(default_factory=_default_prefer_quality)
    preferred_provider: str | None = None
    preferred_model: str | None = None
    allowed_providers: list[str] | None = None
    task_type: str = ""  # informational / telemetry


@dataclass
class RoutingDecision:
    provider: str
    model: str
    reason: str
    fallbacks: list[tuple[str, str]] = field(default_factory=list)


class NoModelAvailable(Exception):
    pass


class ModelRouter:
    def __init__(self, catalog: list[ModelProfile] = None):
        self.catalog = catalog if catalog is not None else MODEL_CATALOG

    # --- availability -----------------------------------------------------

    def _available(self) -> list[ModelProfile]:
        out = []
        for profile in self.catalog:
            if profile.provider not in registry:
                continue
            if registry.get(profile.provider).is_available():
                out.append(profile)
        return out

    # --- ranking ----------------------------------------------------------

    def _rank(self, profiles, required_tier, prefer_quality):
        def key(p: ModelProfile):
            real_first = int(p.is_fallback_only)  # real models before stub
            if p.tier >= required_tier:
                group = 0  # sufficient
                sub = (
                    (-p.tier, p.avg_cost_per_mtok)
                    if prefer_quality
                    else (p.avg_cost_per_mtok, p.tier)  # cheapest sufficient
                )
            else:
                group = 1  # degraded: best available effort
                sub = (-p.tier, p.avg_cost_per_mtok)
            return (real_first, group, *sub, p.model)

        return sorted(profiles, key=key)

    # --- routing ----------------------------------------------------------

    def route(self, request: RoutingRequest) -> RoutingDecision:
        profiles = self._available()
        if request.allowed_providers:
            allowed = set(request.allowed_providers)
            profiles = [p for p in profiles if p.provider in allowed]

        def meets_hard_constraints(p: ModelProfile) -> bool:
            if (
                request.required_context_tokens
                and p.context_window < request.required_context_tokens
            ):
                return False
            if (
                request.max_cost_per_mtok is not None
                and p.avg_cost_per_mtok > request.max_cost_per_mtok
            ):
                return False
            return True

        feasible = [p for p in profiles if meets_hard_constraints(p)]
        if not feasible:
            raise NoModelAvailable(
                "No available model satisfies the routing constraints."
            )

        required_tier = _REQUIRED_TIER[request.complexity]
        ordered = self._rank(feasible, required_tier, request.prefer_quality)

        primary = self._apply_preference(feasible, ordered, request)
        fallbacks = [p for p in ordered if p is not primary]

        degraded = primary.tier < required_tier
        reason = self._describe(primary, request, required_tier, degraded)
        return RoutingDecision(
            provider=primary.provider,
            model=primary.model,
            reason=reason,
            fallbacks=[(p.provider, p.model) for p in fallbacks],
        )

    @staticmethod
    def _apply_preference(feasible, ordered, request):
        # A satisfiable customer preference wins over the default policy.
        if request.preferred_model:
            match = next(
                (p for p in feasible if p.model == request.preferred_model), None
            )
            if match:
                return match
        if request.preferred_provider:
            of_provider = [
                p for p in ordered if p.provider == request.preferred_provider
            ]
            if of_provider:
                return of_provider[0]
        return ordered[0]

    @staticmethod
    def _describe(primary, request, required_tier, degraded):
        # A deliberately-chosen model wins the explanation even if it's below the
        # tier the router would otherwise require.
        if request.preferred_model == primary.model:
            return f"Honoured preferred model {primary.model}."
        if degraded:
            return (
                f"{primary.provider}:{primary.model} is the most capable model "
                f"available (tier {primary.tier}); no tier-{required_tier} model "
                f"is usable for {request.complexity} work."
            )
        if request.prefer_quality:
            return (
                f"{primary.model} is the most capable available model for "
                f"{request.complexity} work (quality preferred)."
            )
        return (
            f"{primary.model} is the cheapest model meeting {request.complexity} "
            f"complexity (tier {primary.tier}, ~${primary.avg_cost_per_mtok:.2f}/Mtok)."
        )

    # --- execution with failover -----------------------------------------

    def complete(self, request: RoutingRequest, *, messages, system="", max_tokens=1024,
                 temperature=None):
        decision = self.route(request)
        candidates = [(decision.provider, decision.model), *decision.fallbacks]

        last_error = None
        for provider_name, model in candidates:
            try:
                return gateway_complete(
                    CompletionRequest(
                        messages=messages,
                        model=model,
                        system=system,
                        max_tokens=max_tokens,
                        temperature=temperature,
                    ),
                    provider=provider_name,
                )
            except ProviderUnavailable as exc:
                last_error = exc
                continue
        raise last_error or NoModelAvailable("All routing candidates failed.")
