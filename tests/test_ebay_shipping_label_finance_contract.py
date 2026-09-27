from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "services" / "governed_ebay_shipping_label_finance.py").read_text(encoding="utf-8")


def test_ebay_shipping_label_finance_read_is_exact_and_read_only():
    assert '("filter", "transactionType:{SHIPPING_LABEL}")' in SOURCE
    assert '("filter", f"orderId:{{{order_id}}}")' in SOURCE
    assert '("limit", "100")' not in SOURCE
    assert '"filter": f"transactionType:{{SHIPPING_LABEL}},orderId:{{{order_id}}}"' not in SOURCE
    assert 'EBAY_FINANCES_SCOPE' in SOURCE
    assert 'marketplace_write_started": False' in SOURCE
    assert 'shipment_created": False' in SOURCE
    assert 'FBMShipment(' not in SOURCE
    assert 'requests.post(\n        EBAY_TOKEN_URL' in SOURCE
    assert 'requests.Session().send(prepared' in SOURCE


def test_uk_finances_read_requires_ebay_digital_signature_material():
    assert 'EBAY_SIGNATURE_PRIVATE_KEY' in SOURCE
    assert 'EBAY_SIGNATURE_PUBLIC_KEY_JWE' in SOURCE
    assert 'x-ebay-signature-key' in SOURCE
    assert 'Signature-Input' in SOURCE
    assert '"Signature"' in SOURCE
    assert 'ebay_finances_signature_credentials_missing' in SOURCE


def test_shipping_label_truth_reuses_existing_spend_ledger():
    assert 'INSERT INTO shipping_spend_ledger' in SOURCE
    assert "'ebay'" in SOURCE
    assert 'ebay_finances_shipping_label' in SOURCE
    assert 'ON CONFLICT (dispatch_key)' in SOURCE
    assert 'source_reference' in SOURCE
    assert 'confirmed' in SOURCE


def test_non_json_finance_evidence_is_non_fatal_and_never_confirms_purchase():
    assert 'except (ValueError, requests.exceptions.JSONDecodeError):' in SOURCE
    assert 'ebay_finances_shipping_label_response_not_json' in SOURCE
    assert '"purchase_confirmed": False' in SOURCE
    assert '"transactions_persisted": 0' in SOURCE

def test_exact_recovery_has_bounded_historical_finance_fallback():
    assert 'if response.status_code == 204:' in SOURCE
    assert 'MIN(created_at) AS created_at, MAX(shipped_at) AS shipped_at' in SOURCE
    assert '("filter", date_filter)' in SOURCE
    assert 'historical_fallback_used = True' in SOURCE
    assert 'and _text(row.get("orderId")) == order_id' in SOURCE
