from flask import request, render_template
from types import SimpleNamespace
from extensions import db
from models import WarehouseStock

def build_product_linking():
    q = (request.args.get("q") or request.args.get("search") or "").strip()

    query = db.session.query(WarehouseStock).filter(
        WarehouseStock.is_active == True
    )

    if q:
        term = f"%{q}%"
        query = query.filter(
            (WarehouseStock.sku.ilike(term)) |
            (WarehouseStock.product_name.ilike(term))
        )

    rows = query.limit(300).all()

    items = []

    for s in rows:
        qty = int(getattr(s, "sellable_quantity", 0) or 0)

        items.append(SimpleNamespace(
            id=s.id,
            sku=s.sku,
            name=s.product_name or s.sku,
            qty=qty,
            group_id=getattr(s, "master_product_group_id", None),
        ))

    return {
        "items": items,
        "total": len(items),
    }
