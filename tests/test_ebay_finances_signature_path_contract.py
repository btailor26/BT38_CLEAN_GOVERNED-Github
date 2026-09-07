from services.governed_ebay_shipping_label_finance import (
    _signature_authority,
    _signature_path,
)


def test_ebay_finances_signature_path_excludes_query_string():
    url = (
        "https://api.ebay.com/sell/finances/v1/transaction"
        "?filter=transactionType%3A%7BSHIPPING_LABEL%7D%2CorderId%3A%7B27-15097-79712%7D"
        "&limit=100"
    )

    assert _signature_path(url) == "/sell/finances/v1/transaction"
    assert _signature_authority(url) == "api.ebay.com"


def test_ebay_finances_signature_path_defaults_to_root():
    assert _signature_path("https://api.ebay.com") == "/"
