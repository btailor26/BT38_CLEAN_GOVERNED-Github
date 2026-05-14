"""
STEP A: Amazon Transactions Parser
Parses Amazon settlement/transactions CSV exports into canonical order lines.
"""
import csv
import logging
from typing import List, Dict, Optional
from datetime import datetime
from services.parsers.base_parser import BaseParser

logger = logging.getLogger(__name__)


class AmazonTransactionsParser(BaseParser):
    """
    Parser for Amazon settlement/transactions CSV exports.
    
    Handles transaction types: Order, Refund, Service Fee, etc.
    Maps Amazon-specific columns to canonical CanonicalOrderLine format.
    """
    
    PLATFORM = 'amazon'
    TEMPLATE_NAME = 'amazon_settlement_v1'
    TEMPLATE_VERSION = '1.0'
    
    COLUMN_MAPPINGS = {
        'date/time': 'posted_at',
        'settlement id': 'settlement_id',
        'type': 'transaction_type',
        'order id': 'external_order_id',
        'sku': 'sku',
        'description': 'description',
        'quantity': 'quantity',
        'marketplace': 'marketplace',
        'fulfilment': 'fulfillment_channel',
        'order city': 'order_city',
        'order state': 'order_state',
        'order postal': 'order_postal',
        'tax collection model': 'tax_collection_model',
        'product sales': 'product_sales',
        'product sales tax': 'product_sales_tax',
        'postage credits': 'shipping_credit',
        'shipping credits tax': 'shipping_credit_tax',
        'gift wrap credits': 'gift_wrap_credit',
        'giftwrap credits tax': 'gift_wrap_credit_tax',
        'promotional rebates': 'promotional_rebates',
        'promotional rebates tax': 'promotional_rebates_tax',
        'marketplace withheld tax': 'marketplace_withheld_tax',
        'selling fees': 'selling_fees',
        'fba fees': 'fba_fees',
        'other transaction fees': 'other_transaction_fees',
        'other': 'other_fees',
        'total': 'total_amount'
    }
    
    TRANSACTION_TYPES = ['Order', 'Refund', 'Service Fee', 'Adjustment', 'Transfer', 'FBA Inventory Fee']
    
    def get_required_fields(self) -> List[str]:
        return ['date/time', 'type', 'order id', 'sku', 'total']
    
    def get_optional_fields(self) -> List[str]:
        return [
            'settlement id', 'description', 'quantity', 'marketplace', 'fulfilment',
            'order city', 'order state', 'order postal', 'tax collection model',
            'product sales', 'product sales tax', 'postage credits', 'shipping credits tax',
            'gift wrap credits', 'giftwrap credits tax', 'promotional rebates',
            'promotional rebates tax', 'marketplace withheld tax', 'selling fees',
            'fba fees', 'other transaction fees', 'other'
        ]
    
    def get_field_mappings(self) -> Dict[str, str]:
        return self.COLUMN_MAPPINGS
    
    def parse_csv(self, file_path: str) -> List[Dict]:
        """
        Parse Amazon settlement CSV file.
        
        Args:
            file_path: Path to CSV file
            
        Returns:
            List of canonical order line dicts
        """
        logger.info(f"[TEMPLATE_REGISTRY] Loading template: {self.TEMPLATE_NAME} v{self.TEMPLATE_VERSION}")
        logger.info(f"[CANONICAL_SALES] Starting parse of {file_path}")
        
        self.parsed_rows = []
        self.errors = []
        self.warnings = []
        self.stats = {'total_rows': 0, 'valid_rows': 0, 'skipped_rows': 0, 'error_rows': 0}
        
        try:
            with open(file_path, 'r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                headers = reader.fieldnames or []
                
                is_valid, missing = self.validate_headers(headers)
                if not is_valid:
                    logger.error(f"[TEMPLATE_REGISTRY] Invalid CSV: missing fields {missing}")
                    return []
                
                for row_num, row in enumerate(reader, start=2):
                    self.stats['total_rows'] += 1
                    
                    parsed = self.parse_row(row, row_num, file_path)
                    
                    if parsed:
                        self.parsed_rows.append(parsed)
                        self.stats['valid_rows'] += 1
                    elif parsed is None:
                        self.stats['skipped_rows'] += 1
                    else:
                        self.stats['error_rows'] += 1
            
            logger.info(f"[CANONICAL_SALES] Parse complete: {self.stats['valid_rows']} valid, "
                       f"{self.stats['skipped_rows']} skipped, {self.stats['error_rows']} errors")
            
            return self.parsed_rows
            
        except Exception as e:
            logger.error(f"[CANONICAL_SALES] Parse failed: {str(e)}")
            raise
    
    def parse_row(self, row: Dict, row_num: int, source_file: str) -> Optional[Dict]:
        """Parse single Amazon settlement row into canonical format"""
        
        normalized_row = {self.normalize_column_name(k): v for k, v in row.items()}
        
        transaction_type = normalized_row.get('type', '').strip()
        order_id = normalized_row.get('order_id', '').strip()
        sku = normalized_row.get('sku', '').strip()
        
        if not order_id or not sku:
            if transaction_type in ('Transfer', 'Service Fee'):
                return None
            self.add_warning(row_num, f"Missing order_id or sku for type '{transaction_type}'")
            return None
        
        settlement_id = normalized_row.get('settlement_id', '').strip()
        idempotency_key = f"amazon:{settlement_id}:{order_id}:{sku}:{row_num}"
        
        canonical = {
            'platform': self.PLATFORM,
            'template_name': self.TEMPLATE_NAME,
            'template_version': self.TEMPLATE_VERSION,
            'source_file': source_file,
            'source_row': row_num,
            'raw_payload': dict(row),
            
            'idempotency_key': idempotency_key,
            'settlement_id': settlement_id,
            'external_order_id': order_id,
            'sku': sku,
            'description': normalized_row.get('description', ''),
            'quantity': self.parse_int(normalized_row.get('quantity', '0')),
            'transaction_type': transaction_type,
            'marketplace': normalized_row.get('marketplace', ''),
            'fulfillment_channel': normalized_row.get('fulfilment', ''),
            
            'order_city': normalized_row.get('order_city', ''),
            'order_state': normalized_row.get('order_state', ''),
            'order_postal': normalized_row.get('order_postal', ''),
            'tax_collection_model': normalized_row.get('tax_collection_model', ''),
            
            'product_sales': self.parse_float(normalized_row.get('product_sales', '0')),
            'product_sales_tax': self.parse_float(normalized_row.get('product_sales_tax', '0')),
            'shipping_credit': self.parse_float(normalized_row.get('postage_credits', '0')),
            'shipping_credit_tax': self.parse_float(normalized_row.get('shipping_credits_tax', '0')),
            'gift_wrap_credit': self.parse_float(normalized_row.get('gift_wrap_credits', '0')),
            'gift_wrap_credit_tax': self.parse_float(normalized_row.get('giftwrap_credits_tax', '0')),
            'promotional_rebates': self.parse_float(normalized_row.get('promotional_rebates', '0')),
            'promotional_rebates_tax': self.parse_float(normalized_row.get('promotional_rebates_tax', '0')),
            'marketplace_withheld_tax': self.parse_float(normalized_row.get('marketplace_withheld_tax', '0')),
            
            'selling_fees': self.parse_float(normalized_row.get('selling_fees', '0')),
            'fba_fees': self.parse_float(normalized_row.get('fba_fees', '0')),
            'other_transaction_fees': self.parse_float(normalized_row.get('other_transaction_fees', '0')),
            'other_fees': self.parse_float(normalized_row.get('other', '0')),
            'total_amount': self.parse_float(normalized_row.get('total', '0')),
            
            'posted_at': self.parse_datetime(normalized_row.get('date/time', '')),
            'status': 'imported'
        }
        
        canonical['gross_amount'] = (
            canonical['product_sales'] + 
            canonical['shipping_credit'] + 
            canonical['gift_wrap_credit']
        )
        
        canonical['fees_breakdown'] = {
            'selling_fees': canonical['selling_fees'],
            'fba_fees': canonical['fba_fees'],
            'other_transaction_fees': canonical['other_transaction_fees'],
            'other_fees': canonical['other_fees']
        }
        
        logger.debug(f"[CANONICAL_SALES] Row {row_num}: {transaction_type} order={order_id} sku={sku} total={canonical['total_amount']}")
        
        return canonical
    
    def save_to_database(self, store_id: int = None) -> Dict:
        """
        Save parsed rows to CanonicalOrderLine table.
        Only works if feature flag is enabled and dry_run is False.
        """
        if self.dry_run:
            logger.info(f"[CANONICAL_SALES] DRY RUN: Would insert {len(self.parsed_rows)} rows")
            return {'success': True, 'dry_run': True, 'rows': len(self.parsed_rows)}
        
        if not self.is_feature_enabled():
            logger.warning(f"[TEMPLATE_REGISTRY] Feature flag disabled - no writes")
            return {'success': False, 'error': 'Feature flag disabled'}
        
        from app import db
        from models import CanonicalOrderLine
        
        inserted = 0
        skipped = 0
        
        for row in self.parsed_rows:
            existing = CanonicalOrderLine.query.filter_by(
                idempotency_key=row['idempotency_key']
            ).first()
            
            if existing:
                skipped += 1
                continue
            
            record = CanonicalOrderLine(
                store_id=store_id,
                platform=row['platform'],
                template_name=row['template_name'],
                template_version=row['template_version'],
                external_order_id=row['external_order_id'],
                settlement_id=row['settlement_id'],
                sku=row['sku'],
                description=row['description'],
                quantity=row['quantity'],
                transaction_type=row['transaction_type'],
                fulfillment_channel=row['fulfillment_channel'],
                marketplace=row['marketplace'],
                gross_amount=row['gross_amount'],
                product_sales=row['product_sales'],
                product_sales_tax=row['product_sales_tax'],
                shipping_credit=row['shipping_credit'],
                shipping_credit_tax=row['shipping_credit_tax'],
                gift_wrap_credit=row['gift_wrap_credit'],
                gift_wrap_credit_tax=row['gift_wrap_credit_tax'],
                promotional_rebates=row['promotional_rebates'],
                promotional_rebates_tax=row['promotional_rebates_tax'],
                marketplace_withheld_tax=row['marketplace_withheld_tax'],
                selling_fees=row['selling_fees'],
                fba_fees=row['fba_fees'],
                other_transaction_fees=row['other_transaction_fees'],
                other_fees=row['other_fees'],
                total_amount=row['total_amount'],
                fees_breakdown=row['fees_breakdown'],
                order_city=row['order_city'],
                order_state=row['order_state'],
                order_postal=row['order_postal'],
                tax_collection_model=row['tax_collection_model'],
                posted_at=row['posted_at'],
                source_file=row['source_file'],
                source_row=row['source_row'],
                raw_payload=row['raw_payload'],
                status=row['status'],
                idempotency_key=row['idempotency_key']
            )
            db.session.add(record)
            inserted += 1
        
        db.session.commit()
        logger.info(f"[CANONICAL_SALES] Inserted {inserted} rows, skipped {skipped} duplicates")
        
        return {'success': True, 'inserted': inserted, 'skipped': skipped}
