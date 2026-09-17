from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_ebay_shipping_notification_alignment_installs_before_runtime_recovery():
    source = _read("services/__init__.py")
    shipping_import = "import services.governed_ebay_shipping_notification_registration_alignment"
    recovery_import = "import services.governed_ebay_runtime_recovery_alignment"
    assert shipping_import in source
    assert recovery_import in source
    assert source.index(shipping_import) < source.index(recovery_import)


def test_ebay_shipping_notification_alignment_remains_event_driven():
    source = _read("services/governed_ebay_shipping_notification_registration_alignment.py")
    assert "no worker, poller, scheduler" in source
    assert "setInterval" not in source
    assert "while True" not in source
