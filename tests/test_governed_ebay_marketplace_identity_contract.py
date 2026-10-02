from pathlib import Path


SOURCE = Path("governed_routes.py").read_text(encoding="utf-8")


def test_ebay_oauth_verifies_resource_owner_before_store_creation():
    introspect = SOURCE.index("https://api.ebay.com/identity/v1/oauth2/token/introspect")
    subject = SOURCE.index('ebay_subject = str(introspection.get("sub")')
    create = SOURCE.index("store = Store(", subject)
    assert introspect < subject < create


def test_ebay_oauth_persists_stable_marketplace_identity():
    assert '"ebay_oauth_subject": ebay_subject' in SOURCE
    assert '"ebay_oauth_username": ebay_username or existing.get("ebay_oauth_username")' in SOURCE


def test_ebay_oauth_reuses_matching_identity_and_blocks_duplicates():
    assert '"duplicate_ebay_marketplace_identity"' in SOURCE
    assert "identity_store = identity_matches[0] if identity_matches else None" in SOURCE
    assert "store = identity_store" in SOURCE
    assert '"ebay_marketplace_identity_store_mismatch"' in SOURCE


def test_ebay_oauth_does_not_reduce_account_to_one_ebay_store():
    # Multi-store packages remain valid. Uniqueness is marketplace identity,
    # not platform/account cardinality.
    callback = SOURCE[SOURCE.index("def governed_ebay_oauth_callback"):SOURCE.index("def governed_ebay_oauth_refresh_token")]
    assert "len(account_ebay_stores) == 1" not in callback
    assert "ebay_oauth_subject" in callback
