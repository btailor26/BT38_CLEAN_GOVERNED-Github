from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "services" / "governed_fbm_dispatch_queue_alignment.py").read_text(encoding="utf-8")


def test_fbm_history_default_ignores_pre_owner_stale_browser_state():
    assert "var sessionEpoch='fbm-history-3d-v1';" in SOURCE
    assert "range:'3d'" in SOURCE
    assert "window.sessionStorage.getItem('bt38:page:fbm')" in SOURCE
    assert "storedEpoch===sessionEpoch?window.BT38.getPageSession('fbm',sessionDefaults):sessionDefaults" in SOURCE


def test_fbm_user_history_selection_remains_owned_for_active_session():
    assert "session_epoch:sessionEpoch" in SOURCE
    assert "window.BT38.setPageSession('fbm',next)" in SOURCE
    assert "range=String(rangeInput&&rangeInput.value||'3d').toLowerCase()" in SOURCE


def test_session_ownership_fix_adds_no_polling_or_parallel_controller():
    ownership = SOURCE.split("var sessionEpoch='fbm-history-3d-v1';", 1)[1].split("var params=new URLSearchParams", 1)[0]
    assert "fetch(" not in ownership
    assert "setInterval" not in ownership
    assert "setTimeout" not in ownership
    assert "EventSource" not in ownership
