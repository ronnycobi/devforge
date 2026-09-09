"""Wire the e-commerce engine into the build flow (spec §32).

When a build's brief implies a store, DevForge sets up the store CAPABILITY for that
project — a Website, a starter catalogue, a default shipping option, and generated
storefront pages — all connected to the tested engine (products/cart/checkout/
payments/inventory), rather than an agent hand-writing a bespoke store.

Starter products are DRAFTS the merchant edits: DevForge doesn't know the real
catalogue, so it proposes editable starters (AI when a model is available, otherwise
one clearly-labelled sample). Nothing is faked as a real product.
"""
from __future__ import annotations

import json
import re

from apps.audit.service import record as audit
from apps.publishing import ecommerce_service as shop
from apps.publishing import service as pub
from apps.publishing import storefront


def provision_store(project, brief="", *, user=None) -> dict | None:
    """Set up the store capability for a project. Idempotent: does nothing if the
    website already has products."""
    website = pub.get_or_create_website(project)
    if website.products.exists():
        return None

    for p in _suggest_products(brief or project.description or project.name):
        shop.create_product(website, name=p["name"], price_cents=p["price_cents"],
                            description=p.get("description", ""), user=user)
    shop.create_shipping_rate(website, name="Standard shipping", price_cents=500, user=user)

    pages = 0
    try:
        pages = storefront.generate_storefront(website, user=user)["pages"]
    except storefront.StorefrontError:
        pass   # nothing to generate yet — fine

    audit("shop.provision", actor=user, organization=project.organization,
          target=f"website:{website.id}", summary=f"{website.products.count()} starter product(s)")
    return {"products": website.products.count(), "storefront_pages": pages}


_FALLBACK = [{"name": "Sample product",
              "price_cents": 1000,
              "description": "An example product — edit or replace this with your own."}]


def _suggest_products(brief: str) -> list[dict]:
    """Draft editable starter products from the brief (AI, with a deterministic sample
    fallback). Marked as starters — the merchant replaces them."""
    try:
        from apps.ai_providers.base import Message
        from apps.model_router.router import ModelRouter, RoutingRequest, TaskComplexity
        router = ModelRouter()
        system = (
            "Suggest up to 4 STARTER products for the described store, as JSON: a list of "
            '{"name","price","description"} — price in whole/decimal currency units. These '
            "are editable placeholders based only on the brief; invent nothing beyond "
            "plausible example items. JSON only."
        )
        resp = router.complete(
            RoutingRequest(complexity=TaskComplexity.LOW, task_type="store_starter"),
            messages=[Message(role="user", content=f"Store: {brief}")],
            system=system, max_tokens=400)
        m = re.search(r"\[.*\]", resp.text, re.S)
        if m:
            data = json.loads(m.group(0))
            out = []
            for item in data[:4]:
                name = str(item.get("name", "")).strip()
                if not name:
                    continue
                try:
                    cents = int(round(float(item.get("price", 10)) * 100))
                except (TypeError, ValueError):
                    cents = 1000
                out.append({"name": name[:200], "price_cents": max(0, cents),
                            "description": str(item.get("description", ""))[:500]})
            if out:
                return out
    except Exception:
        pass
    return list(_FALLBACK)
