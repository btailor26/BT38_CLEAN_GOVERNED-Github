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

def test_payment_provider_is_internal_not_customer_invoice_content():
 assert 'record_completed_revolut_invoice(' in REVOLUT
 assert 'client.retrieve_order(order_ref)' in REVOLUT
 assert 'order identity did not match' in REVOLUT
 pdf_body=INVOICE.split('def _pdf_bytes',1)[1].split('@app.get',1)[0]
 csv_body=INVOICE.split('def bt38_billing_invoice_csv',1)[1]
 assert 'Payment provider:' not in pdf_body
 assert 'Payment reference:' not in pdf_body
 assert 'payment_provider' not in csv_body
 assert 'payment_reference' not in csv_body

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

def test_billing_page_exposes_supported_checkout_choices_without_storing_credentials():
 assert 'Choose how you want to pay' in BILLING
 assert '>Card<' in BILLING
 assert '>Pay by Bank<' in BILLING
 assert '>Apple Pay<' in BILLING
 assert '>Google Pay<' in BILLING
 assert 'BT38 does not store card, bank or wallet credentials.' in BILLING
