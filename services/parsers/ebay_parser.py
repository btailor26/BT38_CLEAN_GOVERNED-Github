"""
STEP 31: eBay Parser - Full Implementation
Parses eBay transaction exports into canonical settlement lines.
Template: ebay_settlement_v1 (approved Step 30.1)

SIGN RULE: All fee components stored as NEGATIVE (deductions).
           selling_fees = sum of fee components (NO abs).

USAGE STATUS (Basic Package - Visibility):
- Parser: IMPLEMENTED
- Route/Endpoint: NOT YET WIRED (no admin upload route exists)
- Storage: CanonicalOrderLine table (canonical_order_lines)
- Purpose: FINANCIAL RECONCILIATION ONLY (settlement/payout data)
- Does NOT affect: Warehouse stock (no decrements from settlement imports)
- To enable CSV upload: Create route calling EbayParser(dry_run=False).import_to_db()
"""
import csv
import logging
from typing import List, Dict, Optional
from datetime import datetime
from services.parsers.base_parser import BaseParser

logger = logging.getLogger(__name__)


class EbayParser(BaseParser):
    """
    Parser for eBay transaction CSV exports.
    
    Implements ebay_settlement_v1 template contract:
    - Net amount -> total_amount
    - Transaction ID -> external_line_id
    - Payout ID -> settlement_id
    - Fee components -> fees_breakdown (NEGATIVE values)
    - eBay-only fields -> raw_payload
    """
    
    PLATFORM = 'ebay'
    TEMPLATE_NAME = 'ebay_settlement_v1'
    TEMPLATE_VERSION = '1.0'
    
    COLUMN_MAPPINGS = {
        'transaction creation date': 'posted_at',
        'type': 'transaction_type',
        'order number': 'external_order_id',
        'custom label': 'sku',
        'net amount': 'total_amount',
        'transaction id': 'external_line_id',
        'payout id': 'settlement_id',
        'item title': 'description',
        'quantity': 'quantity',
        'item subtotal': 'product_sales',
        'postage and packaging': 'shipping_credit',
        'post to city': 'order_city',
        'post to province/region/state': 'order_state',
        'post to postcode': 'order_postal',
        'payout currency': 'currency',
    }
    
    FEE_COLUMNS = {
        'final value fee – fixed': 'final_value_fee_fixed',
        'final value fee – variable': 'final_value_fee_variable',
        'regulatory operating fee': 'regulatory_operating_fee',
        "very high 'item not as described' fee": 'inad_fee',
        'below standard performance fee': 'performance_fee',
        'international fee': 'international_fee',
    }
    
    RAW_PAYLOAD_COLUMNS = [
        'item id',
        'legacy order id',
        'gross transaction amount',
        'reference id',
        'description',
        'buyer username',
        'buyer name',
        'post to country',
        'seller collected tax',
        'ebay collected tax',
        'exchange rate',
    ]
    
    SKIP_TYPES = {'Payout', 'Postage label'}
    
    HEADER_SIGNATURE = 'transaction creation date'
    
    def get_required_fields(self) -> List[str]:
        return [
            'Transaction creation date',
            'Type',
            'Order number',
            'Custom label',
            'Net amount',
        ]
    
    def get_optional_fields(self) -> List[str]:
        return [
            'Legacy order ID',
            'Buyer username',
            'Buyer name',
            'Post to city',
            'Post to province/region/state',
            'Post to postcode',
            'Post to country',
            'Payout currency',
            'Payout date',
            'Payout ID',
            'Item ID',
            'Transaction ID',
            'Item title',
            'Quantity',
            'Item subtotal',
            'Postage and packaging',
            'Seller collected tax',
            'eBay collected tax',
            'Final value fee – fixed',
            'Final value fee – variable',
            'Regulatory operating fee',
            "Very high 'item not as described' fee",
            'Below standard performance fee',
            'International fee',
            'Gross transaction amount',
            'Transaction currency',
            'Exchange rate',
            'Reference ID',
            'Description',
        ]
    
    def get_field_mappings(self) -> Dict[str, str]:
        return self.COLUMN_MAPPINGS
    
    def detect_header_row(self, lines: List[str]) -> int:
        """Find the header row index by looking for signature column."""
        for i, line in enumerate(lines):
            if self.HEADER_SIGNATURE in line.lower():
                return i
        return -1
    
    def parse_ebay_date(self, value: str) -> Optional[datetime]:
        """Parse eBay date formats."""
        if not value or value.strip() in ('', '--'):
            return None
        
        formats = [
            '%d %b %Y',
            '%d-%b-%y',
            '%d/%m/%Y',
            '%Y-%m-%d',
        ]
        
        date_part = value.strip().split()[0:3]
        date_str = ' '.join(date_part) if len(date_part) >= 3 else value.strip()
        
        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue
        
        return None
    
    def get_cell_value(self, row: Dict, key: str, default: str = '') -> str:
        """Get cell value, treating '--' as empty."""
        value = row.get(key, default)
        if value is None or str(value).strip() == '--':
            return ''
        return str(value).strip()
    
    def parse_row(self, row: Dict, row_num: int, source_file: str) -> Optional[Dict]:
        """
        Parse single eBay transaction row into canonical format.
        
        SIGN RULE: Fee components stored as NEGATIVE (deductions).
        """
        normalized = {self.normalize_column_name(k): v for k, v in row.items()}
        
        tx_type = self.get_cell_value(normalized, 'type')
        order_number = self.get_cell_value(normalized, 'order_number')
        sku = self.get_cell_value(normalized, 'custom_label')
        
        if tx_type in self.SKIP_TYPES:
            return None
        
        if not order_number:
            return None
        
        payout_id = self.get_cell_value(normalized, 'payout_id')
        settlement_id = payout_id if payout_id else ''
        
        external_line_id = self.get_cell_value(normalized, 'transaction_id')
        external_line_id = external_line_id if external_line_id else None
        
        idempotency_key = f"ebay:{settlement_id}:{order_number}:{sku or 'NOSKU'}:{row_num}"
        
        product_sales = self.parse_float(self.get_cell_value(normalized, 'item_subtotal'))
        shipping_credit = self.parse_float(self.get_cell_value(normalized, 'postage_and_packaging'))
        total_amount = self.parse_float(self.get_cell_value(normalized, 'net_amount'))
        
        fee_fixed = self.parse_float(self.get_cell_value(normalized, 'final_value_fee_–_fixed'))
        fee_variable = self.parse_float(self.get_cell_value(normalized, 'final_value_fee_–_variable'))
        fee_regulatory = self.parse_float(self.get_cell_value(normalized, 'regulatory_operating_fee'))
        fee_inad = self.parse_float(self.get_cell_value(normalized, "very_high_'item_not_as_described'_fee"))
        fee_performance = self.parse_float(self.get_cell_value(normalized, 'below_standard_performance_fee'))
        fee_international = self.parse_float(self.get_cell_value(normalized, 'international_fee'))
        
        selling_fees = fee_fixed + fee_variable + fee_regulatory + fee_inad + fee_performance + fee_international
        
        gross_amount = product_sales + shipping_credit
        
        currency = self.get_cell_value(normalized, 'payout_currency')
        if not currency:
            currency = 'GBP'
        
        posted_at = self.parse_ebay_date(self.get_cell_value(normalized, 'transaction_creation_date'))
        
        fees_breakdown = {
            'final_value_fee_fixed': fee_fixed,
            'final_value_fee_variable': fee_variable,
            'regulatory_operating_fee': fee_regulatory,
            'inad_fee': fee_inad,
            'performance_fee': fee_performance,
            'international_fee': fee_international,
        }
        
        raw_payload = {
            'marketplace_item_id': self.get_cell_value(normalized, 'item_id') or None,
            'legacy_order_id': self.get_cell_value(normalized, 'legacy_order_id') or None,
            'gross_transaction_amount': self.parse_float(self.get_cell_value(normalized, 'gross_transaction_amount')),
            'reference_id': self.get_cell_value(normalized, 'reference_id') or None,
            'description_notes': self.get_cell_value(normalized, 'description') or None,
            'buyer_username': '[REDACTED]',
            'post_to_country': self.get_cell_value(normalized, 'post_to_country') or None,
            'seller_collected_tax': self.parse_float(self.get_cell_value(normalized, 'seller_collected_tax')),
            'ebay_collected_tax': self.parse_float(self.get_cell_value(normalized, 'ebay_collected_tax')),
        }
        
        canonical = {
            'platform': self.PLATFORM,
            'template_name': self.TEMPLATE_NAME,
            'template_version': self.TEMPLATE_VERSION,
            'source_file': source_file,
            'source_row': row_num,
            
            'idempotency_key': idempotency_key,
            'settlement_id': settlement_id,
            'external_order_id': order_number,
            'external_line_id': external_line_id,
            'sku': sku or None,
            'description': self.get_cell_value(normalized, 'item_title') or None,
            'quantity': self.parse_int(self.get_cell_value(normalized, 'quantity')),
            'transaction_type': tx_type,
            'currency': currency,
            
            'order_city': self.get_cell_value(normalized, 'post_to_city') or None,
            'order_state': self.get_cell_value(normalized, 'post_to_province/region/state') or None,
            'order_postal': self.get_cell_value(normalized, 'post_to_postcode') or None,
            
            'product_sales': product_sales,
            'shipping_credit': shipping_credit,
            'gross_amount': gross_amount,
            'selling_fees': selling_fees,
            'total_amount': total_amount,
            
            'posted_at': posted_at,
            'status': 'imported',
            
            'fees_breakdown': fees_breakdown,
            'raw_payload': raw_payload,
        }
        
        logger.debug(f"[CANONICAL_SALES] Row {row_num}: {tx_type} order={order_number} sku={sku} total={total_amount}")
        
        return canonical
    
    def parse_csv(self, file_path: str) -> List[Dict]:
        """
        Parse eBay transaction CSV file.
        
        Detects header row automatically (skips notes/metadata rows).
        Applies skip rules for Payout/Postage label rows.
        """
        logger.info(f"[TEMPLATE_REGISTRY] Loading template: {self.TEMPLATE_NAME} v{self.TEMPLATE_VERSION}")
        logger.info(f"[CANONICAL_SALES] Starting parse of {file_path}")
        
        self.parsed_rows = []
        self.errors = []
        self.warnings = []
        self.stats = {
            'total_rows': 0,
            'valid_rows': 0,
            'skipped_rows': 0,
            'error_rows': 0,
            'skip_reasons': {}
        }
        
        try:
            with open(file_path, 'r', encoding='utf-8-sig') as f:
                lines = f.readlines()
            
            header_idx = self.detect_header_row(lines)
            if header_idx < 0:
                logger.error(f"[TEMPLATE_REGISTRY] Could not detect header row in {file_path}")
                return []
            
            logger.info(f"[TEMPLATE_REGISTRY] Header detected at row {header_idx + 1}")
            
            data_lines = lines[header_idx:]
            reader = csv.DictReader(data_lines)
            headers = list(reader.fieldnames or [])
            
            is_valid, missing = self.validate_headers(headers)
            if not is_valid:
                logger.error(f"[TEMPLATE_REGISTRY] Invalid CSV: missing fields {missing}")
                return []
            
            source_file = file_path.split('/')[-1]
            
            for row_num, row in enumerate(reader, start=1):
                self.stats['total_rows'] += 1
                
                tx_type = row.get('Type', '').strip()
                order_number = row.get('Order number', '').strip()
                
                if tx_type in self.SKIP_TYPES:
                    self.stats['skipped_rows'] += 1
                    reason = f"{tx_type} (skip rule)"
                    self.stats['skip_reasons'][reason] = self.stats['skip_reasons'].get(reason, 0) + 1
                    continue
                
                if not order_number or order_number == '--':
                    self.stats['skipped_rows'] += 1
                    reason = "No order number"
                    self.stats['skip_reasons'][reason] = self.stats['skip_reasons'].get(reason, 0) + 1
                    continue
                
                # STEP 33: NO_SKU hard skip rule
                sku = row.get('Custom label', '').strip()
                if not sku or sku == '--':
                    self.stats['skipped_rows'] += 1
                    reason = "No SKU (Custom label empty)"
                    self.stats['skip_reasons'][reason] = self.stats['skip_reasons'].get(reason, 0) + 1
                    continue
                
                try:
                    parsed = self.parse_row(row, row_num, source_file)
                    
                    if parsed:
                        self.parsed_rows.append(parsed)
                        self.stats['valid_rows'] += 1
                    else:
                        self.stats['skipped_rows'] += 1
                        
                except Exception as e:
                    self.stats['error_rows'] += 1
                    self.add_error(row_num, str(e))
            
            logger.info(f"[CANONICAL_SALES] Parse complete: {self.stats['valid_rows']} valid, "
                       f"{self.stats['skipped_rows']} skipped, {self.stats['error_rows']} errors")
            
            return self.parsed_rows
            
        except Exception as e:
            logger.error(f"[CANONICAL_SALES] Parse failed: {str(e)}")
            raise
    
    def get_summary(self) -> Dict:
        """Get parsing summary including skip reasons."""
        summary = super().get_summary()
        summary['skip_reasons'] = self.stats.get('skip_reasons', {})
        return summary
    
    def run_integrity_audit(self, parsed_rows: Optional[List[Dict]] = None) -> Dict:
        """
        STEP 32: DRY-RUN integrity audit for eBay parser output.
        
        Validates:
        A) Required fields present and non-empty
        B) Numeric fields validate
        C) SIGN + SUM INVARIANT: selling_fees == sum(fees_breakdown)
        D) Duplicate idempotency detection
        
        Returns audit results dict (in-memory, no DB writes).
        """
        if parsed_rows is None:
            parsed_rows = self.parsed_rows
        
        REQUIRED_FIELDS = ['platform', 'external_order_id', 'sku', 'idempotency_key']
        NUMERIC_FIELDS = ['product_sales', 'shipping_credit', 'gross_amount', 'total_amount', 'selling_fees']
        TOLERANCE = 0.01
        
        audit_results = {
            'total_rows_audited': len(parsed_rows),
            'valid_rows': 0,
            'error_rows': 0,
            'invariant_failures': 0,
            'duplicate_idempotency': 0,
            'missing_required_fields': 0,
            'numeric_validation_errors': 0,
            'invariant_failure_samples': [],
            'duplicate_keys': [],
            'missing_field_samples': [],
        }
        
        seen_keys = {}
        duplicates = []
        
        for i, row in enumerate(parsed_rows):
            row_valid = True
            row_num = row.get('source_row', i + 1)
            
            for field in REQUIRED_FIELDS:
                value = row.get(field)
                if value is None or (isinstance(value, str) and value.strip() == ''):
                    row_valid = False
                    audit_results['missing_required_fields'] += 1
                    if len(audit_results['missing_field_samples']) < 3:
                        audit_results['missing_field_samples'].append({
                            'row': row_num,
                            'field': field,
                            'value': value
                        })
                    break
            
            for field in NUMERIC_FIELDS:
                value = row.get(field, 0.0)
                if not isinstance(value, (int, float)):
                    row_valid = False
                    audit_results['numeric_validation_errors'] += 1
                    break
            
            fees_breakdown = row.get('fees_breakdown', {})
            if isinstance(fees_breakdown, dict):
                component_sum = sum(fees_breakdown.values())
                selling_fees = row.get('selling_fees', 0.0)
                
                if abs(selling_fees - component_sum) > TOLERANCE:
                    row_valid = False
                    audit_results['invariant_failures'] += 1
                    if len(audit_results['invariant_failure_samples']) < 3:
                        audit_results['invariant_failure_samples'].append({
                            'row': row_num,
                            'selling_fees': selling_fees,
                            'component_sum': component_sum,
                            'difference': abs(selling_fees - component_sum),
                            'fees_breakdown': fees_breakdown
                        })
            
            idempotency_key = row.get('idempotency_key', '')
            if idempotency_key in seen_keys:
                audit_results['duplicate_idempotency'] += 1
                if len(duplicates) < 5:
                    duplicates.append({
                        'key': idempotency_key,
                        'first_row': seen_keys[idempotency_key],
                        'duplicate_row': row_num
                    })
            else:
                seen_keys[idempotency_key] = row_num
            
            if row_valid:
                audit_results['valid_rows'] += 1
            else:
                audit_results['error_rows'] += 1
        
        audit_results['duplicate_keys'] = duplicates
        
        logger.info(f"[INTEGRITY_AUDIT] Audit complete: {audit_results['valid_rows']} valid, "
                   f"{audit_results['error_rows']} errors, "
                   f"{audit_results['invariant_failures']} invariant failures, "
                   f"{audit_results['duplicate_idempotency']} duplicates")
        
        return audit_results
    
    def import_to_db(self, file_path: str) -> Dict:
        """
        STEP 34: Controlled DB import to canonical_order_lines.
        
        - Parses CSV using existing parse_csv (with skip rules)
        - Maps parsed rows to CanonicalOrderLine model
        - Inserts with idempotency: skip on duplicate idempotency_key
        - Returns import stats
        
        REQUIRES: dry_run=False in constructor
        """
        if self.dry_run:
            raise ValueError("import_to_db cannot run in dry_run mode. Set dry_run=False.")
        
        from app import db
        from models import CanonicalOrderLine
        from sqlalchemy.exc import IntegrityError
        
        logger.info(f"[DB_IMPORT] Starting controlled import: {file_path}")
        
        parsed_rows = self.parse_csv(file_path)
        
        import_stats = {
            'parsed_count': len(parsed_rows),
            'inserted_count': 0,
            'skipped_duplicate': 0,
            'error_count': 0,
            'errors': []
        }
        
        source_file = file_path.split('/')[-1]
        
        # Get existing idempotency keys for this file to skip duplicates efficiently
        existing_keys = set()
        existing_records = db.session.query(CanonicalOrderLine.idempotency_key).filter(
            CanonicalOrderLine.source_file == source_file
        ).all()
        existing_keys = {r[0] for r in existing_records}
        
        # Also check for any matching keys from parsed rows
        parsed_keys = [r['idempotency_key'] for r in parsed_rows]
        all_existing = db.session.query(CanonicalOrderLine.idempotency_key).filter(
            CanonicalOrderLine.idempotency_key.in_(parsed_keys)
        ).all()
        existing_keys.update(r[0] for r in all_existing)
        
        records_to_add = []
        
        for row in parsed_rows:
            if row['idempotency_key'] in existing_keys:
                import_stats['skipped_duplicate'] += 1
                continue
            
            try:
                record = CanonicalOrderLine(
                    platform=row.get('platform', self.PLATFORM),
                    template_name=row.get('template_name', self.TEMPLATE_NAME),
                    template_version=row.get('template_version', self.TEMPLATE_VERSION),
                    external_order_id=row.get('external_order_id'),
                    external_line_id=row.get('external_line_id'),
                    settlement_id=row.get('settlement_id'),
                    sku=row.get('sku'),
                    description=row.get('description'),
                    quantity=row.get('quantity', 0),
                    transaction_type=row.get('transaction_type'),
                    fulfillment_channel=row.get('fulfillment_channel'),
                    marketplace=row.get('marketplace'),
                    gross_amount=row.get('gross_amount', 0.0),
                    product_sales=row.get('product_sales', 0.0),
                    product_sales_tax=row.get('product_sales_tax', 0.0),
                    shipping_credit=row.get('shipping_credit', 0.0),
                    shipping_credit_tax=row.get('shipping_credit_tax', 0.0),
                    gift_wrap_credit=row.get('gift_wrap_credit', 0.0),
                    gift_wrap_credit_tax=row.get('gift_wrap_credit_tax', 0.0),
                    promotional_rebates=row.get('promotional_rebates', 0.0),
                    promotional_rebates_tax=row.get('promotional_rebates_tax', 0.0),
                    marketplace_withheld_tax=row.get('marketplace_withheld_tax', 0.0),
                    selling_fees=row.get('selling_fees', 0.0),
                    fba_fees=row.get('fba_fees', 0.0),
                    other_transaction_fees=row.get('other_transaction_fees', 0.0),
                    other_fees=row.get('other_fees', 0.0),
                    total_amount=row.get('total_amount', 0.0),
                    fees_breakdown=row.get('fees_breakdown', {}),
                    order_city=row.get('order_city'),
                    order_state=row.get('order_state'),
                    order_postal=row.get('order_postal'),
                    tax_collection_model=row.get('tax_collection_model'),
                    posted_at=row.get('posted_at'),
                    source_file=source_file,
                    source_row=row.get('source_row'),
                    raw_payload=row.get('raw_payload'),
                    status='imported',
                    idempotency_key=row['idempotency_key']
                )
                records_to_add.append(record)
                existing_keys.add(row['idempotency_key'])  # Prevent in-batch duplicates
                
            except Exception as e:
                import_stats['error_count'] += 1
                if len(import_stats['errors']) < 5:
                    import_stats['errors'].append(str(e))
                logger.error(f"[DB_IMPORT] Error creating row {row.get('source_row')}: {e}")
        
        # Batch insert
        if records_to_add:
            try:
                db.session.add_all(records_to_add)
                db.session.commit()
                import_stats['inserted_count'] = len(records_to_add)
            except IntegrityError as e:
                db.session.rollback()
                logger.error(f"[DB_IMPORT] Batch insert failed: {e}")
                # Fall back to one-by-one for remaining
                for record in records_to_add:
                    try:
                        db.session.add(record)
                        db.session.commit()
                        import_stats['inserted_count'] += 1
                    except IntegrityError:
                        db.session.rollback()
                        import_stats['skipped_duplicate'] += 1
                    except Exception as ex:
                        db.session.rollback()
                        import_stats['error_count'] += 1
        
        logger.info(f"[DB_IMPORT] Import complete: {import_stats['inserted_count']} inserted, "
                   f"{import_stats['skipped_duplicate']} duplicates skipped, "
                   f"{import_stats['error_count']} errors")
        
        return import_stats
