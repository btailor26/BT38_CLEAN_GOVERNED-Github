from __future__ import annotations

from flask import Blueprint, jsonify, request
try:
    from flask_login import current_user
except Exception:
    current_user = None


governed_group_propagation_bp = Blueprint("governed_group_propagation", __name__)


@governed_group_propagation_bp.post("/governed/groups/<int:group_id>/propagate-quantity")
def governed_group_propagate_quantity(group_id: int):
    """Propagate group quantity through the one clear governed path.

    Locked rules:
    - Group resolution happens before propagation.
    - WarehouseStock.sellable_quantity is the authority.
    - Request body quantity must not override warehouse truth.
    - Route wrapper does not call marketplace execution directly.
    - WarehousePushCoordinator owns propagation and execution routing.
    """
    from warehouse_push_coordinator import WarehousePushCoordinator

    body = dict(request.get_json(silent=True) or {})
    coordinator = WarehousePushCoordinator(
        actor=_actor(),
        dry_run=bool(body.get("dry_run", False)),
    )
    result = coordinator.propagate_group_quantity(
        group_id=group_id,
        actor=_actor(),
        dry_run=bool(body.get("dry_run", False)),
        requested_quantity=body.get("quantity"),
    )
    status = 200 if result.get("ok") or result.get("success") or result.get("execution_blocked") else 400
    return jsonify(result), status


def _actor() -> str:
    try:
        if current_user and current_user.is_authenticated:
            return f"user:{current_user.id}"
    except Exception:
        pass
    return request.headers.get("X-Actor", "governed-group-propagation")
