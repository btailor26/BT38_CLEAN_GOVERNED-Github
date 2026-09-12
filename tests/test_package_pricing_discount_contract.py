from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def _read(path):
    return (ROOT / path).read_text(encoding="utf-8")

def test_package_has_marked_discount_and_exact_billing_price():
    source = _read("services/package_catalog_alignment.py")
    assert "list_price_pence = db.Column" in source
    assert "discount_percent = db.Column" in source
    assert "price_pence = db.Column" in source
    assert "# exact amount billed" in source

def test_admin_can_enter_marked_discount_and_customer_price():
    template = _read("templates/admin/packages.html")
    assert 'name="list_price"' in template
    assert 'name="discount_percent"' in template
    assert 'name="price"' in template
    assert "amount billed" in template

def test_customer_price_is_billing_authority_and_discount_is_derived():
    source = _read("services/package_catalog_alignment.py")
    assert "customer_price > list_price" in source
    assert "calculated =" in source
    assert "Customer price is billing authority" in source
    assert "discount = calculated" in source

def test_discount_migration_is_guarded():
    migration = _read("migrations/manual/20260912-package-pricing-discount.sql")
    assert "ADD COLUMN IF NOT EXISTS list_price_pence" in migration
    assert "ADD COLUMN IF NOT EXISTS discount_percent" in migration
    assert "discount_percent >= 0 AND discount_percent <= 100" in migration
    assert "price_pence <= list_price_pence" in migration
