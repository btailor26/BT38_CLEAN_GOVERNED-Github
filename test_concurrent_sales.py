"""Concurrency contracts for the active governed marketplace-order stock path."""

from types import SimpleNamespace
import os
import threading
import time

import pytest

from app import app, db
from models import Warehouse, WarehouseStock, StockLedgerEntry, Store, MarketplaceListing
from services.governed_order_stock_mutation import mutate_warehouse_stock_from_order_line


class TestConcurrentSales:
    @pytest.fixture(autouse=True)
    def setup_and_teardown(self):
        app_env = str(os.getenv("APP_ENV") or app.config.get("ENV") or "").upper()
        database_uri = str(app.config.get("SQLALCHEMY_DATABASE_URI") or "")
        if app_env in {"PROD", "PRODUCTION"} or "ep-royal-fire-ai8c32qw" in database_uri:
            pytest.fail("Database-writing concurrency tests are forbidden against PROD")
        if str(os.getenv("BT38_ALLOW_DATABASE_TESTS") or "").lower() != "true":
            pytest.skip("Set BT38_ALLOW_DATABASE_TESTS=true with an isolated test database")

        with app.app_context():
            warehouse = Warehouse.query.filter_by(name="BT38 CI Test Warehouse").first()
            if warehouse is None:
                warehouse = Warehouse(name="BT38 CI Test Warehouse")
                db.session.add(warehouse)
                db.session.commit()
            self.warehouse_id = warehouse.id
            yield
            db.session.rollback()

    def _create_linked_stock(self, quantity, suffix):
        sku = f"TEST-{suffix}-{time.time_ns()}"
        stock = WarehouseStock(
            sku=sku,
            warehouse_id=self.warehouse_id,
            available_quantity=quantity,
            stock_version=0,
            location="Test Warehouse",
            is_active=True,
        )
        store = Store(name=f"Store-{suffix}-{time.time_ns()}", platform="test", is_active=True)
        db.session.add_all([stock, store])
        db.session.flush()
        listing = MarketplaceListing(
            warehouse_stock_id=stock.id,
            store_id=store.id,
            external_listing_id=f"LISTING-{suffix}-{time.time_ns()}",
            external_sku=sku,
            is_active=True,
        )
        db.session.add(listing)
        db.session.commit()
        return stock, store

    @staticmethod
    def _line(store_id, stock_id, sku, order_id, quantity, status="processed"):
        return SimpleNamespace(
            store_id=store_id,
            warehouse_stock_id=stock_id,
            marketplace_order_id=order_id,
            sku=sku,
            quantity=quantity,
            status=status,
            fulfillment_type="FBM",
        )

    def test_simultaneous_sales_single_unit(self):
        """Only one of two simultaneous one-unit sales may consume the last unit."""
        with app.app_context():
            stock, store = self._create_linked_stock(1, "LAST-UNIT")
            stock_id, store_id, sku = stock.id, store.id, stock.sku

        results = []
        start = threading.Barrier(2)

        def sell(order_id):
            with app.app_context():
                start.wait()
                result = mutate_warehouse_stock_from_order_line(
                    self._line(store_id, stock_id, sku, order_id, 1),
                    source="concurrency_contract",
                )
                results.append(result)

        threads = [
            threading.Thread(target=sell, args=("ORDER-A",)),
            threading.Thread(target=sell, args=("ORDER-B",)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert sum(1 for result in results if result.get("success") and not result.get("skipped")) == 1
        assert sum(1 for result in results if result.get("reason") == "insufficient_stock") == 1
        with app.app_context():
            final_stock = db.session.get(WarehouseStock, stock_id)
            assert final_stock.available_quantity == 0

    def test_idempotency_duplicate_order(self):
        with app.app_context():
            stock, store = self._create_linked_stock(10, "IDEMPOTENT")
            line = self._line(store.id, stock.id, stock.sku, "DUP-ORDER", 3)
            first = mutate_warehouse_stock_from_order_line(line, source="concurrency_contract")
            second = mutate_warehouse_stock_from_order_line(line, source="concurrency_contract")

            assert first.get("success") is True and first.get("skipped") is False
            assert second.get("success") is True and second.get("skipped") is True
            assert second.get("reason") in {"already_mutated", "already_mutated_after_lock"}
            db.session.refresh(stock)
            assert stock.available_quantity == 7
            assert StockLedgerEntry.query.filter_by(warehouse_stock_id=stock.id, transaction_type="sale").count() == 1

    def test_concurrent_sales_with_sufficient_stock(self):
        with app.app_context():
            stock, store = self._create_linked_stock(10, "SUFFICIENT")
            stock_id, store_id, sku = stock.id, store.id, stock.sku

        results = []
        start = threading.Barrier(3)

        def sell(order_id, quantity):
            with app.app_context():
                start.wait()
                results.append(
                    mutate_warehouse_stock_from_order_line(
                        self._line(store_id, stock_id, sku, order_id, quantity),
                        source="concurrency_contract",
                    )
                )

        threads = [
            threading.Thread(target=sell, args=("ORDER-1", 2)),
            threading.Thread(target=sell, args=("ORDER-2", 3)),
            threading.Thread(target=sell, args=("ORDER-3", 4)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert all(result.get("success") and not result.get("skipped") for result in results)
        with app.app_context():
            final_stock = db.session.get(WarehouseStock, stock_id)
            assert final_stock.available_quantity == 1
            assert StockLedgerEntry.query.filter_by(warehouse_stock_id=stock_id, transaction_type="sale").count() == 3

    def test_insufficient_stock_handling(self):
        with app.app_context():
            stock, store = self._create_linked_stock(5, "INSUFFICIENT")
            result = mutate_warehouse_stock_from_order_line(
                self._line(store.id, stock.id, stock.sku, "TOO-LARGE", 10),
                source="concurrency_contract",
            )

            assert result.get("success") is False
            assert result.get("reason") == "insufficient_stock"
            db.session.refresh(stock)
            assert stock.available_quantity == 5
            assert StockLedgerEntry.query.filter_by(warehouse_stock_id=stock.id).count() == 0

    def test_return_restores_stock(self):
        with app.app_context():
            stock, store = self._create_linked_stock(10, "RETURN")
            sale = mutate_warehouse_stock_from_order_line(
                self._line(store.id, stock.id, stock.sku, "RETURN-SALE", 3),
                source="concurrency_contract",
            )
            assert sale.get("success") is True
            db.session.refresh(stock)
            assert stock.available_quantity == 7

            returned = mutate_warehouse_stock_from_order_line(
                self._line(store.id, stock.id, stock.sku, "RETURN-EVENT", 3, status="returned"),
                source="concurrency_contract",
            )
            assert returned.get("success") is True
            db.session.refresh(stock)
            assert stock.available_quantity == 10
            assert StockLedgerEntry.query.filter_by(warehouse_stock_id=stock.id, transaction_type="return").count() == 1
