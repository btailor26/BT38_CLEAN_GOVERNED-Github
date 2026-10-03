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


def test_store_delete_revokes_persisted_ebay_authority_before_local_delete():
    route = _delete_route()
    revoke = route.index("revoke_persisted_ebay_grant(store)")
    delete = route.index("db.session.delete(store)")
    assert revoke < delete
    assert '"authorization_revoked"' in route
    assert '"marketplace_action": bool(marketplace_disconnect.get("marketplace_action"))' in route
    assert '"marketplace_disconnect_failed"' in route
    assert "db.session.rollback()" in route
    assert "requests." not in route


def test_store_delete_blocks_running_work_and_retires_queue_dependency():
    route = _delete_route()
    assert 'SyncJob.status == "running"' in route
    assert '"store_has_running_work"' in route
    assert "SyncJob.query.filter(SyncJob.store_id == deleted_store_id).delete" in route
    assert "db.session.delete(store)" in route
