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


def test_ebay_oauth_state_binds_exact_connection_attempt():
    authorize = SOURCE[SOURCE.index("def governed_ebay_oauth_authorize"):SOURCE.index("def governed_ebay_oauth_callback")]
    callback = SOURCE[SOURCE.index("def governed_ebay_oauth_callback"):SOURCE.index("def governed_ebay_oauth_refresh_token")]

    assert '"store_id": int(store.id) if store else None' in authorize
    assert '"nonce": state_nonce' in authorize
    assert '"intent": "connect_ebay_store"' in authorize

    assert 'state_store_id = state_payload.get("store_id")' in callback
    assert 'state_intent == "connect_ebay_store"' in callback
    assert '(not expected_state or str(state) == str(expected_state))' in callback
    assert "selected_store_id = state_store_id" in callback
    assert 'session.get("governed_ebay_oauth_store_id")' not in callback
