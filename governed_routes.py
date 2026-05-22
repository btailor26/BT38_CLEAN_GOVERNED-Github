from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
import json

from flask import Blueprint, jsonify, request, render_template, redirect, url_for
try:
    from flask_login import current_user
except Exception:
    current_user = None

governed_bp = Blueprint("governed", __name__)

@governed_bp.get("/")
def governed_root_page():
    return redirect("/dashboard")



@governed_bp.get("/dashboard")
def governed_dashboard_page():

    class MockStats:
        total_items = 0
        total_groups = 0
        total_marketplaces = 0
        total_stores = 0
        low_stock_count = 0
        low_stock_items = 0
        out_of_stock_count = 0
        failed_syncs = 0
        successful_syncs = 0
        pending_syncs = 0
        success_rate = 100
        total_value = 0

    return render_template(
        "dashboard.html",
        stats=MockStats(),
        recent_items=[],
        recent_syncs=[]
    )


@governed_bp.get("/stores")
def governed_stores_page():
    from models import Store

    stores = Store.query.order_by(Store.id).all()
    return render_template("stores.html", stores=stores)


@governed_bp.post("/governed/stores/<int:store_id>/toggle")
def governed_store_toggle(store_id):
    from extensions import db
    from models import Store

    store = Store.query.get_or_404(store_id)
    body = request.get_json(silent=True) or {}
    store.is_active = bool(body.get("is_active"))
    db.session.commit()

    return jsonify({
        "ok": True,
        "success": True,
        "store_id": store.id,
        "is_active": store.is_active,
        "message": "Store active state updated through governed path."
    })


@governed_bp.post("/governed/stores/<int:store_id>/sync-preview")
def governed_store_sync_preview(store_id):
    from models import Store

    store = Store.query.get_or_404(store_id)
    return jsonify({
        "ok": True,
        "success": True,
        "store_id": store.id,
        "store_name": store.name,
        "platform": store.platform,
        "message": "Preview only. No marketplace sync was executed.",
        "governed": True
    })


@governed_bp.post("/governed/stores/<int:store_id>/delete-preview")
def governed_store_delete_preview(store_id):
    from models import Store

    store = Store.query.get_or_404(store_id)
    return jsonify({
        "ok": False,
        "success": False,
        "store_id": store.id,
        "store_name": store.name,
        "message": "Store deletion is disabled in governed mode until delete rules are approved.",
        "governed": True
    })


@governed_bp.get("/governed/stores/amazon/setup-preview")
def governed_amazon_setup_preview():
    return jsonify({
        "ok": True,
        "success": True,
        "message": "Amazon setup preview only. Live credential setup is not wired through old routes.",
        "governed": True
    })


@governed_bp.get("/settings")
def governed_settings_page():
    from flask import render_template
    from models import Store, SystemConfig

    default_config = {
        "push_enabled": "false",
        "runtime_push_enabled": "false",
        "marketplace_push_enabled": "false",
        "import_enabled": "false",
        "runtime_import_enabled": "false",
        "marketplace_import_enabled": "false",
        "sync_enabled": "false",
        "runtime_sync_enabled": "false",
        "marketplace_sync_enabled": "false",
        "manual_push_enabled": "false",
        "manual_import_enabled": "false",
        "manual_sync_enabled": "false",
        "quantity_push_enabled": "false",
        "price_push_enabled": "false",
        "group_push_enabled": "false",
        "bulk_push_enabled": "false",
        "read_only_mode": "false",
        "dry_run_mode": "false",
        "queue_frozen": "false",
        "scheduler_enabled": "false",
        "sync_worker_enabled": "false",
        "push_worker_enabled": "false",
        "retry_queue_enabled": "false",
        "reconcile_15m_enabled": "false",
        "webhook_worker_enabled": "false",
        "webhook_ebay_enabled": "false",
        "webhook_amazon_enabled": "false",
        "default_push_frequency_minutes": "15",
        "default_batch_size": "25",
        "default_retry_attempts": "3",
        "api_rate_limit_buffer": "0.8",
        "error_rate_threshold": "0.3",
    }

    config = dict(default_config)

    rows = SystemConfig.query.filter(
        SystemConfig.key.in_(list(default_config.keys()))
    ).all()

    for row in rows:
        config[row.key] = str(row.value)

    class Stats:
        failed_24h = 0
        failed_syncs = 0
        success_rate = 100

    stores = Store.query.order_by(Store.id).all()

    return render_template(
        "settings.html",
        config=config,
        stores=stores,
        stats=Stats(),
    )


@governed_bp.get("/listings")
def governed_listings_page():
    return render_template(
        "listings.html",
        listings=[],
        groups=[],
        stats={},
        filtered_count=0,
        total_listings=0,
        active_listings=0,
        blocked_listings=0,
        current_search="",
        current_platform_filter="",
        current_store_filter="",
        current_status_filter="",
        all_stores=[]
    )


@governed_bp.get("/groups")
def governed_groups_page():
    return render_template("groups.html")


@governed_bp.get("/product-linking")
def governed_product_linking_page():
    return render_template(
        "product_linking.html",
        warehouse_products=[],
        unlinked_listings=[],
        unlinked_by_platform={},
        all_marketplace_listings=[],
        all_stores=[],
        current_search="",
        current_platform="all",
        current_store="all",
        current_show_linked="all"
    )


@governed_bp.get("/inventory")
def governed_inventory_page():
    return render_template("inventory.html")



