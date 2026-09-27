from pathlib import Path

ALIGNMENT = (Path(__file__).resolve().parents[1] / "services" / "governed_fbm_dispatch_queue_alignment.py").read_text()


def test_sds_is_display_badge_only_and_not_amazon_or_queue_logic():
    assert "Seller Delivery Service" in ALIGNMENT
    assert "var sdsBadge=document.createElement('span')" in ALIGNMENT
    assert "sdsBadge.textContent='SDS'" in ALIGNMENT
    assert "addWorkflowButton(tabBar,'sds'" not in ALIGNMENT


def test_manual_upload_accepts_all_formats_and_routes_to_existing_support_review():
    assert "manualUploadInput.type='file'" in ALIGNMENT
    assert "manualUploadInput.accept=" not in ALIGNMENT
    assert "manualUploadInput.multiple=true" in ALIGNMENT
    assert "manualUploadInput.click()" in ALIGNMENT
    assert "/support/cases/manual-upload-review" in ALIGNMENT
    assert "Under Review · " in ALIGNMENT
