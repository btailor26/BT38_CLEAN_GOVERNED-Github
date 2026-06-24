"""BT38 governed group resolution bridge (CLEAN BUILD)."""

from __future__ import annotations
from typing import Iterable, List, Any


def resolve_group_id(stock_row) -> int | None:
    if not stock_row:
        return None

    group_id = getattr(stock_row, "master_product_group_id", None)
    if group_id:
        return int(group_id)

    stock_id = getattr(stock_row, "id", None)
    return int(stock_id) if stock_id is not None else None


def get_full_group_stock(group_id: int) -> list:
    from extensions import db
    from models import WarehouseStock

    group_id = int(group_id)

    rows = (
        db.session.query(WarehouseStock)
        .filter(WarehouseStock.is_active == True)
        .filter(
            (WarehouseStock.master_product_group_id == group_id)
            | (WarehouseStock.id == group_id)
        )
        .all()
    )

    seen = {}
    for r in rows:
        if getattr(r, "id", None):
            seen[int(r.id)] = r

    return list(seen.values())


def normalize_push_group(stock_rows: Iterable[Any]) -> List[Any]:
    rows = [r for r in stock_rows if r is not None]
    if not rows:
        return []

    resolved = [resolve_group_id(r) for r in rows]
    group_id = next((g for g in resolved if g), None)

    rows.sort(key=lambda r: (
        str(getattr(r, "sku", "") or ""),
        int(getattr(r, "id", 0) or 0),
    ))

    master_seen = False

    for r in rows:
        gid = resolve_group_id(r) or group_id
        setattr(r, "resolved_group_id", gid)

        is_master = bool(gid and getattr(r, "id", None) == gid)

        if not is_master and not master_seen:
            is_master = True

        setattr(r, "is_group_master", is_master)
        master_seen = master_seen or is_master

    rows.sort(key=lambda r: (
        not bool(getattr(r, "is_group_master", False)),
        str(getattr(r, "sku", "") or ""),
        int(getattr(r, "id", 0) or 0),
    ))

    return rows
