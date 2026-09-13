"""Proof tests for the current governed execution choke point."""

from pathlib import Path
from types import SimpleNamespace

import governed_execution
from marketplace_adapters.amazon_fbm import AmazonFbmAdapter
from marketplace_adapters.ebay import EbayAdapter

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_one_governed_entry_point_and_dry_run_never_executes_live(monkeypatch):
    assert governed_execution.ONE_GOVERNED_ENTRY_POINT == "submit_governed_marketplace_action"

    monkeypatch.setattr(
        governed_execution,
        "_check_fuse_box_authority",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("dry run must not enter live fuse box")),
    )
    monkeypatch.setattr(
        governed_execution,
        "_adapter_for",
        lambda marketplace: (_ for _ in ()).throw(AssertionError("dry run must not select live adapter")),
    )

    result = governed_execution.submit_governed_marketplace_action(
        payload={
            "marketplace": "amazon",
            "action": "push_inventory",
            "sku": "FBM-SAFE-01",
            "amazon_fulfillment_channel": "MFN",
        },
        actor="test",
        dry_run=True,
    )

    assert result["governed"] is True
    assert result["dry_run"] is True
    assert result["ok"] is True
    assert result["fuse_box_checked"] is False
    assert result["execution_started"] is False


def test_live_action_must_pass_fuse_box_before_adapter(monkeypatch):
    store = SimpleNamespace(
        id=1,
        name="Amazon",
        platform="Amazon",
        is_active=True,
        fbm_sync_enabled=True,
        store_mode="live",
        api_key="credentials",
    )
    listing = SimpleNamespace(
        id=2,
        store_id=1,
        external_sku="FBM-SAFE-01",
        amazon_fulfillment_channel="MFN",
    )
    monkeypatch.setattr(governed_execution, "_resolve_store", lambda store_id: store)
    monkeypatch.setattr(governed_execution, "_resolve_listing", lambda listing_id: listing)
    monkeypatch.setattr(
        governed_execution,
        "_check_fuse_box_authority",
        lambda *args, **kwargs: {"allowed": False, "reason": "Fuse box push_enabled is OFF"},
    )
    monkeypatch.setattr(
        governed_execution,
        "_adapter_for",
        lambda marketplace: (_ for _ in ()).throw(AssertionError("blocked live action must not select adapter")),
    )

    result = governed_execution.submit_governed_marketplace_action(
        payload={
            "marketplace": "amazon",
            "action": "push_inventory",
            "sku": "FBM-SAFE-01",
            "store_id": 1,
            "listing_id": 2,
            "quantity": 4,
            "amazon_fulfillment_channel": "MFN",
        },
        actor="test",
        dry_run=False,
    )

    assert result["ok"] is False
    assert result["fuse_box_checked"] is True
    assert result["execution_started"] is False
    assert "Fuse box" in result["reason"]


def test_fuse_approved_live_action_enters_exact_marketplace_adapter(monkeypatch):
    store = SimpleNamespace(
        id=1,
        name="Amazon",
        platform="Amazon",
        is_active=True,
        fbm_sync_enabled=True,
        store_mode="live",
        api_key="credentials",
    )
    listing = SimpleNamespace(
        id=2,
        store_id=1,
        external_sku="FBM-SAFE-01",
        amazon_fulfillment_channel="MFN",
    )
    calls = []
    monkeypatch.setattr(governed_execution, "_resolve_store", lambda store_id: store)
    monkeypatch.setattr(governed_execution, "_resolve_listing", lambda listing_id: listing)
    monkeypatch.setattr(
        governed_execution,
        "_check_fuse_box_authority",
        lambda *args, **kwargs: {"allowed": True, "reason": "Fuse box allowed action"},
    )

    class FakeAdapter:
        def execute(self, action, payload):
            calls.append((action, payload))
            return {"ok": True, "success": True, "reason": "done"}

    monkeypatch.setattr(governed_execution, "_adapter_for", lambda marketplace: FakeAdapter())
    result = governed_execution.submit_governed_marketplace_action(
        payload={
            "marketplace": "amazon",
            "action": "push_inventory",
            "sku": "FBM-SAFE-01",
            "store_id": 1,
            "listing_id": 2,
            "quantity": 4,
            "amazon_fulfillment_channel": "MFN",
        },
        actor="test",
        dry_run=False,
    )

    assert result["ok"] is True
    assert len(calls) == 1
    assert calls[0][0] == "push_inventory"
    assert calls[0][1]["_governed_fuse_box_checked"] is True


def test_amazon_adapter_blocks_fba_unknown_and_unprepared_live_payload():
    adapter = AmazonFbmAdapter()

    fba = adapter.execute(
        "push_inventory",
        {"sku": "FBA-CG-UN-05", "amazon_fulfillment_channel": "AFN"},
    )
    unknown = adapter.execute(
        "push_inventory",
        {"sku": "UNKNOWN-01", "amazon_fulfillment_channel": ""},
    )
    fbm = adapter.execute(
        "push_inventory",
        {"sku": "FBM-SAFE-01", "amazon_fulfillment_channel": "MFN"},
    )

    assert fba["execution_blocked"] is True
    assert "read-only" in fba["reason"]
    assert unknown["execution_blocked"] is True
    assert "unknown" in unknown["reason"].lower()
    assert fbm["execution_blocked"] is True


def test_ebay_adapter_fails_closed_before_network_without_governed_store(monkeypatch):
    import marketplace_adapters.ebay as ebay_module

    monkeypatch.setattr(
        ebay_module.requests,
        "post",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network must not run without governed store")),
    )
    result = EbayAdapter().execute(
        "push_inventory",
        {"sku": "EB-OD-CR-100g-X3", "marketplace": "ebay"},
    )

    assert result["marketplace"] == "ebay"
    assert result["execution_blocked"] is True
    assert "Missing store" in result["reason"]


def test_execution_choke_point_has_no_worker_scheduler_or_queue_execution():
    governed = read("governed_execution.py")
    forbidden = [
        "threading",
        "BackgroundScheduler",
        "APScheduler",
        "enqueue_sync_job",
        "queue_manager",
    ]
    for marker in forbidden:
        assert marker not in governed, marker

    assert "def submit_governed_marketplace_action" in governed
    assert "_check_fuse_box_authority" in governed
    assert "_adapter_for(command.marketplace)" in governed
