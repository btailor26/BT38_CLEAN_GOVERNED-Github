from pathlib import Path


def test_customer_behaviour_recorder_is_event_driven_and_privacy_bounded():
    text = Path("services/governed_customer_behaviour_recorder.py").read_text(encoding="utf-8")
    assert '"page_view"' in text
    assert '"scroll_depth"' in text
    assert '"click"' in text
    assert '"form_start"' in text
    assert '"form_submit"' in text
    assert '"page_exit"' in text
    assert "IntersectionObserver" not in text
    assert 'addEventListener("click"' in text
    assert 'addEventListener("scroll"' in text
    assert 'addEventListener("pagehide"' in text
    assert "setInterval(" not in text
    core_script = text.split("_VIDEO_CONTROL_SCRIPT =", 1)[0]
    assert "setTimeout(" not in core_script
    assert "requestAnimationFrame(" not in core_script
    assert "input_value" not in text
    assert "_SECRET_TERMS" in text
    assert "request.form" not in text
    assert "request.get_json" in text
    assert 'log_type="customer_behaviour"' in text


def test_customer_behaviour_recorder_is_installed_once_for_non_operational_html_pages():
    main = Path("main.py").read_text(encoding="utf-8")
    recorder = Path("services/governed_customer_behaviour_recorder.py").read_text(encoding="utf-8")
    assert "install_governed_customer_behaviour_recorder(app)" in main
    assert "@app.after_request" in recorder
    assert '"text/html"' in recorder
    assert 'injected = _SCRIPT' in recorder
    assert 'body.replace("</body>", injected + "\\n</body>", 1)' in recorder
    assert "_bt38_customer_behaviour_recorder_installed" in recorder


def test_customer_behaviour_recorder_covers_operational_workspaces_without_form_values():
    text = Path("services/governed_customer_behaviour_recorder.py").read_text(encoding="utf-8")
    assert "_OPERATIONAL_PATH_PREFIXES" in text
    assert '"/fbm"' in text
    assert '"/governed/warehouse"' in text
    assert '"/product-linking"' in text
    assert '"/mcf"' in text
    assert 'if request.path == _ENDPOINT or request.method != "GET": return response' in text
    assert "request.form" not in text
    assert "input_value" not in text


def test_customer_behaviour_endpoint_rejects_arbitrary_payload_fields():
    text = Path("services/governed_customer_behaviour_recorder.py").read_text(encoding="utf-8")
    assert "_ALLOWED_EVENTS" in text
    assert "_ALLOWED_KEYS" in text
    assert "_MAX_BODY" in text
    assert '== "cross-site"' in text
    assert "isinstance(value, (dict, list))" in text


def test_system_recorder_covers_operational_frontend_and_backend_without_values():
    SOURCE = Path("services/governed_customer_behaviour_recorder.py").read_text(encoding="utf-8")
    assert 'if request.path == _ENDPOINT or request.method != "GET": return response' in SOURCE
    assert '"event": "request_complete"' in SOURCE
    assert '"db_query_count"' in SOURCE
    assert '"db_duration_ms"' in SOURCE
    assert 'query_keys' in SOURCE
    assert 'window.fetch=function' in SOURCE
    assert '"browser_request"' in SOURCE
    assert '"browser_error"' in SOURCE
    assert '_SECRET_TERMS' in SOURCE


def test_recorder_transport_bypasses_its_own_fetch_instrumentation():
    source = Path("services/governed_customer_behaviour_recorder.py").read_text(encoding="utf-8")
    assert 'if(url===endpoint)return originalFetch.apply(this,arguments);' in source
    assert 'send("browser_request"' in source
    assert "setInterval(" not in source


def test_recorder_emits_only_from_real_events_not_idle_loops():
    source = Path("services/governed_customer_behaviour_recorder.py").read_text(encoding="utf-8")
    assert "setInterval(" not in source
    core_script = source.split("_VIDEO_CONTROL_SCRIPT =", 1)[0]
    assert "setTimeout(" not in core_script
    assert "requestAnimationFrame(" not in core_script
    assert 'if(url===endpoint)return originalFetch.apply(this,arguments);' in source
    assert 'if request.path == _ENDPOINT or request.method != "GET": return response' in source


