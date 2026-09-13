"""
Test Suite for Concurrent Marketplace Sales

Tests the concurrency protection system to ensure:
1. No overselling when simultaneous sales occur on different marketplaces
2. Row-level locking prevents race conditions
3. Idempotency prevents duplicate order processing
4. Stock version tracking works correctly
5. Proper audit trails are created

Run with: pytest test_concurrent_sales.py -v
"""

import pytest
import os
import threading
import time
from datetime import datetime
from app import app, db
from models import Warehouse, WarehouseStock, MarketplaceOrder, StockLedgerEntry, Store, MarketplaceListing
from marketplace_order_processor import MarketplaceOrderProcessor


class TestConcurrentSales:
    """Test concurrent marketplace sales scenarios"""

    @pytest.fixture(autouse=True)
    def setup_and_teardown(self):
        """Setup test database and cleanup after each test"""
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

    def test_simultaneous_sales_single_unit(self):
        """
        CRITICAL TEST: Two marketplaces try to sell the last unit simultaneously.
        Only ONE sale should succeed.
        """
        with app.app_context():
            test_sku = f'TEST-SKU-{int(time.time())}'
            warehouse_stock = WarehouseStock(
                sku=test_sku,
                warehouse_id=self.warehouse_id,
                available_quantity=1,
                stock_version=0,
                location='Test Warehouse',
                is_active=True
            )
            db.session.add(warehouse_stock)

            store1 = Store(name='eBay-Test', platform='ebay', is_active=True)
            store2 = Store(name='Amazon-Test', platform='amazon', is_active=True)
            db.session.add(store1)
            db.session.add(store2)
            db.session.commit()

            store1_id = store1.id
            store2_id = store2.id
            results = {'store1': None, 'store2': None}

            def process_sale_store1():
                with app.app_context():
                    success, msg, order = MarketplaceOrderProcessor.process_order(
                        store_id=store1_id,
                        marketplace_order_id='EBAY-ORDER-001',
                        sku=test_sku,
                        quantity=1,
                        notes='Concurrent test - eBay'
                    )
                    results['store1'] = {'success': success, 'message': msg, 'order': order}

            def process_sale_store2():
                with app.app_context():
                    success, msg, order = MarketplaceOrderProcessor.process_order(
                        store_id=store2_id,
                        marketplace_order_id='AMAZON-ORDER-001',
                        sku=test_sku,
                        quantity=1,
                        notes='Concurrent test - Amazon'
                    )
                    results['store2'] = {'success': success, 'message': msg, 'order': order}

            thread1 = threading.Thread(target=process_sale_store1)
            thread2 = threading.Thread(target=process_sale_store2)
            thread1.start()
            thread2.start()
            thread1.join()
            thread2.join()

            success_count = sum(1 for r in results.values() if r and r['success'])
            assert success_count == 1, f"Expected exactly 1 successful sale, got {success_count}"

            final_stock = WarehouseStock.query.filter_by(sku=test_sku).first()
            assert final_stock.available_quantity == 0, \
                f"Expected 0 stock remaining, got {final_stock.available_quantity}"
            assert final_stock.stock_version == 1, \
                f"Expected version=1, got {final_stock.stock_version}"

            processed_orders = MarketplaceOrder.query.filter_by(
                sku=test_sku, status='processed'
            ).count()
            assert processed_orders == 1, \
                f"Expected exactly 1 processed order, got {processed_orders}"

            failed_orders = MarketplaceOrder.query.filter_by(
                sku=test_sku, status='failed'
            ).count()
            assert failed_orders == 1, \
                f"Expected exactly 1 failed order, got {failed_orders}"

            print("✅ PASS: Concurrent single-unit test - no overselling detected")

    def test_idempotency_duplicate_order(self):
        """Test that processing the same order twice doesn't double-decrement stock"""
        with app.app_context():
            test_sku = f'TEST-SKU-IDEM-{int(time.time())}'
            warehouse_stock = WarehouseStock(
                sku=test_sku,
                warehouse_id=self.warehouse_id,
                available_quantity=10,
                stock_version=0,
                location='Test Warehouse',
                is_active=True
            )
            db.session.add(warehouse_stock)

            store = Store(name='Test-Store', platform='test', is_active=True)
            db.session.add(store)
            db.session.commit()

            success1, msg1, order1 = MarketplaceOrderProcessor.process_order(
                store_id=store.id,
                marketplace_order_id='DUP-ORDER-001',
                sku=test_sku,
                quantity=3
            )

            success2, msg2, order2 = MarketplaceOrderProcessor.process_order(
                store_id=store.id,
                marketplace_order_id='DUP-ORDER-001',
                sku=test_sku,
                quantity=3
            )

            assert success1 is True, "First order should succeed"
            assert success2 is True, "Second attempt should succeed (already processed)"
            assert 'already processed' in msg2.lower(), \
                f"Expected 'already processed' message, got: {msg2}"

            final_stock = WarehouseStock.query.filter_by(sku=test_sku).first()
            assert final_stock.available_quantity == 7, \
                f"Expected 7 units remaining (10-3), got {final_stock.available_quantity}"

            ledger_count = StockLedgerEntry.query.filter_by(
                warehouse_stock_id=warehouse_stock.id,
                transaction_type='marketplace_sale'
            ).count()
            assert ledger_count == 1, \
                f"Expected 1 ledger entry, got {ledger_count}"

            print("✅ PASS: Idempotency test - duplicate order handled correctly")

    def test_concurrent_sales_with_sufficient_stock(self):
        """Test that concurrent sales work correctly when sufficient stock exists"""
        with app.app_context():
            test_sku = f'TEST-SKU-MULTI-{int(time.time())}'
            warehouse_stock = WarehouseStock(
                sku=test_sku,
                warehouse_id=self.warehouse_id,
                available_quantity=10,
                stock_version=0,
                location='Test Warehouse',
                is_active=True
            )
            db.session.add(warehouse_stock)

            store1 = Store(name='Store1', platform='test1', is_active=True)
            store2 = Store(name='Store2', platform='test2', is_active=True)
            store3 = Store(name='Store3', platform='test3', is_active=True)
            db.session.add(store1)
            db.session.add(store2)
            db.session.add(store3)
            db.session.commit()

            store1_id, store2_id, store3_id = store1.id, store2.id, store3.id
            results = []

            def process_sale(store_id, order_id, qty):
                with app.app_context():
                    success, msg, order = MarketplaceOrderProcessor.process_order(
                        store_id=store_id,
                        marketplace_order_id=order_id,
                        sku=test_sku,
                        quantity=qty
                    )
                    results.append({'success': success, 'qty': qty, 'msg': msg})

            threads = [
                threading.Thread(target=process_sale, args=(store1_id, 'ORD-1', 2)),
                threading.Thread(target=process_sale, args=(store2_id, 'ORD-2', 3)),
                threading.Thread(target=process_sale, args=(store3_id, 'ORD-3', 4))
            ]

            for t in threads:
                t.start()
            for t in threads:
                t.join()

            success_count = sum(1 for r in results if r['success'])
            assert success_count == 3, \
                f"Expected all 3 sales to succeed, got {success_count}"

            final_stock = WarehouseStock.query.filter_by(sku=test_sku).first()
            assert final_stock.available_quantity == 1, \
                f"Expected 1 unit remaining, got {final_stock.available_quantity}"
            assert final_stock.stock_version == 3, \
                f"Expected version=3, got {final_stock.stock_version}"

            print("✅ PASS: Concurrent multi-sale test - all transactions processed correctly")

    def test_insufficient_stock_handling(self):
        """Test that orders with insufficient stock are properly rejected"""
        with app.app_context():
            test_sku = f'TEST-SKU-INSUF-{int(time.time())}'
            warehouse_stock = WarehouseStock(
                sku=test_sku,
                warehouse_id=self.warehouse_id,
                available_quantity=5,
                stock_version=0,
                location='Test Warehouse',
                is_active=True
            )
            db.session.add(warehouse_stock)

            store = Store(name='Test-Store', platform='test', is_active=True)
            db.session.add(store)
            db.session.commit()

            success, msg, order = MarketplaceOrderProcessor.process_order(
                store_id=store.id,
                marketplace_order_id='INSUF-ORDER-001',
                sku=test_sku,
                quantity=10
            )

            assert success is False, "Order should fail due to insufficient stock"
            assert 'insufficient stock' in msg.lower(), \
                f"Expected 'insufficient stock' message, got: {msg}"
            assert order.status == 'failed', \
                f"Order status should be 'failed', got: {order.status}"

            final_stock = WarehouseStock.query.filter_by(sku=test_sku).first()
            assert final_stock.available_quantity == 5, \
                f"Stock should remain at 5, got {final_stock.available_quantity}"

            ledger_count = StockLedgerEntry.query.filter_by(
                warehouse_stock_id=warehouse_stock.id
            ).count()
            assert ledger_count == 0, \
                f"Expected no ledger entries for failed order, got {ledger_count}"

            print("✅ PASS: Insufficient stock test - order properly rejected")

    def test_order_cancellation_restores_stock(self):
        """Test that canceling an order restores stock correctly"""
        with app.app_context():
            test_sku = f'TEST-SKU-CANCEL-{int(time.time())}'
            warehouse_stock = WarehouseStock(
                sku=test_sku,
                warehouse_id=self.warehouse_id,
                available_quantity=10,
                stock_version=0,
                location='Test Warehouse',
                is_active=True
            )
            db.session.add(warehouse_stock)

            store = Store(name='Test-Store', platform='test', is_active=True)
            db.session.add(store)
            db.session.commit()

            success, msg, order = MarketplaceOrderProcessor.process_order(
                store_id=store.id,
                marketplace_order_id='CANCEL-ORDER-001',
                sku=test_sku,
                quantity=3
            )

            assert success is True, "Initial order should succeed"

            stock_after_sale = WarehouseStock.query.filter_by(sku=test_sku).first()
            assert stock_after_sale.available_quantity == 7

            cancel_success, cancel_msg = MarketplaceOrderProcessor.cancel_order(
                order.id,
                reason="Customer requested refund"
            )

            assert cancel_success is True, f"Cancellation should succeed: {cancel_msg}"

            final_stock = WarehouseStock.query.filter_by(sku=test_sku).first()
            assert final_stock.available_quantity == 10, \
                f"Stock should be restored to 10, got: {final_stock.available_quantity}"

            db.session.refresh(order)
            assert order.status == 'cancelled', \
                f"Order status should be 'cancelled', got: {order.status}"

            refund_ledger = StockLedgerEntry.query.filter_by(
                warehouse_stock_id=warehouse_stock.id,
                transaction_type='marketplace_refund'
            ).first()
            assert refund_ledger is not None, "Refund ledger entry should exist"
            quantity_restored = refund_ledger.available_quantity_after - refund_ledger.available_quantity_before
            assert quantity_restored == 3, \
                f"Refund should restore 3 units, got: {quantity_restored}"

            print("✅ PASS: Order cancellation test - stock properly restored")


if __name__ == '__main__':
    pytest.main([__file__, '-v', '-s'])
