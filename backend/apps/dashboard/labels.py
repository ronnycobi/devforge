"""Customer-facing translation of internal work into plain outcomes.

The Client Transparency Boundary (docs/PRODUCT.md): the customer sees WHAT DevForge
did, never the internal agent that did it. Every customer-facing view runs task /
step identifiers through friendly_step() so proprietary agent names, capabilities
and orchestration never reach the UI.
"""
from __future__ import annotations

_FRIENDLY = {
    "lead": "Planning the work",
    "product": "Understanding what you need",
    "requirements": "Understanding what you need",
    "architect": "Designing your application",
    "database": "Setting up your data",
    "backend": "Building the core features",
    "frontend": "Building the interface",
    "mobile": "Building the mobile experience",
    "testing": "Testing everything works",
    "code_review": "Quality review",
    "security": "Security review",
    "devops": "Preparing to deploy",
}


def friendly_step(key: str) -> str:
    return _FRIENDLY.get((key or "").strip(), "Working on your application")