@governed_bp.route("/login", methods=["GET", "POST"])
def login():
    from datetime import datetime
    from flask_login import login_user
    from extensions import db
    from models import User

    requested_next = request.args.get("next") or request.form.get("next") or ""
    if requested_next.startswith("/") and not requested_next.startswith("//") and "\\" not in requested_next:
        next_url = requested_next
    else:
        next_url = url_for("governed.governed_warehouse_page")

    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""

        user = (
            db.session.query(User)
            .filter((User.email == username) | (User.username == username))
            .first()
        )

        if user and user.is_active and user.check_password(password):
            user.last_login = datetime.utcnow()
            db.session.commit()
            login_user(user, remember=True)
            return redirect(next_url)

        error = "Invalid login details or inactive user."
    else:
        error = ""

    return render_template(
        "login.html",
        error=error,
        next_url=next_url,
    )


@governed_bp.get("/shutdown-proof/status")
def shutdown_proof_status():
    return jsonify({
        "success": True,
        "ok": True,
        "shutdown_mode": True,
        "old_marketplace_routes_present": False,
    })


@governed_bp.get("/warehouse")
def governed_warehouse_page():
    """Governed Master Stock UI.

    Speed-safe route:
    - no marketplace execution
    - no old routes
    - eager-loads relationships to avoid N+1 queries
    - limits initial render size
    """
    from extensions import db
    from models import MarketplaceListing, WarehouseStock, Store
    from sqlalchemy import or_
    from sqlalchemy.orm import joinedload

    q = (request.args.get("q") or "").strip().lower()
    view = (request.args.get("view") or "all").strip().lower()

    try:
        row_limit = int(request.args.get("per_page") or 15)
    except Exception:
        row_limit = 15

    if row_limit not in (15, 25, 50, 100):
        row_limit = 15

    listing_query = (
        db.session.query(MarketplaceListing)
        .options(
            joinedload(MarketplaceListing.store),
            joinedload(MarketplaceListing.warehouse_stock),
        )
        .filter(MarketplaceListing.is_active == True)  # noqa: E712
    )

    if q:
        like = f"%{q}%"
        listing_query = listing_query.filter(
            or_(
                MarketplaceListing.external_sku.ilike(like),
                MarketplaceListing.title.ilike(like),
                MarketplaceListing.external_listing_id.ilike(like),
                MarketplaceListing.asin.ilike(like),
                MarketplaceListing.fnsku.ilike(like),
                MarketplaceListing.barcode.ilike(like),
            )
        )

    marketplace_filter = (request.args.get("marketplace") or "").strip().lower()
    status_filter = (request.args.get("status") or "").strip().lower()
    group_filter = (request.args.get("group") or "").strip().lower()
    listing_status_filter = (request.args.get("listing_status") or "").strip().lower()

    if marketplace_filter and marketplace_filter != "all":
        listing_query = listing_query.join(Store, MarketplaceListing.store_id == Store.id).filter(
            Store.platform.ilike(f"%{marketplace_filter}%")
        )

    if status_filter and status_filter != "all":
        listing_query = listing_query.filter(MarketplaceListing.status.ilike(f"%{status_filter}%"))

    if group_filter == "grouped":
        listing_query = listing_query.filter(MarketplaceListing.master_product_group_id.isnot(None))
    elif group_filter == "ungrouped":
        listing_query = listing_query.filter(MarketplaceListing.master_product_group_id.is_(None))

    if listing_status_filter == "linked":
        listing_query = listing_query.filter(MarketplaceListing.warehouse_stock_id.isnot(None))
    elif listing_status_filter == "unlinked":
        listing_query = listing_query.filter(MarketplaceListing.warehouse_stock_id.is_(None))

    listing_rows = (
        listing_query
        .order_by(MarketplaceListing.updated_at.desc(), MarketplaceListing.id.desc())
        .limit(row_limit)
        .all()
    )

    rows = []
    linked_stock_ids = set()

    for listing in listing_rows:
        stock = listing.warehouse_stock
        if stock:
            linked_stock_ids.add(stock.id)

        platform = (listing.store.platform if listing.store else "Marketplace") or "Marketplace"
        platform_lower = platform.lower()
        channel = (listing.normalized_amazon_fulfillment_channel or "").upper()
        is_amazon = "amazon" in platform_lower
        is_fbm = is_amazon and channel in ("MFN", "FBM", "MERCHANT")
        is_fba = is_amazon and not is_fbm
        location = f"{platform} {'FBA' if is_fba else 'FBM'}" if is_amazon else platform

        rows.append(SimpleNamespace(
            id=stock.id if stock else 0,
            inventory_item_id=None,
            item_id=None,
            marketplace_listing_id=listing.id,
            sku=(stock.sku if stock else listing.external_sku) or "",
            master_product_group_id=listing.master_product_group_id or (stock.master_product_group_id if stock else None),
            location=location,
            image_url=stock.image_url if stock else None,
            product_name=(stock.product_name if stock else None) or listing.title,
            title=listing.title,
            group_title=stock.group_title if stock else None,
            barcode=listing.fnsku or listing.barcode or (stock.barcode if stock else None),
            mcf_group_source=bool(is_fba),
            is_fba=bool(is_fba),
            is_fbm=bool(is_fbm),
            is_group_controlled=bool(stock.is_group_controlled) if stock else False,
            available_quantity=stock.sellable_quantity if stock else 0,
            price=listing.price or 0,
            store_name=listing.store.name if listing.store else platform,
            platform=platform,
            external_listing_id=listing.external_listing_id,
            external_sku=listing.external_sku,
            asin=listing.asin,
            fnsku=listing.fnsku,
        ))

    if len(rows) < row_limit:
        stock_query = (
            db.session.query(WarehouseStock)
            .options(joinedload(WarehouseStock.warehouse))
            .filter(WarehouseStock.is_active == True)  # noqa: E712
            .filter(WarehouseStock.is_deleted == False)  # noqa: E712
        )

        if q:
            like = f"%{q}%"
            stock_query = stock_query.filter(
                or_(
                    WarehouseStock.sku.ilike(like),
                    WarehouseStock.product_name.ilike(like),
                    WarehouseStock.barcode.ilike(like),
                    WarehouseStock.group_title.ilike(like),
                )
            )

        unlinked_stock = (
            stock_query
            .order_by(WarehouseStock.updated_at.desc(), WarehouseStock.id.desc())
            .limit(row_limit)
            .all()
        )

        for stock in unlinked_stock:
            if stock.id in linked_stock_ids:
                continue

            rows.append(SimpleNamespace(
                id=stock.id,
                inventory_item_id=None,
                item_id=None,
                marketplace_listing_id=None,
                sku=stock.sku,
                master_product_group_id=stock.master_product_group_id,
                location="Warehouse",
                image_url=stock.image_url,
                product_name=stock.product_name,
                title=stock.product_name,
                group_title=stock.group_title,
                barcode=stock.barcode,
                mcf_group_source=False,
                is_fba=False,
                is_fbm=False,
                is_group_controlled=bool(stock.is_group_controlled),
                available_quantity=stock.sellable_quantity,
                price=0,
                store_name=stock.warehouse.name if stock.warehouse else "Warehouse",
                platform="Warehouse",
                external_listing_id=None,
                external_sku=None,
                asin=None,
                fnsku=None,
            ))

            if len(rows) >= row_limit:
                break

    if view == "available":
        rows = [row for row in rows if int(getattr(row, "available_quantity", 0) or 0) > 0]
    elif view == "low-stock":
        rows = [row for row in rows if int(getattr(row, "available_quantity", 0) or 0) <= 0]
    elif view == "listings":
        rows = [row for row in rows if getattr(row, "marketplace_listing_id", None)]
    elif view == "fba":
        rows = [row for row in rows if getattr(row, "is_fba", False)]
    elif view == "fbm":
        rows = [row for row in rows if getattr(row, "is_fbm", False)]
    elif view == "groups":
        rows = [row for row in rows if getattr(row, "master_product_group_id", None) or getattr(row, "is_group_controlled", False)]

    # Real database totals for the top information boxes.
    # Do not calculate these from the limited visible rows.
    active_stock_rows = (
        db.session.query(WarehouseStock)
        .filter(WarehouseStock.is_active == True)  # noqa: E712
        .filter(WarehouseStock.is_deleted == False)  # noqa: E712
        .all()
    )

    total_skus = len(active_stock_rows)
    total_available = sum(int(getattr(stock, "sellable_quantity", 0) or 0) for stock in active_stock_rows)
    low_stock_count = sum(1 for stock in active_stock_rows if int(getattr(stock, "sellable_quantity", 0) or 0) <= 0)

    listing_count = (
        db.session.query(MarketplaceListing)
        .filter(MarketplaceListing.is_active == True)  # noqa: E712
        .count()
    )

    inventory_value = 0.0
    for row in rows:
        try:
            inventory_value += float(getattr(row, "price", 0) or 0) * int(getattr(row, "available_quantity", 0) or 0)
        except Exception:
            pass

    stats = SimpleNamespace(
        total_skus=total_skus,
        total_available=total_available,
        low_stock_count=low_stock_count,
        listing_count=listing_count,
        inventory_value=round(float(inventory_value), 2),
    )

    warehouse_items = SimpleNamespace(items=rows, total=len(rows))

    html = render_template(
        "warehouse.html",
        warehouse_items=warehouse_items,
        stats=stats,
        search_query=q,
        active_view=view,
    )
    return _patch_warehouse_phase1_ui(html, stats, q, view)


