from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DB_AUTHORITY = (ROOT / "services" / "governed_fbm_db_authority_alignment.py").read_text(encoding="utf-8")
MARKETPLACE_AUTHORITY = (ROOT / "services" / "governed_fbm_marketplace_dispatch_authority_alignment.py").read_text(encoding="utf-8")


def test_late_db_authority_preserves_existing_marketplace_dispatch_wrapper():
    assert '_bt38_marketplace_dispatch_authority_aligned' in DB_AUTHORITY
    assert 'authority_map = (' in DB_AUTHORITY
    assert 'page._shipment_map' in DB_AUTHORITY
    assert 'else _canonical_persisted_shipment_map' in DB_AUTHORITY
    assert 'routes._shipment_map = authority_map' in DB_AUTHORITY
    assert 'global_search._shipment_map = authority_map' in DB_AUTHORITY
    assert 'dispatch_queue._shipment_map = authority_map' in DB_AUTHORITY


def test_unverified_provider_draft_is_not_physical_authority():
    assert 'draft_verification_required' in MARKETPLACE_AUTHORITY
    assert 'if status in _UNVERIFIED_SHIPMENT_STATES and not has_durable_evidence:' in MARKETPLACE_AUTHORITY
    assert 'return False' in MARKETPLACE_AUTHORITY
    assert 'result[key] = marketplace' in MARKETPLACE_AUTHORITY


def test_alignment_stays_read_only():
    combined = DB_AUTHORITY + MARKETPLACE_AUTHORITY
    assert 'requests.post(' not in combined
    assert 'requests.put(' not in combined
    assert 'requests.patch(' not in combined
    assert 'requests.delete(' not in combined
    assert 'db.session.commit(' not in combined
    assert 'db.session.add(' not in combined
