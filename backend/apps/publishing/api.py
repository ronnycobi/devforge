"""Commerce API layer (UNIFIED COMMERCE PRINCIPLE, spec §32).

One engine, many experiences: Web, Android and iOS all consume THESE endpoints, which
delegate to the single commerce engine (apps.publishing.ecommerce_service) and the
one order/inventory database. No channel has its own commerce logic or data — a sale
on any channel is immediately reflected on all of them because they read/write the
same source of truth.

Public storefront surface (what a shopper's app calls), scoped by store subdomain:
  GET  /api/v1/stores/<sub>/products
  GET  /api/v1/stores/<sub>/products/<slug>
  POST /api/v1/stores/<sub>/checkout
  GET  /api/v1/stores/<sub>/orders/<reference>
The caller declares its channel (web/android/ios/…) so one admin sees every order's
origin. Card payment stays gated; manual works — no fake charges.
"""
from __future__ import annotations

from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.publishing import ecommerce_service as shop
from apps.publishing.models import Order, Website
from apps.publishing.payments import PaymentError


def _get_store(subdomain):
    return Website.objects.filter(subdomain=subdomain).first()


def _product_json(p):
    return {
        "slug": p.slug, "name": p.name, "description": p.description,
        "price_cents": p.price_cents, "currency": p.currency,
        "in_stock": p.in_stock,
        "stock": p.stock if p.track_inventory else None,
        "image": (f"/sites/{p.website.subdomain}/{p.image.path}" if p.image else None),
    }


def _order_json(o):
    return {
        "reference": o.reference, "channel": o.channel, "status": o.status,
        "currency": o.currency, "subtotal_cents": o.subtotal_cents,
        "discount_cents": o.discount_cents, "tax_cents": o.tax_cents,
        "shipping_cents": o.shipping_cents, "total_cents": o.total_cents,
        "items": [{"name": it.name, "quantity": it.quantity,
                   "unit_price_cents": it.unit_price_cents} for it in o.items.all()],
    }


class ProductListView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, subdomain):
        store = _get_store(subdomain)
        if store is None:
            return Response({"detail": "No such store."}, status=404)
        products = store.products.filter(active=True)
        return Response({"products": [_product_json(p) for p in products]})


class ProductDetailView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, subdomain, slug):
        store = _get_store(subdomain)
        product = store.products.filter(slug=slug, active=True).first() if store else None
        if product is None:
            return Response({"detail": "Not found."}, status=404)
        return Response(_product_json(product))


class CheckoutView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, subdomain):
        store = _get_store(subdomain)
        if store is None:
            return Response({"detail": "No such store."}, status=404)
        data = request.data
        # Accept either [{product_id/slug, quantity}] items or a single product.
        items = []
        for row in data.get("items") or []:
            pid = row.get("product_id")
            if not pid and row.get("slug"):
                p = store.products.filter(slug=row["slug"], active=True).first()
                pid = p.id if p else None
            if pid:
                items.append({"product_id": pid, "quantity": row.get("quantity", 1)})
        channel = data.get("channel", "api")
        try:
            order = shop.create_order(
                store, items=items,
                customer_name=data.get("name", ""), customer_email=data.get("email", ""),
                code=data.get("code", ""), shipping_rate_id=data.get("shipping_rate", ""),
                shipping_address=data.get("shipping_address", ""), channel=channel,
            )
            result = shop.start_checkout(order, provider_key=data.get("provider", "manual"))
        except (shop.EcommerceError, PaymentError) as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response({"order": _order_json(order),
                         "payment": result,
                         "status_url": f"/api/v1/stores/{subdomain}/orders/{order.reference}"},
                        status=201)


class OrderStatusView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, subdomain, reference):
        order = Order.objects.filter(website__subdomain=subdomain, reference=reference).first()
        if order is None:
            return Response({"detail": "Order not found."}, status=404)
        return Response(_order_json(order))
