"""
Profit Calculator Engine

Phase 2: Profit & Fee Calculation per Channel

Supports:
1. FBA orders: Amazon FBA fees, MCF shipping, referral fee + VAT
2. FBM orders: Product cost, platform fee + VAT, shipping label cost

Margin Baseline:
- Default target margin: 15%
- Seller override per listing/channel
- Alert system for low-margin sales
"""

import logging
from typing import Dict, Optional, Tuple
from app import db
from models import (
    WarehouseStock, MarketplaceListing, AmazonFBAListing, AmazonFBMListing,
    OrderFees, ListingMarginConfig, MCFOrder, MarketplaceOrder
)

logger = logging.getLogger(__name__)


class PlatformFeeRates:
    """Standard platform fee rates by channel"""
    
    RATES = {
        'eBay': {
            'final_value_fee': 12.8,
            'payment_processing': 0.0,
            'insertion_fee': 0.0,
            'vat_on_fees': 20.0
        },
        'Amazon': {
            'referral_fee': 15.0,
            'payment_processing': 0.0,
            'vat_on_fees': 20.0
        },
        'AmazonFBA': {
            'referral_fee': 15.0,
            'payment_processing': 0.0,
            'vat_on_fees': 20.0
        },
        'AmazonFBM': {
            'referral_fee': 15.0,
            'payment_processing': 0.0,
            'vat_on_fees': 20.0
        },
        'Etsy': {
            'transaction_fee': 6.5,
            'payment_processing': 4.0,
            'listing_fee': 0.20,
            'vat_on_fees': 20.0
        },
        'TikTok': {
            'referral_fee': 5.0,
            'payment_processing': 2.0,
            'vat_on_fees': 20.0
        },
        'Website': {
            'payment_processing': 2.9,
            'vat_on_fees': 20.0
        }
    }
    
    @classmethod
    def get_rate(cls, platform: str, fee_type: str) -> float:
        """Get fee rate for platform and fee type"""
        platform_rates = cls.RATES.get(platform, cls.RATES.get('Website', {}))
        return platform_rates.get(fee_type, 0.0)
    
    @classmethod
    def get_platform_rates(cls, platform: str) -> Dict:
        """Get all fee rates for a platform"""
        return cls.RATES.get(platform, cls.RATES.get('Website', {}))


