"""Naplata. Stripe Checkout (jednokratno placanje za 1 mjesec) preko REST-a, bez Stripe paketa.

Env: STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET. Bez njih je naplata iskljucena (billing_enabled=False),
a planove admin moze dodijeliti rucno. Drugi pruzalac (Paddle, Lemon Squeezy, PayPal...) samo treba
pozvati Store.activate_plan(...) iz svog webhooka -- ostatak aplikacije se ne mijenja.
"""
import hashlib
import hmac
import json
import os
import time

import requests

from .auth import PLANS, PAID_PLANS

STRIPE_API = "https://api.stripe.com/v1"


def enabled() -> bool:
    return bool(os.getenv("STRIPE_SECRET_KEY"))


def create_checkout(user: dict, plan: str, base_url: str) -> str:
    """Vraca URL Stripe Checkout stranice. Baca RuntimeError uz poruku za korisnika."""
    if plan not in PAID_PLANS:
        raise ValueError("unknown plan")
    key = os.getenv("STRIPE_SECRET_KEY", "")
    if not key:
        raise RuntimeError("Online payments are not enabled yet.")
    p = PLANS[plan]
    data = {
        "mode": "payment",
        "success_url": f"{base_url}/account?checkout=success",
        "cancel_url": f"{base_url}/account?checkout=cancel",
        "client_reference_id": str(user["id"]),
        "line_items[0][quantity]": "1",
        "line_items[0][price_data][currency]": "eur",
        "line_items[0][price_data][unit_amount]": str(p["price_cents"]),
        "line_items[0][price_data][product_data][name]": f"HOOPEDGE {p['label']} - 1 month",
        "metadata[plan]": plan,
        "metadata[user_id]": str(user["id"]),
    }
    if user.get("email"):
        data["customer_email"] = user["email"]
    r = requests.post(f"{STRIPE_API}/checkout/sessions", data=data, auth=(key, ""), timeout=15)
    if r.status_code >= 400:
        raise RuntimeError("Payment provider error. Please try again later.")
    return r.json()["url"]


def verify_signature(payload: bytes, header: str, secret: str, tolerance: int = 300, now=None) -> bool:
    """Stripe-Signature: t=timestamp,v1=hmac_sha256(secret, f'{t}.{payload}')."""
    try:
        parts = dict(kv.split("=", 1) for kv in header.split(","))
        ts = int(parts["t"])
        sigs = [v for k, v in (kv.split("=", 1) for kv in header.split(",")) if k == "v1"]
    except Exception:
        return False
    if abs((now or time.time()) - ts) > tolerance:
        return False
    expected = hmac.new(secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, s) for s in sigs)


def handle_event(store, event: dict):
    """Obradi Stripe event. Vraca opis ishoda (za log). Idempotentno po Checkout session id-u."""
    if event.get("type") not in ("checkout.session.completed", "checkout.session.async_payment_succeeded"):
        return "ignored"
    s = (event.get("data") or {}).get("object") or {}
    if s.get("payment_status") != "paid":
        return "not paid"
    meta = s.get("metadata") or {}
    plan = meta.get("plan")
    try:
        uid = int(meta.get("user_id") or s.get("client_reference_id"))
    except Exception:
        return "no user"
    if plan not in PAID_PLANS or (s.get("currency") or "").lower() != "eur" or int(s.get("amount_total") or -1) != PLANS[plan]["price_cents"]:
        return "amount/plan mismatch"
    res = store.activate_plan(uid, plan, provider="stripe", ref=s.get("id"), amount_cents=s.get("amount_total"))
    return "activated" if res else "duplicate"
