# Automated reorder monitoring and notification service
import logging
from datetime import datetime, timedelta
from typing import List, Dict
from extensions import db
from models import WarehouseStock, Supplier
from notification_service import notification_service

logger = logging.getLogger(__name__)

class ReorderMonitorService:
    """Service for monitoring stock levels and triggering reorder notifications"""
    
    def __init__(self):
        # Minimum time between notifications for the same item (24 hours)
        self.notification_cooldown_hours = 24
    
    def check_reorder_points(self) -> Dict:
        """
        Check all warehouse stock items and send reorder alerts to suppliers
        Returns summary of notifications sent
        """
        logger.info("Starting reorder point check...")
        
        try:
            # Find all items that need reordering
            items_needing_reorder = self._find_items_needing_reorder()
            
            if not items_needing_reorder:
                logger.info("No items need reordering")
                return {
                    'items_checked': WarehouseStock.query.filter_by(is_active=True, track_inventory=True).count(),
                    'items_below_reorder_point': 0,
                    'notifications_sent': 0,
                    'suppliers_notified': 0
                }
            
            logger.info(f"Found {len(items_needing_reorder)} items below reorder point")
            
            # Group items by supplier
            items_by_supplier = self._group_by_supplier(items_needing_reorder)
            
            # Send notifications to each supplier
            notifications_sent = 0
            suppliers_notified = 0
            
            for supplier_id, items in items_by_supplier.items():
                if self._send_supplier_notification(supplier_id, items):
                    notifications_sent += len(items)
                    suppliers_notified += 1
                    
                    # Update last_reorder_alert_at for all items
                    for item in items:
                        item.last_reorder_alert_at = datetime.utcnow()
                    
            db.session.commit()
            
            result = {
                'items_checked': WarehouseStock.query.filter_by(is_active=True, track_inventory=True).count(),
                'items_below_reorder_point': len(items_needing_reorder),
                'notifications_sent': notifications_sent,
                'suppliers_notified': suppliers_notified
            }
            
            logger.info(f"Reorder check complete: {result}")
            return result
            
        except Exception as e:
            logger.error(f"Error checking reorder points: {str(e)}")
            db.session.rollback()
            return {
                'error': str(e),
                'items_checked': 0,
                'items_below_reorder_point': 0,
                'notifications_sent': 0,
                'suppliers_notified': 0
            }
    
    def _find_items_needing_reorder(self) -> List[WarehouseStock]:
        """Find all warehouse items that are below reorder point and need notification"""
        # Calculate cooldown threshold
        cooldown_threshold = datetime.utcnow() - timedelta(hours=self.notification_cooldown_hours)
        
        # Query for items that need reordering:
        # 1. Active and tracked
        # 2. Below reorder point
        # 3. Have a supplier assigned
        # 4. Either never notified OR last notification was before cooldown threshold
        items = db.session.query(WarehouseStock).filter(
            WarehouseStock.is_active == True,
            WarehouseStock.track_inventory == True,
            WarehouseStock.reorder_point > 0,
            WarehouseStock.available_quantity <= WarehouseStock.reorder_point,
            WarehouseStock.supplier_id.isnot(None),
            db.or_(
                WarehouseStock.last_reorder_alert_at.is_(None),
                WarehouseStock.last_reorder_alert_at < cooldown_threshold
            )
        ).all()
        
        return items
    
    def _group_by_supplier(self, items: List[WarehouseStock]) -> Dict[int, List[WarehouseStock]]:
        """Group warehouse items by supplier ID"""
        items_by_supplier = {}
        
        for item in items:
            if item.supplier_id not in items_by_supplier:
                items_by_supplier[item.supplier_id] = []
            items_by_supplier[item.supplier_id].append(item)
        
        return items_by_supplier
    
    def _send_supplier_notification(self, supplier_id: int, items: List[WarehouseStock]) -> bool:
        """Send reorder notification to a supplier for their items"""
        try:
            supplier = db.session.get(Supplier, supplier_id)
            if not supplier or not supplier.is_active:
                logger.warning(f"Supplier {supplier_id} not found or inactive, skipping notification")
                return False
            
            # Prepare item data for notification
            low_stock_items = []
            for item in items:
                low_stock_items.append({
                    'sku': item.sku,
                    'name': item.sku,  # We could join with InventoryItem to get name
                    'quantity': item.available_quantity,
                    'reorder_point': item.reorder_point,
                    'reorder_quantity': item.reorder_quantity,
                    'unit_cost': item.unit_cost,
                    'location': item.location
                })
            
            # Prepare notification settings based on supplier preferences
            notification_settings = {
                'from_email': 'inventory@yourcompany.com',  # Configure this
                'whatsapp_enabled': bool(supplier.whatsapp_number),
                'whatsapp_number': supplier.whatsapp_number,
                'sms_enabled': bool(supplier.phone and not supplier.whatsapp_number),
                'sms_number': supplier.phone,
                'email_enabled': bool(supplier.email),
                'email_address': supplier.email
            }
            
            # Send notifications
            logger.info(f"Sending reorder alert to {supplier.name} for {len(items)} items")
            results = notification_service.send_reorder_alerts(low_stock_items, notification_settings)
            
            logger.info(f"Notification result for {supplier.name}: {results['message']}")
            return any([results.get('whatsapp'), results.get('sms'), results.get('email')])
            
        except Exception as e:
            logger.error(f"Error sending notification to supplier {supplier_id}: {str(e)}")
            return False
    
    def get_items_needing_reorder(self) -> List[Dict]:
        """Get a list of all items currently below reorder point (for dashboard display)"""
        items = db.session.query(WarehouseStock).filter(
            WarehouseStock.is_active == True,
            WarehouseStock.track_inventory == True,
            WarehouseStock.reorder_point > 0,
            WarehouseStock.available_quantity <= WarehouseStock.reorder_point
        ).all()
        
        result = []
        for item in items:
            result.append({
                'id': item.id,
                'sku': item.sku,
                'available_quantity': item.available_quantity,
                'reorder_point': item.reorder_point,
                'reorder_quantity': item.reorder_quantity,
                'supplier_id': item.supplier_id,
                'supplier_name': item.supplier.name if item.supplier else 'No supplier',
                'last_alert_at': item.last_reorder_alert_at.isoformat() if item.last_reorder_alert_at else None,
                'needs_notification': self._needs_notification(item)
            })
        
        return result
    
    def _needs_notification(self, item: WarehouseStock) -> bool:
        """Check if an item needs a notification sent"""
        if not item.supplier_id:
            return False
        
        if not item.last_reorder_alert_at:
            return True
        
        cooldown_threshold = datetime.utcnow() - timedelta(hours=self.notification_cooldown_hours)
        return item.last_reorder_alert_at < cooldown_threshold

# Global reorder monitor service instance
reorder_monitor = ReorderMonitorService()
