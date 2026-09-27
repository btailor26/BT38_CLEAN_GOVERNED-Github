from pathlib import Path

TEMPLATE = (Path(__file__).resolve().parents[1] / "templates" / "fbm.html").read_text()


def test_unverified_source_uses_existing_persisted_mapping_review():
    assert "mapping_review and mapping_review.status == 'under_review' and carrier_mapping" in TEMPLATE
    assert 'class="badge bg-secondary border-0 source-unverified-mapping"' in TEMPLATE
    assert 'data-mapping-id="{{ carrier_mapping.id }}"' in TEMPLATE
    assert "Map this exact carrier/service using the existing saved mapping workflow" in TEMPLATE


def test_unverified_badge_opens_existing_mapping_editor_without_new_mapping_path():
    assert "closest('.source-unverified-mapping')" in TEMPLATE
    assert "document.querySelector(`.mapping-editor[data-mapping-id=" in TEMPLATE
    assert "scrollIntoView({behavior:'smooth',block:'center'})" in TEMPLATE
    assert "save-inline-mapping" in TEMPLATE
    assert "/fbm/carrier-mappings/${button.dataset.mappingId}/verify" in TEMPLATE
