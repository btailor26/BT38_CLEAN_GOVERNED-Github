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
    assert "@app.errorhandler(Exception)" not in text
    assert "@got_request_exception.connect_via(app)" in text
    assert '"event": "backend_error"' in text
    assert 'window.addEventListener("error"' in text
    assert 'window.addEventListener("unhandledrejection"' in text
    assert 'event:"browser_error"' in text
    assert 'log_type="system_recorder"' in text
    assert '_record_system_event(f"Customer behaviour: {event}", details)' in text


def test_customer_behaviour_replay_is_retired():
    text = _source()
    assert '@app.get("/admin/customer-behaviour")' not in text
    assert 'render_template("admin/customer_behaviour.html"' not in text


def test_dashboard_receives_manual_video_recorder():
    text = _source()
    assert '    "/dashboard",' in text
    assert 'if not _operational_path(request.path):' in text or 'not _operational_path(request.path)' in text


def test_manual_video_recorder_remains_explicit_authenticated_only():
    text = _source()
    assert "_VIDEO_CONTROL_SCRIPT" in text
    assert "bt38JourneyVideoRecord" in text
    assert 'displaySurface:"browser"' in text
    assert 'preferCurrentTab:true' in text
    assert 'monitorTypeSurfaces:"exclude"' in text
    assert 'captureTrack.getSettings().displaySurface!=="browser"' in text
    assert "new MediaRecorder(stream)" in text
    assert "recorder.start()" in text
    assert 'if current_user.is_authenticated:' in text
    assert text.count("getDisplayMedia(") == 1
    assert 'startButton.addEventListener("click",async function()' in text
    assert 'document.getElementById("bt38NotificationBell")' in text
    assert 'bell.parentNode.insertBefore(button,bell)' in text


def test_recorder_controller_survives_full_page_navigation():
    text = _source()
    assert 'window.open("","bt38JourneyRecorderController"' in text
    assert 'controller.document.write(controllerHtml(note))' in text
    assert 'selfBrowserSurface:"exclude"' in text
    assert 'window.addEventListener("pagehide",stop' not in text
    assert 'window.addEventListener("beforeunload"' in text
    assert 'Choose the BT38 browser tab' in text


def test_controller_document_closes_inline_script_correctly():
    text = _source()
    # One JavaScript source backslash escapes the slash for the outer HTML parser;
    # two backslashes would emit a literal backslash and leave the popup script open.
    assert r'})();<\/script></body></html>' in text
    assert r'})();<\\/script></body></html>' not in text


def test_exception_transport_cannot_recursively_record_itself():
    text = _source()
    assert "if request.path == _ENDPOINT or not _operational_path(request.path):" in text
    assert "@app.errorhandler(Exception)" not in text
    assert "raise error" not in text
    assert "@got_request_exception.connect_via(app)" in text
