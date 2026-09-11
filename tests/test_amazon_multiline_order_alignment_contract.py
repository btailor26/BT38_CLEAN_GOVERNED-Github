from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_existing_amazon_order_row_does_not_hide_sibling_items():
    alignment = _read("services/governed_amazon_multiline_order_alignment.py")
    services_init = _read("services/__init__.py")

    assert "governed_amazon_multiline_order_alignment" in services_init
    assert "client.get_order_items(order_id)" in alignment
    assert "if existing_rows:" in alignment
    assert "_hydrate_existing_amazon_rows(" in alignment

    existing_block = alignment.split("if existing_rows:", 1)[1].split(
        "# Always ask Amazon for the exact line set", 1
    )[0]
    assert "continue" not in existing_block

    assert "for item in items:" in alignment
    assert 'item.get("OrderItemId")' in alignment
    assert "upsert_governed_marketplace_order_line(" in alignment
    assert 'if result.get("created"):' in alignment
    assert '"existing_line_stock_processing_skipped"' in alignment


def test_multiline_alignment_keeps_existing_governed_boundaries():
    alignment = _read("services/governed_amazon_multiline_order_alignment.py")

    assert "timedelta(hours=24)" in alignment
    assert "MarketplaceOrder" in alignment
    assert "_process_exact_imported_order(" in alignment
    assert "db.session.commit()" in alignment

    forbidden = (
        "Thread(",
        "while True",
        "schedule.",
        "create_all(",
        "inventory_quantity =",
        "warehouse.quantity =",
        "requests.post(",
        "requests.put(",
        "requests.patch(",
        "requests.delete(",
    )
    for token in forbidden:
        assert token not in alignment
