from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
JOURNEY = (ROOT / "static/js/fbm_tracking_journey.js").read_text(encoding="utf-8")
TEMPLATE = (ROOT / "templates/fbm.html").read_text(encoding="utf-8")
QZ = (ROOT / "static/js/fbm_qz_print.js").read_text(encoding="utf-8")


def test_existing_packlink_status_uses_saved_label_without_rebuying_postage():
    assert ".packlink-existing-status[data-shipment-id]" in JOURNEY
    assert "bridge.packlinkStatus(button.dataset.shipmentId)" in JOURNEY
    assert "payload.label_ready" in JOURNEY
    assert "bridge.printLabel(label)" in JOURNEY
    assert "label.url" in JOURNEY
    assert "label.base64" in JOURNEY
    assert "event.stopImmediatePropagation()" in JOURNEY
    assert "location.reload()" not in JOURNEY
    assert "/packlink/draft" not in JOURNEY
    assert "/amazon/purchase" not in JOURNEY


def test_qz_printing_remains_separate_from_postage_purchase():
    assert "async function printLabel(label)" in QZ
    assert "global.qz.print(config, labelData(label))" in QZ
    assert "Printing is deliberately separate from postage purchase" in QZ
    assert "Auto-print after purchase" in TEMPLATE
