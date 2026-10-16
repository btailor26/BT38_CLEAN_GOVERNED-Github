"""Isolated BT38-hosted Billing test checkout.

Creates only a GBP 1 Revolut hosted checkout when explicitly requested.
No BT38 marketplace writes, credits, background jobs or new machine.
"""
import os
import uuid
import requests
from flask import Blueprint, jsonify, redirect, render_template, request, url_for

billing_dash_test_bp = Blueprint("billing_dash_test", __name__)
REVOLUT_BASE = "https://merchant.revolut.com"


def _revolut_key():
    return (os.environ.get("REVOLUT_PRODUCTION_API_SECRET_KEY")
            or os.environ.get("REVOLUT_MERCHANT_SECRET_KEY") or "").strip()


@billing_dash_test_bp.get("/billing-dash-test")
def billing_dash_test():
    return render_template("billing_dash_test.html", checkout_available=bool(_revolut_key()))


@billing_dash_test_bp.get("/billing-dash-test/health")
def billing_dash_test_health():
    return jsonify(ok=True, page="billing-dash-test",
                   checkout_configured=bool(_revolut_key()),
                   payment_verification_enabled=False)


@billing_dash_test_bp.post("/billing-dash-test/checkout")
def billing_dash_test_checkout():
    key = _revolut_key()
    if not key:
        return render_template("billing_dash_test_result.html",
                               title="Checkout unavailable",
                               detail="Revolut Merchant API credentials are not configured."), 503
    reference = "bt38-billing-test-" + uuid.uuid4().hex
    payload = {
        "amount": 100,
        "currency": "GBP",
        "merchant_order_ext_ref": reference,
        "redirect_url": url_for("billing_dash_test.billing_dash_test_return",
                                _external=True, _scheme="https"),
    }
    headers = {
        "Authorization": "Bearer " + key,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Idempotency-Key": reference,
    }
    version = os.environ.get("REVOLUT_MERCHANT_API_VERSION", "").strip()
    if version:
        headers["Revolut-Api-Version"] = version
    try:
        response = requests.post(REVOLUT_BASE + "/api/orders", json=payload,
                                 headers=headers, timeout=(5, 20))
        response.raise_for_status()
        order = response.json()
    except (requests.RequestException, ValueError):
        return render_template("billing_dash_test_result.html",
                               title="Checkout could not start",
                               detail="Revolut did not accept the order. No payment has been confirmed."), 502
    checkout_url = order.get("checkout_url")
    if not isinstance(checkout_url, str) or not checkout_url.startswith(
            ("https://checkout.revolut.com/", "https://merchant.revolut.com/")):
        return render_template("billing_dash_test_result.html",
                               title="Checkout unavailable",
                               detail="Revolut did not return an approved checkout URL."), 502
    return redirect(checkout_url, code=303)


@billing_dash_test_bp.get("/billing-dash-test/return")
def billing_dash_test_return():
    return render_template("billing_dash_test_result.html",
                           title="Returned from Revolut",
                           detail="Payment is not verified. Check the Revolut Merchant dashboard for the actual transaction status.")