@governed_bp.post("/governed/actions/sku/dry-run")
def governed_sku_dry_run():
    from governed_execution import submit_governed_marketplace_action

    governed_payload = dict(request.get_json(silent=True) or {})
    governed_payload.setdefault("action", "push_inventory")

    result = submit_governed_marketplace_action(
        governed_payload,
        actor=request.headers.get("X-Actor", "manual-governed-dry-run"),
        approval={"approved": True, "source": "manual_sku_dry_run_route"},
        dry_run=True,
    )
    return jsonify(result), 200


@governed_bp.post("/governed/actions/listings/<int:listing_id>/push")
def governed_listing_push(listing_id: int):
    body = dict(request.get_json(silent=True) or {})
    result = _push_one_listing(
        listing_id=listing_id,
        quantity=body.get("quantity"),
        actor=_actor(),
        source="ui_listing_button",
    )
    return jsonify(result), 200 if result.get("ok") else 400


@governed_bp.post("/governed/actions/groups/<int:group_id>/push")
def governed_group_push(group_id: int):
    from extensions import db
    from models import MarketplaceListing

    body = dict(request.get_json(silent=True) or {})
    listings = (
        db.session.query(MarketplaceListing)
        .filter(MarketplaceListing.master_product_group_id == group_id)
        .filter(MarketplaceListing.is_active == True)  # noqa: E712
        .order_by(MarketplaceListing.id)
        .all()
    )
    results = [
        _push_one_listing(
            listing_id=listing.id,
            quantity=body.get("quantity"),
            actor=_actor(),
            source="ui_group_button",
        )
        for listing in listings
    ]
    ok_count = sum(1 for item in results if item.get("ok"))
    return jsonify({
        "success": ok_count == len(results) and bool(results),
        "ok": ok_count == len(results) and bool(results),
        "governed": True,
        "group_id": group_id,
        "total": len(results),
        "ok_count": ok_count,
        "results": results,
    }), 200


