"""Governed route handlers for BT38 Stage 4 shutdown proof.

This module keeps the governed manual dry-run handler separate from legacy UI
routes. It only forwards requests to the single governed execution entry point;
it does not import marketplace adapters or services directly.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request


governed_bp = Blueprint("governed", __name__)


def _submit_governed_sku_dry_run(payload, actor):
    from governed_execution import submit_governed_marketplace_action

    governed_payload = dict(payload or {})
    governed_payload.setdefault("action", "push_inventory")

    return submit_governed_marketplace_action(
        governed_payload,
        actor=actor or "manual-governed-dry-run",
        approval={"approved": True, "source": "manual_sku_dry_run_route"},
        dry_run=True,
    )


@governed_bp.post("/governed/actions/sku/dry-run")
def governed_sku_dry_run():
    """Manual governed SKU dry-run trigger; never performs live execution."""
    result = _submit_governed_sku_dry_run(
        request.get_json(silent=True) or {},
        request.headers.get("X-Actor", "manual-governed-dry-run"),
    )
    return jsonify(result), 200
