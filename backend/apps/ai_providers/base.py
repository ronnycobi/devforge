"""Provider-independent AI interface.

The rest of DevForge speaks only in these types — CompletionRequest and
CompletionResponse — never a vendor SDK's objects (docs/PRODUCT.md §3). Swapping
Claude for another provider is implementing one AIProvider subclass; nothing
upstream changes. The Model Router (Phase 7) chooses which provider/model to use;
this layer only defines the contract and the concrete providers.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class Message:
    role: str  # "user" | "assistant"
    content: str


@dataclass
class CompletionRequest:
    messages: list[Message]
    model: str | None = None  # None -> the provider's default model
    system: str = ""
    max_tokens: int = 1024
    temperature: float | None = None
    metadata: dict = field(default_factory=dict)


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class CompletionResponse:
    text: str
    model: str
    provider: str
    usage: Usage
    finish_reason: str = ""
    raw: dict = field(default_factory=dict)


class ProviderUnavailable(Exception):
    """Raised when a provider is asked to complete but isn't usable
    (missing SDK, missing API key, etc.)."""


class AIProvider(ABC):
    name: str = ""

    def default_model(self) -> str:
        raise NotImplementedError

    def available_models(self) -> list[str]:
        return [self.default_model()]

    def is_available(self) -> bool:
        """Whether this provider can actually serve a request right now."""
        return True

    @abstractmethod
    def complete(self, request: CompletionRequest) -> CompletionResponse:
        """Run a completion. Must raise ProviderUnavailable if not is_available()."""
        raise NotImplementedError
