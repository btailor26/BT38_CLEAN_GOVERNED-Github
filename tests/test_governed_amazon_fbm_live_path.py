"""Contracts for the one governed Amazon FBM live path.

The current execution authority is the SystemConfig + Store fuse box through
services.runtime_action_guard. Legacy dual runtime flags and approval objects
are intentionally not part of this path.
"""

from __future__ import annotations

from types import SimpleNamespace

import governed_execution
import queue_manager
import shutdown_http_guard


def live_payload(**overrides):
    payload = {
        "marketplace": "amazon",
        "action": "push_inventory",
        "sku": "FBM-SAFE-01",
        "store_id": 10,
        "listing_id": 20,
        "quantity": 7,
        "amazon_fulfillment_channel": "MFN",
        "marketplace_id": "A1F83G8C2ARO7P",
    }
    payload.update(overrides)
    return payload


def patch_valid_store_and_listing(monkeypatch, *, fulfillment="MFN", sku="FBM-SAFE-01"):
    store = SimpleNamespace(
        id=10,
        name="Amazon-Test",
        platform="Amazon",
        is_active=True,
        fbm_sync_enabled=True,
        store_mode="live",
        api_key="test-credentials",
    )
    listing = SimpleNamespace(
        id=20,
        store_id=10,
        external_sku=sku,
        amazon_fulfillment_channel=fulfillment,
    )
    monkeypatch.setattr(governed_execution, "_resolve_store", lambda store_id: store)
    monkeypatch.setattr(governed_execution, "_resolve_listing", lambda listing_id: listing)
    return store, listing


def test_fba_live_push_blocked_before_adapter(monkeypatch):
    payload = live_payload(sku="FBA-CG-UN-05", amazon_fulfillment_channel="AFN")
    patch_valid_store_and_listing(monkeypatch, fulfillment="AFN", sku="FBA-CG-UN-05")
    monkeypatch.setattr(
        governed_execution,
        "_adapter_for",
        lambda _marketplace: (_ for _ in ()).throw(AssertionError("FBA must block before adapter")),
    )

    result = governed_execution.submit_governed_marketplace_action(
        payload=payload,
        actor="pytest",
        dry_run=False,
    )

    assert result["ok"] is False
    assert result["governed"] is True
    assert "read-only" in result["reason"]


def test_unknown_fulfillment_live_push_blocked_before_adapter(monkeypatch):
    payload = live_payload(amazon_fulfillment_channel="")
    patch_valid_store_and_listing(monkeypatch, fulfillment="")
    monkeypatch.setattr(
        governed_execution,
        "_adapter_for",
        lambda _marketplace: (_ for _ in ()).throw(AssertionError("unknown fulfillment must block before adapter")),
    )

    result = governed_execution.submit_governed_marketplace_action(
        payload=payload,
        actor="pytest",
        dry_run=False,
    )

    assert result["ok"] is False
    assert "unknown" in result["reason"].lower()


def test_fuse_box_blocks_live_push_before_adapter(monkeypatch):
    payload = live_payload()
    patch_valid_store_and_listing(monkeypatch)
    monkeypatch.setattr(
        governed_execution,
        "_check_fuse_box_authority",
        lambda *args, **kwargs: {
            "allowed": False,
            "reason": "Fuse box marketplace_push_enabled is OFF",
            "fuse_box_checked": True,
        },
    )
    monkeypatch.setattr(
        governed_execution,
        "_adapter_for",
        lambda _marketplace: (_ for _ in ()).throw(AssertionError("closed fuse box must block before adapter")),
    )

    result = governed_execution.submit_governed_marketplace_action(
        payload=payload,
        actor="pytest",
        dry_run=False,
    )

    assert result["ok"] is False
    assert result["fuse_box_checked"] is True
    assert result["execution_started"] is False
    assert "fuse box" in result["reason"].lower()


def test_fbm_dry_run_never_checks_fuse_or_calls_adapter(monkeypatch):
    payload = live_payload()
    patch_valid_store_and_listing(monkeypatch)
    monkeypatch.setattr(
        governed_execution,
        "_check_fuse_box_authority",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("dry run must not consult live fuse box")),
    )
    monkeypatch.setattr(
        governed_execution,
        "_adapter_for",
        lambda _marketplace: (_ for _ in ()).throw(AssertionError("dry run must not call adapter")),
    )

    result = governed_execution.submit_governed_marketplace_action(
        payload=payload,
        actor="pytest",
        dry_run=True,
    )

    assert result["ok"] is True
    assert result["success"] is True
    assert result["dry_run"] is True
    assert result["fuse_box_checked"] is False
    assert result["execution_started"] is False


