"""Deterministic offline provider.

This is NOT a language model and does not pretend to be one. It produces a
deterministic, echo-style response so DevForge can run, be developed against, and
be tested with no API key and no network. It is the default provider until a real
key is configured (AI_DEFAULT_PROVIDER). Use it wherever a real model isn't
needed; never present its output as model output.
"""
from __future__ import annotations

from apps.ai_providers.base import (
    AIProvider,
    CompletionRequest,
    CompletionResponse,
    Usage,
)


def _estimate_tokens(text: str) -> int:
    # ~4 chars/token, a stand-in until real tokenization matters (Phase 20 costs).
    return max(1, len(text) // 4)


class StubProvider(AIProvider):
    name = "stub"

    def default_model(self) -> str:
        return "stub-1"

    def available_models(self) -> list[str]:
        return ["stub-1"]

    def is_available(self) -> bool:
        return True

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        model = request.model or self.default_model()
        last_user = next(
            (m.content for m in reversed(request.messages) if m.role == "user"),
            "",
        )
        text = f"[stub:{model}] {last_user[:500]}".rstrip()
        prompt_chars = request.system + "".join(m.content for m in request.messages)
        return CompletionResponse(
            text=text,
            model=model,
            provider=self.name,
            usage=Usage(
                input_tokens=_estimate_tokens(prompt_chars),
                output_tokens=_estimate_tokens(text),
            ),
            finish_reason="stop",
            raw={"stub": True},
        )
