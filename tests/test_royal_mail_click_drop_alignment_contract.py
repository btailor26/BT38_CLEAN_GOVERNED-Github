from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLIENT = (ROOT / "services" / "royal_mail_click_drop.py").read_text(encoding="utf-8")
ROUTES = (ROOT / "governed_royal_mail_routes.py").read_text(encoding="utf-8")
MODEL = (ROOT / "royal_mail_models.py").read_text(encoding="utf-8")
INSTALLER = (ROOT / "services" / "governed_royal_mail_click_drop_alignment.py").read_text(encoding="utf-8")
SCRIPT = (ROOT / "static" / "js" / "royal_mail_click_drop_connection.js").read_text(encoding="utf-8")
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")


def test_click_drop_uses_account_api_key_not_website_password():
    assert '"Authorization": str(self.api_key).strip()' in CLIENT
    assert "Royal Mail's public Click & Drop API does not authenticate" in ROUTES
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


def test_royal_mail_read_path_is_exact_and_non_mutating():
    assert 'get_exact_orders(self, order_reference: str)' in CLIENT
    assert 'get/orders/{orderIdentifiers}' not in CLIENT  # documentation wording, not a broad implementation
    assert 'f"/orders/{encoded}"' in CLIENT
    assert '"exact_order_only": True' in ROUTES
    assert '"marketplace_write_started": False' in ROUTES
    assert '"label_purchase_started": False' in ROUTES
    assert '"broad_scan_started": False' in ROUTES
    assert "requests.post(" not in CLIENT
    assert "requests.put(" not in CLIENT
    assert "requests.patch(" not in CLIENT
    assert "requests.delete(" not in CLIENT


def test_alignment_adds_only_connection_table_not_another_shipment_model():
    assert '__tablename__ = "royal_mail_connections"' in MODEL
    assert "FBMShipment" not in MODEL
    assert "shipment" not in MODEL.lower()
    assert "no second shipment table" in INSTALLER.lower()


def test_alignment_is_installed_and_fbm_card_is_injected():
    assert "install_governed_royal_mail_click_drop_alignment" in MAIN
    assert "royal_mail_click_drop_connection.js" in INSTALLER
    assert "Royal Mail · Click & Drop" in SCRIPT
    assert "/governed/royal-mail/connection" in SCRIPT
