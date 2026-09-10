"""
MCF Service - Multi-Channel Fulfillment Engine

Phase 2: FBA as the Multi-Channel Fulfillment Engine

This service handles:
1. Creating MCF orders via Amazon Fulfillment Outbound API
2. Mapping external SKUs to FBA SKUs
3. Getting MCF shipping estimates for suggestions
4. Tracking MCF order status and shipments
5. Preserving Amazon-supplied financial truth for actual MCF costs

Financial authority rule:
- The local MCF fee calculator is estimate-only and may be used before an order
  exists to power BT38 suggestions.
- Once an MCF order exists, BT38 must not manufacture an actual fulfilment cost
  from a rate card, quantity formula, fallback, or zero.
- Actual MCF cost/profit remains unknown until Amazon supplies order-specific
  financial data for that exact MCF fulfilment.

Critical: FBA orders do NOT deduct warehouse stock - Amazon holds the inventory.
"""

import logging
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from app import db
from models import (
    MCFOrder, MCFOrderItem, MarketplaceOrder, AmazonFBAInventory,
    MarketplaceListing, Store, WarehouseStock, OrderFees,
    ListingMarginConfig
)
from amazon_rest_api import AmazonRestAPIClient

logger = logging.getLogger(__name__)


class MCFShippingSpeed:
    """MCF Shipping speed options"""
    STANDARD = 'Standard'
    EXPEDITED = 'Expedited'
    PRIORITY = 'Priority'
    
    @classmethod
    def all(cls):
        return [cls.STANDARD, cls.EXPEDITED, cls.PRIORITY]


class MCFFeeCalculator:
    """
    Estimate MCF fees for BT38 suggestions only.

    These local values are not Amazon order-specific financial evidence and must
    never be persisted or presented as the actual cost of an existing MCF order.

    Approximate legacy UK suggestion values:
    - Standard: £4.49 first unit, +£0.90 per additional unit
    - Expedited: £5.99 first unit, +£1.20 per additional unit
    - Priority: £8.99 first unit, +£1.80 per additional unit

    Plus legacy estimate assumptions for weight/per-shipment handling.
    """
    
    MCF_FEES = {
        'Standard': {'first_unit': 4.49, 'additional_unit': 0.90, 'per_shipment': 0.50},
        'Expedited': {'first_unit': 5.99, 'additional_unit': 1.20, 'per_shipment': 0.75},
        'Priority': {'first_unit': 8.99, 'additional_unit': 1.80, 'per_shipment': 1.00},
    }
    
    WEIGHT_HANDLING_PER_KG = 0.35
    WEIGHT_HANDLING_THRESHOLD_KG = 0.5
    
    @classmethod
    def calculate_item_fee(cls, quantity: int, shipping_speed: str = 'Standard', 
                          weight_kg: float = 0.0) -> Dict:
        """Return a local estimate for suggestion/planning UI only."""
        fees = cls.MCF_FEES.get(shipping_speed, cls.MCF_FEES['Standard'])
        first_unit_fee = fees['first_unit']
        additional_unit_fee = fees['additional_unit']
        if quantity <= 0:
            return {'first_unit_fee': 0, 'additional_unit_fee': 0, 'total_fee': 0, 'weight_handling': 0, 'units': 0, 'authority': 'estimate', 'source': 'bt38_rate_card_estimate'}
        fulfillment_fee = first_unit_fee if quantity == 1 else first_unit_fee + (additional_unit_fee * (quantity - 1))
        weight_handling = 0
        if weight_kg > cls.WEIGHT_HANDLING_THRESHOLD_KG:
            extra_weight = weight_kg - cls.WEIGHT_HANDLING_THRESHOLD_KG
            weight_handling = extra_weight * cls.WEIGHT_HANDLING_PER_KG * quantity
        return {'first_unit_fee': first_unit_fee, 'additional_unit_fee': additional_unit_fee, 'total_fee': fulfillment_fee + weight_handling, 'weight_handling': weight_handling, 'units': quantity, 'authority': 'estimate', 'source': 'bt38_rate_card_estimate'}
    
    @classmethod
    def calculate_order_fee(cls, items: List[Dict], shipping_speed: str = 'Standard') -> Dict:
        """Return a local order-level estimate for suggestion/planning UI only."""
        fees = cls.MCF_FEES.get(shipping_speed, cls.MCF_FEES['Standard'])
        per_shipment_fee = fees['per_shipment']
        total_units = sum(item.get('quantity', 1) for item in items)
        total_fulfillment = 0
        total_weight_handling = 0
        for item in items:
            item_fee = cls.calculate_item_fee(item.get('quantity', 1), shipping_speed, item.get('weight_kg', 0))
            total_fulfillment += item_fee['total_fee']
            total_weight_handling += item_fee['weight_handling']
        return {'per_shipment_fee': per_shipment_fee, 'fulfillment_fee': total_fulfillment, 'weight_handling': total_weight_handling, 'total_units': total_units, 'total_fee': per_shipment_fee + total_fulfillment, 'authority': 'estimate', 'source': 'bt38_rate_card_estimate'}


