from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INBOX = ROOT / "services" / "governed_admin_attention_inbox_alignment.py"
TRUTH = ROOT / "services" / "governed_truth_attention_alignment.py"
INIT = ROOT / "services" / "__init__.py"


def test_review_click_and_owner_inbox_share_one_event_stream():
    truth = TRUTH.read_text(encoding="utf-8")
    inbox = INBOX.read_text(encoding="utf-8")

    assert '_REVIEW_CATEGORY = "admin_truth_review_request"' in truth
    assert '_REVIEW_CATEGORY = "admin_truth_review_request"' in inbox
    assert 'SystemEvent(' in truth
    assert 'SystemEvent.query' in inbox


def test_under_review_states_are_included_in_same_owner_section():
    source = INBOX.read_text(encoding="utf-8")

    assert '"under_review"' in source
    assert '"under review"' in source
    assert '"needs_admin_attention"' in source
    assert 'def _event_is_under_review' in source
    assert 'details.get(key)' in source


def test_owner_inbox_stays_compact_and_settings_only():
    source = INBOX.read_text(encoding="utf-8")

    assert 'str(request.path or "") == "/settings"' in source
    assert 'bt38-admin-attention-body{display:none' in source
    assert 'View reviews' in source
    assert 'Needs admin attention' in source
    assert 'current_user' in source
    assert '== "admin"' in source


def test_inbox_is_installed_without_new_marketplace_execution_path():
    source = INIT.read_text(encoding="utf-8")
    inbox = INBOX.read_text(encoding="utf-8")

    assert 'import services.governed_admin_attention_inbox_alignment' in source
    assert 'MarketplaceOrder' not in inbox
    assert 'requests.' not in inbox
    assert 'worker' in inbox.lower()