def test_visual_session_replay_is_wired_for_every_bt38_html_page():
    source = Path("services/governed_customer_behaviour_recorder.py").read_text(encoding="utf-8")
    template = Path("templates/admin/customer_behaviour.html").read_text(encoding="utf-8")
    assert '"visual_frame"' in source
    assert 'if _operational_path(request.path) is False' not in source
    assert '"frame", "scroll_x", "scroll_y"' in source
    assert 'visualFrame("page_view")' in source
    assert 'addEventListener("bt38-page-refreshed"' in source
    assert 'visualFrame(reason)' in source
    assert 'visualFrame("click")' not in source
    assert 'visualFrame("change")' not in source
    assert 'visualFrame("dom_change")' not in source
    assert "MutationObserver" not in source
    assert 'pagePath==="/fbm"' not in source
    assert 'body *' in source
    assert "input_value" not in source
    assert "request.form" not in source
    assert "bt38-replay-play" in template
    assert "bt38-replay-frame" in template
    assert "Play replay" in template


def test_recorder_records_session_state_only_on_page_load_or_real_refresh():
    source = Path("services/governed_customer_behaviour_recorder.py").read_text(encoding="utf-8")
    refresh = Path("static/js/bt38-live-page-refresh.js").read_text(encoding="utf-8")

    assert 'send("page_view")' in source
    assert 'visualFrame("page_view")' in source
    assert 'addEventListener("bt38-page-refreshed"' in source
    assert "MutationObserver" not in source
    assert "IntersectionObserver" not in source
    assert 'send("display_snapshot"' not in source
    assert "new CustomEvent('bt38-page-refreshed'" in refresh
    assert "committed_event_refresh" in refresh


def test_journey_video_capture_requires_explicit_admin_acceptance_and_never_auto_starts():
    source = Path("services/governed_customer_behaviour_recorder.py").read_text(encoding="utf-8")
    assert "_VIDEO_CONTROL_SCRIPT" in source
    assert "bt38JourneyVideoRecord" in source
    assert 'addEventListener("click",async function()' in source
    assert "getDisplayMedia({video:true,audio:false})" in source
    assert "new MediaRecorder(stream)" in source
    assert "recorder.start()" in source
    assert 'getattr(current_user, "role", "") == "admin"' in source
    assert 'button.textContent="Stop journey video"' in source
    assert 'track.addEventListener("ended",stop' in source
    assert 'window.addEventListener("pagehide",stop' in source
    assert "audio:false" in source
    # No page/session/event hook is allowed to invoke screen capture.
    assert source.count("getDisplayMedia(") == 1


def test_journey_video_note_structures_manual_capture_without_starting_it():
    source = Path("services/governed_customer_behaviour_recorder.py").read_text(encoding="utf-8")
    assert 'id="bt38JourneyVideoNotePanel"' in source
    assert 'What should we look at?' in source
    assert 'id="bt38JourneyVideoNote"' in source
    assert 'maxlength="500"' in source
    assert 'Continue to screen permission' in source
    assert 'What to check' in source
    assert 'showNoteOverlay()' in source
    assert 'window.setTimeout(hideNoteOverlay,5000)' in source
    assert 'audio:false' in source
    assert source.count("getDisplayMedia(") == 1
    assert source.index('startButton.addEventListener("click",async function()') < source.index("getDisplayMedia({video:true,audio:false})")



def test_journey_video_control_stays_above_bottom_workspace_bar_without_overlap():
    source = Path("services/governed_customer_behaviour_recorder.py").read_text(encoding="utf-8")
    assert 'right:18px;top:72px;bottom:auto' in source
    assert 'right:18px;top:116px;bottom:auto' in source
    assert 'max-height:calc(100vh - 134px);overflow:auto' in source
    assert 'button.style.cssText="position:fixed;right:18px;bottom:18px' not in source
    assert 'panel.style.cssText="position:fixed;right:18px;bottom:62px' not in source
