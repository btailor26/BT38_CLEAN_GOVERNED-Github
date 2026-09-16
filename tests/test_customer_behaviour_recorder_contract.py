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
    assert "password" not in text.lower()
    assert "request.form" not in text
    assert "request.get_json" in text
    assert 'log_type="customer_behaviour"' in text


def test_customer_behaviour_recorder_is_installed_once_for_all_html_pages():
    main = Path("main.py").read_text(encoding="utf-8")
    recorder = Path("services/governed_customer_behaviour_recorder.py").read_text(encoding="utf-8")
    assert "install_governed_customer_behaviour_recorder(app)" in main
    assert "@app.after_request" in recorder
    assert '"text/html"' in recorder
    assert 'body.replace("</body>", _SCRIPT + "\\n</body>", 1)' in recorder
    assert "_bt38_customer_behaviour_recorder_installed" in recorder


def test_customer_behaviour_endpoint_rejects_arbitrary_payload_fields():
    text = Path("services/governed_customer_behaviour_recorder.py").read_text(encoding="utf-8")
    assert "_ALLOWED_EVENTS" in text
    assert "_ALLOWED_KEYS" in text
    assert "_MAX_BODY" in text
    assert '== "cross-site"' in text
    assert "isinstance(value, (dict, list))" in text
