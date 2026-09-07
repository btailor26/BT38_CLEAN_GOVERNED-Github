import os

from Crypto.PublicKey import ECC
from Crypto.Signature import eddsa

from services.governed_ebay_shipping_label_finance import (
    _import_ed25519_private_key,
    _signature_authority,
    _signature_headers,
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


def test_ebay_finances_imports_raw_ed25519_hex_seed():
    seed = bytes(range(32))
    key = _import_ed25519_private_key(seed.hex())

    assert key.curve == "Ed25519"
    assert key.has_private()
    signature = eddsa.new(key, "rfc8032").sign(b"bt38-test")
    assert len(signature) == 64


def test_ebay_finances_signature_headers_accept_raw_ed25519_hex_seed(monkeypatch):
    seed = bytes(range(32))
    monkeypatch.setenv("EBAY_SIGNATURE_PRIVATE_KEY", seed.hex())
    monkeypatch.setenv("EBAY_SIGNATURE_PUBLIC_KEY_JWE", "synthetic-jwe")

    headers = _signature_headers(
        method="GET",
        url="https://api.ebay.com/sell/finances/v1/transaction?limit=100",
    )

    assert headers["x-ebay-signature-key"] == "synthetic-jwe"
    assert headers["Signature-Input"].startswith('sig1=("x-ebay-signature-key"')
    assert headers["Signature"].startswith("sig1=:")
