from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "templates" / "product_linking.html"
ROUTES = ROOT / "governed_routes.py"

def execute_group_push_body():
    text = TEMPLATE.read_text(encoding="utf-8")
    start = text.index("async function executeGroupPush()")
    end = text.index("// ==========================================", start)
    return text[start:end]

def test_inline_execute_group_push_uses_governed_group_push_route():
    body = execute_group_push_body()
    assert "/governed/actions/groups/${groupId}/push" in body
    assert "/governed/groups/${groupId}/propagate-quantity" not in body

def test_adjust_push_button_is_bound_to_execute_group_push():
    text = TEMPLATE.read_text(encoding="utf-8")
    assert 'id="adjustPushBtn"' in text
    assert "e.target.closest ? e.target.closest('#adjustPushBtn')" in text
    assert "executeGroupPush();" in text

def test_backend_group_push_route_contract_exists():
    text = ROUTES.read_text(encoding="utf-8")
    assert '@governed_bp.post("/governed/actions/groups/<int:group_id>/push")' in text
    assert "def governed_group_push(group_id: int):" in text
    assert "push_group_listings(" in text
    assert 'source="ui_group_button"' in text
