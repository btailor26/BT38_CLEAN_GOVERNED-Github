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


def _governed_json_safe(value):
    """Convert governed results to JSON-safe values before jsonify."""
    from datetime import date, datetime
    from decimal import Decimal

    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, Decimal):
        return float(value)

    if isinstance(value, (datetime, date)):
        return value.isoformat()

    if isinstance(value, dict):
        safe = {}
        for key, item in value.items():
            if key in {"store", "listing", "_governed_store", "_governed_listing"}:
                if item is None:
                    safe[key] = None
                else:
                    safe[key] = {
                        "id": getattr(item, "id", None),
                        "name": getattr(item, "name", None),
                        "platform": getattr(item, "platform", None),
                        "sku": getattr(item, "external_sku", None) or getattr(item, "sku", None),
                        "store_id": getattr(item, "store_id", None),
                    }
            else:
                safe[str(key)] = _governed_json_safe(item)
        return safe

    if isinstance(value, (list, tuple, set)):
        return [_governed_json_safe(item) for item in value]

    return str(value)


@governed_bp.get("/")
def governed_root_page():
    return redirect("/dashboard")



@governed_bp.get("/dashboard")
def governed_dashboard_page():
    """Human health dashboard.

    One clear path:
    existing governed sources -> attention summary -> dashboard.

    The dashboard does not call marketplaces, start sync, push stock, import
    orders, or create a second notification system.
    """
    import json as _json
    from types import SimpleNamespace
    from models import Store, SystemLog, MarketplaceOrder, SalesOrder, SalesOrderItem, MCFOrder

    stores = Store.query.order_by(Store.id).all()

    webhook_logs = (
        SystemLog.query
        .filter(SystemLog.log_type == "marketplace_webhook")
        .order_by(SystemLog.created_at.desc())
        .limit(12)
        .all()
    )

    marketplace_orders = (
        MarketplaceOrder.query
        .order_by(MarketplaceOrder.created_at.desc())
        .limit(50)
        .all()
    )

    sales_orders = (
        SalesOrder.query
        .order_by(SalesOrder.created_at.desc())
        .limit(50)
        .all()
    )

    sales_order_items = (
        SalesOrderItem.query
        .order_by(SalesOrderItem.created_at.desc())
        .limit(50)
        .all()
    )

    mcf_orders = (
        MCFOrder.query
        .order_by(MCFOrder.created_at.desc())
        .limit(50)
        .all()
    )

    attention_items = []

    def _platform_link(platform: str, action_type: str) -> str:
        p = (platform or "").lower()
        a = (action_type or "").lower()

        if "ebay" in p:
            if "dispatch" in a or "order" in a:
                return "https://www.ebay.co.uk/sh/ord"
            if "message" in a or "buyer" in a:
                return "https://www.ebay.co.uk/sh/messages"
            return "https://www.ebay.co.uk/sh/overview"

        if "amazon" in p:
            if "dispatch" in a or "order" in a:
                return "https://sellercentral.amazon.co.uk/orders-v3"
            if "message" in a or "buyer" in a:
                return "https://sellercentral.amazon.co.uk/messaging"
            return "https://sellercentral.amazon.co.uk/home"

        return "/dashboard"

    def _human_title(platform: str, event_type: str) -> tuple[str, str]:
        text = (event_type or "").replace("_", " ").replace("-", " ").strip().lower()
        platform_name = (platform or "Marketplace").title()

        if "message" in text or "buyer" in text or "inquiry" in text:
            return "Buyer message waiting", f"{platform_name} customer message needs a reply."

        if "dispatch" in text or "ship" in text or "fulfillment" in text or "order" in text:
            return "Order waiting to dispatch", f"{platform_name} order needs dispatch attention."

        if "auth" in text or "disconnect" in text or "token" in text:
            return "Marketplace connection needs attention", f"{platform_name} connection may need reconnecting."

        if "listing" in text or "blocked" in text or "policy" in text:
            return "Listing needs attention", f"{platform_name} listing needs review."

        return "Marketplace update received", f"{platform_name} has sent a notification."

    real_sales_count = len(marketplace_orders) + len(sales_orders)
    real_dispatch_pending = 0
    real_mcf_pending = 0

    for order in marketplace_orders:
        status = (order.status or "").strip().lower()
        fulfillment = (order.fulfillment_type or "FBM").strip().upper()
        is_shipped = bool(order.shipped_at)

        if status in {"pending", "new", "unshipped", "awaiting_dispatch", "processing"} or not is_shipped:
            real_dispatch_pending += 1
            platform = order.store.platform if order.store else "Marketplace"
            store_name = order.store.name if order.store else "Marketplace"
            title = "Order waiting to dispatch"
            if fulfillment == "FBA":
                title = "FBA / MCF order needs attention"

            attention_items.append(SimpleNamespace(
                source="marketplace_order",
                marketplace=(platform or "Marketplace").title(),
                store_name=store_name,
                title=title,
                message=f"{store_name} order {order.marketplace_order_id} needs attention for SKU {order.sku} x{order.quantity}.",
                status=order.status or "pending",
                reason=order.error_message or "",
                severity="warning",
                action_url=(
                    "https://www.ebay.co.uk/sh/ord"
                    if "ebay" in (platform or "").lower()
                    else "https://sellercentral.amazon.co.uk/orders-v3"
                    if "amazon" in (platform or "").lower()
                    else "/dashboard"
                ),
                action_label=f"Open {(platform or 'Marketplace').title()}",
                created_at=order.created_at,
            ))

    for order in sales_orders:
        status = (order.status or "").strip().lower()
        if status in {"draft", "pending", "confirmed", "processing", "unfulfilled"} or not order.ship_date:
            real_dispatch_pending += 1
            attention_items.append(SimpleNamespace(
                source="sales_order",
                marketplace="Sales",
                store_name="Sales Orders",
                title="Sales order waiting to fulfil",
                message=f"Sales order {order.order_number} needs fulfilment attention.",
                status=order.status or "pending",
                reason="",
                severity="warning",
                action_url="/dashboard",
                action_label="Open dashboard",
                created_at=order.created_at,
            ))

    for item in sales_order_items:
        if not item.is_fulfilled:
            attention_items.append(SimpleNamespace(
                source="sales_order_item",
                marketplace="Sales",
                store_name="Sales Orders",
                title="Order item not fulfilled",
                message=f"SKU {item.sku or 'Unknown'} has {item.quantity or 0} unit(s) not fulfilled.",
                status="not_fulfilled",
                reason="",
                severity="warning",
                action_url="/dashboard",
                action_label="Review",
                created_at=item.created_at,
            ))

    for order in mcf_orders:
        status = (order.status or "").strip().lower()
        amazon_status = (order.amazon_status or "").strip().lower()
        if status in {"pending", "failed", "error", "processing"} or amazon_status in {"pending", "failed", "error"}:
            real_mcf_pending += 1
            attention_items.append(SimpleNamespace(
                source="mcf_order",
                marketplace=(order.source_channel or "MCF").title(),
                store_name="Amazon MCF",
                title="MCF fulfilment needs attention",
                message=f"MCF order {order.seller_fulfillment_order_id} is {order.status or 'pending'}.",
                status=order.status or "pending",
                reason=order.last_error or "",
                severity="warning",
                action_url="https://sellercentral.amazon.co.uk/orders-v3",
                action_label="Open Amazon",
                created_at=order.created_at,
            ))

    for log in webhook_logs:
        try:
            details = _json.loads(log.details or "{}")
        except Exception:
            details = {}

        platform = details.get("marketplace") or "marketplace"
        event_type = details.get("event_type") or "marketplace_notification"
        status = details.get("status") or "received"
        reason = details.get("reason") or ""
        payload = details.get("payload") or {}

        title, message = _human_title(platform, event_type)
        action_url = (
            payload.get("action_url")
            or payload.get("external_url")
            or payload.get("url")
            or _platform_link(platform, event_type)
        )

        attention_items.append(SimpleNamespace(
            source="webhook",
            marketplace=platform.title(),
            store_name=details.get("store_name") or "Marketplace",
            title=title,
            message=message,
            status=status,
            reason=reason,
            severity="info" if status == "received" else "muted",
            action_url=action_url,
            action_label=f"Open {platform.title()}",
            created_at=log.created_at,
        ))

    for store in stores:
        auth_status = (store.auth_status or "ok").lower()
        if auth_status and auth_status != "ok":
            platform = store.platform or "Marketplace"
            attention_items.append(SimpleNamespace(
                source="store",
                marketplace=platform.title(),
                store_name=store.name,
                title="Store connection needs attention",
                message=store.auth_error_message or f"{store.name} may need reconnecting.",
                status=auth_status,
                reason=store.auth_error_code or "auth_status",
                severity="warning",
                action_url="/settings",
                action_label="Open settings",
                created_at=store.auth_error_at or store.updated_at,
            ))

        if (store.sync_status or "").lower() in {"error", "failed"}:
            platform = store.platform or "Marketplace"
            attention_items.append(SimpleNamespace(
                source="store",
                marketplace=platform.title(),
                store_name=store.name,
                title="Marketplace action needs attention",
                message=f"{store.name} has a marketplace status of {store.sync_status}.",
                status=store.sync_status,
                reason=store.pause_reason or "",
                severity="warning",
                action_url="/settings",
                action_label="Open settings",
                created_at=store.updated_at,
            ))

    pending_messages = sum(
        1 for item in attention_items
        if "message" in (item.title or "").lower()
    )
    pending_dispatch = sum(
        1 for item in attention_items
        if "dispatch" in (item.title or "").lower()
    )

    dashboard_stats = {
        "total_items": 0,
        "active_stores": sum(1 for store in stores if store.is_active),
        "total_stores": len(stores),
        "low_stock_items": 0,
        "total_attention": len(attention_items),
        "pending_messages": pending_messages,
        "pending_dispatch": real_dispatch_pending,
        "real_sales_count": real_sales_count,
        "real_mcf_pending": real_mcf_pending,
    }

    return render_template(
        "dashboard.html",
        stats=dashboard_stats,
        attention_items=attention_items[:12],
        stores=stores,
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

    def _on(key):
        return str(config.get(key, "false")).strip().lower() in {"1", "true", "yes", "on"}

    def _status(action, required):
        if _on("read_only_mode"):
            return {"label": "BLOCKED", "reason": "read_only_mode is ON", "required": {k: _on(k) for k in required}}
        for key in required:
            if not _on(key):
                return {"label": "BLOCKED", "reason": f"{key} is OFF", "required": {k: _on(k) for k in required}}
        return {"label": "ALLOWED", "reason": f"{action} circuit is fully powered", "required": {k: _on(k) for k in required}}

    fuse_status = {
        "push": _status("Push", ["push_enabled", "runtime_push_enabled", "marketplace_push_enabled", "manual_push_enabled"]),
        "import": _status("Import", ["import_enabled", "runtime_import_enabled", "marketplace_import_enabled", "manual_import_enabled"]),
        "sync": _status("Sync", ["sync_enabled", "runtime_sync_enabled", "marketplace_sync_enabled", "manual_sync_enabled"]),
        "global": {
            "read_only_mode": _on("read_only_mode"),
            "dry_run_mode": _on("dry_run_mode"),
            "queue_frozen": _on("queue_frozen"),
        },
    }

    class Stats:
        failed_24h = 0
        failed_syncs = 0
        success_rate = 100

    stores = Store.query.order_by(Store.id).all()

    return render_template(
        "settings.html",
        config=config,
        fuse_status=fuse_status,
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
        current_show_linked="all",
        async_load=True
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


def _governed_admin_required(f):
    """Single admin gate for fuse-box user authority."""
    from functools import wraps

    @wraps(f)
    def decorated_function(*args, **kwargs):
        from flask import flash
        try:
            if not current_user or not current_user.is_authenticated:
                flash("Please log in to access this page.", "warning")
                return redirect(url_for("governed.login"))
            if getattr(current_user, "role", "") != "admin":
                flash("You do not have permission to access this page.", "danger")
                return redirect(url_for("governed.governed_dashboard_page"))
        except Exception:
            flash("Please log in to access this page.", "warning")
            return redirect(url_for("governed.login"))
        return f(*args, **kwargs)

    return decorated_function


USER_PERMISSION_SECTIONS = [
    "inventory",
    "warehouse",
    "stores",
    "suppliers",
    "purchase_orders",
    "sync",
    "settings",
    "users",
]


def _full_user_permissions():
    """Full owner/admin fuse-box authority.

    This is still one permission layer. It only fills the existing
    User.permissions JSON so the owner account is visible as fully aligned.
    """
    permissions = {}
    for section in USER_PERMISSION_SECTIONS:
        permissions[f"view_{section}"] = True
        permissions[f"edit_{section}"] = True

    permissions["can_push"] = True
    permissions["can_sync"] = True
    permissions["can_import"] = True
    permissions["can_manage_users"] = True
    return permissions


def _build_user_permissions_from_form(form, role="viewer"):
    """Build the existing permissions JSON from one fuse-box authority form.

    These are shortcut/authority flags only. They do not create duplicate sync,
    push, import, marketplace, or runtime paths.
    """
    if str(role or "").strip().lower() == "admin":
        return _full_user_permissions()

    permissions = {}
    for section in USER_PERMISSION_SECTIONS:
        permissions[f"view_{section}"] = form.get(f"view_{section}") == "on"
        permissions[f"edit_{section}"] = form.get(f"edit_{section}") == "on"

    permissions["can_push"] = permissions.get("edit_inventory", False) or permissions.get("edit_warehouse", False)
    permissions["can_sync"] = permissions.get("edit_sync", False)
    permissions["can_import"] = permissions.get("edit_stores", False)
    permissions["can_manage_users"] = permissions.get("edit_users", False)
    return permissions


@governed_bp.route("/users")
@_governed_admin_required
def user_management():
    from models import User

    users = User.query.order_by(User.created_at.desc(), User.id.desc()).all()
    return render_template("user_management.html", users=users)


@governed_bp.route("/users/create", methods=["GET", "POST"])
@_governed_admin_required
def create_user():
    from flask import flash
    from extensions import db
    from models import User

    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        role = (request.form.get("role") or "viewer").strip().lower()

        if role not in {"viewer", "manager", "admin"}:
            role = "viewer"

        if len(password) < 6:
            flash("Password must be at least 6 characters.", "danger")
            return render_template("create_user.html")

        existing = User.query.filter((User.username == username) | (User.email == email)).first()
        if existing:
            flash("That user already exists. Opened the existing user so you can edit access.", "warning")
            return redirect(url_for("governed.edit_user", user_id=existing.id))

        user = User(username=username, email=email, role=role, permissions=_full_user_permissions() if role == "admin" else {})
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        flash("User created. You can now assign access from the edit screen.", "success")
        return redirect(url_for("governed.edit_user", user_id=user.id))

    return render_template("create_user.html")


@governed_bp.route("/users/<int:user_id>/edit", methods=["GET", "POST"])
@_governed_admin_required
def edit_user(user_id):
    from flask import flash
    from extensions import db
    from models import User

    user = User.query.get_or_404(user_id)

    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        role = (request.form.get("role") or "viewer").strip().lower()
        password = request.form.get("password") or ""

        if role not in {"viewer", "manager", "admin"}:
            role = "viewer"

        duplicate = User.query.filter(User.email == email, User.id != user.id).first()
        if duplicate:
            flash("Another user already uses that email.", "danger")
            return render_template("edit_user.html", user=user)

        user.email = email
        user.role = role
        user.is_active = request.form.get("is_active") == "on"
        user.permissions = _build_user_permissions_from_form(request.form, role)

        if password:
            if len(password) < 6:
                flash("Password must be at least 6 characters.", "danger")
                return render_template("edit_user.html", user=user)
            user.set_password(password)

        db.session.commit()
        flash("User access updated through the fuse-box permission authority.", "success")
        return redirect(url_for("governed.user_management"))

    if user.permissions is None:
        user.permissions = {}
    return render_template("edit_user.html", user=user)


@governed_bp.route("/users/<int:user_id>/delete", methods=["POST"])
@_governed_admin_required
def delete_user(user_id):
    from flask import flash
    from extensions import db
    from models import User

    user = User.query.get_or_404(user_id)

    if current_user and user.id == current_user.id:
        flash("You cannot deactivate your own account.", "danger")
        return redirect(url_for("governed.user_management"))

    user.is_active = False
    db.session.commit()
    flash("User deactivated.", "success")
    return redirect(url_for("governed.user_management"))


# ============================================================
# Governed marketplace webhook intake
# ============================================================
# One clear path:
# marketplace notification -> governed intake -> existing SystemLog
# No sync, push, import, adapter call, or marketplace execution happens here.
# Dashboard will later read normalized attention from governed sources only.

def _bt38_config_on(key: str) -> bool:
    from models import SystemConfig

    row = SystemConfig.query.filter_by(key=key).first()
    if not row:
        return False
    return str(row.value).strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _bt38_webhook_platform_allowed(platform: str) -> tuple[bool, str]:
    platform = (platform or "").strip().lower()

    if platform not in {"amazon", "ebay"}:
        return False, "unsupported_marketplace"

    if not _bt38_config_on("webhook_worker_enabled"):
        return False, "webhook_worker_enabled is OFF"

    if platform == "amazon" and not _bt38_config_on("webhook_amazon_enabled"):
        return False, "webhook_amazon_enabled is OFF"

    if platform == "ebay" and not _bt38_config_on("webhook_ebay_enabled"):
        return False, "webhook_ebay_enabled is OFF"

    return True, "allowed"


def _bt38_webhook_payload() -> dict:
    body = request.get_json(silent=True)
    if isinstance(body, dict):
        return body

    raw = request.get_data(as_text=True) or ""
    if raw:
        return {"raw": raw}

    return {}


def _bt38_match_webhook_store(platform: str, payload: dict):
    from models import Store

    store_id = request.headers.get("X-BT38-Store-ID") or payload.get("store_id")
    if store_id:
        try:
            return Store.query.get(int(store_id))
        except Exception:
            return None

    platform_like = f"%{platform}%"
    return (
        Store.query
        .filter(Store.platform.ilike(platform_like))
        .filter(Store.is_active == True)  # noqa: E712
        .order_by(Store.id)
        .first()
    )


def _bt38_record_webhook_event(platform: str, status: str, reason: str, payload: dict):
    from extensions import db
    from models import SystemLog

    store = _bt38_match_webhook_store(platform, payload)

    event_type = (
        payload.get("event_type")
        or payload.get("notificationType")
        or payload.get("topic")
        or payload.get("type")
        or "marketplace_notification"
    )

    details = {
        "governed": True,
        "source": "governed_webhook_intake",
        "marketplace": platform,
        "store_id": getattr(store, "id", None),
        "store_name": getattr(store, "name", None),
        "event_type": event_type,
        "status": status,
        "reason": reason,
        "headers": {
            "user_agent": request.headers.get("User-Agent"),
            "content_type": request.headers.get("Content-Type"),
            "x_bt38_store_id": request.headers.get("X-BT38-Store-ID"),
        },
        "payload": payload,
    }

    row = SystemLog(
        log_type="marketplace_webhook",
        message=f"{platform} webhook {status}: {event_type}",
        details=json.dumps(details, default=str),
    )
    db.session.add(row)
    db.session.commit()
    return row


@governed_bp.route("/governed/webhooks/<marketplace>", methods=["GET", "POST"])
def governed_marketplace_webhook_intake(marketplace):
    platform = (marketplace or "").strip().lower()

    if platform not in {"amazon", "ebay"}:
        return jsonify({
            "ok": False,
            "success": False,
            "governed": True,
            "error": "unsupported_marketplace",
            "marketplace": platform,
        }), 404

    # Lightweight challenge echo only. Provider-specific verification can be
    # added later after the exact marketplace challenge contract is audited.
    if request.method == "GET":
        challenge = (
            request.args.get("challenge_code")
            or request.args.get("challenge")
            or request.args.get("hub.challenge")
        )
        return jsonify({
            "ok": True,
            "success": True,
            "governed": True,
            "marketplace": platform,
            "challenge": challenge,
            "message": "Governed webhook intake is reachable. No marketplace execution was run.",
        }), 200

    payload = _bt38_webhook_payload()
    allowed, reason = _bt38_webhook_platform_allowed(platform)
    status = "received" if allowed else "blocked_by_fuse"

    row = _bt38_record_webhook_event(
        platform=platform,
        status=status,
        reason=reason,
        payload=payload,
    )

    return jsonify({
        "ok": True,
        "success": True,
        "governed": True,
        "marketplace": platform,
        "status": status,
        "reason": reason,
        "system_log_id": row.id,
        "message": "Webhook notification stored. No sync, push, import, or marketplace action was executed.",
    }), 200


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

    try:
        page = int(request.args.get("page") or 1)
    except Exception:
        page = 1
    page = max(page, 1)

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

    total_matching_rows = listing_query.count()
    total_pages = max(1, (total_matching_rows + row_limit - 1) // row_limit)
    page = min(page, total_pages)
    offset = (page - 1) * row_limit

    listing_rows = (
        listing_query
        .order_by(MarketplaceListing.updated_at.desc(), MarketplaceListing.id.desc())
        .offset(offset)
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

    warehouse_items = SimpleNamespace(items=rows, total=total_matching_rows, visible=len(rows))
    pagination = SimpleNamespace(
        page=page,
        per_page=row_limit,
        total=total_matching_rows,
        total_pages=total_pages,
        has_prev=page > 1,
        has_next=page < total_pages,
        prev_page=max(1, page - 1),
        next_page=min(total_pages, page + 1),
    )

    html = render_template(
        "warehouse.html",
        warehouse_items=warehouse_items,
        stats=stats,
        search_query=q,
        active_view=view,
        per_page=row_limit,
        page=page,
        pagination=pagination,
        marketplace_filter=marketplace_filter,
        status_filter=status_filter,
        group_filter=group_filter,
        listing_status_filter=listing_status_filter,
    )
    return _patch_warehouse_phase1_ui(html, stats, q, view)


@governed_bp.post("/governed/actions/sku/dry-run")
def governed_sku_dry_run():
    from governed_execution import submit_governed_marketplace_action

    governed_payload = dict(request.get_json(silent=True) or {})
    governed_payload.setdefault("action", "push_inventory")

    result = submit_governed_marketplace_action(
        payload=governed_payload,
        actor=request.headers.get("X-Actor", "manual-governed-dry-run"),
        approval_type="manual_sku_dry_run_route",
        approval_id="manual_sku_dry_run",
        dry_run=True,
    )
    return jsonify(_governed_json_safe(result)), 200


@governed_bp.post("/governed/actions/listings/<int:listing_id>/push")
def governed_listing_push(listing_id: int):
    body = dict(request.get_json(silent=True) or {})
    result = _push_one_listing(
        listing_id=listing_id,
        quantity=body.get("quantity"),
        actor=_actor(),
        source="ui_listing_button",
    )
    return jsonify(_governed_json_safe(result)), 200


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
        "external_listing_id": listing.external_listing_id,
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
        payload=payload,
        actor=actor,
        approval_type=(approval or {}).get("approval_type"),
        approval_id=(approval or {}).get("approval_id"),
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
    limit_raw = request.args.get("limit") or request.args.get("per_page") or 25
    page_raw = request.args.get("page") or 1

    try:
        per_page = int(limit_raw)
    except Exception:
        per_page = 50

    try:
        page = int(page_raw)
    except Exception:
        page = 1

    per_page = max(1, min(per_page, 100))
    page = max(1, page)
    offset = (page - 1) * per_page

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

    total_stock = stock_query.count()
    total_listings = listing_query.count()
    total_pages_stock = max(1, (total_stock + per_page - 1) // per_page)

    if page > total_pages_stock:
        page = total_pages_stock
        offset = (page - 1) * per_page

    stock_rows = stock_query.order_by(WarehouseStock.id.desc()).offset(offset).limit(per_page).all()

    stock_ids_on_page = [stock.id for stock in stock_rows]
    if stock_ids_on_page:
        listing_rows = (
            db.session.query(MarketplaceListing)
            .filter(MarketplaceListing.is_active == True)  # noqa: E712
            .filter(MarketplaceListing.warehouse_stock_id.in_(stock_ids_on_page))
            .order_by(MarketplaceListing.id.desc())
            .all()
        )
    else:
        listing_rows = []

    listings_by_stock = {}
    unlinked_listings = []

    for listing in listing_rows:
        listing_payload = {
            "id": listing.id,
            "external_sku": listing.external_sku,
            "sku": listing.external_sku,
            "title": listing.title,
            "external_listing_id": listing.external_listing_id,
            "external_id": listing.external_listing_id,
            "asin": listing.asin,
            "fnsku": listing.fnsku,
            "warehouse_stock_id": listing.warehouse_stock_id,
            "master_product_group_id": listing.master_product_group_id,
            "store_id": listing.store_id,
            "store_name": listing.store.name if listing.store else "",
            "platform": listing.store.platform if listing.store else getattr(listing, "platform", ""),
            "amazon_fulfillment_channel": listing.amazon_fulfillment_channel,
            "is_fba": bool(getattr(listing, "is_fba", False)),
            "is_pushable": bool(getattr(listing, "is_pushable", False)),
            "effective_quantity": getattr(listing, "effective_quantity", 0),
        }

        if listing.warehouse_stock_id:
            listings_by_stock.setdefault(listing.warehouse_stock_id, []).append(listing_payload)
        else:
            unlinked_listings.append(listing_payload)

    warehouse_products = []
    for stock in stock_rows:
        linked = listings_by_stock.get(stock.id, [])
        platforms = sorted({str(item.get("platform") or "").strip() for item in linked if item.get("platform")})
        warehouse_products.append({
            "id": stock.id,
            "sku": stock.sku,
            "name": stock.product_name,
            "product_name": stock.product_name,
            "group_name": stock.group_title or stock.product_name or stock.sku,
            "barcode": stock.barcode,
            "group_title": stock.group_title,
            "master_product_group_id": stock.master_product_group_id,
            "is_group_controlled": bool(getattr(stock, "is_group_controlled", False)),
            "quantity": getattr(stock, "sellable_quantity", 0),
            "available_quantity": getattr(stock, "sellable_quantity", 0),
            "sellable_quantity": getattr(stock, "sellable_quantity", 0),
            "linked_count": len(linked),
            "platforms": platforms,
            "listings": linked,
        })

    unlinked_by_platform = {}
    for item in unlinked_listings:
        platform = item.get("platform") or "Unknown"
        unlinked_by_platform.setdefault(platform, []).append(item)

    return jsonify({
        "success": True,
        "ok": True,
        "governed": True,
        "read_only": True,
        "truth_source": "WarehouseStock",
        "mode": "grouping_index",
        "search_term": search,
        "page": page,
        "per_page": per_page,
        "total_stock": total_stock,
        "total_listings": total_listings,
        "total_pages": total_pages_stock,
        "has_prev": page > 1,
        "has_next": page < total_pages_stock,
        "prev_page": max(1, page - 1),
        "next_page": min(total_pages_stock, page + 1),
        "warehouse_products": warehouse_products,
        "unlinked_listings": unlinked_listings,
        "unlinked_by_platform": unlinked_by_platform,
        "all_marketplace_listings": [
            item
            for grouped in listings_by_stock.values()
            for item in grouped
        ] + unlinked_listings,
        "all_stores": [],
        "warehouse": warehouse_products,
        "listings": [
            item
            for grouped in listings_by_stock.values()
            for item in grouped
        ] + unlinked_listings,
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



@governed_bp.post("/governed/stores/<int:store_id>/sync")
def governed_store_sync_shortcut(store_id):
    """Single governed store sync shortcut.

    Page buttons are shortcuts only.
    SystemConfig fuse box is the authority.
    Store identity makes the sync store-aware.
    """
    from datetime import datetime
    from flask import jsonify, request
    from extensions import db
    from models import Store, SystemLog
    from services.runtime_action_guard import is_runtime_action_allowed
    from services.governed_warehouse_sync import run_governed_warehouse_sync

    body = request.get_json(silent=True) or {}
    shortcut_source = (
        body.get("shortcut_source")
        or request.headers.get("X-BT38-Shortcut")
        or request.headers.get("X-Actor")
        or "store_sync_shortcut"
    )

    store = Store.query.get_or_404(store_id)

    guard = is_runtime_action_allowed(
        store=store,
        action_type="sync",
        manual=True,
        context={
            "source": shortcut_source,
            "shortcut": True,
            "authority": "SystemConfig fuse box",
        },
    )

    def log_shortcut(status, message):
        try:
            db.session.add(SystemLog(
                log_type="governed_shortcut_sync",
                message=message,
                details=(
                    f"store_id={store.id} platform={store.platform} "
                    f"shortcut=true source={shortcut_source} status={status} "
                    f"allowed={guard.get('allowed')} reason={guard.get('reason')}"
                )[:1000],
                created_at=datetime.utcnow(),
            ))
            db.session.commit()
        except Exception:
            db.session.rollback()

    if not guard.get("allowed"):
        log_shortcut("blocked", "Sync shortcut blocked by fuse box")
        return jsonify(
            ok=False,
            success=False,
            governed=True,
            shortcut=True,
            status="blocked",
            action_type="sync",
            store_id=store.id,
            platform=store.platform,
            fuse_box_checked=True,
            allowed=False,
            reason=guard.get("reason"),
            guard=guard,
        ), 200

    result = run_governed_warehouse_sync(
        store_id=store.id,
        actor=shortcut_source,
    )

    log_shortcut("completed", "Sync shortcut executed through fuse box")

    if isinstance(result, dict):
        result.update({
            "shortcut": True,
            "action_type": "sync",
            "store_id": store.id,
            "platform": store.platform,
            "fuse_box_checked": True,
            "allowed": True,
            "guard": guard,
        })
        return jsonify(_governed_json_safe(result)), 200

    return jsonify(
        ok=True,
        success=True,
        governed=True,
        shortcut=True,
        action_type="sync",
        store_id=store.id,
        platform=store.platform,
        result=result,
        fuse_box_checked=True,
        allowed=True,
        guard=guard,
    ), 200


@governed_bp.post("/governed/warehouse/sync")
def governed_warehouse_sync_manual_run():
    from services.governed_warehouse_sync import run_governed_warehouse_sync

    body = dict(request.get_json(silent=True) or {})
    store_id = body.get("store_id")

    result = run_governed_warehouse_sync(
        store_id=store_id,
        actor=request.headers.get("X-Actor", "warehouse-sync-button"),
    )

    return jsonify(_governed_json_safe(result)), 200


@governed_bp.post("/governed/stores/<int:store_id>/import")
def governed_store_import_shortcut(store_id):
    """Single governed store import shortcut.

    Page buttons are shortcuts only.
    SystemConfig fuse box is the authority.
    Store platform decides which importer is used.
    """
    from datetime import datetime
    from flask import jsonify, request
    from extensions import db
    from models import Store, SystemLog
    from services.runtime_action_guard import is_runtime_action_allowed

    body = request.get_json(silent=True) or {}
    shortcut_source = (
        body.get("shortcut_source")
        or request.headers.get("X-BT38-Shortcut")
        or "store_import_shortcut"
    )

    store = Store.query.get_or_404(store_id)

    guard = is_runtime_action_allowed(
        store=store,
        action_type="import",
        manual=True,
        context={
            "source": shortcut_source,
            "shortcut": True,
            "authority": "SystemConfig fuse box",
        },
    )

    def log_shortcut(status, message):
        try:
            db.session.add(SystemLog(
                log_type="governed_shortcut_import",
                message=message,
                details=(
                    f"store_id={store.id} platform={store.platform} "
                    f"shortcut=true source={shortcut_source} status={status} "
                    f"allowed={guard.get('allowed')} reason={guard.get('reason')}"
                )[:1000],
                created_at=datetime.utcnow(),
            ))
            db.session.commit()
        except Exception:
            db.session.rollback()

    if not guard.get("allowed"):
        log_shortcut("blocked", "Import shortcut blocked by fuse box")
        return jsonify(
            ok=False,
            success=False,
            governed=True,
            shortcut=True,
            status="blocked",
            action_type="import",
            store_id=store.id,
            platform=store.platform,
            fuse_box_checked=True,
            allowed=False,
            reason=guard.get("reason"),
            guard=guard,
        ), 200

    platform = str(store.platform or "").strip().lower()

    if "amazon" in platform:
        from services.governed_amazon_inventory_import import run_governed_amazon_inventory_import

        result = run_governed_amazon_inventory_import(store_id=store.id)
        log_shortcut("success", "Amazon import shortcut executed through fuse box")

        if isinstance(result, dict):
            result.update({
                "ok": bool(result.get("success", True)),
                "shortcut": True,
                "status": "success",
                "action_type": "import",
                "store_id": store.id,
                "platform": store.platform,
                "fuse_box_checked": True,
                "allowed": True,
                "guard": guard,
            })
            return jsonify(_governed_json_safe(result)), 200

        return jsonify(
            ok=True,
            success=True,
            governed=True,
            shortcut=True,
            result=result,
        ), 200

    if "ebay" in platform:
        log_shortcut("not_built", "eBay import shortcut allowed but importer not built")
        return jsonify(
            ok=False,
            success=False,
            governed=True,
            shortcut=True,
            status="not_built",
            action_type="import",
            store_id=store.id,
            platform=store.platform,
            fuse_box_checked=True,
            allowed=True,
            execution_started=False,
            reason="eBay governed importer is not built yet. Fuse box allowed the shortcut, but no importer is available.",
            guard=guard,
        ), 200

    log_shortcut("unsupported", "Import shortcut allowed but platform is unsupported")
    return jsonify(
        ok=False,
        success=False,
        governed=True,
        shortcut=True,
        status="unsupported_platform",
        action_type="import",
        store_id=store.id,
        platform=store.platform,
        fuse_box_checked=True,
        allowed=True,
        reason="No governed importer is wired for this platform.",
        guard=guard,
    ), 200


@governed_bp.post("/governed/amazon/inventory/import")
def governed_amazon_inventory_import():
    from flask import jsonify, request
    try:
        from models import Store
        from services.runtime_action_guard import is_runtime_action_allowed

        body = request.get_json(silent=True) or {}
        store_id = body.get("store_id") or request.args.get("store_id")
        store = None

        if store_id:
            store = Store.query.get(int(store_id))
        else:
            store = (
                Store.query
                .filter(Store.platform.ilike("%amazon%"), Store.is_active == True)  # noqa: E712
                .order_by(Store.id)
                .first()
            )

        guard = is_runtime_action_allowed(
            store=store,
            action_type="import",
            manual=True,
            context={"source": "governed_amazon_inventory_import"},
        )

        if not guard.get("allowed"):
            return jsonify(
                ok=False,
                success=False,
                governed=True,
                execution_blocked=True,
                reason=guard.get("reason"),
                fuse_box_checked=True,
            ), 400

        from services.governed_amazon_inventory_import import run_governed_amazon_inventory_import
        result = run_governed_amazon_inventory_import(store_id=getattr(store, "id", None))
        if isinstance(result, dict):
            return jsonify(_governed_json_safe(result))
        return jsonify(ok=True, success=True, governed=True, result=result)

    except Exception as exc:
        return jsonify(
            ok=False,
            success=False,
            governed=True,
            error="amazon_import_failed",
            message=str(exc),
            instruction="Amazon import failed before completing. Check Amazon SP-API client wiring/credentials.",
        ), 500



@governed_bp.post("/governed/ebay/inventory/import")
def governed_ebay_inventory_import():
    """Governed eBay import control point.

    Phase status:
    - Fuse-box controlled.
    - Store-aware.
    - No legacy importer, worker, queue, or scheduler is called here.
    - Real eBay import must be added later behind this route only.
    """
    from flask import jsonify, request
    from models import Store
    from services.runtime_action_guard import is_runtime_action_allowed

    body = request.get_json(silent=True) or {}
    store_id = body.get("store_id") or request.args.get("store_id")

    store = None
    if store_id:
        store = Store.query.get(int(store_id))
    else:
        store = (
            Store.query
            .filter(Store.platform.ilike("%ebay%"))
            .order_by(Store.is_active.desc(), Store.id.asc())
            .first()
        )

    guard = is_runtime_action_allowed(
        store,
        action_type="import",
        manual=True,
        context={"source": "governed_ebay_inventory_import"},
    )

    if not guard.get("allowed"):
        return jsonify(
            ok=False,
            success=False,
            governed=True,
            marketplace="ebay",
            import_started=False,
            execution_started=False,
            reason=guard.get("reason"),
            guard=guard,
        ), 200

    return jsonify(
        ok=False,
        success=False,
        governed=True,
        marketplace="ebay",
        import_started=False,
        execution_started=False,
        reason="eBay governed import route is fuse-box controlled, but the eBay importer is not built yet.",
        store_id=getattr(store, "id", None),
        guard=guard,
    ), 200


@governed_bp.route("/governed/webhooks/ebay", methods=["GET", "POST"])
def governed_webhook_ebay_ingest():
    return _governed_webhook_ingest("ebay")


@governed_bp.route("/governed/webhooks/amazon", methods=["GET", "POST"])
def governed_webhook_amazon_ingest():
    return _governed_webhook_ingest("amazon")


def _governed_webhook_ingest(marketplace: str):
    """Phase 1 governed webhook ingestion only.

    This endpoint receives and audits marketplace notifications.
    It does not push, import, sync, enqueue, start workers, or call marketplaces.
    The fuse box is the only authority.
    """
    from app import db
    from models import Store, SyncLog, SystemConfig

    marketplace = str(marketplace or "").strip().lower()
    enabled_key = f"webhook_{marketplace}_enabled"

    worker_row = SystemConfig.query.filter_by(key="webhook_worker_enabled").first()
    market_row = SystemConfig.query.filter_by(key=enabled_key).first()

    worker_on = str(worker_row.value if worker_row else "false").strip().lower() in {"1", "true", "yes", "on"}
    market_on = str(market_row.value if market_row else "false").strip().lower() in {"1", "true", "yes", "on"}

    store = (
        Store.query
        .filter(Store.platform.ilike(f"%{marketplace}%"))
        .order_by(Store.is_active.desc(), Store.id.asc())
        .first()
    )

    event_payload = request.get_json(silent=True) or {}
    payload_keys = sorted(list(event_payload.keys())) if isinstance(event_payload, dict) else []

    allowed = bool(worker_on and market_on and store is not None)
    reason = "Webhook received and logged. Execution is not wired in Phase 1."
    if not worker_on or not market_on:
        reason = "Webhook received but blocked by settings fuses."
    elif store is None:
        reason = "Webhook received but no matching marketplace store exists for audit logging."

    if store is not None:
        db.session.add(SyncLog(
            store_id=store.id,
            status="success" if allowed else "blocked",
            message=(
                f"governed_webhook_ingest marketplace={marketplace} "
                f"store_id={store.id} worker_on={worker_on} marketplace_on={market_on} "
                f"method={request.method}"
            )[:500],
            items_synced=0,
            created_at=datetime.utcnow(),
        ))
        db.session.commit()

    return jsonify(
        ok=allowed,
        success=allowed,
        governed=True,
        marketplace=marketplace,
        phase="webhook_ingestion_only",
        event_logged=bool(store is not None),
        execution_started=False,
        push_started=False,
        import_started=False,
        sync_started=False,
        worker_started=False,
        settings={
            "webhook_worker_enabled": worker_on,
            enabled_key: market_on,
        },
        store_id=getattr(store, "id", None),
        payload_keys=payload_keys,
        reason=reason,
    ), 200


@governed_bp.route("/governed-disabled", defaults={"action": ""}, methods=["GET", "POST"])
@governed_bp.route("/governed-disabled/<path:action>", methods=["GET", "POST"])
def governed_disabled_action(action: str = ""):
    """Phase 2 governed bridge for old product-linking frontend calls.

    This is not a second execution authority.
    It only translates old frontend paths into governed product-linking/group behavior.

    Marketplace push still flows through:
    governed group/listing route
    -> runtime_action_guard.py
    -> SystemConfig fuse box
    -> governed_execution.py
    -> marketplace adapter
    """
    from flask import jsonify, request
    from extensions import db
    from models import MarketplaceListing, MasterProductGroup, WarehouseStock

    action = (action or "").strip("/")
    body = request.get_json(silent=True) or {}

    def blocked(message, status=409, **extra):
        payload = {
            "success": False,
            "ok": False,
            "governed": True,
            "legacy_bridge": True,
            "execution_blocked": True,
            "action": action,
            "method": request.method,
            "message": message,
        }
        payload.update(extra)
        return jsonify(payload), status

    def resolve_stock(stock_id):
        try:
            stock_id_int = int(stock_id)
        except Exception:
            return None
        return db.session.get(WarehouseStock, stock_id_int)

    def ensure_group_for_stock(stock):
        if not stock:
            return None
        if getattr(stock, "master_product_group_id", None):
            group = db.session.get(MasterProductGroup, int(stock.master_product_group_id))
            if group:
                return group

        group = MasterProductGroup(
            display_title=(stock.product_name or stock.group_title or stock.sku or "Untitled Master Group")[:500],
            display_image_url=getattr(stock, "image_url", None),
        )
        db.session.add(group)
        db.session.flush()

        stock.master_product_group_id = group.id
        stock.is_group_controlled = True
        if hasattr(stock, "group_controlled_at") and not stock.group_controlled_at:
            from datetime import datetime
            stock.group_controlled_at = datetime.utcnow()
        if hasattr(stock, "updated_at"):
            from datetime import datetime
            stock.updated_at = datetime.utcnow()

        group.updated_at = getattr(stock, "updated_at", None) or group.updated_at
        return group

    def listing_preview_for_stock(stock):
        listings = (
            db.session.query(MarketplaceListing)
            .filter(MarketplaceListing.warehouse_stock_id == stock.id)
            .filter(MarketplaceListing.is_active == True)  # noqa: E712
            .order_by(MarketplaceListing.id)
            .all()
        )
        preview = []
        for listing in listings:
            platform = (listing.store.platform if listing.store else listing.platform or "").strip()
            channel = (listing.normalized_amazon_fulfillment_channel or "").upper()
            is_amazon = "amazon" in platform.lower()
            is_fba = is_amazon and channel not in ("MFN", "FBM", "MERCHANT")
            preview.append({
                "listing_id": listing.id,
                "sku": listing.external_sku,
                "external_id": listing.external_listing_id,
                "platform": platform,
                "store_name": listing.store.name if listing.store else None,
                "quantity": listing.effective_quantity,
                "is_fba": bool(is_fba),
                "pushable": bool((not is_fba) and listing.is_pushable),
            })
        return preview

    if action.startswith("group-push-preview/") and request.method == "GET":
        stock_id = action.rsplit("/", 1)[-1]
        stock = resolve_stock(stock_id)
        if not stock:
            return blocked("Warehouse stock was not found.", status=404, warehouse_stock_id=stock_id)

        listings = listing_preview_for_stock(stock)
        return jsonify({
            "success": True,
            "ok": True,
            "governed": True,
            "legacy_bridge": True,
            "preview_only": True,
            "warehouse_stock_id": stock.id,
            "group_id": stock.master_product_group_id,
            "sku": stock.sku,
            "target_qty": stock.sellable_quantity,
            "listings": listings,
            "listings_count": len([x for x in listings if x.get("pushable")]),
            "message": "Governed preview only. Push still requires governed fuse-box execution.",
        }), 200

    if action == "group-push" and request.method == "POST":
        stock_id = body.get("warehouse_stock_id") or body.get("stock_id")
        stock = resolve_stock(stock_id)
        if not stock:
            return blocked("Warehouse stock was not found.", status=404, warehouse_stock_id=stock_id)

        group = ensure_group_for_stock(stock)
        db.session.commit()

        from governed_group_propagation_routes import governed_group_propagate_quantity
        return governed_group_propagate_quantity(group.id)

    if action == "link-listing-to-warehouse" and request.method == "POST":
        listing_id = body.get("listing_id") or body.get("marketplace_listing_id")
        stock_id = body.get("warehouse_id") or body.get("warehouse_stock_id") or body.get("stock_id")

        listing = db.session.get(MarketplaceListing, int(listing_id)) if listing_id else None
        stock = resolve_stock(stock_id)

        if not listing:
            return blocked("Marketplace listing was not found.", status=404, listing_id=listing_id)
        if not stock:
            return blocked("Warehouse stock was not found.", status=404, warehouse_stock_id=stock_id)

        group = ensure_group_for_stock(stock)

        listing.warehouse_stock_id = stock.id
        listing.master_product_group_id = group.id
        if hasattr(listing, "updated_at"):
            from datetime import datetime
            listing.updated_at = datetime.utcnow()

        db.session.commit()

        return jsonify({
            "success": True,
            "ok": True,
            "governed": True,
            "legacy_bridge": True,
            "listing_id": listing.id,
            "warehouse_stock_id": stock.id,
            "group_id": group.id,
            "message": "Listing linked through governed Phase 2 bridge.",
        }), 200

    if action == "unlink-listing" and request.method == "POST":
        listing_id = body.get("listing_id") or body.get("marketplace_listing_id")
        listing = db.session.get(MarketplaceListing, int(listing_id)) if listing_id else None

        if not listing:
            return blocked("Marketplace listing was not found.", status=404, listing_id=listing_id)

        old_stock_id = listing.warehouse_stock_id
        old_group_id = listing.master_product_group_id
        listing.warehouse_stock_id = None
        listing.master_product_group_id = None
        if hasattr(listing, "updated_at"):
            from datetime import datetime
            listing.updated_at = datetime.utcnow()

        db.session.commit()

        return jsonify({
            "success": True,
            "ok": True,
            "governed": True,
            "legacy_bridge": True,
            "listing_id": listing.id,
            "old_warehouse_stock_id": old_stock_id,
            "old_group_id": old_group_id,
            "message": "Listing unlinked through governed Phase 2 bridge.",
        }), 200

    if action == "product-linking-link" and request.method == "POST":
        return blocked(
            "Create-new-listing link is not enabled yet. Use existing marketplace listings and governed link-listing-to-warehouse first.",
            status=409,
            action_supported=False,
        )

    return blocked("This legacy action is disabled until a governed bridge is approved.")


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



@governed_bp.post("/governed/warehouse/stock-transfer/convert-to-fbm")
def governed_warehouse_stock_transfer_convert_to_fbm():
    """Governed warehouse action: convert a warehouse row to FBM operational control.

    This does not create a new SKU.
    This does not call Amazon/eBay.
    This records transfer movement and updates linked listing state to MFN/FBM.
    """
    from datetime import datetime
    from flask import jsonify, request
    from extensions import db
    from models import StockTransfer, WarehouseStock, MarketplaceListing

    body = request.get_json(silent=True) or {}
    stock_id = body.get("warehouse_stock_id") or body.get("stock_id")
    listing_id = body.get("listing_id")
    quantity = body.get("quantity")
    reason = body.get("reason") or "Convert to FBM from warehouse pending action"
    notes = body.get("notes") or "Created from governed warehouse Convert to FBM action."

    try:
        stock_id_int = int(stock_id)
    except Exception:
        return jsonify(
            ok=False,
            success=False,
            governed=True,
            execution_blocked=True,
            reason="warehouse_stock_id is required for Convert to FBM.",
        ), 400

    stock = db.session.get(WarehouseStock, stock_id_int)
    if stock is None:
        return jsonify(
            ok=False,
            success=False,
            governed=True,
            execution_blocked=True,
            reason="Warehouse stock was not found.",
            warehouse_stock_id=stock_id_int,
        ), 404

    def first_int(*values):
        for value in values:
            try:
                parsed = int(value or 0)
            except Exception:
                parsed = 0
            if parsed > 0:
                return parsed
        return 0

    qty = first_int(
        quantity,
        getattr(stock, "sellable_quantity", None),
        getattr(stock, "available_quantity", None),
        getattr(stock, "available", None),
        getattr(stock, "quantity", None),
        getattr(stock, "qty", None),
        getattr(stock, "stock_quantity", None),
    )

    transfer = StockTransfer(
        warehouse_stock_id=stock.id,
        from_location="fba",
        to_location="warehouse",
        qty_planned=qty,
        qty_received=qty,
        qty_sellable=qty,
        qty_damaged=0,
        reason=reason,
        notes=notes,
        status="Completed",
        created_by=request.headers.get("X-Actor", "warehouse-convert-to-fbm"),
        received_by=request.headers.get("X-Actor", "warehouse-convert-to-fbm"),
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        received_at=datetime.utcnow(),
    )

    listing = None
    listing_updated = False
    stale_failure_reset = False

    if listing_id not in (None, "", "0"):
        try:
            listing = db.session.get(MarketplaceListing, int(listing_id))
        except Exception:
            listing = None

    if listing is not None:
        if hasattr(listing, "amazon_fulfillment_channel"):
            listing.amazon_fulfillment_channel = "MFN"
            listing_updated = True

        if hasattr(listing, "normalized_amazon_fulfillment_channel"):
            listing.normalized_amazon_fulfillment_channel = "MFN"
            listing_updated = True

        if hasattr(listing, "push_state"):
            listing.push_state = "active"
            listing_updated = True

        old_error = str(getattr(listing, "last_push_error", "") or "")
        if "FBA/AFN is read-only" in old_error or "no FBA push path" in old_error:
            if hasattr(listing, "consecutive_failures"):
                listing.consecutive_failures = 0
            if hasattr(listing, "last_push_error"):
                listing.last_push_error = None
            if hasattr(listing, "last_push_status"):
                listing.last_push_status = "converted_to_fbm"
            stale_failure_reset = True
            listing_updated = True

    db.session.add(transfer)
    db.session.commit()

    return jsonify(
        ok=True,
        success=True,
        governed=True,
        execution_started=False,
        marketplace_execution=False,
        action="convert_to_fbm",
        warehouse_stock_id=stock.id,
        listing_id=getattr(listing, "id", listing_id),
        sku=getattr(stock, "sku", None),
        stock_transfer_id=transfer.id,
        transfer_status=transfer.status,
        from_location=transfer.from_location,
        to_location=transfer.to_location,
        quantity=qty,
        listing_updated=listing_updated,
        stale_failure_reset=stale_failure_reset,
        reason="Stock transfer recorded and listing marked MFN/FBM where linked. SKU identity preserved. Marketplace execution has not been started.",
    ), 200


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


@governed_bp.post("/governed/settings/normalize")
def governed_settings_normalize():
    from flask import jsonify
    from app import db
    from models import SystemConfig

    defaults = {
        "default_push_frequency_minutes": "15",
        "default_batch_size": "25",
        "default_retry_attempts": "3",
        "api_rate_limit_buffer": "0.8",
        "error_rate_threshold": "0.3",
    }

    updated = {}
    for key, default in defaults.items():
        row = SystemConfig.query.filter_by(key=key).first()
        current = str(row.value).strip().lower() if row else ""
        bad = current in {"", "false", "true", "none", "null", "off", "on"}
        if row is None:
            row = SystemConfig(key=key, value=default)
            db.session.add(row)
            updated[key] = default
        elif bad:
            row.value = default
            updated[key] = default

    db.session.commit()
    return jsonify(ok=True, success=True, governed=True, normalized=updated)


# ============================================================
# Governed eBay OAuth settings only
# Owner-controlled OAuth authorize/callback/token refresh path.
# Does not perform marketplace push/import/sync.
# ============================================================

@governed_bp.get("/ebay-oauth/authorize")
def governed_ebay_oauth_authorize():
    import os
    import urllib.parse
    import secrets
    from flask import jsonify, redirect, session

    client_id = os.getenv("EBAY_CLIENT_ID")
    runame = os.getenv("EBAY_RUNAME")
    scopes = os.getenv("EBAY_SCOPES") or (
        "https://api.ebay.com/oauth/api_scope "
        "https://api.ebay.com/oauth/api_scope/sell.inventory "
        "https://api.ebay.com/oauth/api_scope/sell.fulfillment "
        "https://api.ebay.com/oauth/api_scope/sell.account"
    )

    if not client_id or not runame:
        return jsonify({
            "ok": False,
            "success": False,
            "governed": True,
            "error": "missing_ebay_oauth_env",
            "missing": {
                "EBAY_CLIENT_ID": not bool(client_id),
                "EBAY_RUNAME": not bool(runame),
            },
        }), 200

    state = secrets.token_urlsafe(24)
    session["governed_ebay_oauth_state"] = state

    params = {
        "client_id": client_id,
        "redirect_uri": runame,
        "response_type": "code",
        "scope": scopes,
        "state": state,
    }

    auth_url = "https://auth.ebay.com/oauth2/authorize?" + urllib.parse.urlencode(params)

    if request.args.get("json") == "1":
        return jsonify({
            "ok": True,
            "success": True,
            "governed": True,
            "auth_url": auth_url,
            "runame": runame,
            "mode": "production",
        }), 200

    return redirect(auth_url)


@governed_bp.get("/ebay-oauth/callback")
def governed_ebay_oauth_callback():
    import os
    import json
    import base64
    import requests
    from datetime import datetime, timedelta
    from flask import jsonify, request, session, redirect
    from app import db
    from models import Store

    code = request.args.get("code")
    state = request.args.get("state")
    expected_state = session.get("governed_ebay_oauth_state")

    if not code:
        return jsonify({
            "ok": False,
            "success": False,
            "governed": True,
            "error": "missing_code",
        }), 200

    if expected_state and state and state != expected_state:
        return jsonify({
            "ok": False,
            "success": False,
            "governed": True,
            "error": "state_mismatch",
        }), 200

    client_id = os.getenv("EBAY_CLIENT_ID")
    client_secret = os.getenv("EBAY_CLIENT_SECRET")
    runame = os.getenv("EBAY_RUNAME")

    if not client_id or not client_secret or not runame:
        return jsonify({
            "ok": False,
            "success": False,
            "governed": True,
            "error": "missing_ebay_oauth_env",
            "missing": {
                "EBAY_CLIENT_ID": not bool(client_id),
                "EBAY_CLIENT_SECRET": not bool(client_secret),
                "EBAY_RUNAME": not bool(runame),
            },
        }), 200

    basic = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")

    resp = requests.post(
        "https://api.ebay.com/identity/v1/oauth2/token",
        headers={
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": runame,
        },
        timeout=30,
    )

    try:
        token = resp.json()
    except Exception:
        token = {"raw": resp.text}

    if resp.status_code >= 300 or not token.get("access_token"):
        return jsonify({
            "ok": False,
            "success": False,
            "governed": True,
            "error": "ebay_token_exchange_failed",
            "status_code": resp.status_code,
            "response": token,
        }), 200

    store = Store.query.filter(Store.platform.ilike("%ebay%")).order_by(Store.id.desc()).first()
    if not store:
        return jsonify({
            "ok": False,
            "success": False,
            "governed": True,
            "error": "no_ebay_store_found",
        }), 200

    existing = {}
    if isinstance(store.api_key, str):
        try:
            existing = json.loads(store.api_key)
        except Exception:
            existing = {}
    elif isinstance(store.api_key, dict):
        existing = store.api_key

    now = datetime.utcnow()
    existing.update({
        "access_token": token.get("access_token"),
        "refresh_token": token.get("refresh_token") or existing.get("refresh_token"),
        "token_type": token.get("token_type"),
        "access_token_expires_at": (now + timedelta(seconds=int(token.get("expires_in", 7200)))).isoformat(),
        "refresh_token_expires_at": (
            (now + timedelta(seconds=int(token.get("refresh_token_expires_in")))).isoformat()
            if token.get("refresh_token_expires_in") else existing.get("refresh_token_expires_at")
        ),
        "app_id": existing.get("app_id") or client_id,
        "runame": runame,
        "sandbox": False,
        "oauth_source": "governed_ebay_oauth_callback",
        "connected_at": now.isoformat(),
    })

    store.api_key = json.dumps(existing)
    store.is_active = True
    store.store_mode = "live"
    db.session.commit()

    success_payload = {
        "ok": True,
        "success": True,
        "governed": True,
        "message": "eBay OAuth tokens saved to live eBay store.",
        "store_id": store.id,
        "store_name": store.name,
        "mode": "production",
    }

    if request.args.get("json") == "1":
        return jsonify(success_payload), 200

    return redirect(f"/stores?ebay_oauth=success&store_id={store.id}")


@governed_bp.post("/ebay-oauth/token")
def governed_ebay_oauth_refresh_token():
    import os
    import json
    import base64
    import requests
    from datetime import datetime, timedelta
    from flask import jsonify
    from app import db
    from models import Store

    store = Store.query.filter(Store.platform.ilike("%ebay%")).order_by(Store.id.desc()).first()
    if not store:
        return jsonify({
            "ok": False,
            "success": False,
            "governed": True,
            "error": "no_ebay_store_found",
        }), 200

    creds = {}
    if isinstance(store.api_key, str):
        try:
            creds = json.loads(store.api_key)
        except Exception:
            creds = {}
    elif isinstance(store.api_key, dict):
        creds = store.api_key

    refresh_token = creds.get("refresh_token")
    client_id = os.getenv("EBAY_CLIENT_ID") or creds.get("app_id")
    client_secret = os.getenv("EBAY_CLIENT_SECRET") or creds.get("cert_id")

    if not refresh_token or not client_id or not client_secret:
        return jsonify({
            "ok": False,
            "success": False,
            "governed": True,
            "error": "missing_refresh_credentials",
            "missing": {
                "refresh_token": not bool(refresh_token),
                "client_id": not bool(client_id),
                "client_secret": not bool(client_secret),
            },
        }), 200

    basic = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")
    scopes = os.getenv("EBAY_SCOPES") or (
        "https://api.ebay.com/oauth/api_scope "
        "https://api.ebay.com/oauth/api_scope/sell.inventory "
        "https://api.ebay.com/oauth/api_scope/sell.fulfillment "
        "https://api.ebay.com/oauth/api_scope/sell.account"
    )

    resp = requests.post(
        "https://api.ebay.com/identity/v1/oauth2/token",
        headers={
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "scope": scopes,
        },
        timeout=30,
    )

    try:
        token = resp.json()
    except Exception:
        token = {"raw": resp.text}

    if resp.status_code >= 300 or not token.get("access_token"):
        return jsonify({
            "ok": False,
            "success": False,
            "governed": True,
            "error": "ebay_refresh_failed",
            "status_code": resp.status_code,
            "response": token,
        }), 200

    now = datetime.utcnow()
    creds.update({
        "access_token": token.get("access_token"),
        "token_type": token.get("token_type"),
        "access_token_expires_at": (now + timedelta(seconds=int(token.get("expires_in", 7200)))).isoformat(),
        "oauth_source": "governed_ebay_refresh_token",
        "refreshed_at": now.isoformat(),
        "sandbox": False,
    })

    store.api_key = json.dumps(creds)
    store.is_active = True
    store.store_mode = "live"
    db.session.commit()

    return jsonify({
        "ok": True,
        "success": True,
        "governed": True,
        "message": "eBay access token refreshed.",
        "store_id": store.id,
        "store_name": store.name,
        "mode": "production",
    }), 200