@governed_bp.get("/governed/actions/history")
def governed_action_history():
    from extensions import db
    from models import SyncLog

    limit = min(int(request.args.get("limit", 50)), 200)
    query = db.session.query(SyncLog).filter(
        SyncLog.message.contains("governed_push")
    )
    listing_id = request.args.get("listing_id")
    if listing_id:
        query = query.filter(SyncLog.message.contains(f"listing_id={listing_id}"))
    rows = query.order_by(SyncLog.created_at.desc()).limit(limit).all()
    return jsonify({
        "success": True,
        "ok": True,
        "history": [
            {
                "id": row.id,
                "store_id": row.store_id,
                "status": row.status,
                "message": row.message,
                "items_synced": row.items_synced,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ],
    })


def _push_one_listing(*, listing_id: int, quantity, actor: str, source: str) -> dict:
    from extensions import db
    from governed_execution import AMAZON_FBM_LIVE_APPROVAL_TYPE, submit_governed_marketplace_action
    from models import MarketplaceListing, SyncLog

    listing = db.session.get(MarketplaceListing, listing_id)
    if not listing:
        return _blocked(f"Marketplace listing {listing_id} was not found.", listing_id=listing_id)
    if not listing.store:
        return _blocked("Marketplace listing has no store.", listing_id=listing_id)
    if not listing.warehouse_stock:
        return _blocked("Marketplace listing is not linked to warehouse stock.", listing_id=listing_id)

    platform = (listing.store.platform or "").strip().lower()
    marketplace = "amazon" if "amazon" in platform else "ebay" if "ebay" in platform else platform
    try:
        push_quantity = listing.effective_quantity if quantity is None else int(quantity)
    except (TypeError, ValueError):
        return _blocked("Quantity must be an integer.", listing_id=listing_id, quantity=quantity)
    sku = (listing.external_sku or listing.warehouse_stock.sku or "").strip()

    payload = {
        "marketplace": marketplace,
        "action": "push_inventory",
        "sku": sku,
        "store_id": listing.store_id,
        "listing_id": listing.id,
        "quantity": push_quantity,
        "amazon_fulfillment_channel": listing.amazon_fulfillment_channel or "MFN",
        "source": source,
    }
    approval = {
        "approved": True,
        "approval_type": AMAZON_FBM_LIVE_APPROVAL_TYPE,
        "source": source,
        "approved_by": actor,
        "approved_at": datetime.utcnow().isoformat(),
        "scope": {
            "sku": sku,
            "store_id": listing.store_id,
            "listing_id": listing.id,
            "quantity": push_quantity,
        },
    }

    result = submit_governed_marketplace_action(
        payload,
        actor=actor,
        approval=approval,
        dry_run=False,
    )

    ok = bool(result.get("ok") or result.get("success"))
    listing.last_push_at = datetime.utcnow()
    listing.last_push_quantity = push_quantity if ok else listing.last_push_quantity
    listing.last_push_status = "success" if ok else "error"
    listing.last_push_error = None if ok else str(result.get("reason") or result.get("failure_reason") or result)[:1000]
    listing.push_attempts = 0 if ok else (listing.push_attempts or 0) + 1
    listing.consecutive_failures = 0 if ok else (listing.consecutive_failures or 0) + 1

    db.session.add(SyncLog(
        store_id=listing.store_id,
        status="success" if ok else "error",
        message=(
            f"governed_push listing_id={listing.id} sku={sku} "
            f"marketplace={marketplace} source={source} ok={ok}"
        )[:500],
        items_synced=1 if ok else 0,
        created_at=datetime.utcnow(),
    ))
    db.session.commit()

    result.update({
        "ui_action_wired": True,
        "grouping_layer_ready": True,
        "audit_history_logged": True,
        "listing_last_push_updated": True,
    })
    return result


def _actor() -> str:
    try:
        if current_user and current_user.is_authenticated:
            return f"user:{current_user.id}"
    except Exception:
        pass
    return request.headers.get("X-Actor", "governed-ui-action")


def _blocked(reason: str, **extra) -> dict:
    result = {
        "success": False,
        "ok": False,
        "governed": True,
        "execution_blocked": True,
        "reason": reason,
    }
    result.update(extra)
    return result


def _patch_warehouse_phase1_ui(html: str, stats, search_query: str, active_view: str) -> str:
    """Safely wire existing warehouse.html without replacing the finished template.

    This keeps the approved layout intact and adds only runtime behavior:
    search, KPI filters, tab filters, and real dynamic KPI values.
    """
    listing_count = f"{int(getattr(stats, 'listing_count', 0) or 0):,}"
    inventory_value = f"£{float(getattr(stats, 'inventory_value', 0) or 0):,.0f}"
    html = html.replace("<strong>1,156</strong>", f"<strong>{listing_count}</strong>")
    html = html.replace("<strong>£183k</strong>", f"<strong>{inventory_value}</strong>")

    payload = {
        "searchQuery": search_query or "",
        "activeView": active_view or "all",
    }
    script = f"""
<script id="bt38Phase1WarehouseWiring">
(function() {{
  const state = {json.dumps(payload)};

  function go(view, extra) {{
    const url = new URL(window.location.href);
    if (view && view !== 'all') url.searchParams.set('view', view);
    else url.searchParams.delete('view');
    if (extra && Object.prototype.hasOwnProperty.call(extra, 'q')) {{
      const q = String(extra.q || '').trim();
      if (q) url.searchParams.set('q', q);
      else url.searchParams.delete('q');
    }}
    window.location.href = url.pathname + (url.search ? url.search : '');
  }}

  function wireSearch() {{
    const input = document.querySelector('.bt38-search-wrap input');
    if (!input) return;
    input.value = state.searchQuery || '';
    input.setAttribute('name', 'q');
    input.setAttribute('aria-label', 'Search SKU, product, ASIN, FNSKU or barcode');
    input.addEventListener('keydown', function(e) {{
      if (e.key === 'Enter') go(state.activeView || 'all', {{ q: input.value }});
    }});
  }}

  function makeClickable(el, title, fn) {{
    if (!el) return;
    el.setAttribute('role', 'button');
    el.setAttribute('tabindex', '0');
    el.style.cursor = 'pointer';
    if (title) el.setAttribute('title', title);
    el.addEventListener('click', fn);
    el.addEventListener('keydown', function(e) {{
      if (e.key === 'Enter' || e.key === ' ') {{ e.preventDefault(); fn(); }}
    }});
  }}

  function wireKpis() {{
    const cards = Array.from(document.querySelectorAll('.bt38-kpi-card'));
    makeClickable(cards[0], 'Show all SKUs', () => go('all'));
    makeClickable(cards[1], 'Show available stock', () => go('available'));
    makeClickable(cards[2], 'Show low stock', () => go('low-stock'));
    makeClickable(cards[3], 'Open system activity', () => {{ window.location.href = '/admin/system-activity'; }});
    makeClickable(cards[4], 'Show marketplace listings', () => go('listings'));
    makeClickable(cards[5], 'Show available stock value', () => go('available'));
  }}

  function wireTabs() {{
    const buttons = Array.from(document.querySelectorAll('.bt38-operational-tabs button'));
    const map = {{
      'Master Stock': () => go('all'),
      'FBA Read Only': () => go('fba'),
      'Group View': () => go('groups'),
      'Listings': () => go('listings'),
      'Orders': () => alert('Orders view will be wired after Master Stock runtime is proven.'),
      'Stock Transfer': () => alert('Stock Transfer will be wired after quantity and grouping are proven.')
    }};
    buttons.forEach(btn => {{
      const text = (btn.textContent || '').trim();
      if (map[text]) makeClickable(btn, text, map[text]);
      btn.classList.remove('active');
      if ((state.activeView === 'all' && text === 'Master Stock') ||
          (state.activeView === 'fba' && text === 'FBA Read Only') ||
          (state.activeView === 'groups' && text === 'Group View') ||
          (state.activeView === 'listings' && text === 'Listings')) {{
        btn.classList.add('active');
      }}
    }});
  }}

  function applyRuntimeState(row, state) {{
    if (!row || !state) return;

    row.dataset.runtimeRole = state.runtime_role || '';
    row.dataset.actionState = state.action_state || '';
    row.dataset.quantityAuthority = state.quantity_authority || '';

    const statusCell = row.querySelector('.bt38-status');
    if (statusCell) {{
      if (state.is_fba) {{
        statusCell.textContent = 'FBA Locked';
        statusCell.title = state.reason || 'FBA read-only';
      }} else if (state.is_pushable) {{
        statusCell.textContent = 'Governed Pushable';
        statusCell.title = state.reason || 'Governed pushable';
      }} else if (state.action_state === 'blocked') {{
        statusCell.textContent = 'Blocked';
        statusCell.title = state.reason || 'Blocked';
      }}
    }}

    const groupCell = row.querySelector('.bt38-group-pill');
    if (groupCell) {{
      if (state.is_mcf_eligible) {{
        groupCell.textContent = 'MCF';
        groupCell.title = 'MCF eligible: Amazon FBA only';
      }} else if (state.is_group_controlled) {{
        groupCell.title = 'Controlled by MasterProductGroup';
      }}
    }}

    const btn = row.querySelector('.bt38-marketplace-control');
    if (btn) {{
      if (state.is_fba) {{
        btn.title = 'FBA read-only';
        btn.setAttribute('aria-disabled', 'true');
      }} else if (state.is_pushable) {{
        btn.title = 'Governed pushable receiver';
      }} else {{
        btn.title = state.reason || 'Not pushable';
      }}
    }}
  }}

  function loadRuntimeOverlay() {{
    fetch('/governed/warehouse/runtime-state')
      .then(r => r.json())
      .then(data => {{
        if (!data || !Array.isArray(data.rows)) return;

        const byListing = new Map();
        const byStock = new Map();

        data.rows.forEach(state => {{
          if (state.listing_id) byListing.set(String(state.listing_id), state);
          if (state.warehouse_stock_id) byStock.set(String(state.warehouse_stock_id), state);
        }});

        document.querySelectorAll('tr[data-stock-id], tr[data-listing-id]').forEach(row => {{
          const listingId = row.dataset.listingId || '';
          const stockId = row.dataset.stockId || '';

          const state =
            (listingId && byListing.get(String(listingId))) ||
            (stockId && byStock.get(String(stockId)));

          applyRuntimeState(row, state);
        }});
      }})
      .catch(() => console.warn('Governed runtime overlay unavailable'));
  }}

  document.addEventListener('DOMContentLoaded', function() {{
    wireSearch();
    wireKpis();
    wireTabs();
    loadRuntimeOverlay();
  }});
}})();
</script>
<style id="bt38Phase1WarehouseWiringStyle">
.bt38-kpi-card:hover{{box-shadow:0 0 0 2px rgba(37,99,235,.10);}}
tr[data-runtime-role="quantity_authority"]{{outline:1px solid rgba(37,99,235,.12);}}
tr[data-action-state="governed_pushable"]{{outline:1px solid rgba(22,163,74,.12);}}
tr[data-action-state="skip_before_push"]{{outline:1px solid rgba(245,158,11,.16);}}
tr[data-action-state="blocked"]{{outline:1px solid rgba(220,38,38,.14);}}
</style>
"""
    return html + script


@governed_bp.post("/amazon-inventory-hydration/manual-run")
def governed_amazon_inventory_hydration_manual_run():
    from services.governed_amazon_inventory_hydration import hydrate_amazon_inventory

    result = hydrate_amazon_inventory()

    return jsonify({
        "success": True,
        "manual": True,
        "governed": True,
        "auto_execution": False,
        "result": result,
    })



@governed_bp.get("/governed/product-linking/data")
def governed_product_linking_data_compat():
    """Governed compatibility endpoint for old product-linking data calls.

    This keeps the frontend inside the governed namespace.
    It is read-only and does not push, sync, repair, or mutate marketplace state.
    """
    from extensions import db
    from models import WarehouseStock, MarketplaceListing
    from sqlalchemy import or_

    search = (request.args.get("search") or request.args.get("q") or "").strip()
    limit_raw = request.args.get("limit") or 50

    try:
        limit = int(limit_raw)
    except Exception:
        limit = 50

    limit = max(1, min(limit, 100))

    stock_query = db.session.query(WarehouseStock).filter(
        WarehouseStock.is_active == True,  # noqa: E712
        WarehouseStock.is_deleted == False,  # noqa: E712
    )

    listing_query = db.session.query(MarketplaceListing).filter(
        MarketplaceListing.is_active == True  # noqa: E712
    )

    if search:
        like = f"%{search}%"
        stock_query = stock_query.filter(or_(
            WarehouseStock.sku.ilike(like),
            WarehouseStock.product_name.ilike(like),
            WarehouseStock.barcode.ilike(like),
            WarehouseStock.group_title.ilike(like),
        ))
        listing_query = listing_query.filter(or_(
            MarketplaceListing.external_sku.ilike(like),
            MarketplaceListing.title.ilike(like),
            MarketplaceListing.external_listing_id.ilike(like),
            MarketplaceListing.asin.ilike(like),
            MarketplaceListing.fnsku.ilike(like),
            MarketplaceListing.barcode.ilike(like),
        ))

    stock_rows = stock_query.order_by(WarehouseStock.id.desc()).limit(limit).all()
    listing_rows = listing_query.order_by(MarketplaceListing.id.desc()).limit(limit).all()

    return jsonify({
        "success": True,
        "ok": True,
        "governed": True,
        "read_only": True,
        "warehouse": [
            {
                "id": s.id,
                "sku": s.sku,
                "product_name": s.product_name,
                "barcode": s.barcode,
                "group_title": s.group_title,
                "master_product_group_id": s.master_product_group_id,
                "sellable_quantity": getattr(s, "sellable_quantity", 0),
            }
            for s in stock_rows
        ],
        "listings": [
            {
                "id": l.id,
                "external_sku": l.external_sku,
                "title": l.title,
                "external_listing_id": l.external_listing_id,
                "asin": l.asin,
                "fnsku": l.fnsku,
                "warehouse_stock_id": l.warehouse_stock_id,
                "master_product_group_id": l.master_product_group_id,
                "store_id": l.store_id,
            }
            for l in listing_rows
        ],
    })


@governed_bp.get("/governed/product-linking/search-all-listings")
def governed_product_linking_search_all_listings_compat():
    return governed_product_linking_data_compat()


@governed_bp.get("/governed/product-linking/search-warehouse")
def governed_product_linking_search_warehouse_compat():
    data_response = governed_product_linking_data_compat()
    return data_response


@governed_bp.get("/governed/product-linking/diagnostics/<int:warehouse_id>")
def governed_product_linking_diagnostics_compat(warehouse_id: int):
    """Safe governed diagnostic shell.

    Read-only. No repair, no sync, no push.
    """
    from extensions import db
    from models import WarehouseStock, MarketplaceListing

    stock = db.session.get(WarehouseStock, warehouse_id)
    linked = (
        db.session.query(MarketplaceListing)
        .filter(MarketplaceListing.warehouse_stock_id == warehouse_id)
        .limit(100)
        .all()
    )

    return jsonify({
        "success": True,
        "ok": True,
        "governed": True,
        "read_only": True,
        "warehouse_id": warehouse_id,
        "stock_found": bool(stock),
        "linked_listing_count": len(linked),
        "linked_listings": [
            {
                "id": l.id,
                "external_sku": l.external_sku,
                "title": l.title,
                "store_id": l.store_id,
                "master_product_group_id": l.master_product_group_id,
            }
            for l in linked
        ],
        "message": "Governed diagnostics are read-only. Repair actions are blocked until explicitly governed.",
    })


@governed_bp.post("/governed/product-linking/repair/<int:warehouse_id>")
def governed_product_linking_repair_compat(warehouse_id: int):
    """Safe governed repair shell.

    This intentionally blocks repair mutation until the repair rules are governed.
    """
    return jsonify({
        "success": False,
        "ok": False,
        "governed": True,
        "repair_blocked": True,
        "warehouse_id": warehouse_id,
        "message": "Governed repair is not enabled yet. This old repair action is safely blocked.",
    }), 409


@governed_bp.post("/governed/product-linking/bulk-action")
def governed_product_linking_bulk_action_compat():
    """Safe governed bulk shell.

    Bulk mutation is blocked until the governed bulk model is proven.
    """
    return jsonify({
        "success": False,
        "ok": False,
        "governed": True,
        "bulk_blocked": True,
        "message": "Governed bulk product-linking action is not enabled yet.",
    }), 409


@governed_bp.post("/governed/warehouse/<int:stock_id>/upload-image")
def governed_warehouse_upload_image_compat(stock_id: int):
    """Safe governed upload shell.

    Blocks upload mutation until governed storage policy is approved.
    """
    return jsonify({
        "success": False,
        "ok": False,
        "governed": True,
        "upload_blocked": True,
        "stock_id": stock_id,
        "message": "Governed warehouse image upload is not enabled yet.",
    }), 409




@governed_bp.post("/governed/actions/listings/<int:listing_id>/quantity")
def governed_listing_quantity_update(listing_id: int):
    """Governed local warehouse quantity update.

    This updates warehouse truth only. It does not push to marketplaces.
    Marketplace push remains a separate explicit governed action.
    """
    from extensions import db
    from models import MarketplaceListing, WarehouseStock
    from flask import request, jsonify

    listing = db.session.get(MarketplaceListing, listing_id)
    if not listing:
        return jsonify(success=False, ok=False, error="listing_not_found"), 404

    stock = listing.warehouse_stock
    if not stock and listing.warehouse_stock_id:
        stock = db.session.get(WarehouseStock, listing.warehouse_stock_id)

    if not stock:
        return jsonify(success=False, ok=False, error="warehouse_stock_not_found"), 404

    payload = request.get_json(silent=True) or {}
    try:
        qty = int(payload.get("quantity"))
    except Exception:
        return jsonify(success=False, ok=False, error="invalid_quantity"), 400

    if qty < 0:
        return jsonify(success=False, ok=False, error="negative_quantity_not_allowed"), 400

    writable_columns = [
        "quantity",
        "available_quantity",
        "stock_quantity",
        "on_hand_quantity",
        "qty",
    ]

    updated_column = None
    stock_columns = set(stock.__table__.columns.keys())
    for col in writable_columns:
        if col in stock_columns:
            setattr(stock, col, qty)
            updated_column = col
            break

    if not updated_column:
        return jsonify(
            success=False,
            ok=False,
            governed=True,
            error="no_supported_quantity_column",
            message="No writable warehouse quantity column was found.",
        ), 409

    db.session.commit()

    return jsonify(
        success=True,
        ok=True,
        governed=True,
        listing_id=listing.id,
        warehouse_stock_id=stock.id,
        quantity=qty,
        updated_column=updated_column,
        message="Warehouse quantity saved locally. Use Push to sync marketplace.",
    )


@governed_bp.post("/governed/actions/listings/<int:listing_id>/price")
def governed_listing_price_update(listing_id: int):
    """Governed local listing price update.

    This updates local listing price only. It does not push to marketplaces.
    """
    from extensions import db
    from models import MarketplaceListing
    from flask import request, jsonify

    listing = db.session.get(MarketplaceListing, listing_id)
    if not listing:
        return jsonify(success=False, ok=False, error="listing_not_found"), 404

    payload = request.get_json(silent=True) or {}
    try:
        price = float(payload.get("price"))
    except Exception:
        return jsonify(success=False, ok=False, error="invalid_price"), 400

    if price < 0:
        return jsonify(success=False, ok=False, error="negative_price_not_allowed"), 400

    if "price" not in set(listing.__table__.columns.keys()):
        return jsonify(success=False, ok=False, error="price_column_missing"), 409

    listing.price = price
    db.session.commit()

    return jsonify(
        success=True,
        ok=True,
        governed=True,
        listing_id=listing.id,
        price=price,
        message="Listing price saved locally. Use Push to sync marketplace.",
    )



@governed_bp.post("/governed/warehouse/sync")
def governed_warehouse_sync_manual_run():
    from services.governed_warehouse_sync import run_governed_warehouse_sync

    body = dict(request.get_json(silent=True) or {})
    store_id = body.get("store_id")

    result = run_governed_warehouse_sync(
        store_id=store_id,
        actor=request.headers.get("X-Actor", "warehouse-sync-button"),
    )

    return jsonify(result), 200 if result.get("success") else 400


@governed_bp.post("/governed/amazon/inventory/import")
def governed_amazon_inventory_import():
    from services.governed_amazon_inventory_import import (
        run_governed_amazon_inventory_import
    )

    body = dict(request.get_json(silent=True) or {})

    result = run_governed_amazon_inventory_import(
        store_id=body.get("store_id")
    )

    return jsonify(result), 200


@governed_bp.route("/governed-disabled", defaults={"action": ""}, methods=["GET", "POST"])
@governed_bp.route("/governed-disabled/<path:action>", methods=["GET", "POST"])
def governed_disabled_action(action: str = ""):
    from flask import jsonify, request
    return jsonify({
        "success": False,
        "ok": False,
        "governed": True,
        "execution_blocked": True,
        "action": action,
        "method": request.method,
        "message": "This legacy action is disabled until the governed route is approved."
    }), 409


@governed_bp.post("/governed/product-linking/repair/reset-failures")
def governed_product_linking_repair_reset_failures():
    from flask import jsonify
    return jsonify({
        "success": False,
        "ok": False,
        "governed": True,
        "execution_blocked": True,
        "action": "reset-failures",
        "message": "This governed repair action is disabled until approved."
    }), 409


@governed_bp.post("/governed/product-linking/repair/rebuild-link")
def governed_product_linking_repair_rebuild_link():
    from flask import jsonify
    return jsonify({
        "success": False,
        "ok": False,
        "governed": True,
        "execution_blocked": True,
        "action": "rebuild-link",
        "message": "This governed repair action is disabled until approved."
    }), 409


@governed_bp.post("/governed/product-linking/repair/create-missing-sku")
def governed_product_linking_repair_create_missing_sku():
    from flask import jsonify
    return jsonify({
        "success": False,
        "ok": False,
        "governed": True,
        "execution_blocked": True,
        "action": "create-missing-sku",
        "message": "This governed repair action is disabled until approved."
    }), 409


@governed_bp.post("/governed/product-linking/repair/sync-now")
def governed_product_linking_repair_sync_now():
    from flask import jsonify
    return jsonify({
        "success": False,
        "ok": False,
        "governed": True,
        "execution_blocked": True,
        "action": "sync-now",
        "message": "This governed repair action is disabled until approved."
    }), 409


# === BT38 PRIVATE SETTINGS COCKPIT API ===
def _bt38_settings_bool(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value).strip().lower()
    return "true" if text in {"1", "true", "yes", "on", "enabled"} else "false"


def _bt38_settings_set_config(key, value):
    from app import db
    from models import SystemConfig
    cfg = SystemConfig.query.filter_by(key=key).first()
    if cfg is None:
        cfg = SystemConfig(key=key, value=str(value))
        db.session.add(cfg)
    else:
        cfg.value = str(value)
    db.session.commit()
    return cfg


@governed_bp.get("/governed/settings/state")
def governed_settings_state():
    from flask import jsonify
    from models import SystemConfig, Store

    keys = [
        "push_enabled", "runtime_push_enabled", "marketplace_push_enabled",
        "import_enabled", "runtime_import_enabled", "marketplace_import_enabled",
        "sync_enabled", "runtime_sync_enabled", "marketplace_sync_enabled",
        "manual_push_enabled", "manual_import_enabled", "manual_sync_enabled",
        "quantity_push_enabled", "price_push_enabled", "group_push_enabled", "bulk_push_enabled",
        "read_only_mode", "dry_run_mode", "queue_frozen",
        "scheduler_enabled", "sync_worker_enabled", "push_worker_enabled",
        "retry_queue_enabled", "reconcile_15m_enabled",
        "webhook_worker_enabled", "webhook_ebay_enabled", "webhook_amazon_enabled",
        "default_push_frequency_minutes", "default_batch_size", "default_retry_attempts",
        "api_rate_limit_buffer", "error_rate_threshold",
    ]

    config = {key: "false" for key in keys}
    for row in SystemConfig.query.filter(SystemConfig.key.in_(keys)).all():
        config[row.key] = str(row.value)

    stores = []
    for store in Store.query.order_by(Store.id).all():
        stores.append({
            "id": store.id,
            "name": store.name,
            "platform": store.platform,
            "store_mode": getattr(store, "store_mode", None),
            "is_active": bool(getattr(store, "is_active", False)),
            "fba_import_enabled": bool(getattr(store, "fba_import_enabled", False)),
            "fbm_sync_enabled": bool(getattr(store, "fbm_sync_enabled", False)),
            "auto_push_enabled": bool(getattr(store, "auto_push_enabled", False)),
            "sync_status": getattr(store, "sync_status", None),
            "last_sync": str(getattr(store, "last_sync", "") or ""),
        })

    return jsonify(ok=True, success=True, governed=True, config=config, stores=stores)


@governed_bp.post("/governed/settings/config")
def governed_settings_config_update():
    from flask import jsonify, request

    allowed = {
        "push_enabled", "runtime_push_enabled", "marketplace_push_enabled",
        "import_enabled", "runtime_import_enabled", "marketplace_import_enabled",
        "sync_enabled", "runtime_sync_enabled", "marketplace_sync_enabled",
        "manual_push_enabled", "manual_import_enabled", "manual_sync_enabled",
        "quantity_push_enabled", "price_push_enabled", "group_push_enabled", "bulk_push_enabled",
        "read_only_mode", "dry_run_mode", "queue_frozen",
        "scheduler_enabled", "sync_worker_enabled", "push_worker_enabled",
        "retry_queue_enabled", "reconcile_15m_enabled",
        "webhook_worker_enabled", "webhook_ebay_enabled", "webhook_amazon_enabled",
        "default_push_frequency_minutes", "default_batch_size", "default_retry_attempts",
        "api_rate_limit_buffer", "error_rate_threshold",
    }

    body = request.get_json(silent=True) or {}
    key = str(body.get("key", "")).strip()
    value = body.get("value")

    if key not in allowed:
        return jsonify(ok=False, success=False, governed=True, error="setting_not_allowed", key=key), 400

    numeric_settings = {
        "default_push_frequency_minutes": int,
        "default_batch_size": int,
        "default_retry_attempts": int,
        "api_rate_limit_buffer": float,
        "error_rate_threshold": float,
    }

    if key in numeric_settings:
        try:
            value = numeric_settings[key](value)
        except Exception:
            return jsonify(ok=False, success=False, governed=True, error="invalid_numeric_value", key=key, value=value), 400
    elif isinstance(value, bool):
        value = _bt38_settings_bool(value)

    _bt38_settings_set_config(key, value)
    return jsonify(ok=True, success=True, governed=True, key=key, value=str(value))


@governed_bp.post("/governed/settings/stores/<int:store_id>")
def governed_settings_store_update(store_id):
    from flask import jsonify, request
    from app import db
    from models import Store

    allowed = {
        "is_active": "bool",
        "fba_import_enabled": "bool",
        "fbm_sync_enabled": "bool",
        "auto_push_enabled": "bool",
        "store_mode": "mode",
    }

    body = request.get_json(silent=True) or {}
    field = str(body.get("field", "")).strip()
    value = body.get("value")

    if field not in allowed:
        return jsonify(ok=False, success=False, governed=True, error="store_field_not_allowed", field=field), 400

    store = Store.query.get(store_id)
    if store is None:
        return jsonify(ok=False, success=False, governed=True, error="store_not_found", store_id=store_id), 404

    if allowed[field] == "bool":
        setattr(store, field, bool(value))
    else:
        mode = str(value).strip().lower()
        if mode not in {"safe", "live", "disabled"}:
            return jsonify(ok=False, success=False, governed=True, error="invalid_store_mode", value=value), 400
        setattr(store, field, mode)

    db.session.commit()
    return jsonify(ok=True, success=True, governed=True, store_id=store.id, field=field, value=getattr(store, field))


@governed_bp.post("/governed/settings/emergency-freeze")
def governed_settings_emergency_freeze():
    from flask import jsonify

    freeze = {
        "push_enabled": "false",
        "runtime_push_enabled": "false",
        "marketplace_push_enabled": "false",
        "import_enabled": "false",
        "runtime_import_enabled": "false",
        "marketplace_import_enabled": "false",
        "sync_enabled": "false",
        "runtime_sync_enabled": "false",
        "marketplace_sync_enabled": "false",
        "manual_push_enabled": "false",
        "manual_import_enabled": "false",
        "manual_sync_enabled": "false",
        "queue_frozen": "true",
        "read_only_mode": "true",
    }

    for key, value in freeze.items():
        _bt38_settings_set_config(key, value)

    return jsonify(ok=True, success=True, governed=True, emergency_freeze=True, updated=freeze)
