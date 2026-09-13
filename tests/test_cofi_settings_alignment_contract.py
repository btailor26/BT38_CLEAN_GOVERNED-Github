from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "services" / "cofi_settings_alignment.py").read_text(encoding="utf-8")
INIT = (ROOT / "services" / "__init__.py").read_text(encoding="utf-8")
DB_CONTRACT = (ROOT / "scripts" / "verify_production_db_contract.py").read_text(encoding="utf-8")


def test_cofi_reuses_existing_system_config_authority_only():
    assert 'from models import SystemConfig' in SOURCE
    assert '"cofi_enabled"' in SOURCE
    assert '"cofi_opportunities_enabled"' in SOURCE
    assert '"cofi_customer_visibility_enabled"' in SOURCE
    assert 'authority": "SystemConfig"' in SOURCE
    assert 'import services.cofi_settings_alignment' in INIT
    assert '"system_config"' in DB_CONTRACT
    assert '"key", "value"' in DB_CONTRACT


def test_cofi_effective_visibility_requires_all_parent_fuses():
    assert 'raw["cofi_enabled"] and raw["cofi_opportunities_enabled"]' in SOURCE
    assert 'raw["cofi_customer_visibility_enabled"]' in SOURCE


def test_cofi_settings_are_admin_scoped_and_use_existing_settings_routes():
    assert '@app.get("/governed/settings/cofi")' in SOURCE
    assert '@app.post("/governed/settings/cofi")' in SOURCE
    assert 'admin_required' in SOURCE
    assert 'unsupported_cofi_setting' in SOURCE
    assert 'db.session.commit()' in SOURCE
