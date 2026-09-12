from pathlib import Path


SERVICE = Path("services/support_attachment_alignment.py").read_text(encoding="utf-8")
TEMPLATE = Path("templates/support_case.html").read_text(encoding="utf-8")
INIT = Path("services/__init__.py").read_text(encoding="utf-8")


def test_support_attachment_storage_is_private_and_durable():
    assert '__tablename__ = "support_case_attachments"' in SERVICE
    assert "db.LargeBinary" in SERVICE
    assert "db.ForeignKey(\"support_cases.id\"" in SERVICE
    assert "db.create_all()" in SERVICE
    assert "send_from_directory" not in SERVICE
    assert "static_folder" not in SERVICE
    assert "os.path.join" not in SERVICE
    assert "import services.support_attachment_alignment" in INIT


def test_upload_is_case_scoped_bounded_and_content_verified():
    assert '@app.post("/support/cases/<case_id>/attachments")' in SERVICE
    assert "case = _case_or_404(case_id)" in SERVICE
    assert "MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024" in SERVICE
    assert "MAX_UPLOAD_BYTES = 10 * 1024 * 1024" in SERVICE
    assert "MAX_FILES_PER_UPLOAD = 3" in SERVICE
    assert "MAX_ATTACHMENTS_PER_CASE = 25" in SERVICE
    assert "_verified_content_type(safe_name, payload)" in SERVICE
    assert "payload.startswith(b\"%PDF-\")" in SERVICE
    assert "payload.startswith(b\"\\x89PNG\\r\\n\\x1a\\n\")" in SERVICE
    assert "payload.startswith(b\"\\xff\\xd8\\xff\")" in SERVICE
    assert 'payload[:4] == b"RIFF" and payload[8:12] == b"WEBP"' in SERVICE
    assert "secure_filename(original)" in SERVICE


def test_download_rechecks_case_scope_and_forces_attachment():
    assert '@app.get("/support/cases/<case_id>/attachments/<int:attachment_id>")' in SERVICE
    download_block = SERVICE.split("def bt38_support_download_attachment", 1)[1]
    assert "case = _case_or_404(case_id)" in download_block
    assert "case_pk=case.id" in download_block
    assert "as_attachment=True" in download_block
    assert 'response.headers["X-Content-Type-Options"] = "nosniff"' in download_block
    assert 'response.headers["Cache-Control"] = "private, no-store, max-age=0"' in download_block
    assert 'response.headers["Content-Security-Policy"] = "default-src \'none\'; sandbox"' in download_block


def test_case_ui_uses_private_multipart_evidence_form():
    assert 'action="/support/cases/{{ case.case_id }}/attachments"' in TEMPLATE
    assert 'enctype="multipart/form-data"' in TEMPLATE
    assert 'name="attachments"' in TEMPLATE
    assert 'accept=".png,.jpg,.jpeg,.webp,.pdf,.txt,.csv"' in TEMPLATE
    assert "/support/cases/{{ case.case_id }}/attachments/{{ attachment.id }}" in TEMPLATE
    assert "Files stay private to this case." in TEMPLATE


def test_attachment_layer_has_no_external_execution_path():
    lowered = SERVICE.lower()
    for forbidden in (
        "requests.",
        "httpx",
        "amazon",
        "ebay",
        "revolut",
        "packlink",
        "marketplaceorder",
        "marketplacelisting",
    ):
        assert forbidden not in lowered
