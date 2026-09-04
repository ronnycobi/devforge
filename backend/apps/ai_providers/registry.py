"""Registry of AI providers, and the gateway used to call them.

The gateway is the single entry point the rest of DevForge uses to run a
completion. It resolves a provider (explicit, or the configured default) and
delegates. The Model Router (Phase 7) will layer smart provider/model selection
on top of this; today the choice is "explicit provider, or the default".
"""
from __future__ import annotations

from dataclasses import replace

from django.conf import settings

from apps.ai_providers.anthropic_provider import AnthropicProvider
from apps.ai_providers.base import AIProvider, CompletionRequest, CompletionResponse
from apps.ai_providers.stub import StubProvider


class ProviderRegistry:
    def __init__(self):
        self._providers: dict[str, AIProvider] = {}

    def register(self, provider: AIProvider) -> AIProvider:
        if provider.name in self._providers:
            raise ValueError(f"Provider '{provider.name}' already registered")
        self._providers[provider.name] = provider
        return provider

    def get(self, name: str) -> AIProvider:
        return self._providers[name]

    def all(self) -> list[AIProvider]:
        return list(self._providers.values())

    def __contains__(self, name: str) -> bool:
        return name in self._providers


registry = ProviderRegistry()
registry.register(StubProvider())
registry.register(AnthropicProvider())


def default_provider_name() -> str:
    # Defaults to the offline stub so a fresh checkout runs with no keys.
    return getattr(settings, "AI_DEFAULT_PROVIDER", "stub")


def get_provider(name: str | None = None) -> AIProvider:
    resolved = name or default_provider_name()
    if resolved not in registry:
        raise ValueError(f"Unknown AI provider '{resolved}'")
    return registry.get(resolved)


def complete(request: CompletionRequest, *, provider=None) -> CompletionResponse:
    """Run a completion through the given provider (instance or name) or default."""
    prov = provider if isinstance(provider, AIProvider) else get_provider(provider)
    if request.model is None:
        request = replace(request, model=prov.default_model())
    return prov.complete(request)
