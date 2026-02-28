"""
Test fixture: payment-service.py

A payment processing function with multiple intentional resilience gaps,
designed to exercise the production-resilience-reviewer skill across
several failure lenses.

Known issues (for skill verification):
  - No timeout on Stripe HTTP call (Lens 3: Network & Latency)
  - No idempotency key on charge creation (Lens 5: Retry & Backpressure)
  - Bare except swallows all errors (Lens 6: Debuggability)
  - No metrics or structured logging (Lens 7: Observability)
  - No retry budget or circuit breaker (Lens 5)
"""

import requests


def charge_customer(customer_id: str, amount_cents: int) -> dict:
    try:
        response = requests.post(
            "https://api.stripe.com/v1/charges",
            auth=("sk_live_YOUR_KEY_HERE", ""),  # noqa: S106 — intentional for review fixture
            data={
                "amount": amount_cents,
                "currency": "usd",
                "customer": customer_id,
            },
        )
        return response.json()
    except Exception:
        return {"error": "payment failed"}
