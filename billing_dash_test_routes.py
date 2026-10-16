"""BT38-hosted, read-only Billing dashboard test.

No payment provider calls, DB writes, background jobs, or new machines.
Billing's actual payment implementation remains in btailor26/billing.
"""
from flask import Blueprint, jsonify, render_template

billing_dash_test_bp = Blueprint("billing_dash_test", __name__)


@billing_dash_test_bp.get("/billing-dash-test")
def billing_dash_test():
    return render_template("billing_dash_test.html")


@billing_dash_test_bp.get("/billing-dash-test/health")
def billing_dash_test_health():
    return jsonify(ok=True, page="billing-dash-test", payments_enabled=False)
