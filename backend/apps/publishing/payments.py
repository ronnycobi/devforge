"""Payment provider abstraction (spec §24, §32).

One interface, many providers. The `manual` provider is REAL and works offline: it
records an order as awaiting a manual payment (EFT / bank transfer / invoice) that
the merchant later confirms — a legitimate payment method, not a fake charge. Card
gateways (Stripe, PayFast) are declared but report unavailable until their secret
key is configured in the environment AND a doc-verified integration exists; they
refuse rather than fabricate a successful charge (spec §50).

SECURITY: gateway secrets come from the environment only — never stored in the DB,
never returned to the frontend or an agent. This module reads key presence to decide
availability; it does not persist or expose the key.
"""
from __future__ import annotations

import os


class PaymentError(Exception):
    pass


class PaymentProvider:
    key = ""
    name = ""

    def is_available(self) -> bool:
        return False

    def start_checkout(self, order) -> dict:
        """Begin payment for an order. Returns {"mode","instructions"|"redirect_url"}.
        Raise PaymentError when the provider isn't configured."""
        raise NotImplementedError

    def refund(self, payment) -> None:
        raise PaymentError(f"{self.name} refunds are not available in this configuration.")


class ManualProvider(PaymentProvider):
    """Manual / off-platform payment (EFT, bank transfer, invoice). Real and offline-
    friendly: the order awaits payment until the merchant confirms it was received."""

    key = "manual"
    name = "Manual payment (EFT / invoice)"

    def is_available(self) -> bool:
        return True

    def start_checkout(self, order) -> dict:
        return {
            "mode": "manual",
            "instructions": (
                f"Order {order.reference} for {order.total_display} is recorded. "
                "Pay by EFT/bank transfer using the details the seller provides; the "
                "order is marked paid once the seller confirms your payment."
            ),
        }


class _GatewayProvider(PaymentProvider):
    """A card gateway that is inert until configured. Reads its secret from the env to
    decide availability; refuses to charge until a verified live integration exists."""

    env_var = ""

    def is_available(self) -> bool:
        return bool(os.environ.get(self.env_var))

    def start_checkout(self, order):
        if not self.is_available():
            raise PaymentError(
                f"{self.name} is not configured ({self.env_var} not set). "
                "Card payments are unavailable until the gateway is connected."
            )
        # A key is present, but the live API call needs the gateway SDK and a
        # doc-verified integration — not built here, so we refuse rather than
        # fabricate a charge or a redirect that doesn't work.
        raise PaymentError(
            f"{self.name} credentials are present, but the live {self.name} integration "
            "is not enabled in this build yet. Use manual payment, or complete the "
            f"{self.name} integration before taking card payments."
        )


class StripeProvider(_GatewayProvider):
    key = "stripe"
    name = "Stripe"
    env_var = "STRIPE_SECRET_KEY"


class PayFastProvider(_GatewayProvider):
    key = "payfast"
    name = "PayFast"
    env_var = "PAYFAST_MERCHANT_KEY"


_PROVIDERS: dict[str, PaymentProvider] = {
    p.key: p for p in (ManualProvider(), StripeProvider(), PayFastProvider())
}


def get_provider(key: str) -> PaymentProvider | None:
    return _PROVIDERS.get(key)


def provider_status() -> list[dict]:
    return [{"key": p.key, "name": p.name, "available": p.is_available()} for p in _PROVIDERS.values()]


def available_providers() -> list[PaymentProvider]:
    return [p for p in _PROVIDERS.values() if p.is_available()]
