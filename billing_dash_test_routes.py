"""Isolated BT38-hosted Billing test checkout.

Creates only a GBP 1 Revolut hosted checkout when explicitly requested.
No BT38 marketplace writes, credits, background jobs or new machine.
"""
import os
import uuid
import requests
from flask import Blueprint, jsonify, redirect, render_template, session, url_for

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
                   payment_verification_enabled=True)


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
    order_id = order.get("id")\n    if not isinstance(order_id, str) or not order_id:\n        return render_template("billing_dash_test_result.html",\n                               title="Checkout unavailable",\n                               detail="Revolut returned no order ID for verification."), 502\n    session["billing_dash_test_order_id"] = order_id\n    session["billing_dash_test_order_reference"] = reference\n    return redirect(checkout_url, code=303)


@billing_dash_test_bp.get("/billing-dash-test/return")
def billing_dash_test_return():
    """Read the server-side Revolut order, never trust redirect parameters."""
    order_id = session.get("billing_dash_test_order_id")
    expected_ref = session.get("billing_dash_test_order_reference")
    if not order_id or not expected_ref:
        return render_template(
            "billing_dash_test_result.html",
            title="Payment status unavailable",
            detail="No order is linked to this browser session. Check Revolut Merchant for the payment result.")
    key = _revolut_key()
    if not key:
        return render_template("billing_dash_test_result.html",
                               title="Verification unavailable",
                               detail="Revolut credentials are unavailable."), 503
    headers = {"Authorization": "Bearer " + key, "Accept": "application/json"}
    version = os.environ.get("REVOLUT_MERCHANT_API_VERSION", "").strip()
    if version:
        headers["Revolut-Api-Version"] = version
    try:
        response = requests.get(
            REVOLUT_BASE + "/api/orders/" + order_id,
            headers=headers, timeout=(5, 20))
        response.raise_for_status()
        order = response.json()
        if not isinstance(order, dict):
            raise ValueError("Invalid provider response")
    except (requests.RequestException, ValueError):
        return render_template("billing_dash_test_result.html",
                               title="Verification unavailable",
                               detail="Unable to retrieve this order from Revolut. Check your Merchant dashboard."), 502

    if (order.get("id") != order_id
            or order.get("merchant_order_ext_ref") != expected_ref
            or order.get("currency") != "GBP"
            or order.get("amount") != 100):
        return render_template("billing_dash_test_result.html",
                               title="Payment not verified",
                               detail="The Revolut order does not match this £1 test. Do not treat it as paid."), 409

    state = str(order.get("state", "")).lower()
    if state == "completed":
        title = "£1 payment completed"
        detail = "Revolut confirms this order is completed. No credits have been issued."
    elif state in ("pending", "processing", "authorised", "authorized"):
        title = "Payment pending"
        detail = "Revolut has not confirmed completion. Check again shortly."
    elif state in ("failed", "cancelled", "canceled"):
        title = "Payment not completed"
        detail = "Revolut reports that this payment was " + state + "."
    else:
        title = "Payment not yet verified"
        detail = "Revolut returned status: " + (state or "unknown") + "."
    return render_template("billing_dash_test_result.html",
                           title=title, detail=detail)
