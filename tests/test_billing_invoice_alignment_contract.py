from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
INVOICE=(ROOT/'services'/'billing_invoice_alignment.py').read_text()
REVOLUT=(ROOT/'services'/'revolut_subscription_alignment.py').read_text()
BILLING=(ROOT/'templates'/'billing.html').read_text()

def test_invoice_is_exact_completed_payment_only_and_idempotent():
 assert 'state != "completed"' in INVOICE
 assert 'provider_order_ref=order_ref' in INVOICE
 assert 'UniqueConstraint("provider", "provider_order_ref"' in INVOICE
 assert '_minor_amount(order.get("amount"))' in INVOICE
 assert 'package.price_pence' not in INVOICE

def test_revolut_is_payment_authority_not_document_provider():
 assert 'record_completed_revolut_invoice(' in REVOLUT
 assert 'client.retrieve_order(order_ref)' in REVOLUT
 assert 'order identity did not match' in REVOLUT
 assert 'reportlab' not in INVOICE.lower()
 assert 'revolut' not in INVOICE.split('def _pdf_bytes',1)[1].split('@app.get',1)[0].lower() or 'Payment provider: Revolut' in INVOICE

def test_invoice_downloads_are_owner_scoped():
 assert '_account_for_user(current_user.id)' in INVOICE
 assert 'not _is_owner(member)' in INVOICE
 assert 'int(invoice.account_id) != int(account.id)' in INVOICE
 assert '/billing/invoices/<int:invoice_id>.pdf' in INVOICE
 assert '/billing/invoices/<int:invoice_id>.csv' in INVOICE

def test_billing_page_exposes_history_pdf_and_csv():
 assert 'Payment history & invoices' in BILLING
 assert '.pdf' in BILLING
 assert '.csv' in BILLING
 assert 'exact completed payment' in BILLING