class ProfitCalculator:
    """
    Calculate profit and margins for orders.
    
    Supports both FBA (MCF) and FBM fulfillment paths with
    channel-specific fee structures.
    """
    
    DEFAULT_TARGET_MARGIN = 15.0
    DEFAULT_ALERT_THRESHOLD = 10.0
    DEFAULT_MINIMUM_MARGIN = 5.0
    
    def __init__(self):
        self.platform_fees = PlatformFeeRates()
    
    def get_margin_config(self, warehouse_stock_id: int = None, 
                         listing_id: int = None,
                         listing_type: str = 'marketplace') -> Dict:
        """
        Get margin configuration for a listing or warehouse stock.
        
        Hierarchy:
        1. Listing-specific config
        2. Warehouse stock config
        3. System defaults
        """
        config = {
            'target_margin': self.DEFAULT_TARGET_MARGIN,
            'alert_threshold': self.DEFAULT_ALERT_THRESHOLD,
            'minimum_margin': self.DEFAULT_MINIMUM_MARGIN,
            'alerts_enabled': True,
            'block_below_minimum': False,
            'source': 'default'
        }
        
        if listing_id:
            if listing_type == 'fba':
                margin_config = ListingMarginConfig.query.filter_by(
                    fba_listing_id=listing_id
                ).first()
            elif listing_type == 'fbm':
                margin_config = ListingMarginConfig.query.filter_by(
                    fbm_listing_id=listing_id
                ).first()
            else:
                margin_config = ListingMarginConfig.query.filter_by(
                    marketplace_listing_id=listing_id
                ).first()
            
            if margin_config and margin_config.override_channel_defaults:
                config.update({
                    'target_margin': margin_config.target_margin,
                    'alert_threshold': margin_config.alert_threshold,
                    'minimum_margin': margin_config.minimum_margin,
                    'alerts_enabled': margin_config.alerts_enabled,
                    'block_below_minimum': margin_config.block_below_minimum,
                    'source': 'listing'
                })
                return config
        
        if warehouse_stock_id:
            margin_config = ListingMarginConfig.query.filter_by(
                warehouse_stock_id=warehouse_stock_id
            ).first()
            
            if margin_config:
                config.update({
                    'target_margin': margin_config.target_margin,
                    'alert_threshold': margin_config.alert_threshold,
                    'minimum_margin': margin_config.minimum_margin,
                    'alerts_enabled': margin_config.alerts_enabled,
                    'block_below_minimum': margin_config.block_below_minimum,
                    'source': 'warehouse'
                })
        
        return config
    
    def calculate_fba_profit(self, sale_price: float, quantity: int,
                            product_cost: float, landed_cost: float,
                            platform: str, mcf_fee: float = 0.0,
                            fba_fulfillment_fee: float = 0.0,
                            shipping_charged: float = 0.0) -> Dict:
        """
        Calculate profit for FBA/MCF fulfilled order.
        
        FBA Fee Structure:
        - Source Platform Fee (eBay final value, Etsy transaction, etc.)
        - Amazon Referral Fee (15% of sale price) - applies when selling via Amazon channels
        - FBA Fulfillment Fee (pick, pack, ship)
        - MCF Shipping Fee (for non-Amazon channels using FBA fulfillment)
        - VAT on all fees (UK 20%)
        """
        rates = self.platform_fees.get_platform_rates(platform)
        vat_rate = rates.get('vat_on_fees', 20.0) / 100
        
        sale_amount = sale_price * quantity
        
        source_platform_fee = 0.0
        if platform not in ['Amazon', 'AmazonFBA', 'AmazonFBM']:
            referral_rate = rates.get('referral_fee', rates.get('final_value_fee', rates.get('transaction_fee', 12.0)))
            source_platform_fee = sale_amount * (referral_rate / 100)
            payment_processing_rate = rates.get('payment_processing', 0.0)
            source_platform_fee += sale_amount * (payment_processing_rate / 100)
        
        amazon_referral_fee = 0.0
        if platform in ['Amazon', 'AmazonFBA', 'AmazonFBM']:
            amazon_referral_fee = sale_amount * (15.0 / 100)
        
        vat_on_platform_fees = (source_platform_fee + amazon_referral_fee) * vat_rate
        
        vat_on_fba_fees = fba_fulfillment_fee * vat_rate
        vat_on_mcf_fees = mcf_fee * vat_rate
        
        total_vat = vat_on_platform_fees + vat_on_fba_fees + vat_on_mcf_fees
        
        total_revenue = sale_amount + shipping_charged
        
        total_fees = (
            source_platform_fee +
            amazon_referral_fee +
            fba_fulfillment_fee +
            mcf_fee +
            total_vat
        )
        
        total_product_cost = (product_cost + landed_cost) * quantity
        total_costs = total_product_cost + total_fees
        
        gross_profit = total_revenue - total_costs
        margin_percent = (gross_profit / total_revenue * 100) if total_revenue > 0 else 0
        
        return {
            'fulfillment_type': 'FBA',
            'sale_price': sale_price,
            'quantity': quantity,
            'shipping_charged': shipping_charged,
            'total_revenue': total_revenue,
            'product_cost': product_cost * quantity,
            'landed_cost': landed_cost * quantity,
            'source_platform_fee': source_platform_fee,
            'platform_fee': source_platform_fee,
            'amazon_referral_fee': amazon_referral_fee,
            'fba_fulfillment_fee': fba_fulfillment_fee,
            'mcf_shipping_fee': mcf_fee,
            'vat_on_fees': total_vat,
            'total_fees': total_fees,
            'total_costs': total_costs,
            'gross_profit': gross_profit,
            'margin_percent': round(margin_percent, 2)
        }
    
    def calculate_fbm_profit(self, sale_price: float, quantity: int,
                            product_cost: float, landed_cost: float,
                            platform: str, shipping_charged: float = 0.0,
                            shipping_label_cost: float = 0.0,
                            packaging_cost: float = 0.0) -> Dict:
        """
        Calculate profit for FBM (warehouse fulfilled) order.
        
        FBM Fee Structure:
        - Platform Fee (eBay final value, Amazon referral, etc.)
        - Payment Processing Fee (if applicable)
        - Shipping Label Cost (actual carrier cost)
        - Packaging Cost
        - VAT on platform/payment fees (UK 20%)
        
        Note: Shipping label and packaging are business costs, not VATable platform fees.
        """
        rates = self.platform_fees.get_platform_rates(platform)
        vat_rate = rates.get('vat_on_fees', 20.0) / 100
        
        referral_rate = rates.get('referral_fee', rates.get('final_value_fee', 12.8))
        payment_processing_rate = rates.get('payment_processing', 0.0)
        
        sale_amount = sale_price * quantity
        platform_fee = sale_amount * (referral_rate / 100)
        payment_fee = sale_amount * (payment_processing_rate / 100)
        
        vat_on_platform_fees = (platform_fee + payment_fee) * vat_rate
        
        total_revenue = sale_amount + shipping_charged
        
        total_fees = (
            platform_fee +
            payment_fee +
            vat_on_platform_fees +
            shipping_label_cost +
            packaging_cost
        )
        
        total_product_cost = (product_cost + landed_cost) * quantity
        total_costs = total_product_cost + total_fees
        
        gross_profit = total_revenue - total_costs
        margin_percent = (gross_profit / total_revenue * 100) if total_revenue > 0 else 0
        
        return {
            'fulfillment_type': 'FBM',
            'sale_price': sale_price,
            'quantity': quantity,
            'shipping_charged': shipping_charged,
            'total_revenue': total_revenue,
            'product_cost': product_cost * quantity,
            'landed_cost': landed_cost * quantity,
            'platform_fee': platform_fee,
            'payment_processing_fee': payment_fee,
            'shipping_label_cost': shipping_label_cost,
            'packaging_cost': packaging_cost,
            'vat_on_fees': vat_on_platform_fees,
            'total_fees': total_fees,
            'total_costs': total_costs,
            'gross_profit': gross_profit,
            'margin_percent': round(margin_percent, 2)
        }
    
    def calculate_expected_margin(self, sku: str, sale_price: float,
                                 fulfillment_type: str = 'FBM',
                                 platform: str = 'eBay',
                                 quantity: int = 1) -> Dict:
        """
        Calculate expected margin for a potential sale.
        
        Used for pricing decisions and margin alerts.
        """
        warehouse_stock = WarehouseStock.query.filter_by(sku=sku).first()
        if not warehouse_stock:
            return {'error': f'SKU {sku} not found', 'margin_percent': 0}
        
        product_cost = warehouse_stock.unit_cost or 0
        landed_cost = warehouse_stock.landed_cost or 0
        
        if fulfillment_type == 'FBA':
            fba_listing = AmazonFBAListing.query.filter_by(
                warehouse_stock_id=warehouse_stock.id,
                is_active=True
            ).first()
            
            fba_fee = fba_listing.fba_fulfillment_fee if fba_listing else 3.50
            
            result = self.calculate_fba_profit(
                sale_price=sale_price,
                quantity=quantity,
                product_cost=product_cost,
                landed_cost=landed_cost,
                platform=platform,
                fba_fulfillment_fee=fba_fee * quantity
            )
        else:
            result = self.calculate_fbm_profit(
                sale_price=sale_price,
                quantity=quantity,
                product_cost=product_cost,
                landed_cost=landed_cost,
                platform=platform,
                shipping_label_cost=4.00
            )
        
        margin_config = self.get_margin_config(warehouse_stock_id=warehouse_stock.id)
        
        result['margin_config'] = margin_config
        result['below_target'] = result['margin_percent'] < margin_config['target_margin']
        result['below_alert'] = result['margin_percent'] < margin_config['alert_threshold']
        result['below_minimum'] = result['margin_percent'] < margin_config['minimum_margin']
        
        return result
    
    def check_margin_alert(self, sku: str, sale_price: float,
                          fulfillment_type: str = 'FBM',
                          platform: str = 'eBay',
                          quantity: int = 1) -> Tuple[bool, str, Dict]:
        """
        Check if a sale triggers a margin alert.
        
        Returns:
            Tuple of (requires_confirmation, message, margin_data)
        """
        result = self.calculate_expected_margin(
            sku=sku,
            sale_price=sale_price,
            fulfillment_type=fulfillment_type,
            platform=platform,
            quantity=quantity
        )
        
        if 'error' in result:
            return False, result.get('error', 'Unknown error'), result
        
        margin_config = result.get('margin_config', {})
        
        if margin_config.get('block_below_minimum') and result.get('below_minimum'):
            return True, (
                f"BLOCKED: Margin {result['margin_percent']:.1f}% is below minimum "
                f"{margin_config['minimum_margin']:.1f}%. Sale requires override."
            ), result
        
        if margin_config.get('alerts_enabled') and result.get('below_alert'):
            return True, (
                f"WARNING: Margin {result['margin_percent']:.1f}% is below alert threshold "
                f"{margin_config['alert_threshold']:.1f}%. Confirmation required."
            ), result
        
        if result.get('below_target'):
            return False, (
                f"Note: Margin {result['margin_percent']:.1f}% is below target "
                f"{margin_config['target_margin']:.1f}%."
            ), result
        
        return False, f"Margin OK: {result['margin_percent']:.1f}%", result
    
    def create_order_fee_record(self, order_type: str, order_id: int,
                               profit_data: Dict) -> OrderFees:
        """
        Create an OrderFees record for detailed fee tracking.
        """
        order_fees = OrderFees(
            fulfillment_type=profit_data.get('fulfillment_type', 'FBM'),
            product_cost=profit_data.get('product_cost', 0),
            landed_cost=profit_data.get('landed_cost', 0),
            platform_sale_fee=profit_data.get('platform_fee', 0),
            amazon_referral_fee=profit_data.get('amazon_referral_fee', 0),
            fba_fulfillment_fee=profit_data.get('fba_fulfillment_fee', 0),
            mcf_shipping_fee=profit_data.get('mcf_shipping_fee', 0),
            shipping_label_cost=profit_data.get('shipping_label_cost', 0),
            packaging_cost=profit_data.get('packaging_cost', 0),
            vat_amount=profit_data.get('vat_on_fees', 0),
            total_fees=profit_data.get('total_fees', 0),
            total_costs=profit_data.get('total_costs', 0),
            sale_price=profit_data.get('sale_price', 0) * profit_data.get('quantity', 1),
            shipping_charged=profit_data.get('shipping_charged', 0),
            total_revenue=profit_data.get('total_revenue', 0),
            gross_profit=profit_data.get('gross_profit', 0),
            profit_margin_percent=profit_data.get('margin_percent', 0)
        )
        
        if order_type == 'mcf':
            order_fees.mcf_order_id = order_id
        elif order_type == 'marketplace':
            order_fees.marketplace_order_id = order_id
        elif order_type == 'sales':
            order_fees.sales_order_id = order_id
        
        margin_config = profit_data.get('margin_config', {})
        order_fees.target_margin = margin_config.get('target_margin', self.DEFAULT_TARGET_MARGIN)
        order_fees.margin_alert_threshold = margin_config.get('alert_threshold', self.DEFAULT_ALERT_THRESHOLD)
        order_fees.below_target_margin = profit_data.get('below_target', False)
        
        order_fees.calculate_totals()
        
        db.session.add(order_fees)
        db.session.commit()
        
        return order_fees


