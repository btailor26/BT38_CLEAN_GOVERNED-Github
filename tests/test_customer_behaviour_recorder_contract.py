from pathlib import Path


def _source():
    return Path("services/governed_customer_behaviour_recorder.py").read_text(encoding="utf-8")


def test_automatic_recorder_is_exception_only():
    text = _source()
    assert '_ALLOWED_EVENTS = {"browser_error"}' in text
    assert '"page_view"' not in text
    assert 'event:"scroll_depth"' not in text
    assert 'send("scroll_depth"' not in text
    assert 'send("click"' not in text
    assert 'send("change"' not in text
    assert 'send("form_start"' not in text
    assert 'send("form_submit"' not in text
    assert 'visualFrame(' not in text
    assert "MutationObserver" not in text
    assert "setInterval(" not in text


def test_successful_backend_requests_do_not_persist_recorder_rows():
    text = _source()
    assert "if int(response.status_code) < 400:" in text
    assert "return response" in text
    assert '"event": "request_failed"' in text
    assert "_record_system_event" in text


def test_backend_and_browser_errors_are_retained():
    text = _source()
    assert "@app.errorhandler(Exception)" in text
    assert '"event": "backend_error"' in text
    assert 'window.addEventListener("error"' in text
    assert 'window.addEventListener("unhandledrejection"' in text
    assert 'event:"browser_error"' in text
    assert 'log_type="system_recorder"' in text
    assert 'log_type="customer_behaviour"' in text


def test_customer_behaviour_replay_is_retired():
    text = _source()
    assert '@app.get("/admin/customer-behaviour")' not in text
    assert 'render_template("admin/customer_behaviour.html"' not in text


def test_manual_video_recorder_remains_explicit_admin_only():
    text = _source()
    assert "_VIDEO_CONTROL_SCRIPT" in text
    assert "bt38JourneyVideoRecord" in text
    assert "getDisplayMedia({video:true,audio:false})" in text
    assert "new MediaRecorder(stream)" in text
    assert "recorder.start()" in text
    assert 'getattr(current_user, "role", "") == "admin"' in text
    assert text.count("getDisplayMedia(") == 1
    assert 'startButton.addEventListener("click",async function()' in text
    assert 'document.getElementById("bt38NotificationBell")' in text
    assert 'bell.parentNode.insertBefore(button,bell)' in text


def test_exception_transport_cannot_recursively_record_itself():
    text = _source()
    assert "if request.path == _ENDPOINT: return" in text
    assert "if request.path == _ENDPOINT:" in text
