"""Targeted FBA cancellation safety alignment.

This module adds one owner-controlled safety fuse without creating a new
inventory system, worker, poller, full-catalogue scan, Warehouse mutation, or
FBM path.

When enabled, a successfully stored Amazon FBA/AFN cancellation uses the exact
persisted MarketplaceOrder rows to identify only the affected Seller SKU(s),
then hands those identities to the existing governed runtime verification path.
Amazon remains the FBA inventory authority.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from flask import jsonify, redirect, request, url_for


SETTING_KEY = "fba_cancel_targeted_refresh_enabled"
_TRUE_VALUES = {"1", "true", "yes", "on", "enabled"}
_FBA_TYPES = {"FBA", "AFN", "AMAZON"}


def _config_on(default: bool = False) -> bool:
    try:
        from models import SystemConfig

        row = SystemConfig.query.filter_by(key=SETTING_KEY).first()
        if row is None:
            return default
        return str(row.value or "").strip().lower() in _TRUE_VALUES
    except Exception:
        return default


def _set_config(enabled: bool):
    from extensions import db
    from models import SystemConfig

    value = "true" if bool(enabled) else "false"
    row = SystemConfig.query.filter_by(key=SETTING_KEY).first()
    if row is None:
        row = SystemConfig(key=SETTING_KEY, value=value)
        db.session.add(row)
    else:
        row.value = value
    db.session.commit()
    return value


def _owner_secret_ok(payload: dict) -> bool:
    import os

    expected = str(os.environ.get("BT38_SYNC_ALL_SECRET") or "").strip()
    provided = str((payload or {}).get("structure_secret") or "").strip()
    return bool(expected and provided and provided == expected)


def _json_payload(response):
    if isinstance(response, tuple):
        body = response[0]
        status = int(response[1]) if len(response) > 1 else 200
    else:
        body = response
        status = int(getattr(body, "status_code", 200) or 200)
    payload = body.get_json(silent=True) if hasattr(body, "get_json") else None
    return body, status, payload


def _patch_cancellation_handoff() -> None:
    import services.governed_webhook_execution as execution

    if getattr(execution, "_bt38_fba_cancel_safety_patched", False):
        return

    original = execution._handle_marketplace_cancellation

    def aligned_cancellation(*, marketplace: str, event_type: str, payload: dict):
        result = original(
            marketplace=marketplace,
            event_type=event_type,
            payload=payload,
        )
        if not isinstance(result, dict):
            return result

        # Preserve every existing cancellation behaviour. Targeted FBA work is
        # additive only after the canonical cancellation has succeeded.
        if (
            str(marketplace or "").strip().lower() != "amazon"
            or result.get("status") != "cancellation_processed"
        ):
            return result

        from models import MarketplaceOrder

        order_id = str(result.get("order_id") or "").strip()
        if not order_id:
            return result

        query = MarketplaceOrder.query.filter(
            MarketplaceOrder.marketplace_order_id == order_id
        )
        resolved_store_id = execution._deep_get(payload, "_bt38_store_id")
        try:
            resolved_store_id = (
                int(resolved_store_id)
                if resolved_store_id is not None
                else None
            )
        except (TypeError, ValueError):
            resolved_store_id = None
        if resolved_store_id is not None:
            query = query.filter(MarketplaceOrder.store_id == resolved_store_id)

        lines = query.order_by(MarketplaceOrder.id).all()
        exact = []
        seen = set()
        for line in lines:
            fulfillment = str(
                getattr(line, "fulfillment_type", None) or ""
            ).strip().upper()
            seller_sku = str(getattr(line, "sku", None) or "").strip()
            store_id = getattr(line, "store_id", None)
            if fulfillment not in _FBA_TYPES or not seller_sku or store_id is None:
                continue
            identity = (int(store_id), seller_sku)
            if identity in seen:
                continue
            seen.add(identity)
            exact.append({
                "store_id": int(store_id),
                "seller_sku": seller_sku,
                "fulfillment_type": fulfillment,
                "warehouse_stock_id": getattr(line, "warehouse_stock_id", None),
            })

        enabled = _config_on(False)
        result.update({
            "fba_cancel_targeted_refresh_enabled": enabled,
            "fba_cancel_targeted_refresh_applicable": bool(exact),
            "cancellation_store_ids": sorted({row["store_id"] for row in exact}),
            "cancellation_seller_skus": sorted({row["seller_sku"] for row in exact}),
            "stock_changed": False,
            "correction_started": False,
            "push_started": False,
        })

        if not enabled or not exact:
            result["fba_cancel_targeted_refresh"] = {
                "queued": False,
                "reason": (
                    "safety_fuse_off" if not enabled else "no_exact_fba_identity"
                ),
                "full_scan_started": False,
                "warehouse_mutation_started": False,
                "marketplace_push_started": False,
            }
            return result

        from services.governed_runtime_engine import (
            LIGHT_RECONCILE_SECONDS,
            notify_governed_runtime_work,
        )

        queued = []
        now = datetime.utcnow()
        for row in exact:
            base_event = {
                "event_type": "order_change",
                "marketplace": "amazon",
                "store_id": row["store_id"],
                "seller_sku": row["seller_sku"],
                "order_id": order_id,
                "warehouse_stock_id": row.get("warehouse_stock_id"),
                "payload": {
                    "fulfillment_type": "FBA",
                    "cancellation_targeted_refresh": True,
                },
            }

            settlement = dict(base_event)
            settlement["verify_after"] = now + timedelta(seconds=90)
            settlement_result = notify_governed_runtime_work(
                source="webhook_amazon_cancel_settlement_recheck",
                event=settlement,
            )

            follow_up = dict(base_event)
            follow_up["verify_after"] = now + timedelta(
                seconds=LIGHT_RECONCILE_SECONDS
            )
            follow_up_result = notify_governed_runtime_work(
                source="webhook_amazon_cancel_15m_reconcile",
                event=follow_up,
            )

            queued.append({
                "store_id": row["store_id"],
                "seller_sku": row["seller_sku"],
                "settlement_recheck": settlement_result,
                "light_reconcile": follow_up_result,
            })

        result["fba_inventory_verification_required"] = True
        result["fba_cancel_targeted_refresh"] = {
            "queued": True,
            "order_id": order_id,
            "sku_count": len(exact),
            "exact_skus": [row["seller_sku"] for row in exact],
            "events": queued,
            "full_scan_started": False,
            "warehouse_mutation_started": False,
            "marketplace_push_started": False,
            "fbm_changed": False,
        }
        return result

    execution._handle_marketplace_cancellation = aligned_cancellation
    execution._bt38_fba_cancel_safety_patched = True


def _patch_settings_endpoints(app) -> None:
    if getattr(app, "_bt38_fba_cancel_settings_patched", False):
        return

    config_endpoint = "governed.governed_settings_config_update"
    if config_endpoint in app.view_functions:
        original_config = app.view_functions[config_endpoint]

        def aligned_config_update():
            body = request.get_json(silent=True) or {}
            key = str(body.get("key") or "").strip()
            if key != SETTING_KEY:
                return original_config()
            if not _owner_secret_ok(body):
                return jsonify({
                    "ok": False,
                    "success": False,
                    "governed": True,
                    "locked": True,
                    "execution_blocked": True,
                    "reason": "Structure change locked. Enter the owner password to change this safety fuse.",
                }), 423
            value = _set_config(bool(body.get("value")))
            return jsonify(
                ok=True,
                success=True,
                governed=True,
                key=SETTING_KEY,
                value=value,
            )

        app.view_functions[config_endpoint] = aligned_config_update

    state_endpoint = "governed.governed_settings_state"
    if state_endpoint in app.view_functions:
        original_state = app.view_functions[state_endpoint]

        def aligned_settings_state():
            response = original_state()
            body, status, data = _json_payload(response)
            if not isinstance(data, dict):
                return response

            config = dict(data.get("config") or {})
            config[SETTING_KEY] = "true" if _config_on(False) else "false"
            data["config"] = config

            # Do not claim that legacy config toggles independently start
            # threads. Report the actual engine separately from stored config.
            live = dict(data.get("live_runtime") or {})
            engine = dict(live.get("engine") or {})
            engine_running = bool(engine.get("engine_started") or live.get("workers_running"))
            automation = dict(live.get("automation_runtime_status") or {})

            def cfg_on(key):
                return str(config.get(key, "false")).strip().lower() in _TRUE_VALUES

            for name, key in (
                ("scheduler", "scheduler_enabled"),
                ("sync_worker", "sync_worker_enabled"),
                ("push_worker", "push_worker_enabled"),
                ("retry_queue", "retry_queue_enabled"),
                ("reconcile_15m", "reconcile_15m_enabled"),
            ):
                automation[name] = (
                    "ENGINE RUNNING / CONFIG ON"
                    if engine_running and cfg_on(key)
                    else "ENGINE RUNNING / CONFIG OFF"
                    if engine_running
                    else "NOT RUNNING"
                )

            automation["webhook_worker"] = (
                "GATE ON / RUNTIME ON" if cfg_on("webhook_worker_enabled") and engine_running
                else "GATE ON / RUNTIME OFF" if cfg_on("webhook_worker_enabled")
                else "GATE OFF"
            )
            automation["webhook_ebay"] = (
                "GATE + GOVERNED RUNTIME" if cfg_on("webhook_ebay_enabled") and cfg_on("webhook_worker_enabled") and engine_running
                else "GATE ON / RUNTIME OFF" if cfg_on("webhook_ebay_enabled") and cfg_on("webhook_worker_enabled")
                else "GATE OFF"
            )
            automation["webhook_amazon"] = (
                "GATE + GOVERNED RUNTIME" if cfg_on("webhook_amazon_enabled") and cfg_on("webhook_worker_enabled") and engine_running
                else "GATE ON / RUNTIME OFF" if cfg_on("webhook_amazon_enabled") and cfg_on("webhook_worker_enabled")
                else "GATE OFF"
            )
            automation["fba_cancel_targeted_refresh"] = (
                "SAFETY FUSE ON" if cfg_on(SETTING_KEY) else "SAFETY FUSE OFF"
            )
            live["automation_runtime_status"] = automation
            data["live_runtime"] = live
            return jsonify(data), status

        app.view_functions[state_endpoint] = aligned_settings_state

    freeze_endpoint = "governed.governed_settings_emergency_freeze"
    if freeze_endpoint in app.view_functions:
        original_freeze = app.view_functions[freeze_endpoint]

        def aligned_emergency_freeze():
            response = original_freeze()
            _set_config(False)
            body, status, data = _json_payload(response)
            if isinstance(data, dict):
                updated = dict(data.get("updated") or {})
                updated[SETTING_KEY] = "false"
                data["updated"] = updated
                return jsonify(data), status
            return response

        app.view_functions[freeze_endpoint] = aligned_emergency_freeze

    page_endpoint = "governed.governed_settings_page"
    if page_endpoint in app.view_functions:
        original_page = app.view_functions[page_endpoint]

        def aligned_settings_page():
            response = original_page()
            if isinstance(response, tuple):
                html = response[0]
                status = response[1] if len(response) > 1 else 200
            else:
                html = response
                status = None
            if not isinstance(html, str):
                return response

            enabled = _config_on(False)
            checked = " checked" if enabled else ""
            row = (
                '<tr data-bt38-safety-control="fba-cancel-targeted-refresh">'
                '<td>FBA Cancellation Inventory Refresh</td>'
                '<td><label class="bt38-toggle">'
                f'<input type="checkbox"{checked} onchange="bt38ConfigUpdate(\'{SETTING_KEY}\', this.checked)">'
                '<span></span>'
                f'<b class="{"on" if enabled else "off"}">{"CONFIG ON" if enabled else "CONFIG OFF"}</b>'
                '</label></td>'
                '<td>SAFETY FUSE: When ON, a cancelled Amazon FBA/AFN order queues exact Amazon inventory verification only for the Seller SKU(s) already stored on that order. Amazon returned Available, Reserved, Inbound and Unfulfillable truth is persisted through the existing FBA inventory path. No BT38 stock arithmetic, full FBA scan, Warehouse mutation, marketplace quantity push or FBM change.</td>'
                '</tr>'
            )
            marker = '<tbody>\n        <tr><td>Push Frequency</td>'
            if marker in html and 'data-bt38-safety-control="fba-cancel-targeted-refresh"' not in html:
                html = html.replace(
                    marker,
                    '<tbody>\n        ' + row + '\n        <tr><td>Push Frequency</td>',
                    1,
                )

            # Protect the new safety fuse with the same owner-password prompt
            # used by structural automation controls.
            old_keys = '  "webhook_amazon_enabled"\n]);'
            new_keys = '  "webhook_amazon_enabled",\n  "fba_cancel_targeted_refresh_enabled"\n]);'
            html = html.replace(old_keys, new_keys, 1)

            # Correct the explanatory text: engine state is live truth; the
            # legacy CONFIG toggles are permissions/config, not proof that an
            # independent worker thread exists.
            html = html.replace(
                'CEO truth layer: Automation, webhook and import work as one governed refresh lane. Webhooks can trigger import/DB hydration only. Push remains separately governed.',
                'Runtime truth: CONFIG shows stored permission/configuration; Live Runtime shows the actual engine state. Webhook Worker plus the marketplace notification switches are direct execution gates. Scheduler/worker/reconcile CONFIG does not by itself prove that a separate worker is running. Push remains separately governed.',
                1,
            )

            return (html, status) if status is not None else html

        app.view_functions[page_endpoint] = aligned_settings_page

    app._bt38_fba_cancel_settings_patched = True


def install_governed_fba_cancellation_safety_alignment(app) -> None:
    if getattr(app, "_bt38_fba_cancel_safety_alignment_installed", False):
        return
    _patch_cancellation_handoff()
    _patch_settings_endpoints(app)
    app._bt38_fba_cancel_safety_alignment_installed = True
    app.logger.info(
        "BT38 FBA cancellation safety alignment installed: Section 5 fuse -> exact cancelled-order Seller SKU -> existing governed FBA verification"
    )
