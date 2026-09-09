"""E-commerce orchestration (spec §32).

Products → cart/order (totals computed from real product prices) → checkout via a
PaymentProvider → payment → order status. An order becomes 'paid' only on a real
confirmation (a merchant confirming a manual payment, or — once built — a gateway
callback). Card processing is gated; nothing here marks an order paid without a
genuine confirmation (spec §50).
"""
from __future__ import annotations

import secrets

from django.db import transaction
from django.db.models import F
from django.utils import timezone
from django.utils.text import slugify

from apps.audit.service import record as audit
from apps.publishing.models import (
    DiscountCode, Order, OrderItem, Payment, Product, ShippingRate, TaxRate,
)
from apps.publishing.payments import PaymentError, get_provider


class EcommerceError(Exception):
    pass


class DiscountError(EcommerceError):
    pass


def create_discount(website, *, code, kind="percent", percent_off=0, amount_off_cents=0,
                    currency="USD", min_subtotal_cents=0, max_uses=0, expires_at=None,
                    user=None) -> DiscountCode:
    code = (code or "").strip().upper()
    if not code:
        raise DiscountError("A code is required.")
    if website.discount_codes.filter(code=code).exists():
        raise DiscountError(f"Code {code} already exists.")
    if kind == DiscountCode.PERCENT and not (1 <= int(percent_off) <= 100):
        raise DiscountError("Percentage must be between 1 and 100.")
    if kind == DiscountCode.FIXED and int(amount_off_cents) <= 0:
        raise DiscountError("Fixed amount must be greater than zero.")
    dc = DiscountCode.objects.create(
        website=website, code=code, kind=kind,
        percent_off=int(percent_off or 0), amount_off_cents=int(amount_off_cents or 0),
        currency=currency, min_subtotal_cents=int(min_subtotal_cents or 0),
        max_uses=int(max_uses or 0),
    )
    audit("shop.discount", actor=user, organization=website.project.organization,
          target=f"discount:{dc.id}", summary=f"{code} · {dc.summary}")
    return dc


def _discount_for(code_obj: DiscountCode, subtotal_cents: int, currency: str) -> int:
    """Compute the discount in cents, or raise DiscountError explaining why not."""
    from django.utils import timezone
    if not code_obj.active:
        raise DiscountError("That code is no longer active.")
    if code_obj.expires_at and code_obj.expires_at < timezone.now():
        raise DiscountError("That code has expired.")
    if code_obj.max_uses and code_obj.used_count >= code_obj.max_uses:
        raise DiscountError("That code has reached its usage limit.")
    if subtotal_cents < code_obj.min_subtotal_cents:
        raise DiscountError(
            f"That code needs a minimum order of "
            f"{currency} {code_obj.min_subtotal_cents / 100:.2f}.")
    if code_obj.kind == DiscountCode.PERCENT:
        discount = subtotal_cents * code_obj.percent_off // 100
    else:
        if code_obj.currency != currency:
            raise DiscountError("That code can't be used in this currency.")
        discount = code_obj.amount_off_cents
    return min(discount, subtotal_cents)   # never below zero total


def resolve_image(website, image_asset_id):
    """An image asset that belongs to this website, or None. Guards cross-tenant use."""
    if not image_asset_id:
        return None
    return website.assets.filter(pk=image_asset_id, kind__in=["image", "icon"]).first()


def create_product(website, *, name, price_cents, currency="USD", description="",
                   track_inventory=False, stock=0, image_asset_id=None, user=None) -> Product:
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
        track_inventory=bool(track_inventory), stock=max(0, int(stock)),
        image=resolve_image(website, image_asset_id),
    )
    audit("shop.product", actor=user, organization=website.project.organization,
          target=f"product:{product.id}", summary=name)
    return product


def create_shipping_rate(website, *, name, price_cents, currency="USD",
                         free_over_cents=0, user=None) -> ShippingRate:
    if not (name or "").strip():
        raise EcommerceError("A shipping option needs a name.")
    if int(price_cents) < 0:
        raise EcommerceError("Shipping price cannot be negative.")
    rate = ShippingRate.objects.create(
        website=website, name=name.strip(), price_cents=int(price_cents),
        currency=currency, free_over_cents=max(0, int(free_over_cents or 0)),
    )
    audit("shop.shipping_rate", actor=user, organization=website.project.organization,
          target=f"shipping:{rate.id}", summary=f"{name} · {rate.price_display}")
    return rate


def set_tax_rate(website, *, name, percent, user=None) -> TaxRate:
    """Set the store's tax rate (one active rate). Percent may be like 15 or 7.5."""
    try:
        bps = int(round(float(percent) * 100))
    except (TypeError, ValueError):
        raise EcommerceError("Enter a valid tax percentage.")
    if not (0 < bps <= 10000):
        raise EcommerceError("Tax must be between 0 and 100%.")
    website.tax_rates.filter(active=True).update(active=False)   # only one active
    rate = TaxRate.objects.create(website=website, name=(name or "Tax").strip(), rate_bps=bps)
    audit("shop.tax_rate", actor=user, organization=website.project.organization,
          target=f"tax:{rate.id}", summary=f"{rate.name} {rate.rate_display}")
    return rate


