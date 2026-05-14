"""
STEP A: Base Parser - Abstract base class for marketplace parsers.
All marketplace-specific parsers inherit from this class.
"""
import logging
from abc import ABC, abstractmethod
from typing import List, Dict, Optional, Tuple
from datetime import datetime

logger = logging.getLogger(__name__)


class BaseParser(ABC):
    """
    Abstract base class for marketplace data parsers.
    Provides common utilities for CSV parsing, validation, and normalization.
    """
    
    PLATFORM = 'unknown'
    TEMPLATE_NAME = 'base_template_v1'
    TEMPLATE_VERSION = '1.0'
    
    def __init__(self, dry_run: bool = True, feature_flag: str = 'CANONICAL_SALES_IMPORTS'):
        """
        Initialize parser.
        
        Args:
            dry_run: If True, parse and validate but don't write to DB
            feature_flag: Environment variable name to check for enabled state
        """
        self.dry_run = dry_run
        self.feature_flag = feature_flag
        self.errors: List[Dict] = []
        self.warnings: List[Dict] = []
        self.parsed_rows: List[Dict] = []
        self.stats = {
            'total_rows': 0,
            'valid_rows': 0,
            'skipped_rows': 0,
            'error_rows': 0
        }
    
    def is_feature_enabled(self) -> bool:
        """Check if the feature flag is enabled"""
        import os
        flag_value = os.environ.get(self.feature_flag, 'false').lower()
        enabled = flag_value in ('true', '1', 'yes', 'enabled')
        logger.info(f"[TEMPLATE_REGISTRY] Feature flag {self.feature_flag} = {flag_value} (enabled={enabled})")
        return enabled
    
    @abstractmethod
    def get_required_fields(self) -> List[str]:
        """Return list of required CSV column names"""
        pass
    
    @abstractmethod
    def get_optional_fields(self) -> List[str]:
        """Return list of optional CSV column names"""
        pass
    
    @abstractmethod
    def get_field_mappings(self) -> Dict[str, str]:
        """Return mapping from CSV column names to canonical field names"""
        pass
    
    @abstractmethod
    def parse_row(self, row: Dict, row_num: int, source_file: str) -> Optional[Dict]:
        """
        Parse a single CSV row into canonical format.
        
        Args:
            row: Raw CSV row as dict
            row_num: Row number in source file
            source_file: Source filename for audit
            
        Returns:
            Canonical record dict or None if row should be skipped
        """
        pass
    
    def validate_headers(self, headers: List[str]) -> Tuple[bool, List[str]]:
        """
        Validate that required headers are present.
        
        Returns:
            Tuple of (is_valid, list of missing required fields)
        """
        headers_lower = [h.lower().strip() for h in headers]
        required = self.get_required_fields()
        missing = []
        
        for field in required:
            if field.lower() not in headers_lower:
                missing.append(field)
        
        is_valid = len(missing) == 0
        
        if is_valid:
            logger.info(f"[TEMPLATE_REGISTRY] Headers validated successfully for {self.TEMPLATE_NAME}")
        else:
            logger.error(f"[TEMPLATE_REGISTRY] Missing required fields: {missing}")
        
        return is_valid, missing
    
    def normalize_column_name(self, name: str) -> str:
        """Normalize column name for consistent matching"""
        return name.lower().strip().replace(' ', '_').replace('-', '_')
    
    def parse_float(self, value: str, default: float = 0.0) -> float:
        """Safely parse a float value from string"""
        if not value or value.strip() == '':
            return default
        try:
            clean_value = value.replace(',', '').replace('£', '').replace('$', '').strip()
            return float(clean_value)
        except (ValueError, TypeError):
            return default
    
    def parse_int(self, value: str, default: int = 0) -> int:
        """Safely parse an integer value from string"""
        if not value or value.strip() == '':
            return default
        try:
            return int(float(value.strip()))
        except (ValueError, TypeError):
            return default
    
    def parse_datetime(self, value: str, formats: List[str] = None) -> Optional[datetime]:
        """Parse datetime from various formats"""
        if not value or value.strip() == '':
            return None
        
        if formats is None:
            formats = [
                '%Y-%m-%d %H:%M:%S',
                '%Y-%m-%dT%H:%M:%S',
                '%d/%m/%Y %H:%M:%S',
                '%d/%m/%Y %H:%M',
                '%d-%m-%Y %H:%M:%S',
                '%Y-%m-%d',
                '%d/%m/%Y',
            ]
        
        for fmt in formats:
            try:
                return datetime.strptime(value.strip(), fmt)
            except ValueError:
                continue
        
        return None
    
    def add_error(self, row_num: int, message: str, field: str = None):
        """Record a parsing error"""
        self.errors.append({
            'row': row_num,
            'field': field,
            'message': message
        })
        logger.warning(f"[CANONICAL_SALES] Row {row_num}: {message}")
    
    def add_warning(self, row_num: int, message: str, field: str = None):
        """Record a parsing warning"""
        self.warnings.append({
            'row': row_num,
            'field': field,
            'message': message
        })
    
    def get_summary(self) -> Dict:
        """Get parsing summary"""
        return {
            'template': self.TEMPLATE_NAME,
            'version': self.TEMPLATE_VERSION,
            'platform': self.PLATFORM,
            'dry_run': self.dry_run,
            'stats': self.stats,
            'error_count': len(self.errors),
            'warning_count': len(self.warnings)
        }
