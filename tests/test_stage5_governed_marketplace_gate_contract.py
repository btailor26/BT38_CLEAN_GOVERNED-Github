"""Stage 5 contracts for the current one clean governed marketplace path.

Current authority:
UI/governed caller -> governed_execution -> SystemConfig + Store fuse box -> adapter.
Legacy dual runtime flags and approval dictionaries are retired.
"""

from __future__ import annotations

from types import SimpleNamespace

import governed_execution
import queue_manager
import shutdown_http_guard
from services import runtime_action_guard


def live_payload(**overrides):
    payload = {
        "marketplace": "amazon",
        "action": "push_inventory",
        "sku": "FBM-STAGE5-01",
        "store_id": 101,
        "listing_id": 202,
        "quantity": 9,
        "amazon_fulfillment_channel": "MFN",
        "marketplace_id": "A1F83G8C2ARO7P",
    }
    payload.update(overrides)
    return payload


def patch_valid_store_and_listing(monkeypatch, *, fulfillment="MFN", sku="FBM-STAGE5-01"):
    store = SimpleNamespace(
        id=101,
        name="Amazon Stage5",
        platform="Amazon",
        is_active=True,
        fbm_sync_enabled=True,
        store_mode="live",
        api_key="test-credentials",
    )
    listing = SimpleNamespace(
        id=202,
        store_id=101,
        external_sku=sku,
        amazon_fulfillment_channel=fulfillment,
    )
    monkeypatch.setattr(governed_execution, "_resolve_store", lambda store_id: store)
    monkeypatch.setattr(governed_execution, "_resolve_listing", lambda listing_id: listing)
    return store, listing


def test_stage5_dry_run_is_eligible_but_never_executes_live(monkeypatch):
    payload = live_payload()
    patch_valid_store_and_listing(monkeypatch)
    monkeypatch.setattr(
        governed_execution,
        "_check_fuse_box_authority",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("dry-run must not enter live fuse box")),
    )
    monkeypatch.setattr(
        governed_execution,
        "_adapter_for",
        lambda _marketplace: (_ for _ in ()).throw(AssertionError("dry-run must not select adapter")),
    )

    result = governed_execution.submit_governed_marketplace_action(
        payload=payload,
        actor="stage5-test",
        dry_run=True,
    )

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["fuse_box_checked"] is False
    assert result["execution_started"] is False


def test_stage5_fba_and_unknown_fulfillment_fail_before_live_authority(monkeypatch):
    for payload in (
        live_payload(sku="FBA-STAGE5-01", amazon_fulfillment_channel="AFN"),
        live_payload(sku="UNKNOWN-STAGE5-01", amazon_fulfillment_channel=""),
    ):
        monkeypatch.setattr(
            governed_execution,
            "_check_fuse_box_authority",
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("ineligible Amazon listing must fail before fuse box")),
        )
        result = governed_execution.submit_governed_marketplace_action(
            payload=payload,
            actor="stage5-test",
            dry_run=False,
        )
        assert result["ok"] is False
        assert result["governed"] is True
        assert "read-only" in result["reason"] or "unknown" in result["reason"].lower()


def test_stage5_exact_store_and_listing_validation_precedes_fuse_box(monkeypatch):
    payload = live_payload()
    monkeypatch.setattr(governed_execution, "_resolve_store", lambda store_id: None)
    monkeypatch.setattr(
        governed_execution,
        "_check_fuse_box_authority",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("missing store must fail before fuse box")),
    )

    result = governed_execution.submit_governed_marketplace_action(
        payload=payload,
        actor="stage5-test",
        dry_run=False,
    )

    assert result["ok"] is False
    assert "missing store" in result["reason"].lower()


def test_stage5_fuse_box_denial_stops_before_adapter(monkeypatch):
    payload = live_payload()
    patch_valid_store_and_listing(monkeypatch)
    monkeypatch.setattr(
        governed_execution,
        "_check_fuse_box_authority",
        lambda *args, **kwargs: {
            "allowed": False,
            "reason": "Fuse box runtime_push_enabled is OFF",
            "fuse_box_checked": True,
        },
    )
    monkeypatch.setattr(
        governed_execution,
        "_adapter_for",
        lambda _marketplace: (_ for _ in ()).throw(AssertionError("denied action must not select adapter")),
    )

    result = governed_execution.submit_governed_marketplace_action(
        payload=payload,
        actor="stage5-test",
        dry_run=False,
    )

    assert result["ok"] is False
    assert result["fuse_box_checked"] is True
    assert result["execution_started"] is False
    assert "runtime_push_enabled" in result["reason"]


