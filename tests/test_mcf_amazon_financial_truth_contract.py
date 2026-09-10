from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MCF = (ROOT / "mcf_service.py").read_text(encoding="utf-8")
CONFIRMATION = (ROOT / "services" / "governed_mcf_confirmation.py").read_text(encoding="utf-8")


def test_rate_card_is_explicitly_estimate_only():
    assert "Estimate MCF fees for BT38 suggestions only" in MCF
    assert "'financial_authority': 'estimate'" in MCF
    assert "'financial_source': 'bt38_rate_card_estimate'" in MCF


def test_actual_mcf_order_does_not_persist_local_rate_card_money():
    create_order = MCF.split("def create_mcf_order", 1)[1].split("def submit_mcf_to_amazon", 1)[0]
    assert "self.fee_calculator.calculate_item_fee" not in create_order
    assert "self.fee_calculator.calculate_order_fee" not in create_order
    assert "mcf_fulfillment_fee=None" in create_order
    assert "mcf_first_unit_fee=None" in create_order
    assert "mcf_additional_unit_fee=None" in create_order
    assert "self._mark_actual_financials_pending(mcf_order)" in create_order
    assert "mcf_order.calculate_totals()" not in create_order


def test_missing_amazon_money_remains_pending_not_zero_or_estimated():
    pending = MCF.split("def _mark_actual_financials_pending", 1)[1].split("def _resolve_mcf_fba_store", 1)[0]
    assert "mcf_order.total_mcf_fee = None" in pending
    assert "mcf_order.gross_profit = None" in pending
    assert "mcf_order.profit_margin_percent = None" in pending


def test_status_readback_does_not_calculate_financials():
    status = MCF.split("def get_mcf_order_status", 1)[1].split("def cancel_mcf_order", 1)[0]
    assert "fee_calculator" not in status
    assert "pending_amazon_financial_truth" in status


def test_governed_confirmation_still_uses_exact_amazon_readback():
    assert "refresh_mcf_order_status(order.id)" in CONFIRMATION
    assert '"exact_amazon_readback"' in CONFIRMATION
