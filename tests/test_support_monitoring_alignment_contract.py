from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MONITOR = (ROOT / "services" / "support_monitoring_alignment.py").read_text(encoding="utf-8")
INIT = (ROOT / "services" / "__init__.py").read_text(encoding="utf-8")


def test_monitor_reuses_existing_support_authority_only():
    assert "from services.support_case_alignment import SupportCase, SupportCaseMessage" in MONITOR
    assert "SupportCase.query" in MONITOR
    assert "SupportCaseMessage.query" in MONITOR
    for forbidden in ("requests.", "MarketplaceOrder", "WarehouseStock", "amazon_client", "ebay_client", "configured_revolut_client", "setInterval("):
        assert forbidden not in MONITOR


def test_owner_cockpit_support_summary_is_settings_admin_only_and_compact():
    assert 'str(request.path or "") == "/settings"' in MONITOR
    assert '== "admin"' in MONITOR
    assert 'data-bt38-support-monitor="1"' in MONITOR
    for label in ("Active", "Urgent", "Waiting", "First response due", "View cases"):
        assert label in MONITOR
    # Source is an f-string, so literal CSS braces are escaped as {{ / }}.
    assert ".bt38-support-monitor-body{{display:none" in MONITOR
    assert ".bt38-support-monitor.is-open .bt38-support-monitor-body{{display:block" in MONITOR


def test_first_response_attention_uses_explicit_priority_thresholds():
    assert '_FIRST_RESPONSE_HOURS = {"urgent": 1, "high": 4, "normal": 24, "low": 48}' in MONITOR
    assert "def _needs_first_response" in MONITOR
    assert "_has_admin_reply(case)" in MONITOR
    assert "created_at" in MONITOR
    assert "timedelta(hours=hours)" in MONITOR


def test_monitor_is_installed_after_support_case_authority():
    support_index = INIT.index("import services.support_case_alignment")
    monitor_index = INIT.index("import services.support_monitoring_alignment")
    assert support_index < monitor_index
