"""Serve published websites from DevForge at a stable URL (spec §10, §11).

This serves the immutable per-version snapshot for a website's CURRENT version. It
only ever returns files — it executes no customer code — and it refuses any path
that escapes the version's directory (path-traversal guard). This is the working
DevForge URL a customer gets on publish; a public *.devforge.app domain with real
DNS/SSL is the Phase-2 gated path and is not served here.
"""
from __future__ import annotations

import mimetypes
from pathlib import Path

from django.http import FileResponse, Http404, HttpResponse, HttpResponseRedirect
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.publishing.models import AcmeChallenge, Form, Website


def serve_files_for(website, path: str):
    """Serve one file from a website's current published snapshot (shared by the
    path-based /sites/ route and custom-domain host routing)."""
    version = website.current
    if version is None or not version.artifact_dir:
        raise Http404("This site is not published.")
    root = Path(version.artifact_dir).resolve()
    rel = path or "index.html"
    if rel.endswith("/"):
        rel += "index.html"
    target = (root / rel).resolve()
    if root != target and root not in target.parents:
        raise Http404("Not found.")
    if target.is_dir():
        target = (target / "index.html").resolve()
    if not target.is_file():
        raise Http404("Not found.")
    content_type, _ = mimetypes.guess_type(str(target))
    return FileResponse(open(target, "rb"), content_type=content_type or "application/octet-stream"), content_type


def acme_challenge(request, token):
    """Serve an ACME HTTP-01 challenge response (spec §22). The CA fetches this during
    certificate issuance; we return the stored key authorization as plain text."""
    ch = AcmeChallenge.objects.filter(token=token).first()
    if ch is None:
        raise Http404("Unknown challenge.")
    return HttpResponse(ch.key_authorization, content_type="text/plain")


def serve_published(request, subdomain, path=""):
    website = Website.objects.filter(subdomain=subdomain).first()
    if website is None:
        raise Http404("No such site.")
    response, content_type = serve_files_for(website, path)
    # Count real HTML page views (not assets) — privacy-first, honors Do-Not-Track.
    if (content_type or "").startswith("text/html"):
        from apps.publishing import analytics
        analytics.record_view(website, request)
    return response


@csrf_exempt
@require_POST
def submit_form(request, subdomain, slug):
    """Public form endpoint for published sites (spec §23).

    CSRF-exempt by design: this is a public submission endpoint that static customer
    pages post to (like any SaaS form endpoint). Spam is handled by a honeypot field
    and required-field validation, not a CSRF token. It stores the submission, emails
    a notification (best-effort) and creates a CRM lead.
    """
    from apps.publishing import forms_service as forms
    form = Form.objects.filter(website__subdomain=subdomain, slug=slug, active=True).first()
    if form is None:
        raise Http404("No such form.")
    data = {k: v for k, v in request.POST.items()}
    try:
        forms.submit(form, data)
    except forms.FormError as exc:
        # Re-show the errors plainly (a real generated site would style this).
        items = "".join(f"<li>{e}</li>" for e in exc.errors)
        return HttpResponse(
            f"<h1>Please check the form</h1><ul>{items}</ul><p><a href='javascript:history.back()'>Go back</a></p>",
            status=400,
        )
    if request.headers.get("Accept", "").startswith("application/json"):
        return HttpResponse('{"ok":true}', content_type="application/json")
    # Only redirect within this site — never to an attacker-supplied external URL.
    home = f"/sites/{subdomain}/"
    nxt = request.POST.get("_next") or ""
    safe = nxt if nxt.startswith(home) else home
    return HttpResponseRedirect(safe)


