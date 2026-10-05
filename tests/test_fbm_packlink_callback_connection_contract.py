from pathlib import Path


ROUTES = Path("governed_fbm_routes.py").read_text(encoding="utf-8")
CALLBACK_ROUTES = Path("governed_packlink_callback_routes.py").read_text(encoding="utf-8")


def test_packlink_connection_registers_existing_governed_callback_after_authentication():
    section = ROUTES.split("def packlink_connection():", 1)[1]
    section = section.split("\n@", 1)[0]
    assert "adapter = PacklinkAdapter()" in section
    assert "result = adapter.connection_check()" in section
    assert "from governed_packlink_callback_routes import _register_callback" in section
    assert "_register_callback(adapter)" in section
    assert '"callback_registered": callback_registered' in section


def test_packlink_connection_fails_closed_when_callback_registration_fails():
    section = ROUTES.split("def packlink_connection():", 1)[1]
    section = section.split("\n@", 1)[0]
    assert "except (PacklinkConfigurationError, PacklinkRequestError)" in section
    assert '"authenticated": True' in section
    assert '"callback_registered": False' in section
    assert "webhook registration failed" in section


def test_packlink_callback_registration_remains_single_existing_authority():
    assert 'def _register_callback(adapter: PacklinkAdapter)' in CALLBACK_ROUTES
    assert 'adapter.register_callback(callback_url)' in CALLBACK_ROUTES
    assert 'shipments/callback' not in ROUTES
