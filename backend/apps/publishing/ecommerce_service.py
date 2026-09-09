"""E-commerce orchestration (spec §32).

Products → cart/order (totals computed from real product prices) → checkout via a
PaymentProvider → payment → order status. An order becomes 'paid' only on a real
confirmation (a merchant confirming a manual payment, or — once built — a gateway
callback). Card processing is gated; nothing here marks an order paid without a
genuine confirmation (spec §50).
"""
from __future__ import annotations

import secrets

from django.utils import timezone
from django.utils.text import slugify

from apps.audit.service import record as audit
from apps.publishing.models import Order, OrderItem, Payment, Product
from apps.publishing.payments import PaymentError, get_provider


class EcommerceError(Exception):
    pass


def create_product(website, *, name, price_cents, currency="USD", description="", user=None) -> Product:
    if price_cents < 0:
        raise EcommerceError("Price cannot be negative.")
    base = slugify(name) or "product"
    slug, n = base, 1
    while website.products.filter(slug=slug).exists():
        n += 1
        slug = f"{base}-{n}"
    product = Product.objects.create(
        website=website, slug=slug, name=name, description=description,
        price_cents=int(price_cents), currency=currency,
    )
    audit("shop.product", actor=user, organization=website.project.organization,
          target=f"product:{product.id}", summary=name)
    return product


def create_order(website, *, items, customer_name="", customer_email="") -> Order:
    """items: list of {product_id or product, quantity}. Totals are computed from the
    products' real prices — never trusted from the client."""
    if not items:
        raise EcommerceError("An order needs at least one item.")
    order = Order.objects.create(
        website=website, reference=_reference(),
        customer_name=customer_name.strip(), customer_email=customer_email.strip(),
        currency=website.products.first().currency if website.products.exists() else "USD",
        status="pending",
    )
    subtotal = 0
    currency = order.currency
    for row in items:
        product = row.get("product")
        if product is None:
            product = website.products.filter(pk=row.get("product_id"), active=True).first()
        if product is None:
            continue
        qty = max(1, int(row.get("quantity", 1)))
        OrderItem.objects.create(
            order=order, product=product, name=product.name,
            unit_price_cents=product.price_cents, quantity=qty,
        )
        subtotal += product.price_cents * qty
        currency = product.currency
    if not order.items.exists():
        order.delete()
        raise EcommerceError("None of the requested products are available.")
    order.subtotal_cents = subtotal
    order.currency = currency
    order.save(update_fields=["subtotal_cents", "currency"])
    return order


def start_checkout(order: Order, *, provider_key="manual") -> dict:
    provider = get_provider(provider_key)
    if provider is None:
        raise EcommerceError(f"Unknown payment provider '{provider_key}'.")
    result = provider.start_checkout(order)   # raises PaymentError if not configured
    order.provider = provider_key
    order.status = "awaiting_payment"
    order.save(update_fields=["provider", "status", "updated_at"])
    Payment.objects.create(
        order=order, provider=provider_key, method=result.get("mode", ""),
        amount_cents=order.subtotal_cents, currency=order.currency, status="pending",
        detail=result.get("instructions", "")[:500],
    )
    audit("shop.checkout", organization=order.website.project.organization,
          target=f"order:{order.id}", summary=f"{provider_key} · {order.total_display}")
    return result


def confirm_manual_payment(order: Order, *, user) -> Order:
    """Merchant confirms a manual payment was received (spec §32). This is a real human
    confirmation of real money received — the only way a manual order becomes paid."""
    if order.provider != "manual":
        raise EcommerceError("Only manual orders are confirmed this way.")
    payment = order.payments.filter(status="pending").first()
    if payment:
        payment.status = "succeeded"
        payment.confirmed_by = user
        payment.detail = "Confirmed received by the seller."
        payment.save(update_fields=["status", "confirmed_by", "detail"])
    order.status = "paid"
    order.save(update_fields=["status", "updated_at"])
    audit("shop.paid", actor=user, organization=order.website.project.organization,
          target=f"order:{order.id}", summary=order.total_display)
    return order


def cancel_order(order: Order, *, user=None) -> Order:
    order.status = "cancelled"
    order.save(update_fields=["status", "updated_at"])
    audit("shop.cancel", actor=user, organization=order.website.project.organization,
          target=f"order:{order.id}")
    return order


def _reference() -> str:
    return "ORD-" + secrets.token_hex(4).upper()
