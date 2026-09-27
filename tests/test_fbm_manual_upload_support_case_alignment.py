from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUPPORT = (ROOT / "services" / "support_case_alignment.py").read_text()
MIGRATION = (ROOT / "migrations" / "manual" / "20260911-support-cases.sql").read_text()
CASE = (ROOT / "templates" / "support_case.html").read_text()


def test_manual_upload_reuses_existing_support_case_authority():
    assert '@app.post("/support/cases/manual-upload-review")' in SUPPORT
    assert 'category="data_review"' in SUPPORT
    assert 'case.case_id = _case_number(case)' in SUPPORT
    assert 'review_state": "under_review"' in SUPPORT
    assert 'SupportCaseAttachment' in SUPPORT
    assert 'support_case_attachments' in MIGRATION


def test_unknown_upload_does_not_guess_operational_truth():
    assert "Admin mapping is required before any operational truth may be updated." in SUPPORT
    assert "MarketplaceOrder.query" in SUPPORT
    for token in ("FBMShipment", "WarehouseStock"):
        assert token not in SUPPORT


def test_uploaded_evidence_is_admin_reviewable_on_existing_case():
    assert "Uploaded evidence" in CASE
    assert "Only Admin can map or approve an unknown format." in CASE
    assert '@app.get("/admin/support/cases/<case_id>/attachments/<int:attachment_id>")' in SUPPORT
    assert "if not _is_admin()" in SUPPORT


def test_manual_upload_checks_persisted_db_truth_before_support_fallback():
    source = SUPPORT.read_text(encoding="utf-8")
    route = source.split('@app.post("/support/cases/manual-upload-review")', 1)[1].split('@app.get("/admin/support/cases/', 1)[0]
    assert "MarketplaceOrder.query" in route
    assert "matched_order_ids" in route
    assert '"completed": True' in route
    assert route.index("MarketplaceOrder.query") < route.index("case = SupportCase(")
    assert "no marketplace/provider call" in route.lower()
    assert "db.session.commit()" in route


def test_existing_attachment_table_is_additively_aligned_before_upload():
    assert "ALTER TABLE support_case_attachments ADD COLUMN IF NOT EXISTS size_bytes" in MIGRATION
    assert "ALTER TABLE support_case_attachments ADD COLUMN IF NOT EXISTS content BYTEA" in MIGRATION
    assert "def _align_support_attachment_schema()" in SUPPORT
    assert "db.create_all()" in SUPPORT
    assert SUPPORT.index("db.create_all()") < SUPPORT.index("_align_support_attachment_schema()")


def test_manual_upload_populates_live_attachment_authority_columns():
    assert "uploader_role = db.Column" in SUPPORT
    assert "byte_size = db.Column" in SUPPORT
    assert "sha256_hex = db.Column" in SUPPORT
    assert "payload = db.Column" in SUPPORT
    route = SUPPORT.split('@app.post("/support/cases/manual-upload-review")', 1)[1].split('@app.get("/admin/support/cases/', 1)[0]
    assert 'uploader_role="admin" if _is_admin() else "customer"' in route
    assert "byte_size=evidence_size" in route
    assert "hashlib.sha256(payload).hexdigest()" in route
    assert "payload=payload" in route
    assert "size_bytes=evidence_size" in route
    assert "content=payload" in route


def test_attachment_download_supports_existing_and_newer_payload_alias():
    assert "attachment.content if attachment.content is not None else attachment.payload" in SUPPORT