def _order_page_html(order, *, thanks: bool) -> str:
    """A public order-confirmation page. Shows the order's items and status but NOT
    the buyer's personal details (the reference URL is shareable)."""
    import html as _h
    rows = "".join(
        f"<tr><td>{it.quantity} × {_h.escape(it.name)}</td>"
        f"<td style='text-align:right'>{order.currency} {it.line_total_cents / 100:.2f}</td></tr>"
        for it in order.items.all()
    )
    totals = f"<tr><td>Subtotal</td><td style='text-align:right'>{order.subtotal_display}</td></tr>"
    if order.discount_cents:
        totals += (f"<tr><td>Discount</td><td style='text-align:right'>"
                   f"-{order.discount_display}</td></tr>")
    if order.tax_rate:
        totals += (f"<tr><td>{_h.escape(order.tax_rate.name)} ({order.tax_rate.rate_display})</td>"
                   f"<td style='text-align:right'>{order.tax_display}</td></tr>")
    if order.shipping_rate:
        totals += (f"<tr><td>Shipping ({_h.escape(order.shipping_rate.name)})</td>"
                   f"<td style='text-align:right'>{order.shipping_display}</td></tr>")
    totals += (f"<tr><td><strong>Total</strong></td><td style='text-align:right'>"
               f"<strong>{order.total_display}</strong></td></tr>")
    status_line = {
        "awaiting_payment": "Awaiting payment.",
        "paid": "Paid — thank you!",
        "pending": "Pending.",
        "refunded": "This order was refunded.",
        "cancelled": "This order was cancelled.",
        "failed": "Payment failed.",
    }.get(order.status, order.get_status_display())
    pay = order.payments.filter(status="pending").first()
    instructions = f"<p>{_h.escape(pay.detail)}</p>" if pay and order.status == "awaiting_payment" and pay.detail else ""
    heading = "Thank you for your order" if thanks else f"Order {_h.escape(order.reference)}"
    return _doc_page(
        f"Order {order.reference}",
        f"<h1>{heading}</h1>"
        f"<p>Reference: <strong>{_h.escape(order.reference)}</strong> — {_h.escape(status_line)}</p>"
        f"<table>{rows}{totals}</table>{instructions}"
        f"<p><a href='/sites/{_h.escape(order.website.subdomain)}/'>Back to the site</a></p>"
    )


def _doc_page(title: str, main: str) -> str:
    import html as _h
    from apps.publishing.storefront import STOREFRONT_CSS
    return (
        f"<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        f"<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>{_h.escape(title)}</title><style>{STOREFRONT_CSS}</style></head>"
        f"<body><div class=\"wrap\">{main}</div></body></html>"
    )


def order_status(request, subdomain, reference):
    """Public order-confirmation / status page, looked up by its reference."""
    from apps.publishing.models import Order
    order = Order.objects.filter(website__subdomain=subdomain, reference=reference).first()
    if order is None:
        raise Http404("Order not found.")
    return HttpResponse(_order_page_html(order, thanks=False))


@csrf_exempt
@require_POST
def checkout(request, subdomain):
    """Public checkout endpoint for a published store (spec §32).

    CSRF-exempt public endpoint (like the form endpoint): a static storefront posts
    product_id + quantity + customer details. Totals are computed server-side from
    real product prices; payment starts via the chosen provider (manual works; card
    gateways refuse until configured — no fake charge)."""
    from apps.publishing import ecommerce_service as shop
    from apps.publishing.payments import PaymentError
    website = Website.objects.filter(subdomain=subdomain).first()
    if website is None:
        raise Http404("No such site.")
    provider_key = request.POST.get("provider", "manual")
    # Multi-item cart: repeated `line` fields "<product_id>:<qty>". Falls back to a
    # single product_id/quantity (a direct "buy now").
    items = []
    for raw in request.POST.getlist("line"):
        pid, _, q = raw.partition(":")
        pid = pid.strip()
        if not pid:
            continue
        try:
            qty = max(1, int(q or 1))
        except ValueError:
            qty = 1
        items.append({"product_id": pid, "quantity": qty})
    if not items:
        try:
            qty = max(1, int(request.POST.get("quantity", "1")))
        except (TypeError, ValueError):
            qty = 1
        items = [{"product_id": request.POST.get("product_id"), "quantity": qty}]
    try:
        order = shop.create_order(
            website, items=items,
            customer_name=request.POST.get("name", ""),
            customer_email=request.POST.get("email", ""),
            code=request.POST.get("code", ""),
            shipping_rate_id=request.POST.get("shipping_rate", ""),
            shipping_address=request.POST.get("shipping_address", ""),
            channel="web",
        )
        result = shop.start_checkout(order, provider_key=provider_key)
    except (shop.EcommerceError, PaymentError) as exc:
        return HttpResponse(f"<h1>Checkout</h1><p>{exc}</p>", status=400)
    if request.headers.get("Accept", "").startswith("application/json"):
        return HttpResponse(
            '{"ok":true,"reference":"%s","url":"/sites/%s/order/%s"}'
            % (order.reference, subdomain, order.reference),
            content_type="application/json")
    if result.get("mode") == "manual" or result.get("mode") == "":
        # Show the order-confirmation page (also reachable at /sites/<sub>/order/<ref>).
        return HttpResponse(_order_page_html(order, thanks=True))
    return HttpResponseRedirect(result.get("redirect_url", f"/sites/{subdomain}/order/{order.reference}"))
