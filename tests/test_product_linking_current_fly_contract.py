from pathlib import Path

def test_product_linking_template_matches_current_fly_contract():
    s = Path("templates/product_linking.html").read_text(encoding="utf-8")

    required = [
        "GroupView",
        "This page manages RELATIONSHIPS only",
        "Product Groups",
        "adjustPushBtn",
        "executeGroupPush",
        "/governed/groups/${groupId}/propagate-quantity",
        "Push from GroupView",
        "originalFetch",
    ]
    for token in required:
        assert token in s

    forbidden = [
        "bt38WarehouseSyncBtn",
        "Warehouse Truth",
    ]
    for token in forbidden:
        assert token not in s


def test_product_linking_backend_routes_exist_in_source():
    governed = Path("governed_routes.py").read_text(encoding="utf-8")
    propagation = Path("governed_group_propagation_routes.py").read_text(encoding="utf-8")
    app = Path("app.py").read_text(encoding="utf-8")

    assert '/governed/actions/groups/<int:group_id>/push' in governed
    assert "def governed_group_push" in governed
    assert "push_group_listings" in governed
    assert 'source="ui_group_button"' in governed

    assert "/governed/groups/<int:group_id>/propagate-quantity" in propagation
    assert "def governed_group_propagate_quantity" in propagation
    assert "WarehouseStock.sellable_quantity is the authority" in propagation

    assert "governed_group_propagation_bp" in app
    assert "register_blueprint(governed_group_propagation_bp)" in app
