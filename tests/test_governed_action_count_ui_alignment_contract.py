from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ALIGNMENT = (ROOT / "services" / "governed_action_count_ui_alignment.py").read_text(encoding="utf-8")
SERVICES = (ROOT / "services" / "__init__.py").read_text(encoding="utf-8")
READY = (ROOT / "services" / "governed_fbm_ready_landing_alignment.py").read_text(encoding="utf-8")


def test_existing_authority_bell_exposes_action_count():
    assert '"action_count": action_count' in READY
    assert 'record.get("requires_action") is True' in READY
    assert '"source": "current_authority_projection"' in READY
    assert '"marketplace_calls": False' in READY
    assert '"polling": False' in READY


def test_visible_counters_use_existing_bell_action_count_not_unread_history_or_dashboard_count():
    assert "payload.action_count" in ALIGNMENT
    assert "bt38NotificationBadge" in ALIGNMENT
    assert "bt38AssistantBubble" in ALIGNMENT
    assert "bt38-governed-action-count" in ALIGNMENT
    assert "seenEventsKey" not in ALIGNMENT
    assert "dashboardActionCount" not in ALIGNMENT
    assert "dashboardPath" not in ALIGNMENT


def test_alignment_adds_no_second_read_poll_or_marketplace_path():
    assert "window.fetch=async function" in ALIGNMENT
    assert "previousFetch(input,init)" in ALIGNMENT
    assert "response.clone().json()" in ALIGNMENT
    assert "setInterval" not in ALIGNMENT
    assert "setTimeout" not in ALIGNMENT
    assert "MarketplaceOrder.query" not in ALIGNMENT
    assert "db.session" not in ALIGNMENT
    assert "requests.get" not in ALIGNMENT
    assert "requests.post" not in ALIGNMENT
    assert "get_or_refresh_amazon_profile" not in ALIGNMENT
    assert "hydrate_exact_ebay_order" not in ALIGNMENT


def test_alignment_installs_after_logical_bell_projection():
    logical = SERVICES.index("import services.governed_fbm_logical_bell_alignment")
    visible = SERVICES.index("import services.governed_action_count_ui_alignment")
    assert visible > logical
    assert "small_alignment._install_final_bell_alignment = aligned_install" in ALIGNMENT