def create_order(website, *, items, customer_name="", customer_email="", code="",
                 shipping_rate_id="", shipping_address="") -> Order:
    """items: list of {product_id or product, quantity}. Totals are computed from the
    products' real prices — never trusted from the client. An optional discount `code`
    is validated and applied server-side."""
    if not items:
        raise EcommerceError("An order needs at least one item.")
    # Resolve products + quantities first (outside the transaction).
    resolved = []
    for row in items:
        product = row.get("product")
        if product is None:
            product = website.products.filter(pk=row.get("product_id"), active=True).first()
        if product is None:
            continue
        resolved.append((product, max(1, int(row.get("quantity", 1)))))
    if not resolved:
        raise EcommerceError("None of the requested products are available.")
    currency = resolved[-1][0].currency

    code = (code or "").strip().upper()
    code_obj = website.discount_codes.filter(code=code).first() if code else None
    if code and code_obj is None:
        raise DiscountError("That discount code isn't recognised.")

    rate = None
    if shipping_rate_id:
        rate = website.shipping_rates.filter(pk=shipping_rate_id, active=True).first()
        if rate is None:
            raise EcommerceError("That shipping option isn't available.")
        if rate.currency != currency:
            raise EcommerceError("That shipping option can't be used in this currency.")

    with transaction.atomic():
        order = Order.objects.create(
            website=website, reference=_reference(),
            customer_name=customer_name.strip(), customer_email=customer_email.strip(),
            currency=currency, status="pending",
        )
        subtotal = 0
        for product, qty in resolved:
            if product.track_inventory:
                # Atomic, race-safe reserve: only succeeds if enough stock remains.
                reserved = Product.objects.filter(
                    pk=product.pk, stock__gte=qty
                ).update(stock=F("stock") - qty)
                if not reserved:
                    raise EcommerceError(f"“{product.name}” is out of stock.")
            OrderItem.objects.create(
                order=order, product=product, name=product.name,
                unit_price_cents=product.price_cents, quantity=qty,
            )
            subtotal += product.price_cents * qty

        discount = 0
        if code_obj is not None:
            discount = _discount_for(code_obj, subtotal, currency)   # raises DiscountError
            # Atomic usage-limit guard (like stock): only claim a use if one remains.
            if code_obj.max_uses:
                claimed = DiscountCode.objects.filter(
                    pk=code_obj.pk, used_count__lt=code_obj.max_uses
                ).update(used_count=F("used_count") + 1)
                if not claimed:
                    raise DiscountError("That code has reached its usage limit.")
            else:
                DiscountCode.objects.filter(pk=code_obj.pk).update(used_count=F("used_count") + 1)
            code_obj.refresh_from_db(fields=["used_count"])
            order.discount_code = code_obj

        goods_net = subtotal - discount
        tax_rate = website.tax_rates.filter(active=True).first()
        tax = tax_rate.tax_for(goods_net) if tax_rate else 0
        shipping = rate.cost_for(subtotal) if rate else 0

        order.subtotal_cents = subtotal
        order.discount_cents = discount
        order.tax_cents = tax
        order.tax_rate = tax_rate
        order.shipping_cents = shipping
        order.shipping_rate = rate
        order.shipping_address = (shipping_address or "").strip()
        order.total_cents = goods_net + tax + shipping
        order.currency = currency
        order.save(update_fields=["subtotal_cents", "discount_cents", "tax_cents",
                                  "shipping_cents", "total_cents", "discount_code",
                                  "tax_rate", "shipping_rate", "shipping_address", "currency"])
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
        amount_cents=order.total_cents, currency=order.currency, status="pending",
        detail=result.get("instructions", "")[:500],
    )
    # Confirmation email to the buyer (best-effort, only if they gave an address).
    body = (f"Thanks for your order {order.reference} from "
            f"{order.website.project.name}.\n\n{_order_lines(order)}\n")
    if order.discount_cents or order.shipping_cents or order.tax_cents:
        body += f"Subtotal: {order.subtotal_display}\n"
        if order.discount_cents:
            body += f"Discount: -{order.discount_display}\n"
        if order.tax_rate:
            body += f"{order.tax_rate.name} ({order.tax_rate.rate_display}): {order.tax_display}\n"
        if order.shipping_rate:
            body += f"Shipping ({order.shipping_rate.name}): {order.shipping_display}\n"
    body += f"Total: {order.total_display}\n"
    body += (f"\nTrack your order: /sites/{order.website.subdomain}/order/{order.reference}\n")
    if result.get("instructions"):
        body += f"\n{result['instructions']}\n"
    order.confirmation_sent = _email_buyer(order, f"Order {order.reference} received", body)
    order.save(update_fields=["confirmation_sent", "updated_at"])
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
    # Receipt email to the buyer (best-effort).
    body = (f"We've received your payment for order {order.reference} from "
            f"{order.website.project.name}.\n\n{_order_lines(order)}\n"
            f"Total paid: {order.total_display}\n\nThank you!")
    order.receipt_sent = _email_buyer(order, f"Payment received — order {order.reference}", body)
    order.save(update_fields=["status", "receipt_sent", "updated_at"])
    audit("shop.paid", actor=user, organization=order.website.project.organization,
          target=f"order:{order.id}", summary=order.total_display)
    return order


