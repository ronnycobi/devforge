"""Anthropic (Claude) provider.

A real implementation: when the `anthropic` SDK is installed and ANTHROPIC_API_KEY
is set, complete() calls the Messages API. When either is missing, is_available()
is False and complete() raises ProviderUnavailable with a clear reason — an honest
"not configured", never a fabricated response. The API key is read from the
environment only; it is never stored in settings, the database, or logs.
"""
from __future__ import annotations

import os

from apps.ai_providers.base import (
    AIProvider,
    CompletionRequest,
    CompletionResponse,
    ProviderUnavailable,
    Usage,
)


class AnthropicProvider(AIProvider):
    name = "anthropic"

    DEFAULT_MODEL = "claude-opus-5"
    MODELS = ["claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5"]

    def default_model(self) -> str:
        return self.DEFAULT_MODEL

    def available_models(self) -> list[str]:
        return list(self.MODELS)

    @staticmethod
    def _api_key() -> str:
        return os.environ.get("ANTHROPIC_API_KEY", "")

    def is_available(self) -> bool:
        if not self._api_key():
            return False
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return False
        return True

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        if not self.is_available():
            raise ProviderUnavailable(
                "Anthropic provider unavailable: set ANTHROPIC_API_KEY and "
                "install the 'anthropic' package."
            )
        import anthropic

        client = anthropic.Anthropic(api_key=self._api_key())
        model = request.model or self.default_model()

        kwargs = {
            "model": model,
            "max_tokens": request.max_tokens,
            "messages": [
                {"role": m.role, "content": m.content} for m in request.messages
            ],
        }
        if request.system:
            kwargs["system"] = request.system
        if request.temperature is not None:
            kwargs["temperature"] = request.temperature

        response = client.messages.create(**kwargs)

        text = "".join(
            block.text
            for block in response.content
            if getattr(block, "type", None) == "text"
        )
        usage = Usage(
            input_tokens=getattr(response.usage, "input_tokens", 0),
            output_tokens=getattr(response.usage, "output_tokens", 0),
        )
        return CompletionResponse(
            text=text,
            model=getattr(response, "model", model),
            provider=self.name,
            usage=usage,
            finish_reason=getattr(response, "stop_reason", "") or "",
        )