class MCFService:
    """Multi-Channel Fulfillment Service."""
    
    def __init__(self):
        self.fee_calculator = MCFFeeCalculator()

    @staticmethod
    def _mark_actual_financials_pending(mcf_order: MCFOrder) -> None:
        """Never manufacture actual MCF money before Amazon supplies it."""
        mcf_order.mcf_fulfillment_fee = None
        mcf_order.mcf_per_unit_fee = None
        mcf_order.mcf_per_shipment_fee = None
        mcf_order.mcf_weight_handling_fee = None
        mcf_order.total_mcf_fee = None
        mcf_order.gross_profit = None
        mcf_order.profit_margin_percent = None

    def _resolve_mcf_fba_store(self, mcf_order):
        """Use the Amazon store already resolved by governed MCF."""
        store_id = getattr(mcf_order, "fba_store_id", None)
        if store_id:
            store = db.session.get(Store, int(store_id))
            if store is not None and bool(getattr(store, "is_active", False)) and "amazon" in str(getattr(store, "platform", "") or "").lower():
                return store
        return Store.query.filter(Store.is_active == True).filter(Store.platform.ilike("%amazon%")).order_by(Store.id.asc()).first()
    
    def find_fba_listing_for_sku(self, sku: str, store_id: int = None) -> Optional[AmazonFBAInventory]:
        """Resolve FBA through the existing Product Linking group."""
        warehouse_stock = WarehouseStock.query.filter_by(sku=sku).first()
        if warehouse_stock is None or not warehouse_stock.master_product_group_id:
            return None
        group_members = WarehouseStock.query.filter(WarehouseStock.master_product_group_id == int(warehouse_stock.master_product_group_id)).all()
        stock_ids = [int(row.id) for row in group_members]
        amazon_stores = [store for store in Store.query.filter(Store.is_active == True).all() if "amazon" in str(store.platform or "").lower()]
        amazon_store_ids = [int(store.id) for store in amazon_stores]
        if store_id:
            amazon_store_ids = [value for value in amazon_store_ids if value == int(store_id)]
        if not amazon_store_ids:
            return None
        listings = MarketplaceListing.query.filter(MarketplaceListing.store_id.in_(amazon_store_ids), MarketplaceListing.warehouse_stock_id.in_(stock_ids), MarketplaceListing.is_active == True).all()
        seller_skus = {str(listing.external_sku or "").strip() for listing in listings if str(listing.external_sku or "").strip()}
        fnskus = {str(listing.fnsku or "").strip() for listing in listings if str(listing.fnsku or "").strip()}
        if not seller_skus and not fnskus:
            return None
        query = AmazonFBAInventory.query.filter(AmazonFBAInventory.store_id.in_(amazon_store_ids), AmazonFBAInventory.is_active == True, AmazonFBAInventory.is_archived == False, AmazonFBAInventory.mcf_enabled == True)
        if seller_skus and fnskus:
            query = query.filter(db.or_(AmazonFBAInventory.seller_sku.in_(seller_skus), AmazonFBAInventory.fnsku.in_(fnskus)))
        elif seller_skus:
            query = query.filter(AmazonFBAInventory.seller_sku.in_(seller_skus))
        else:
            query = query.filter(AmazonFBAInventory.fnsku.in_(fnskus))
        return query.order_by(AmazonFBAInventory.available_quantity.desc(), AmazonFBAInventory.updated_at.desc(), AmazonFBAInventory.id.desc()).first()

    def check_fba_availability(self, sku: str, quantity: int) -> Tuple[bool, str, Optional[AmazonFBAInventory]]:
        fba_inventory = self.find_fba_listing_for_sku(sku)
        if not fba_inventory:
            return False, f"No linked FBA inventory found for SKU: {sku}", None
        available_qty = int(fba_inventory.available_quantity or 0)
        if available_qty < int(quantity or 0):
            return False, f"Insufficient FBA inventory: {available_qty} available, {quantity} needed", fba_inventory
        return True, f"FBA inventory available: {available_qty}", fba_inventory

    def get_mcf_estimate(self, items: List[Dict], shipping_speed: str = 'Standard', destination_country: str = 'GB') -> Dict:
        """Get an explicitly non-authoritative MCF estimate for BT38 suggestions."""
        result = {'available': True, 'items': [], 'shipping_speed': shipping_speed, 'fees': {}, 'estimated_delivery': None, 'errors': [], 'financial_authority': 'estimate', 'financial_source': 'bt38_rate_card_estimate'}
        all_available = True
        fee_items = []
        for item in items:
            sku = item.get('sku')
            quantity = item.get('quantity', 1)
            weight_kg = item.get('weight_kg', 0.3)
            available, message, fba_listing = self.check_fba_availability(sku, quantity)
            item_result = {'sku': sku, 'quantity': quantity, 'available': available, 'message': message, 'fba_sku': fba_listing.seller_sku if fba_listing else None, 'fba_available_qty': fba_listing.available_quantity if fba_listing else 0}
            if available and fba_listing:
                item_fee = self.fee_calculator.calculate_item_fee(quantity, shipping_speed, weight_kg)
                item_result['fee'] = item_fee
                fee_items.append({'quantity': quantity, 'weight_kg': weight_kg})
            else:
                all_available = False
                result['errors'].append(message)
            result['items'].append(item_result)
        result['available'] = all_available
        if all_available and fee_items:
            result['fees'] = self.fee_calculator.calculate_order_fee(fee_items, shipping_speed)
            delivery_days = {'Standard': 5, 'Expedited': 3, 'Priority': 2}.get(shipping_speed, 5)
            if destination_country != 'GB':
                delivery_days += 3
            result['estimated_delivery'] = (datetime.utcnow() + timedelta(days=delivery_days)).isoformat()
        return result
    
    def create_mcf_order(self, source_order_id: str, source_channel: str, source_store_id: int, items: List[Dict], shipping_address: Dict, shipping_speed: str = 'Standard', order_total: float = 0.0, platform_fees: float = 0.0) -> Tuple[bool, str, Optional[MCFOrder]]:
        """Create an MCF order without manufacturing actual Amazon financials."""
        try:
            fulfillment_order_id = f"MCF-{source_channel[:3].upper()}-{uuid.uuid4().hex[:8].upper()}"
            mcf_order = MCFOrder(source_order_id=source_order_id, source_channel=source_channel, source_store_id=source_store_id, seller_fulfillment_order_id=fulfillment_order_id, displayable_order_id=source_order_id[:50] if source_order_id else fulfillment_order_id, destination_name=shipping_address.get('name', ''), destination_address_line1=shipping_address.get('address_line1', ''), destination_address_line2=shipping_address.get('address_line2', ''), destination_city=shipping_address.get('city', ''), destination_state=shipping_address.get('state', ''), destination_postcode=shipping_address.get('postcode', ''), destination_country=shipping_address.get('country', 'GB'), destination_phone=shipping_address.get('phone', ''), shipping_speed=shipping_speed, displayable_comment=f"Order from {source_channel}: {source_order_id}", status='pending', order_total=order_total, platform_fees=platform_fees, currency='GBP')
            self._mark_actual_financials_pending(mcf_order)
            db.session.add(mcf_order)
            db.session.flush()
            total_product_cost = 0
            for item_data in items:
                sku = item_data.get('sku')
                quantity = item_data.get('quantity', 1)
                unit_price = item_data.get('unit_price', 0)
                product_cost = item_data.get('product_cost', 0)
                available, message, fba_listing = self.check_fba_availability(sku, quantity)
                if not available:
                    db.session.rollback()
                    return False, message, None
                mcf_item = MCFOrderItem(mcf_order_id=mcf_order.id, source_sku=sku, fba_listing_id=None, fba_sku=fba_listing.seller_sku, asin=fba_listing.asin, fnsku=fba_listing.fnsku, quantity=quantity, unit_price=unit_price, product_cost=product_cost, mcf_fulfillment_fee=None, mcf_first_unit_fee=None, mcf_additional_unit_fee=None, status='pending')
                db.session.add(mcf_item)
                total_product_cost += product_cost * quantity
            mcf_order.product_cost = total_product_cost
            self._mark_actual_financials_pending(mcf_order)
            db.session.commit()
            logger.info("Created MCF order %s for %s order %s; actual MCF cost pending Amazon financial truth", fulfillment_order_id, source_channel, source_order_id)
            return True, f"MCF order created: {fulfillment_order_id}", mcf_order
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error creating MCF order: {str(e)}")
            return False, f"Error creating MCF order: {str(e)}", None
    
    def submit_mcf_to_amazon(self, mcf_order: MCFOrder) -> Tuple[bool, str]:
        """Submit MCF order to Amazon Fulfillment Outbound API."""
        try:
            fba_store = self._resolve_mcf_fba_store(mcf_order)
            if not fba_store:
                return False, "No active Amazon FBA store configured"
            credentials = fba_store.amazon_credentials
            if not credentials:
                return False, "Amazon FBA credentials not configured"
            api_client = AmazonRestAPIClient(credentials, 'A1F83G8C2ARO7P')
            items_payload = []
            for item in mcf_order.items.all():
                items_payload.append({'sellerSku': item.fba_sku, 'sellerFulfillmentOrderItemId': f"{mcf_order.seller_fulfillment_order_id}-{item.id}", 'quantity': item.quantity, 'perUnitDeclaredValue': {'currencyCode': 'GBP', 'value': str(item.unit_price or 0)}})
            payload = {'sellerFulfillmentOrderId': mcf_order.seller_fulfillment_order_id, 'displayableOrderId': mcf_order.displayable_order_id, 'displayableOrderDate': mcf_order.created_at.isoformat() + 'Z', 'displayableOrderComment': mcf_order.displayable_comment or '', 'shippingSpeedCategory': mcf_order.shipping_speed.upper(), 'destinationAddress': {'name': mcf_order.destination_name or 'Customer', 'addressLine1': mcf_order.destination_address_line1 or '', 'addressLine2': mcf_order.destination_address_line2 or '', 'city': mcf_order.destination_city or '', 'stateOrRegion': mcf_order.destination_state or '', 'postalCode': mcf_order.destination_postcode or '', 'countryCode': mcf_order.destination_country or 'GB', 'phone': mcf_order.destination_phone or ''}, 'items': items_payload}
            success, data, error = api_client._make_request('POST', '/fba/outbound/2020-07-01/fulfillmentOrders', json_data=payload)
            if success:
                mcf_order.status = 'submitted'
                mcf_order.amazon_status = 'RECEIVED'
                mcf_order.amazon_status_updated_at = datetime.utcnow()
                db.session.commit()
                logger.info(f"MCF order {mcf_order.seller_fulfillment_order_id} submitted to Amazon")
                return True, "MCF order submitted to Amazon successfully"
            mcf_order.status = 'failed'
            mcf_order.last_error = error
            mcf_order.retry_count += 1
            db.session.commit()
            logger.error(f"Failed to submit MCF order to Amazon: {error}")
            return False, f"Failed to submit to Amazon: {error}"
        except Exception as e:
            mcf_order.status = 'failed'
            mcf_order.last_error = str(e)
            mcf_order.retry_count += 1
            db.session.commit()
            logger.error(f"Error submitting MCF order to Amazon: {str(e)}")
            return False, f"Error: {str(e)}"
    
    def get_mcf_order_status(self, mcf_order: MCFOrder) -> Tuple[bool, Dict]:
        """Get updated non-financial status/tracking truth for an MCF order from Amazon."""
        try:
            fba_store = self._resolve_mcf_fba_store(mcf_order)
            if not fba_store:
                return False, {'error': 'No active Amazon FBA store'}
            credentials = fba_store.amazon_credentials
            if not credentials:
                return False, {'error': 'Amazon FBA credentials not configured'}
            api_client = AmazonRestAPIClient(credentials, 'A1F83G8C2ARO7P')
            success, data, error = api_client._make_request('GET', f'/fba/outbound/2020-07-01/fulfillmentOrders/{mcf_order.seller_fulfillment_order_id}')
            if success and data:
                payload = data.get('payload', {})
                fulfillment_order = payload.get('fulfillmentOrder', {})
                mcf_order.amazon_status = fulfillment_order.get('fulfillmentOrderStatus')
                mcf_order.amazon_status_updated_at = datetime.utcnow()
                if mcf_order.amazon_status in ['COMPLETE', 'COMPLETE_PARTIALLED']:
                    mcf_order.status = 'completed'
                elif mcf_order.amazon_status in ['CANCELLED', 'INVALID']:
                    mcf_order.status = 'cancelled'
                elif mcf_order.amazon_status in ['PLANNING', 'PROCESSING']:
                    mcf_order.status = 'processing'
                shipments = payload.get('fulfillmentShipments', [])
                if shipments:
                    first_shipment = shipments[0]
                    mcf_order.carrier = first_shipment.get('carrierCode')
                    mcf_order.tracking_number = first_shipment.get('trackingNumber')
                    ship_date = first_shipment.get('shipDate')
                    if ship_date:
                        mcf_order.ship_date = datetime.fromisoformat(ship_date.replace('Z', '+00:00'))
                    est_arrival = first_shipment.get('estimatedArrivalDate')
                    if est_arrival:
                        mcf_order.estimated_arrival_date = datetime.fromisoformat(est_arrival.replace('Z', '+00:00'))
                db.session.commit()
                return True, {'status': mcf_order.amazon_status, 'carrier': mcf_order.carrier, 'tracking_number': mcf_order.tracking_number, 'ship_date': mcf_order.ship_date.isoformat() if mcf_order.ship_date else None, 'estimated_arrival': mcf_order.estimated_arrival_date.isoformat() if mcf_order.estimated_arrival_date else None, 'actual_mcf_cost': None, 'actual_mcf_cost_authority': 'pending_amazon_financial_truth'}
            return False, {'error': error or 'Failed to get status'}
        except Exception as e:
            logger.error(f"Error getting MCF order status: {str(e)}")
            return False, {'error': str(e)}
    
    def cancel_mcf_order(self, mcf_order: MCFOrder) -> Tuple[bool, str]:
        """Cancel an MCF order with Amazon."""
        try:
            if mcf_order.status in ['completed', 'cancelled']:
                return False, f"Cannot cancel order in status: {mcf_order.status}"
            fba_store = self._resolve_mcf_fba_store(mcf_order)
            if not fba_store:
                return False, "No active Amazon FBA store"
            credentials = fba_store.amazon_credentials
            if not credentials:
                return False, "Amazon FBA credentials not configured"
            api_client = AmazonRestAPIClient(credentials, 'A1F83G8C2ARO7P')
            success, data, error = api_client._make_request('PUT', f'/fba/outbound/2020-07-01/fulfillmentOrders/{mcf_order.seller_fulfillment_order_id}/cancel')
            if success:
                mcf_order.status = 'cancelled'
                mcf_order.amazon_status = 'CANCELLED'
                mcf_order.amazon_status_updated_at = datetime.utcnow()
                db.session.commit()
                logger.info(f"MCF order {mcf_order.seller_fulfillment_order_id} cancelled")
                return True, "MCF order cancelled successfully"
            return False, f"Failed to cancel: {error}"
        except Exception as e:
            logger.error(f"Error cancelling MCF order: {str(e)}")
            return False, f"Error: {str(e)}"


