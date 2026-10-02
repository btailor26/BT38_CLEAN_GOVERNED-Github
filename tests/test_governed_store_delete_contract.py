from pathlib import Path


SOURCE = Path("governed_routes.py").read_text(encoding="utf-8")


def _delete_route():
    start = SOURCE.index('@governed_bp.post("/governed/stores/<int:store_id>/delete-preview")')
    end = SOURCE.index("\ndef _governed_marketplace_account_id", start)
    return SOURCE[start:end]


def test_store_delete_is_customer_account_scoped_for_every_marketplace():
    route = _delete_route()
    assert "_bt38_customer_store_or_404(store_id)" in route
    assert "@login_required" in route
    assert "platform.ilike" not in route
    assert "Amazon" not in route
    assert "eBay" not in route


def test_store_delete_never_calls_marketplace():
    route = _delete_route()
    assert '"marketplace_action": False' in route
    assert "requests." not in route
    assert "governed_ebay" not in route
    assert "governed_amazon" not in route


def test_store_delete_blocks_running_work_and_retires_queue_dependency():
    route = _delete_route()
    assert 'SyncJob.status == "running"' in route
    assert '"store_has_running_work"' in route
    assert "SyncJob.query.filter(SyncJob.store_id == deleted_store_id).delete" in route
    assert "db.session.delete(store)" in route