def test_stage5_live_execution_reaches_adapter_only_after_fuse_allow(monkeypatch):
    payload = live_payload()
    patch_valid_store_and_listing(monkeypatch)
    calls = []

    def fuse_allow(command, eligibility, actor_user=None):
        calls.append("fuse")
        return {"allowed": True, "reason": "Fuse box allowed action"}

    class FakeAdapter:
        def execute(self, action, adapter_payload):
            calls.append("adapter")
            assert adapter_payload["_governed_fuse_box_checked"] is True
            assert adapter_payload["_governed_store"].id == 101
            assert adapter_payload["_governed_listing"].id == 202
            return {"success": True, "ok": True, "reason": "fake adapter reached"}

    monkeypatch.setattr(governed_execution, "_check_fuse_box_authority", fuse_allow)
    monkeypatch.setattr(governed_execution, "_adapter_for", lambda marketplace: FakeAdapter())

    result = governed_execution.submit_governed_marketplace_action(
        payload=payload,
        actor="stage5-test",
        dry_run=False,
        approval_type="amazon_fbm_single_sku_inventory_push",
        approval_id="stage5-proof",
    )

    assert result["ok"] is True
    assert result["fuse_box_checked"] is True
    assert calls == ["fuse", "adapter"]


def test_stage5_manual_push_uses_manual_fuse_requirements(monkeypatch):
    required = runtime_action_guard._required_fuses("push", manual=True)
    assert required == [
        "push_enabled",
        "runtime_push_enabled",
        "marketplace_push_enabled",
        "manual_push_enabled",
    ]


def test_stage5_automatic_webhook_push_uses_same_fuse_box_without_manual_fuse(monkeypatch):
    payload = live_payload(source="webhook_amazon_order")
    store, listing = patch_valid_store_and_listing(monkeypatch)
    command = governed_execution._build_command(payload=payload, dry_run=False, actor="marketplace_webhook")
    eligibility = governed_execution._check_marketplace_eligibility(command)
    captured = {}

    def fake_guard(store, action_type, manual=False, context=None):
        captured.update(
            store=store,
            action_type=action_type,
            manual=manual,
            context=context,
        )
        return {"allowed": True, "reason": "test"}

    monkeypatch.setattr(runtime_action_guard, "is_runtime_action_allowed", fake_guard)
    result = governed_execution._check_fuse_box_authority(command, eligibility)

    assert result["allowed"] is True
    assert captured["store"] is store
    assert captured["action_type"] == "push"
    assert captured["manual"] is False
    assert captured["context"]["automatic_push"] is True


def test_real_fba_sku_sr_ay_tc_80g_stays_read_only_before_adapter(monkeypatch):
    payload = live_payload(
        sku="FBA-SR-AY-TC-80g",
        amazon_fulfillment_channel="AFN",
        quantity=1,
    )
    monkeypatch.setattr(
        governed_execution,
        "_adapter_for",
        lambda _marketplace: (_ for _ in ()).throw(AssertionError("FBA stop-transfer must not select adapter")),
    )

    result = governed_execution.submit_governed_marketplace_action(
        payload=payload,
        actor="stage5-real-fba-stop-transfer-test",
        dry_run=False,
    )

    assert result["governed"] is True
    assert result["ok"] is False
    assert result["marketplace"] == "amazon"
    assert result["action"] == "push_inventory"
    assert "FBA/AFN is read-only" in result["reason"]


def test_stage5_http_route_remains_dry_run_only_and_old_paths_stay_shutdown():
    route_source = open("governed_routes.py", encoding="utf-8").read().split(
        '@governed_bp.post("/governed/actions/sku/dry-run")',
        1,
    )[1]
    assert "submit_governed_marketplace_action" in route_source
    assert "dry_run=True" in route_source
    assert "AmazonAPIService" not in route_source
    assert "AmazonFbmAdapter" not in route_source
    assert shutdown_http_guard.is_shutdown_path("/api/push-sku") is True
    assert shutdown_http_guard.is_shutdown_path("/api/sync/amazon/sku/FBA-CG-UN-05") is True

    result = queue_manager.enqueue_sync_job(1, queue_manager.JOB_PUSH_ITEM, {"sku": "FBM-STAGE5-01"})
    assert result["execution_blocked"] is True