def test_live_push_must_pass_fuse_box_before_adapter(monkeypatch):
    payload = live_payload()
    store, listing = patch_valid_store_and_listing(monkeypatch)
    calls = []

    def allow_fuse(command, eligibility, actor_user=None):
        calls.append(("fuse", command.action, eligibility["store"].id))
        return {
            "allowed": True,
            "reason": "Fuse box allowed action",
            "fuse_box_checked": True,
        }

    class FakeAdapter:
        def execute(self, action, adapter_payload):
            calls.append(("adapter", action, adapter_payload["quantity"]))
            return {"success": True, "ok": True, "reason": "fake adapter reached"}

    monkeypatch.setattr(governed_execution, "_check_fuse_box_authority", allow_fuse)
    monkeypatch.setattr(governed_execution, "_adapter_for", lambda marketplace: FakeAdapter())

    result = governed_execution.submit_governed_marketplace_action(
        payload=payload,
        actor="pytest",
        dry_run=False,
        approval_type="amazon_fbm_single_sku_inventory_push",
        approval_id="approval-1",
    )

    assert result["ok"] is True
    assert result["fuse_box_checked"] is True
    assert calls[0] == ("fuse", "push_inventory", 10)
    assert calls[1] == ("adapter", "push_inventory", 7)


def test_live_adapter_payload_preserves_exact_validated_store_listing_and_approval_metadata(monkeypatch):
    payload = live_payload()
    store, listing = patch_valid_store_and_listing(monkeypatch)
    captured = {}

    monkeypatch.setattr(
        governed_execution,
        "_check_fuse_box_authority",
        lambda *args, **kwargs: {"allowed": True, "reason": "Fuse box allowed action"},
    )

    class FakeAdapter:
        def execute(self, action, adapter_payload):
            captured.update(adapter_payload)
            return {"success": True, "ok": True}

    monkeypatch.setattr(governed_execution, "_adapter_for", lambda marketplace: FakeAdapter())
    result = governed_execution.submit_governed_marketplace_action(
        payload=payload,
        dry_run=False,
        actor="pytest",
        approval_type="amazon_fbm_single_sku_inventory_push",
        approval_id="approval-1",
    )

    assert result["ok"] is True
    assert captured["_governed_store"] is store
    assert captured["_governed_listing"] is listing
    assert captured["_governed_dry_run"] is False
    assert captured["_governed_fuse_box_checked"] is True
    assert captured["_governed_approval_type"] == "amazon_fbm_single_sku_inventory_push"
    assert captured["_governed_approval_id"] == "approval-1"


def test_amazon_adapter_live_calls_single_governed_service_method(monkeypatch):
    from marketplace_adapters import amazon_fbm

    payload = live_payload(
        _governed_dry_run=False,
        _governed_store=SimpleNamespace(id=10),
        _governed_listing=SimpleNamespace(id=20),
        _governed_command_id="cmd-1",
        _governed_approval_id="approval-1",
    )
    calls = []

    class FakeAmazonService:
        def update_fbm_inventory_quantity_governed(self, **kwargs):
            calls.append(kwargs)
            return {"success": True, "ok": True, "service": "fake"}

    import amazon_service

    monkeypatch.setattr(amazon_service, "AmazonAPIService", FakeAmazonService)
    result = amazon_fbm.AmazonFbmAdapter().execute("push_inventory", payload)

    assert result["ok"] is True
    assert result["execution_blocked"] is False
    assert calls[0]["sku"] == "FBM-SAFE-01"
    assert calls[0]["quantity"] == 7
    assert calls[0]["fulfillment_channel"] == "MFN"


def test_route_still_dry_run_only_and_old_paths_remain_blocked():
    route_source = open("governed_routes.py", encoding="utf-8").read().split('@governed_bp.post("/governed/actions/sku/dry-run")', 1)[1]
    assert "submit_governed_marketplace_action" in route_source
    assert "dry_run=True" in route_source
    assert "AmazonAPIService" not in route_source
    assert "AmazonFbmAdapter" not in route_source
    assert shutdown_http_guard.is_shutdown_path("/api/push-sku") is True
    assert shutdown_http_guard.is_shutdown_path("/api/sync/amazon/sku/FBA-CG-UN-05") is True
    result = queue_manager.enqueue_sync_job(1, queue_manager.JOB_PUSH_ITEM, {"sku": "FBM-SAFE-01"})
    assert result["execution_blocked"] is True