class OrderFulfillmentRouter:
    """Routes orders to the existing FBA (MCF) or FBM path."""
    def __init__(self):
        self.mcf_service = MCFService()
    def determine_fulfillment_type(self, sku: str, quantity: int = 1) -> Tuple[str, str]:
        available, message, fba_listing = self.mcf_service.check_fba_availability(sku, quantity)
        if available:
            return 'FBA', f"FBA inventory available ({fba_listing.available_quantity} units)"
        warehouse_stock = WarehouseStock.query.filter_by(sku=sku).first()
        if warehouse_stock and warehouse_stock.sellable_quantity >= quantity:
            return 'FBM', f"Warehouse stock available ({warehouse_stock.sellable_quantity} units)"
        if warehouse_stock:
            return 'FBM', f"Insufficient stock (warehouse: {warehouse_stock.sellable_quantity}, needed: {quantity})"
        return 'FBM', "No inventory source found"
    def route_order(self, source_order_id: str, source_channel: str, source_store_id: int, items: List[Dict], shipping_address: Dict, order_total: float = 0.0, platform_fees: float = 0.0) -> Dict:
        result = {'source_order_id': source_order_id, 'source_channel': source_channel, 'fba_items': [], 'fbm_items': [], 'mcf_order': None, 'marketplace_orders': [], 'errors': []}
        for item in items:
            sku = item.get('sku')
            quantity = item.get('quantity', 1)
            fulfillment_type, reason = self.determine_fulfillment_type(sku, quantity)
            item['fulfillment_type'] = fulfillment_type
            item['fulfillment_reason'] = reason
            if fulfillment_type == 'FBA':
                result['fba_items'].append(item)
            else:
                result['fbm_items'].append(item)
        if result['fba_items']:
            success, message, mcf_order = self.mcf_service.create_mcf_order(source_order_id=source_order_id, source_channel=source_channel, source_store_id=source_store_id, items=result['fba_items'], shipping_address=shipping_address, order_total=sum(i.get('unit_price', 0) * i.get('quantity', 1) for i in result['fba_items']), platform_fees=platform_fees * (len(result['fba_items']) / len(items)) if items else 0)
            if success:
                result['mcf_order'] = mcf_order.to_dict()
            else:
                result['errors'].append(f"MCF creation failed: {message}")
        return result


mcf_service = MCFService()
fulfillment_router = OrderFulfillmentRouter()
