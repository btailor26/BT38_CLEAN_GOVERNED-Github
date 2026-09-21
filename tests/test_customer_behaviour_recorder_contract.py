from pathlib import Path


def test_customer_behaviour_recorder_is_event_driven_and_privacy_bounded():
    text = Path("services/governed_customer_behaviour_recorder.py").read_text(encoding="utf-8")
    assert '"page_view"' in text
    assert '"section_view"' in text
    assert '"scroll_depth"' in text
    assert '"click"' in text
    assert '"form_start"' in text
    assert '"form_submit"' in text
    assert '"page_exit"' in text
    assert "IntersectionObserver" in text
    assert 'addEventListener("click"' in text
    assert 'addEventListener("scroll"' in text
    assert 'addEventListener("pagehide"' in text
    assert "setInterval(" not in text
    assert "setTimeout(" not in text
    assert "requestAnimationFrame(" not in text
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
    assert 'body.replace("</body>", _SCRIPT + "\\n</body>", 1)' in recorder
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
    assert "setTimeout(" not in source
    assert "requestAnimationFrame(" not in source
    assert 'if(url===endpoint)return originalFetch.apply(this,arguments);' in source
    assert 'if request.path == _ENDPOINT or request.method != "GET": return response' in source
