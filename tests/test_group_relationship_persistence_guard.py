"""Contracts for Product Linking relationship persistence authority.

Relationship writes are intentionally owned by governed_group_routes.py.
Automatic inventory/webhook/propagation paths may consume relationship identity
but must not become relationship writers. Retired writers fail closed through
legacy_product_linking_guard.py.
"""

from pathlib import Path
import re

import pytest
from flask import Flask

from legacy_product_linking_guard import block_legacy_product_linking_request


WRITER_SOURCE = Path("governed_group_routes.py").read_text(encoding="utf-8")
PROPAGATION_SOURCE = Path("governed_group_propagation_routes.py").read_text(encoding="utf-8")
WEBHOOK_SOURCE = Path("services/governed_webhook_execution.py").read_text(encoding="utf-8")
FBA_IMPORT_SOURCE = Path("services/governed_amazon_inventory_import.py").read_text(encoding="utf-8")


@pytest.fixture()
def app():
    app = Flask(__name__)
    app.config.update(TESTING=True)
    return app


@pytest.mark.parametrize(
    "decorator",
    [
        '@governed_group_bp.post("/governed/groups/create")',
        '@governed_group_bp.post("/governed/groups/<int:group_id>/link-stock")',
        '@governed_group_bp.post("/governed/groups/<int:group_id>/link-listing")',
        '@governed_group_bp.post("/governed/groups/<int:group_id>/unlink")',
    ],
)
def test_explicit_relationship_writes_live_on_governed_post_routes(decorator):
    assert decorator in WRITER_SOURCE


def test_warehouse_original_group_is_immutable_once_owned():
    assert "current_group_id = int(stock.master_product_group_id or 0)" in WRITER_SOURCE
    assert "current_group_id and current_group_id != int(group.id)" in WRITER_SOURCE
    assert '"original_group_immutable": True' not in WRITER_SOURCE  # dict key uses keyword syntax
    assert "original_group_immutable=True" in WRITER_SOURCE
    assert "stock.master_product_group_id = group.id" in WRITER_SOURCE
    assert "stock.is_group_controlled = True" in WRITER_SOURCE


def test_listing_shared_membership_is_mutable_but_returns_to_permanent_original_group():
    assert "listing.master_product_group_id = requested_group_id" in WRITER_SOURCE
    assert "resulting_group_id = int(original_group_id)" in WRITER_SOURCE
    assert "listing.master_product_group_id = resulting_group_id" in WRITER_SOURCE
    assert "Warehouse identity and original group remain permanent" in WRITER_SOURCE


@pytest.mark.parametrize(
    ("source", "name"),
    [
        (PROPAGATION_SOURCE, "group propagation"),
        (WEBHOOK_SOURCE, "marketplace webhook"),
        (FBA_IMPORT_SOURCE, "Amazon FBA inventory import"),
    ],
)
def test_automatic_paths_do_not_assign_product_linking_relationships(source, name):
    assignment_patterns = (
        r"\.master_product_group_id\s*=(?!=)",
        r"\.warehouse_stock_id\s*=(?!=)",
        r"\.is_group_controlled\s*=(?!=)",
    )
    for pattern in assignment_patterns:
        assert re.search(pattern, source) is None, f"{name} became a relationship writer: {pattern}"


def test_fba_import_declares_relationship_and_warehouse_mutation_false():
    assert "Do not mutate warehouse stock quantities or Product Linking relationships" in FBA_IMPORT_SOURCE
    assert '"warehouse_mutation": False' in FBA_IMPORT_SOURCE
    assert '"relationship_mutation": False' in FBA_IMPORT_SOURCE


def test_propagation_is_quantity_push_adapter_not_relationship_writer():
    assert "push_group_listings" in PROPAGATION_SOURCE
    assert "Single unlink authority lives in governed_group_routes.py" in PROPAGATION_SOURCE
    assert "Retired duplicate relationship writer" in PROPAGATION_SOURCE


@pytest.mark.parametrize(
    "path",
    [
        "/governed/groups/45/unlink-disabled",
        "/governed/actions/link-listing-to-warehouse",
        "/governed/actions/unlink-listing",
        "/governed/actions/product-linking-link",
    ],
)
def test_retired_relationship_writers_fail_closed(app, path):
    with app.test_request_context(path, method="POST"):
        response = block_legacy_product_linking_request()
        assert response is not None
        flask_response, status = response
        payload = flask_response.get_json()
        assert status == 409
        assert payload["execution_blocked"] is True
        assert payload["reason"] == "legacy_product_linking_disabled"


@pytest.mark.parametrize(
    "path",
    [
        "/governed/groups/create",
        "/governed/groups/45/link-stock",
        "/governed/groups/45/link-listing",
        "/governed/groups/45/unlink",
        "/governed/groups/45/propagate-quantity",
        "/governed/webhooks/amazon",
        "/governed/amazon/inventory/import",
        "/warehouse",
    ],
)
def test_current_and_read_only_paths_are_not_blocked_by_legacy_guard(app, path):
    method = "POST" if path.startswith("/governed/") else "GET"
    with app.test_request_context(path, method=method):
        assert block_legacy_product_linking_request() is None