def update_listing_margin_config(listing_type: str, listing_id: int,
                                 target_margin: float = None,
                                 alert_threshold: float = None,
                                 minimum_margin: float = None,
                                 alerts_enabled: bool = None,
                                 block_below_minimum: bool = None,
                                 user_id: int = None) -> ListingMarginConfig:
    """
    Update or create margin configuration for a listing.
    """
    if listing_type == 'fba':
        config = ListingMarginConfig.query.filter_by(fba_listing_id=listing_id).first()
        if not config:
            config = ListingMarginConfig(fba_listing_id=listing_id)
    elif listing_type == 'fbm':
        config = ListingMarginConfig.query.filter_by(fbm_listing_id=listing_id).first()
        if not config:
            config = ListingMarginConfig(fbm_listing_id=listing_id)
    elif listing_type == 'warehouse':
        config = ListingMarginConfig.query.filter_by(warehouse_stock_id=listing_id).first()
        if not config:
            config = ListingMarginConfig(warehouse_stock_id=listing_id)
    else:
        config = ListingMarginConfig.query.filter_by(marketplace_listing_id=listing_id).first()
        if not config:
            config = ListingMarginConfig(marketplace_listing_id=listing_id)
    
    if target_margin is not None:
        config.target_margin = target_margin
    if alert_threshold is not None:
        config.alert_threshold = alert_threshold
    if minimum_margin is not None:
        config.minimum_margin = minimum_margin
    if alerts_enabled is not None:
        config.alerts_enabled = alerts_enabled
    if block_below_minimum is not None:
        config.block_below_minimum = block_below_minimum
    
    config.override_channel_defaults = True
    config.updated_by_id = user_id
    
    db.session.add(config)
    db.session.commit()
    
    return config


profit_calculator = ProfitCalculator()