def refund_order(order: Order, *, user, reason="") -> Order:
    """Refund a paid order (spec §32). For manual payments this records that the seller
    refunded the buyer off-platform (real, merchant-confirmed) — it restocks inventory
    and emails the buyer. Card/gateway refunds need the gateway API and stay gated;
    nothing here fabricates a refund it can't perform (spec §50)."""
    if order.status == "refunded":
        return order
    if order.status != "paid":
        raise EcommerceError("Only a paid order can be refunded.")
    if order.provider != "manual":
        raise EcommerceError(
            f"Automatic refunds for {order.provider or 'this provider'} aren't enabled yet — "
            "issue the refund from the gateway, then cancel the order."
        )
    payment = order.payments.filter(status="succeeded").first()
    with transaction.atomic():
        for it in order.items.select_related("product"):
            if it.product and it.product.track_inventory:
                Product.objects.filter(pk=it.product_id).update(stock=F("stock") + it.quantity)
        if payment:
            payment.status = "refunded"
            payment.detail = (reason or "Refunded by the seller.")[:500]
            payment.confirmed_by = user
            payment.save(update_fields=["status", "detail", "confirmed_by"])
        order.status = "refunded"
        order.save(update_fields=["status", "updated_at"])
    body = (f"Your order {order.reference} from {order.website.project.name} has been "
            f"refunded ({order.total_display}).")
    if reason:
        body += f"\n\nNote: {reason}"
    _email_buyer(order, f"Refund for order {order.reference}", body)
    audit("shop.refund", actor=user, organization=order.website.project.organization,
          target=f"order:{order.id}", summary=order.total_display)
    return order


def cancel_order(order: Order, *, user=None) -> Order:
    if order.status in ("cancelled", "refunded"):
        return order
    # Return reserved stock to inventory (only once, and only for tracked products).
    with transaction.atomic():
        for it in order.items.select_related("product"):
            if it.product and it.product.track_inventory:
                Product.objects.filter(pk=it.product_id).update(stock=F("stock") + it.quantity)
        order.status = "cancelled"
        order.save(update_fields=["status", "updated_at"])
    audit("shop.cancel", actor=user, organization=order.website.project.organization,
          target=f"order:{order.id}")
    return order


def sales_summary(website) -> dict:
    """Real sales figures from actual orders (spec §32). Revenue is grouped BY CURRENCY
    — never summed across currencies — so the numbers are honest. Only paid orders
    count as revenue; refunded orders are reported separately and netted per currency."""
    from collections import defaultdict
    from django.db.models import F, Sum

    orders = website.orders.all()
    counts = {s: orders.filter(status=s).count() for s, _ in Order.STATUS}

    paid_cents, refunded_cents = defaultdict(int), defaultdict(int)
    for cur, cents in orders.filter(status="paid").values_list("currency", "total_cents"):
        paid_cents[cur] += cents
    for cur, cents in orders.filter(status="refunded").values_list("currency", "total_cents"):
        refunded_cents[cur] += cents

    revenue = []
    for cur in sorted(set(paid_cents) | set(refunded_cents)):
        gross, ref = paid_cents.get(cur, 0), refunded_cents.get(cur, 0)
        revenue.append({
            "currency": cur,
            "gross": f"{cur} {gross / 100:.2f}",
            "refunded": f"{cur} {ref / 100:.2f}",
            "net": f"{cur} {(gross - ref) / 100:.2f}",
        })

    top = list(
        OrderItem.objects.filter(order__website=website, order__status="paid")
        .values("name")
        .annotate(units=Sum("quantity"), revenue_cents=Sum(F("unit_price_cents") * F("quantity")))
        .order_by("-units")[:8]
    )
    units_sold = (
        OrderItem.objects.filter(order__website=website, order__status="paid")
        .aggregate(n=Sum("quantity"))["n"] or 0
    )

    return {
        "counts": counts,
        "paid_orders": counts.get("paid", 0),
        "revenue": revenue,
        "top_products": top,
        "units_sold": units_sold,
    }


def _reference() -> str:
    return "ORD-" + secrets.token_hex(4).upper()


def _order_lines(order) -> str:
    return "\n".join(
        f"  {it.quantity} × {it.name} — {order.currency} {it.line_total_cents / 100:.2f}"
        for it in order.items.all()
    )


def _email_buyer(order, subject: str, text: str) -> bool:
    """Send an email to the buyer if they gave an address. Returns whether it sent;
    never lets a delivery failure break the order flow (honest: no address / send
    failure → False, and the order still stands)."""
    if not order.customer_email:
        return False
    try:
        from apps.notifications.email import send_email
        return bool(send_email(subject=f"{subject} · {order.website.project.name}",
                               to=order.customer_email, text=text))
    except Exception:
        return False
