from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLIENT = (ROOT / "services" / "royal_mail_click_drop.py").read_text(encoding="utf-8")
ROUTES = (ROOT / "governed_royal_mail_routes.py").read_text(encoding="utf-8")
MODEL = (ROOT / "royal_mail_models.py").read_text(encoding="utf-8")
READBACK = (ROOT / "services" / "governed_royal_mail_label_readback.py").read_text(encoding="utf-8")
INSTALLER = (ROOT / "services" / "governed_royal_mail_click_drop_alignment.py").read_text(encoding="utf-8")
SCRIPT = (ROOT / "static" / "js" / "royal_mail_click_drop_connection.js").read_text(encoding="utf-8")
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")


def test_click_drop_uses_account_api_key_not_website_password():
    assert '"Authorization": str(self.api_key).strip()' in CLIENT
    assert 'if body.get("password")' in ROUTES
    assert "normal Royal Mail website password" in MODEL
    assert "Click & Drop API auth key" in SCRIPT
    assert "Royal Mail account password" not in SCRIPT


def test_connection_is_merchant_owned_and_credentials_are_encrypted():
    assert "user_id = db.Column" in MODEL
    assert "unique=True" in MODEL
    assert "api_key_ciphertext" in MODEL
    assert "AES.MODE_GCM" in CLIENT
    assert "ROYAL_MAIL_CREDENTIAL_ENCRYPTION_KEY" in CLIENT
    assert "api_key=" not in MODEL


def test_connection_validation_uses_real_account_capability():
    assert 'self._get("/carriers")' in CLIENT
    assert '"carrier_count"' in CLIENT
    assert "BT38-CONNECTION-VALIDATION-NO-ORDER" not in CLIENT


def test_royal_mail_read_path_is_exact_and_non_mutating():
    assert 'get_exact_orders(self, order_reference: str)' in CLIENT
    assert 'get_exact_order_evidence(self, order_reference: str)' in CLIENT
    assert 'f"/orders/{encoded}"' in CLIENT
    assert 'f"/orders/{encoded}/full"' in CLIENT
    assert '"exact_order_only": True' in ROUTES
    assert '"marketplace_write_started": False' in ROUTES
    assert '"label_purchase_started": False' in ROUTES
    assert '"broad_scan_started": False' in ROUTES
    assert "requests.post(" not in CLIENT
    assert "requests.put(" not in CLIENT
    assert "requests.patch(" not in CLIENT
    assert "requests.delete(" not in CLIENT


def test_exact_label_recovery_reuses_existing_fbm_shipment_authority():
    assert "/governed/royal-mail/exact-label-recovery" in ROUTES
    assert "hydrate_royal_mail_label_for_order" in ROUTES
    assert "from fbm_models import FBMShipment" in READBACK
    assert 'provider="royal_mail_click_drop"' in READBACK
    assert 'shipment.label_source = "royal_mail_click_drop"' in READBACK
    assert "MarketplaceOrder.query.filter_by" in READBACK
    assert '"marketplace_write_started": False' in READBACK
    assert '"broad_scan_started": False' in READBACK


def test_cost_requires_royal_mail_postage_evidence():
    assert 'detail.get("postageAppliedOn")' in READBACK
    assert 'shipping.get("shippingCost")' in READBACK
    assert 'row.source = "royal_mail_click_drop_postage_applied"' in READBACK
    assert "shippingCostCharged" not in READBACK


def test_alignment_adds_only_connection_table_not_another_shipment_model():
    assert '__tablename__ = "royal_mail_connections"' in MODEL
    assert "FBMShipment" not in MODEL
    assert "no second shipment table" in INSTALLER.lower()


def test_alignment_is_installed_and_fbm_card_is_injected():
    assert "install_governed_royal_mail_click_drop_alignment" in MAIN
    assert "royal_mail_click_drop_connection.js" in INSTALLER
    assert "Royal Mail · Click & Drop" in SCRIPT
    assert "/governed/royal-mail/connection" in SCRIPT
