import os
import json
import logging
import requests
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any
from models import InventoryItem, Store

class eBayAPIService:
    """eBay Trading API integration service for inventory management"""
    
    # Category-specific required ItemSpecifics
    # Used for preflight validation before pushing
    REQUIRED_SPECIFICS_BY_CATEGORY = {
        'books': ['author'],  # Books category requires Author
        'media': ['format'],  # Media items require Format
        'apparel': ['brand', 'size', 'color', 'department', 'material'],  # Clothing/shoes
        'home': ['brand', 'material', 'color'],  # Home décor, statues, etc.
        # Extend as needed for other categories
    }
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.base_url = "https://api.ebay.com"
        self.sandbox_url = "https://api.sandbox.ebay.com"
        
    def authenticate_store(self, store: Store) -> bool:
        """
        Strict production-safe eBay OAuth authentication.

        Rules:
        - Store must contain valid JSON credentials
        - app_id, cert_id, dev_id are required
        - access_token is REQUIRED
        - No fake setup success states
        - Failed auth must return False
        """

        try:
            if not store.api_key:
                self.logger.error(f"No API credentials found for store {store.name}")
                return False

            creds = json.loads(store.api_key)

            required_keys = ['app_id', 'cert_id', 'dev_id']
            missing = [k for k in required_keys if not creds.get(k)]

            if missing:
                self.logger.error(
                    f"Missing required credentials for store {store.name}: {missing}"
                )
                return False

            access_token = creds.get('access_token', '').strip()

            if not access_token:
                self.logger.error(
                    f"Missing OAuth access token for store {store.name}"
                )
                return False

            headers = {
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json'
            }

            api_url = (
                self.sandbox_url
                if creds.get('sandbox') is True
                else self.base_url
            )

            response = requests.get(
                f"{api_url}/sell/account/v1/privilege",
                headers=headers,
                timeout=30
            )

            if response.status_code == 200:
                self.logger.info(
                    f"Successfully authenticated eBay store: {store.name}"
                )
                return True

            self.logger.error(
                f"eBay authentication failed for store {store.name}: "
                f"HTTP {response.status_code}"
            )

            return False

        except Exception as e:
            self.logger.error(
                f"Authentication failed for store {store.name}: {str(e)}"
            )
            return False
    
    def _lookup_internal_sku(self, external_sku: str, external_item_id: str, store_id: int) -> Optional[str]:
        """
        Lookup internal warehouse SKU from external eBay SKU/ItemID
        Returns internal SKU if mapping exists, None otherwise
        """
        try:
            from sqlalchemy import text
            from app import db
            
            if not external_sku and not external_item_id:
                return None
            
            # Try to find SKU mapping by external_sku first (most accurate)
            if external_sku:
                query = text("""
                    SELECT sku FROM sku_external_refs 
                    WHERE platform = 'eBay' 
                    AND (external_sku = :external_sku OR external_item_id = :external_item_id)
                    LIMIT 1
                """)
                result = db.session.execute(query, {
                    'external_sku': external_sku,
                    'external_item_id': external_item_id or external_sku
                }).fetchone()
                
                if result and result[0]:
                    self.logger.debug(f"Found internal SKU mapping: {external_sku} → {result[0]}")
                    return result[0]
            
            # No mapping found
            return None
            
        except Exception as e:
            self.logger.error(f"Error looking up internal SKU for eBay SKU '{external_sku}': {str(e)}")
            return None
    
    def resolve_item_id_by_sku(self, sku: str, store: Store) -> Optional[str]:
        """
        Resolve a numeric ItemID for a given seller SKU.
        Strategy:
          1) Check MarketplaceListing cache for existing numeric ItemID
          2) Try eBay Trading API GetMyeBaySelling to find ItemID by SKU
        Returns numeric ItemID string or None.
        """
        try:
            from models import MarketplaceListing
            import re
            
            # Strategy 1: Check existing MarketplaceListing for a numeric ItemID
            numeric_re = re.compile(r"^\d+$")
            existing = MarketplaceListing.query.filter_by(
                store_id=store.id,
                external_sku=sku
            ).first()
            
            if existing and existing.external_listing_id and numeric_re.match(existing.external_listing_id):
                self.logger.info(f"Found cached numeric ItemID for SKU {sku}: {existing.external_listing_id}")
                return existing.external_listing_id
            
            # Strategy 2: Query eBay API (GetMyeBaySelling or GetItem)
            # This requires parsing active listings to find ItemID by SKU
            # For now, return None - full implementation would call GetMyeBaySelling
            # and parse the response for matching SKU
            
            self.logger.warning(f"Could not resolve numeric ItemID for SKU {sku} - no cached mapping found")
            return None
            
        except Exception as e:
            self.logger.error(f"Error resolving ItemID for SKU {sku}: {str(e)}")
            return None
    
    def get_ebay_official_time(self, store: Store) -> Tuple[bool, str]:
        """
        Health check using GeteBayOfficialTime API
        Returns (success, time_or_error_message)
        """
        try:
            if not store.api_key:
                return False, "No API credentials configured"
            
            creds = json.loads(store.api_key)
            access_token = creds.get('access_token') or creds.get('user_token', '')
            if not access_token:
                return False, "Missing access token or user token"
            
            headers = {
                'Authorization': f'Bearer {access_token}',
                'X-EBAY-API-COMPATIBILITY-LEVEL': '967',
                'X-EBAY-API-DEV-NAME': creds.get('dev_id', ''),
                'X-EBAY-API-APP-NAME': creds['app_id'],
                'X-EBAY-API-CERT-NAME': creds['cert_id'],
                'X-EBAY-API-CALL-NAME': 'GeteBayOfficialTime',
                'X-EBAY-API-SITEID': creds.get('site_id', '0'),
                'Content-Type': 'text/xml'
            }
            
            xml_request = f"""<?xml version="1.0" encoding="utf-8"?>
            <GeteBayOfficialTimeRequest xmlns="urn:ebay:apis:eBLBaseComponents">
                <RequesterCredentials>
                    <eBayAuthToken>{access_token}</eBayAuthToken>
                </RequesterCredentials>
            </GeteBayOfficialTimeRequest>"""
            
            api_url = self.sandbox_url if creds.get('sandbox', False) else self.base_url
            response = requests.post(
                f"{api_url}/ws/api.dll",
                data=xml_request,
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 200:
                import xml.etree.ElementTree as ET
                root = ET.fromstring(response.text)
                timestamp_elem = root.find('.//{urn:ebay:apis:eBLBaseComponents}Timestamp')
                if timestamp_elem is not None:
                    return True, timestamp_elem.text or "No timestamp text"
                else:
                    return False, "No timestamp in response"
            else:
                return False, f"HTTP {response.status_code}"
                
        except Exception as e:
            return False, str(e)
    
    def get_seller_profiles(self, store: Store) -> Tuple[bool, Dict]:
        """
        Get Business Policies (Shipping, Payment, Return profiles) using GetSellerProfiles
        Returns (success, profiles_dict_or_error)
        """
        try:
            if not store.api_key:
                return False, {"error": "No API credentials configured"}
            
            creds = json.loads(store.api_key)
            access_token = creds.get('access_token') or creds.get('user_token', '')
            if not access_token:
                return False, {"error": "Missing access token or user token"}
            
            headers = {
                'Authorization': f'Bearer {access_token}',
                'X-EBAY-API-COMPATIBILITY-LEVEL': '967',
                'X-EBAY-API-DEV-NAME': creds.get('dev_id', ''),
                'X-EBAY-API-APP-NAME': creds['app_id'],
                'X-EBAY-API-CERT-NAME': creds['cert_id'],
                'X-EBAY-API-CALL-NAME': 'GetSellerProfiles',
                'X-EBAY-API-SITEID': creds.get('site_id', '0'),
                'Content-Type': 'text/xml'
            }
            
            xml_request = f"""<?xml version="1.0" encoding="utf-8"?>
            <GetSellerProfilesRequest xmlns="urn:ebay:apis:eBLBaseComponents">
                <RequesterCredentials>
                    <eBayAuthToken>{access_token}</eBayAuthToken>
                </RequesterCredentials>
            </GetSellerProfilesRequest>"""
            
            api_url = self.sandbox_url if creds.get('sandbox', False) else self.base_url
            response = requests.post(
                f"{api_url}/ws/api.dll",
                data=xml_request,
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 200:
                import xml.etree.ElementTree as ET
                root = ET.fromstring(response.text)
                
                ack_elem = root.find('.//{urn:ebay:apis:eBLBaseComponents}Ack')
                if ack_elem is not None and ack_elem.text in ['Success', 'Warning']:
                    profiles = {
                        'shipping': [],
                        'payment': [],
                        'return': []
                    }
                    
                    # Extract shipping profiles
                    for profile in root.findall('.//{urn:ebay:apis:eBLBaseComponents}ShippingPolicyProfile'):
                        profile_id_elem = profile.find('.//{urn:ebay:apis:eBLBaseComponents}ProfileID')
                        profile_name_elem = profile.find('.//{urn:ebay:apis:eBLBaseComponents}ProfileName')
                        if profile_id_elem is not None:
                            profiles['shipping'].append({
                                'id': profile_id_elem.text,
                                'name': profile_name_elem.text if profile_name_elem is not None else 'N/A'
                            })
                    
                    # Extract payment profiles
                    for profile in root.findall('.//{urn:ebay:apis:eBLBaseComponents}PaymentPolicyProfile'):
                        profile_id_elem = profile.find('.//{urn:ebay:apis:eBLBaseComponents}ProfileID')
                        profile_name_elem = profile.find('.//{urn:ebay:apis:eBLBaseComponents}ProfileName')
                        if profile_id_elem is not None:
                            profiles['payment'].append({
                                'id': profile_id_elem.text,
                                'name': profile_name_elem.text if profile_name_elem is not None else 'N/A'
                            })
                    
                    # Extract return profiles
                    for profile in root.findall('.//{urn:ebay:apis:eBLBaseComponents}ReturnPolicyProfile'):
                        profile_id_elem = profile.find('.//{urn:ebay:apis:eBLBaseComponents}ProfileID')
                        profile_name_elem = profile.find('.//{urn:ebay:apis:eBLBaseComponents}ProfileName')
                        if profile_id_elem is not None:
                            profiles['return'].append({
                                'id': profile_id_elem.text,
                                'name': profile_name_elem.text if profile_name_elem is not None else 'N/A'
                            })
                    
                    return True, profiles
                else:
                    error_elem = root.find('.//{urn:ebay:apis:eBLBaseComponents}ShortMessage')
                    error_msg = error_elem.text if error_elem is not None else 'Unknown error'
                    return False, {"error": error_msg}
            else:
                return False, {"error": f"HTTP {response.status_code}"}
                
        except Exception as e:
            return False, {"error": str(e)}

    def get_item_details(self, store: Store, item_id: str) -> Dict:
        """
        Get complete item details including ItemSpecifics AND pricing from GetItem API
        CRITICAL FIX: Now also extracts live pricing data from eBay
        
        Returns backwards-compatible dict with structure:
        {
            'item_specifics': {...},  # Product attributes
            'pricing': {              # LIVE pricing data
                'price': float,
                'currency': str,
                'source': str         # 'CurrentPrice', 'BuyItNow', or 'StartPrice'
            }
        }
        
        For backwards compatibility, also includes item_specifics as top-level keys
        """
        try:
            creds = json.loads(store.api_key)
            access_token = creds.get('access_token') or creds.get('user_token', '')
            
            headers = {
                'Authorization': f'Bearer {access_token}',
                'X-EBAY-API-COMPATIBILITY-LEVEL': '967',
                'X-EBAY-API-DEV-NAME': creds.get('dev_id', ''),
                'X-EBAY-API-APP-NAME': creds['app_id'],
                'X-EBAY-API-CERT-NAME': creds['cert_id'],
                'X-EBAY-API-CALL-NAME': 'GetItem',
                'X-EBAY-API-SITEID': creds.get('site_id', '0'),
                'Content-Type': 'text/xml'
            }
            
            xml_request = f'''<?xml version="1.0" encoding="utf-8"?>
            <GetItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">
                <RequesterCredentials>
                    <eBayAuthToken>{access_token}</eBayAuthToken>
                </RequesterCredentials>
                <ItemID>{item_id}</ItemID>
                <DetailLevel>ReturnAll</DetailLevel>
                <IncludeItemSpecifics>true</IncludeItemSpecifics>
            </GetItemRequest>'''
            
            # CRITICAL FIX: Default to live API (sandbox=False) to prevent production from hitting sandbox
            # Previously defaulted to True, causing production with missing 'sandbox' flag to use sandbox API with 0 items
            api_url = self.sandbox_url if creds.get('sandbox') is True else self.base_url
            response = requests.post(
                f"{api_url}/ws/api.dll",
                data=xml_request,
                headers=headers,
                timeout=5  # CRITICAL FIX: Reduced from 30s to 5s to prevent long hangs during quota exhaustion (217 items × 30s = 110min)
            )
            
            if response.status_code == 200:
                import xml.etree.ElementTree as ET
                root = ET.fromstring(response.text)
                
                # Check for API errors - Accept Success, Warning, PartialSuccess
                ack_elem = root.find('.//{urn:ebay:apis:eBLBaseComponents}Ack')
                if ack_elem is not None and ack_elem.text not in ['Success', 'Warning', 'PartialSuccess']:
                    error_elem = root.find('.//{urn:ebay:apis:eBLBaseComponents}ShortMessage')
                    error_msg = error_elem.text if error_elem is not None else 'Unknown error'
                    self.logger.error(f"GetItem API error for {item_id}: {error_msg}")
                    return {}  # Return empty on hard failures only
                
                # Extract complete ItemSpecifics
                item_specifics = {}
                item_specifics_elem = root.find('.//{urn:ebay:apis:eBLBaseComponents}ItemSpecifics')
                if item_specifics_elem is not None:
                    for name_value_elem in item_specifics_elem.findall('.//{urn:ebay:apis:eBLBaseComponents}NameValueList'):
                        name_elem = name_value_elem.find('.//{urn:ebay:apis:eBLBaseComponents}Name')
                        value_elems = name_value_elem.findall('.//{urn:ebay:apis:eBLBaseComponents}Value')
                        if name_elem is not None and value_elems:
                            values = [v.text for v in value_elems if v.text]
                            item_specifics[name_elem.text] = values[0] if len(values) == 1 else values
                
                # CRITICAL FIX: Extract pricing data from GetItem
                pricing = {'price': 0.0, 'currency': 'GBP', 'source': None}
                
                # Try SellingStatus/CurrentPrice (most reliable for live listings)
                selling_status_elem = root.find('.//{urn:ebay:apis:eBLBaseComponents}SellingStatus')
                if selling_status_elem is not None:
                    current_price_elem = selling_status_elem.find('.//{urn:ebay:apis:eBLBaseComponents}CurrentPrice')
                    if current_price_elem is not None and current_price_elem.text:
                        pricing['price'] = float(current_price_elem.text)
                        pricing['currency'] = current_price_elem.get('currencyID', 'GBP')
                        pricing['source'] = 'CurrentPrice'
                
                # Fallback: Try BuyItNowPrice (fixed-price listings)
                if pricing['price'] == 0:
                    buy_it_now_elem = root.find('.//{urn:ebay:apis:eBLBaseComponents}BuyItNowPrice')
                    if buy_it_now_elem is not None and buy_it_now_elem.text:
                        pricing['price'] = float(buy_it_now_elem.text)
                        pricing['currency'] = buy_it_now_elem.get('currencyID', 'GBP')
                        pricing['source'] = 'BuyItNowPrice'
                
                # Final fallback: Try StartPrice (auction listings)
                if pricing['price'] == 0:
                    start_price_elem = root.find('.//{urn:ebay:apis:eBLBaseComponents}StartPrice')
                    if start_price_elem is not None and start_price_elem.text:
                        pricing['price'] = float(start_price_elem.text)
                        pricing['currency'] = start_price_elem.get('currencyID', 'GBP')
                        pricing['source'] = 'StartPrice'
                
                # Log pricing extraction
                if pricing['price'] > 0:
                    self.logger.debug(f"eBay item {item_id}: £{pricing['price']:.2f} (from {pricing['source']})")
                else:
                    self.logger.warning(f"⚠️ eBay item {item_id}: NO PRICE in GetItem response")
                
                # Return structured data with backwards compatibility
                result = {
                    'item_specifics': item_specifics,
                    'pricing': pricing
                }
                
                # Backwards compatibility: Include item_specifics as top-level keys
                result.update(item_specifics)
                
                return result
            else:
                self.logger.error(f"GetItem HTTP error for {item_id}: {response.status_code}")
                return {}
                
        except Exception as e:
            self.logger.error(f"Error getting item details for {item_id}: {str(e)}")
            return {}
    
    def get_quantity_sold(self, store: Store, item_id: str, sku: Optional[str] = None) -> int:
        """
        Get QuantitySold for an eBay listing via GetItem API.
        
        NOTE: This function is DEPRECATED and NOT USED.
        
        IMPORTANT: eBay's ReviseInventoryStatus Quantity field = AVAILABLE quantity only.
        eBay maintains QuantitySold separately - we do NOT add sold to our push quantity.
        Push operation sends warehouse_stock.available_quantity directly as OVERWRITE.
        
        Args:
            store: Store with eBay credentials
            item_id: eBay Item ID (numeric)
            sku: Optional SKU for variation items
            
        Returns:
            QuantitySold as integer (0 if not found or error)
        """
        try:
            creds = json.loads(store.api_key)
            access_token = creds.get('access_token') or creds.get('user_token', '')
            
            if not access_token:
                self.logger.warning(f"No access token for store {store.name}")
                return 0
            
            headers = {
                'Authorization': f'Bearer {access_token}',
                'X-EBAY-API-COMPATIBILITY-LEVEL': '967',
                'X-EBAY-API-DEV-NAME': creds.get('dev_id', ''),
                'X-EBAY-API-APP-NAME': creds['app_id'],
                'X-EBAY-API-CERT-NAME': creds['cert_id'],
                'X-EBAY-API-CALL-NAME': 'GetItem',
                'X-EBAY-API-SITEID': creds.get('site_id', '3'),  # UK site
                'Content-Type': 'text/xml'
            }
            
            # Request variation details for multi-SKU listings
            xml_request = f'''<?xml version="1.0" encoding="utf-8"?>
            <GetItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">
                <RequesterCredentials>
                    <eBayAuthToken>{access_token}</eBayAuthToken>
                </RequesterCredentials>
                <ItemID>{item_id}</ItemID>
                <DetailLevel>ReturnAll</DetailLevel>
                <IncludeItemSpecifics>false</IncludeItemSpecifics>
            </GetItemRequest>'''
            
            api_url = self.sandbox_url if creds.get('sandbox') is True else self.base_url
            response = requests.post(
                f"{api_url}/ws/api.dll",
                data=xml_request,
                headers=headers,
                timeout=10
            )
            
            if response.status_code == 200:
                import xml.etree.ElementTree as ET
                root = ET.fromstring(response.text)
                
                # Check for success
                ack_elem = root.find('.//{urn:ebay:apis:eBLBaseComponents}Ack')
                if ack_elem is not None and ack_elem.text not in ['Success', 'Warning', 'PartialSuccess']:
                    self.logger.warning(f"GetItem failed for {item_id}: {ack_elem.text}")
                    return 0
                
                # For variations, find the specific SKU's QuantitySold
                if sku:
                    variations = root.findall('.//{urn:ebay:apis:eBLBaseComponents}Variation')
                    for variation in variations:
                        var_sku_elem = variation.find('.//{urn:ebay:apis:eBLBaseComponents}SKU')
                        if var_sku_elem is not None and var_sku_elem.text == sku:
                            selling_status = variation.find('.//{urn:ebay:apis:eBLBaseComponents}SellingStatus')
                            if selling_status is not None:
                                qty_sold_elem = selling_status.find('.//{urn:ebay:apis:eBLBaseComponents}QuantitySold')
                                if qty_sold_elem is not None and qty_sold_elem.text:
                                    sold = int(qty_sold_elem.text)
                                    self.logger.info(f"eBay variation {sku} (ItemID {item_id}): QuantitySold={sold}")
                                    return sold
                    self.logger.warning(f"Variation SKU {sku} not found in ItemID {item_id}")
                    return 0
                
                # For single items, get top-level QuantitySold
                selling_status = root.find('.//{urn:ebay:apis:eBLBaseComponents}SellingStatus')
                if selling_status is not None:
                    qty_sold_elem = selling_status.find('.//{urn:ebay:apis:eBLBaseComponents}QuantitySold')
                    if qty_sold_elem is not None and qty_sold_elem.text:
                        sold = int(qty_sold_elem.text)
                        self.logger.info(f"eBay item {item_id}: QuantitySold={sold}")
                        return sold
                
                self.logger.warning(f"No QuantitySold found for eBay item {item_id}")
                return 0
            else:
                self.logger.error(f"GetItem HTTP error for {item_id}: {response.status_code}")
                return 0
                
        except Exception as e:
            self.logger.error(f"Error getting QuantitySold for {item_id}: {str(e)}")
            return 0
    
    def validate_required_specifics(self, item_specifics: Dict[str, Any], category_name: Optional[str] = None) -> Tuple[bool, List[str]]:
        """
        Validate that required ItemSpecifics are present for a listing's category
        
        This preflight validation prevents aspect validation errors during push.
        Call this BEFORE attempting to push to eBay to detect issues early.
        
        Args:
            item_specifics: Dictionary of ItemSpecifics (from get_item_details or listing)
            category_name: Optional category name to check specific requirements
            
        Returns:
            Tuple of (is_valid: bool, missing_specifics: List[str])
            
        Example:
            >>> specs = {"Title": "Book Title", "Language": "English"}
            >>> valid, missing = service.validate_required_specifics(specs, "books")
            >>> if not valid:
            >>>     print(f"Missing: {', '.join(missing)}")  # "Missing: author"
        """
        missing = []
        
        # Normalize keys to lowercase for case-insensitive comparison
        normalized_specs = {str(k).lower().strip(): v for k, v in item_specifics.items()}
        
        # Determine category type
        category_type = None
        if category_name:
            cat_lower = str(category_name).lower()
            if 'book' in cat_lower:
                category_type = 'books'
            elif any(word in cat_lower for word in ['apparel', 'clothing', 'shoes', 'fashion', 'dress', 'shirt']):
                category_type = 'apparel'
            elif any(word in cat_lower for word in ['home', 'décor', 'decor', 'statue', 'garden']):
                category_type = 'home'
        
        # Check category-specific requirements
        if category_type and category_type in self.REQUIRED_SPECIFICS_BY_CATEGORY:
            for required_field in self.REQUIRED_SPECIFICS_BY_CATEGORY[category_type]:
                field_lower = required_field.lower()
                if field_lower not in normalized_specs or not str(normalized_specs[field_lower]).strip():
                    missing.append(required_field)
                    self.logger.warning(f"Missing required ItemSpecific for {category_type} category: {required_field}")
        
        is_valid = len(missing) == 0
        return is_valid, missing
    
    def preflight_check(self, store: Store, item_id: str) -> Tuple[bool, str, List[str]]:
        """
        Perform preflight validation on an eBay listing before pushing
        
        This checks for missing required ItemSpecifics that would cause
        aspect validation errors. Now supports books, apparel, and home categories.
        
        Use this before scheduling pushes to detect issues early.
        
        Args:
            store: Store object with eBay credentials
            item_id: eBay ItemID to validate
            
        Returns:
            Tuple of (can_push: bool, reason: str, missing_specifics: List[str])
            
        Example:
            >>> can_push, reason, missing = service.preflight_check(store, "116825828130")
            >>> if not can_push:
            >>>     print(f"BLOCKED: {reason}")
            >>>     print(f"Fix in eBay Seller Hub, then re-import to clear block")
        """
        try:
            # Fetch item details with ItemSpecifics
            item_specifics = self.get_item_details(store, item_id)
            
            if not item_specifics:
                return False, "Could not retrieve item details", []
            
            # Auto-detect category based on ItemSpecific indicators
            category = None
            specs_lower = {k.lower() for k in item_specifics.keys()}
            
            # Books: ISBN, Publication Year, Publisher
            if any(indicator in specs_lower for indicator in ['isbn', 'publication year', 'publisher']):
                category = 'books'
            # Apparel: Size, Color, Department, Material (clothing indicators)
            elif any(indicator in specs_lower for indicator in ['size', 'department', 'style', 'fit type']):
                category = 'apparel'
            # Home: Often has Material, Color, Room (home décor indicators)
            elif any(indicator in specs_lower for indicator in ['room', 'theme', 'features']):
                category = 'home'
            
            is_valid, missing = self.validate_required_specifics(item_specifics, category if category else None)
            
            if not is_valid:
                missing_str = ', '.join(missing)
                reason = f"Missing required ItemSpecifics: {missing_str}"
                self.logger.warning(f"❌ Preflight FAILED for {item_id} ({category}): {reason}")
                return False, reason, missing
            
            self.logger.info(f"✅ Preflight PASSED for {item_id} ({category or 'unknown category'})")
            return True, "OK - All required specifics present", []
            
        except Exception as e:
            self.logger.error(f"Error in preflight check for {item_id}: {str(e)}")
            return False, f"Preflight error: {str(e)}", []
    
    def import_inventory_from_ebay(self, store: Store) -> Tuple[bool, List[Dict], str]:
        """
        Import all inventory items from eBay store with proper pagination
        Returns (success, items_list, message)
        """
        try:
            # Parse API credentials
            if not store.api_key:
                return False, [], "No API credentials found"
                
            creds = json.loads(store.api_key)
            required_keys = ['app_id', 'cert_id']
            
            if not all(key in creds for key in required_keys):
                return False, [], "Missing required credentials"
            
            # Use user_token as access_token if access_token is not available
            access_token = creds.get('access_token') or creds.get('user_token', '')
            if not access_token:
                return False, [], "Missing access token or user token"
            
            # Setup headers for API calls
            headers = {
                'Authorization': f'Bearer {access_token}',
                'X-EBAY-API-COMPATIBILITY-LEVEL': '967',
                'X-EBAY-API-DEV-NAME': creds.get('dev_id', ''),
                'X-EBAY-API-APP-NAME': creds['app_id'],
                'X-EBAY-API-CERT-NAME': creds['cert_id'],
                'X-EBAY-API-CALL-NAME': 'GetMyeBaySelling',
                'X-EBAY-API-SITEID': creds.get('site_id', '0'),
                'Content-Type': 'text/xml'
            }
            
            # CRITICAL FIX: Default to live API (sandbox=False) to prevent production from hitting sandbox
            api_url = self.sandbox_url if creds.get('sandbox') is True else self.base_url
            
            # PAGINATION FIX: Loop through all pages
            all_items = []
            page_number = 1
            total_pages = 1  # Will be updated from first response
            
            while page_number <= total_pages:
                self.logger.info(f"📄 Fetching eBay page {page_number}/{total_pages} (200 items/page)...")
                
                # XML request with current page number
                xml_request = f'''<?xml version="1.0" encoding="utf-8"?>
                <GetMyeBaySellingRequest xmlns="urn:ebay:apis:eBLBaseComponents">
                    <RequesterCredentials>
                        <eBayAuthToken>{access_token}</eBayAuthToken>
                    </RequesterCredentials>
                    <ActiveList>
                        <Include>true</Include>
                        <Pagination>
                            <EntriesPerPage>200</EntriesPerPage>
                            <PageNumber>{page_number}</PageNumber>
                        </Pagination>
                    </ActiveList>
                    <DetailLevel>ReturnAll</DetailLevel>
                </GetMyeBaySellingRequest>'''
                
                response = requests.post(
                    f"{api_url}/ws/api.dll",
                    data=xml_request,
                    headers=headers,
                    timeout=30
                )
                
                if response.status_code != 200:
                    error_msg = f"eBay API error: HTTP {response.status_code}, Body: {response.text[:500]}"
                    self.logger.error(error_msg)
                    # Return what we have so far if we got items from previous pages
                    if all_items:
                        return True, all_items, f"Partial import: {len(all_items)} items (page {page_number} failed)"
                    return False, [], error_msg
                
                # Parse XML response
                try:
                    import xml.etree.ElementTree as ET
                    root = ET.fromstring(response.text)
                    
                    # Check for API errors in response
                    ack_elem = root.find('.//{urn:ebay:apis:eBLBaseComponents}Ack')
                    if ack_elem is not None and ack_elem.text not in ['Success', 'Warning', 'PartialSuccess']:
                        # Extract detailed error information
                        error_code_elem = root.find('.//{urn:ebay:apis:eBLBaseComponents}ErrorCode')
                        error_msg_elem = root.find('.//{urn:ebay:apis:eBLBaseComponents}LongMessage')
                        short_msg_elem = root.find('.//{urn:ebay:apis:eBLBaseComponents}ShortMessage')
                        
                        error_code = error_code_elem.text if error_code_elem is not None else 'Unknown'
                        error_msg = error_msg_elem.text if error_msg_elem is not None else (short_msg_elem.text if short_msg_elem is not None else 'Unknown error')
                        
                        full_error = f"eBay API error {error_code}: {error_msg}"
                        self.logger.error(f"EBAY_IMPORT_ERROR: {full_error}")
                        # Return what we have so far
                        if all_items:
                            return True, all_items, f"Partial import: {len(all_items)} items (error on page {page_number})"
                        return False, [], full_error
                    
                    # Extract pagination info from first page
                    if page_number == 1:
                        pagination_elem = root.find('.//{urn:ebay:apis:eBLBaseComponents}PaginationResult')
                        if pagination_elem is not None:
                            total_pages_elem = pagination_elem.find('.//{urn:ebay:apis:eBLBaseComponents}TotalNumberOfPages')
                            total_entries_elem = pagination_elem.find('.//{urn:ebay:apis:eBLBaseComponents}TotalNumberOfEntries')
                            if total_pages_elem is not None:
                                total_pages = int(total_pages_elem.text)
                                total_entries = int(total_entries_elem.text) if total_entries_elem is not None else 0
                                self.logger.info(f"📊 eBay has {total_entries} total listings across {total_pages} pages")
                    
                    # Find all Item elements in this page
                    item_elements = root.findall('.//{urn:ebay:apis:eBLBaseComponents}Item')
                    self.logger.info(f"✅ Page {page_number}: Found {len(item_elements)} items")
                    
                    # Process each item in this page
                    for item in item_elements:
                        item_id_elem = item.find('.//{urn:ebay:apis:eBLBaseComponents}ItemID')
                        title_elem = item.find('.//{urn:ebay:apis:eBLBaseComponents}Title')
                        quantity_elem = item.find('.//{urn:ebay:apis:eBLBaseComponents}Quantity')
                        sku_elem = item.find('.//{urn:ebay:apis:eBLBaseComponents}SKU')
                        
                        # CRITICAL FIX: Try multiple price fields (fixed-price vs auction)
                        start_price_elem = item.find('.//{urn:ebay:apis:eBLBaseComponents}StartPrice')
                        buy_it_now_elem = item.find('.//{urn:ebay:apis:eBLBaseComponents}BuyItNowPrice')
                        current_price_elem = item.find('.//{urn:ebay:apis:eBLBaseComponents}CurrentPrice')
                        
                        # Use the first available price field (prioritize current/buy-it-now for fixed-price listings)
                        price_elem = current_price_elem or buy_it_now_elem or start_price_elem
                        
                        description_elem = item.find('.//{urn:ebay:apis:eBLBaseComponents}Description')
                        
                        # Get SellingStatus for calculating available quantity
                        selling_status_elem = item.find('.//{urn:ebay:apis:eBLBaseComponents}SellingStatus')
                        quantity_sold_elem = selling_status_elem.find('.//{urn:ebay:apis:eBLBaseComponents}QuantitySold') if selling_status_elem is not None else None
                        
                        # Calculate available quantity: Total Quantity - Quantity Sold
                        total_quantity = int(quantity_elem.text) if quantity_elem is not None and quantity_elem.text else 0
                        quantity_sold = int(quantity_sold_elem.text) if quantity_sold_elem is not None and quantity_sold_elem.text else 0
                        available_quantity = max(0, total_quantity - quantity_sold)  # Ensure non-negative
                        
                        # Get eBay SKU and ItemID
                        ebay_sku = sku_elem.text if sku_elem is not None and sku_elem.text else None
                        ebay_item_id = item_id_elem.text if item_id_elem is not None else None
                        
                        # PERFORMANCE OPTIMIZATION: Skip GetItem calls during import
                        # GetMyeBaySelling already provides all data needed: SKU, ItemID, quantity, price
                        # GetItem is only needed when pushing updates (for validation), not during import
                        # Skipping GetItem reduces import time from 13+ minutes to <1 minute for 4000+ items
                        item_specifics = {}
                        get_item_pricing = None
                        
                        # Extract ItemSpecifics from GetMyeBaySelling response (fast, no extra API call)
                        item_specifics_elem = item.find('.//{urn:ebay:apis:eBLBaseComponents}ItemSpecifics')
                        if item_specifics_elem is not None:
                            for name_value_elem in item_specifics_elem.findall('.//{urn:ebay:apis:eBLBaseComponents}NameValueList'):
                                name_elem = name_value_elem.find('.//{urn:ebay:apis:eBLBaseComponents}Name')
                                value_elems = name_value_elem.findall('.//{urn:ebay:apis:eBLBaseComponents}Value')
                                if name_elem is not None and value_elems:
                                    values = [v.text for v in value_elems if v.text]
                                    item_specifics[name_elem.text] = values[0] if len(values) == 1 else values
                        
                        # Check for SKU mapping to internal warehouse SKU
                        internal_sku = self._lookup_internal_sku(ebay_sku or "", ebay_item_id or "", store.id)
                        
                        # Use mapped internal SKU, or fall back to eBay SKU, or ItemID
                        final_sku = internal_sku or ebay_sku or ebay_item_id or f"EBAY-{len(all_items)+1}"
                        
                        # Log quantity calculation and SKU mapping for debugging
                        if internal_sku and internal_sku != ebay_sku:
                            self.logger.info(f"eBay SKU '{ebay_sku}' mapped to internal SKU '{internal_sku}'")
                        
                        # CRITICAL FIX: Use GetItem pricing when available, fall back to GetMyeBaySelling
                        extracted_price = 0.0
                        price_source = None
                        
                        if get_item_pricing and get_item_pricing.get('price', 0) > 0:
                            # Use GetItem pricing (most reliable)
                            extracted_price = get_item_pricing['price']
                            price_source = f"GetItem:{get_item_pricing['source']}"
                        else:
                            # Fallback to GetMyeBaySelling pricing
                            extracted_price = float(price_elem.text) if price_elem is not None and price_elem.text else 0.0
                            if extracted_price > 0:
                                price_source = f"GetMyeBay:{'CurrentPrice' if current_price_elem is not None else ('BuyItNowPrice' if buy_it_now_elem is not None else 'StartPrice')}"
                        
                        # Log price extraction
                        if extracted_price > 0:
                            self.logger.debug(f"eBay item {final_sku}: £{extracted_price:.2f} (from {price_source})")
                        else:
                            self.logger.warning(f"⚠️ eBay item {final_sku}: NO PRICE FOUND in either GetItem or GetMyeBay")
                        
                        self.logger.debug(f"eBay item {final_sku}: Total={total_quantity}, Sold={quantity_sold}, Available={available_quantity}")
                        
                        all_items.append({
                            'sku': final_sku,
                            'listing_id': ebay_item_id,  # CRITICAL: Store numeric eBay ItemID for ReviseInventoryStatus API
                            'external_sku': ebay_sku,  # Store eBay SKU separately for reference
                            'external_item_id': ebay_item_id,  # Keep eBay ItemID for SKU mapping table
                            'name': title_elem.text if title_elem is not None else 'eBay Item',
                            'quantity': available_quantity,
                            'price': extracted_price,  # FIXED: Use GetItem pricing with GetMyeBay fallback
                            'description': description_elem.text[:500] if description_elem is not None and description_elem.text else 'eBay listing',
                            'item_specifics': item_specifics  # Store item specifics for validation
                        })
                
                except Exception as parse_error:
                    self.logger.error(f"Error parsing eBay response on page {page_number}: {str(parse_error)}")
                    # Return what we have so far
                    if all_items:
                        return True, all_items, f"Partial import: {len(all_items)} items (parse error on page {page_number})"
                    return False, [], f"Error parsing eBay response: {str(parse_error)}"
                
                # Log progress after processing this page
                self.logger.info(f"✅ Page {page_number} complete: Processed {len(item_elements)} items (total so far: {len(all_items)})")
                
                # Move to next page
                page_number += 1
            
            # All pages processed successfully
            self.logger.info(f"✅ Successfully imported {len(all_items)} items from eBay store: {store.name}")
            return True, all_items, f"Imported {len(all_items)} real items from eBay"
            
        except Exception as e:
            error_msg = f"Error importing inventory from eBay: {str(e)}"
            self.logger.error(error_msg)
            return False, [], error_msg
    
    def get_ebay_item_id_for_sku(self, item: InventoryItem) -> Optional[str]:
        """
        Lookup eBay ItemID for a given SKU using the new SKU external references table
        Returns eBay ItemID (numeric) or None if not found
        """
        try:
            from sqlalchemy import text
            from app import db
            from models import MarketplaceListing, WarehouseStock
            import re
            
            # First try the new SKU external references table (preferred method)
            query = text("""
                SELECT external_item_id FROM sku_external_refs 
                WHERE sku = :sku AND platform = 'eBay'
                LIMIT 1
            """)
            
            result = db.session.execute(query, {'sku': item.sku}).fetchone()
            if result and result[0]:
                external_item_id = result[0]
                # Only return if it's a numeric eBay ItemID
                if external_item_id.isdigit():
                    self.logger.info(f"Found eBay ItemID {external_item_id} for SKU {item.sku} (via sku_external_refs)")
                    return external_item_id
            
            # Fallback 1: Check MarketplaceListing for numeric ItemID
            numeric_re = re.compile(r"^\d+$")
            ws = WarehouseStock.query.filter_by(sku=item.sku).first()
            if ws:
                listing = (MarketplaceListing.query
                          .join(Store)
                          .filter(MarketplaceListing.warehouse_stock_id == ws.id)
                          .filter(Store.platform == 'eBay')
                          .filter(Store.is_active == True)
                          .filter(MarketplaceListing.is_active == True)
                          .first())
                
                if listing and listing.external_listing_id and numeric_re.match(listing.external_listing_id):
                    self.logger.info(f"Found eBay ItemID {listing.external_listing_id} for SKU {item.sku} (via MarketplaceListing)")
                    return listing.external_listing_id
            
            # Fallback 2: Search group_external_refs for NUMERIC eBay ItemIDs only
            if item.group_id:
                group_query = text("""
                    SELECT external_id FROM group_external_refs 
                    WHERE platform = 'eBay' AND group_id = :group_id 
                    AND external_id ~ '^[0-9]+$'
                """)
                
                group_results = db.session.execute(group_query, {'group_id': item.group_id}).fetchall()
                for row in group_results:
                    external_id = row[0]
                    # Double-check it's numeric (extra safety)
                    if external_id.isdigit():
                        self.logger.info(f"Found eBay ItemID {external_id} for SKU {item.sku} via group {item.group_id}")
                        return external_id
            
            self.logger.warning(f"No eBay ItemID found for SKU {item.sku}")
            return None
            
        except Exception as e:
            self.logger.error(f"Error looking up eBay ItemID for SKU {item.sku}: {str(e)}")
            return None

    def sync_inventory_to_ebay(self, store: Store, item: InventoryItem) -> Tuple[bool, str]:
        """
        Sync a single inventory item to eBay using ReviseInventoryStatus API (qty-only)
        Uses qty-only API to bypass aspect validation and "just work"
        Supports both single listings AND multi-variation listings (Multi-SKU items)
        Returns (success, message)
        """
        try:
            if not store.api_key:
                return False, "No API credentials configured"
                
            creds = json.loads(store.api_key)
            
            access_token = creds.get('access_token') or creds.get('user_token', '')
            if not access_token:
                return False, "Missing access token or user token"
            
            ebay_item_id = self.get_ebay_item_id_for_sku(item)
            if not ebay_item_id:
                if item.sku.startswith('AMZ-') or item.sku.startswith('FBA-'):
                    return False, f"Cannot create eBay listing for Amazon-only SKU {item.sku}. Import this product to eBay first."
                
                self.logger.info(f"No eBay listing found for SKU {item.sku}, attempting to create new listing")
                return self.create_ebay_listing(store, item)
            
            from models import MarketplaceListing, WarehouseStock
            variation_sku = None
            final_item_id = ebay_item_id
            
            ws = WarehouseStock.query.filter_by(sku=item.sku).first()
            if ws:
                listing = MarketplaceListing.query.filter(
                    MarketplaceListing.warehouse_stock_id == ws.id,
                    MarketplaceListing.store_id == store.id,
                    MarketplaceListing.is_active == True
                ).first()
                
                if listing:
                    if listing.parent_item_id and listing.parent_item_id.isdigit():
                        final_item_id = listing.parent_item_id
                        variation_sku = listing.external_sku or item.sku
                        self.logger.info(f"Variation detected: SKU {item.sku} → parent ItemID {final_item_id}, variation SKU {variation_sku}")
                    elif listing.external_sku:
                        variation_sku = listing.external_sku
                        self.logger.info(f"Multi-SKU listing: using external_sku {variation_sku} for SKU {item.sku}")
            
            headers = {
                'Authorization': f'Bearer {access_token}',
                'X-EBAY-API-COMPATIBILITY-LEVEL': '967',
                'X-EBAY-API-DEV-NAME': creds.get('dev_id', ''),
                'X-EBAY-API-APP-NAME': creds['app_id'],
                'X-EBAY-API-CERT-NAME': creds['cert_id'],
                'X-EBAY-API-CALL-NAME': 'ReviseInventoryStatus',
                'X-EBAY-API-SITEID': creds.get('site_id', '0'),
                'Content-Type': 'text/xml'
            }
            
            # CRITICAL: Push warehouse quantity as OVERWRITE - no deltas, no adding sold
            # ReviseInventoryStatus Quantity field = the AVAILABLE quantity for purchase
            # eBay maintains QuantitySold separately and does NOT add it to this value
            warehouse_qty = item.quantity  # Source of truth from warehouse - THIS IS THE ONLY VALUE WE PUSH
            
            self.logger.info(f"[PUSH_DEBUG] SKU={item.sku} | Warehouse qty={warehouse_qty} | Pushing EXACT value (no sold added)")
            self.logger.info(f"[PUSH_DEBUG] This value ({warehouse_qty}) will become eBay's AVAILABLE quantity")
            
            sku_xml = f"<SKU>{variation_sku}</SKU>" if variation_sku else ""
            
            xml_request = f"""<?xml version="1.0" encoding="utf-8"?>
            <ReviseInventoryStatusRequest xmlns="urn:ebay:apis:eBLBaseComponents">
                <RequesterCredentials>
                    <eBayAuthToken>{access_token}</eBayAuthToken>
                </RequesterCredentials>
                <InventoryStatus>
                    <ItemID>{final_item_id}</ItemID>
                    {sku_xml}
                    <Quantity>{warehouse_qty}</Quantity>
                </InventoryStatus>
            </ReviseInventoryStatusRequest>"""
            
            # CRITICAL FIX: Default to live API (sandbox=False) to prevent production from hitting sandbox
            api_url = self.sandbox_url if creds.get('sandbox') is True else self.base_url
            variation_info = f", variation SKU: {variation_sku}" if variation_sku else ""
            self.logger.info(f"Syncing SKU {item.sku} (eBay ItemID: {final_item_id}{variation_info}) with qty={warehouse_qty} using ReviseInventoryStatus")
            
            response = requests.post(
                f"{api_url}/ws/api.dll",
                data=xml_request,
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 200:
                try:
                    import xml.etree.ElementTree as ET
                    root = ET.fromstring(response.text)
                    
                    ack_elem = root.find('.//{urn:ebay:apis:eBLBaseComponents}Ack')
                    ack_value = ack_elem.text if ack_elem is not None else 'None'
                    
                    # CRITICAL FIX: Check for blocking errors EVEN when Ack=Warning
                    # eBay can return Ack=Warning with SeverityCode=Error which means update FAILED
                    errors = root.findall('.//{urn:ebay:apis:eBLBaseComponents}Errors')
                    has_blocking_error = False
                    error_details = []
                    
                    for error_elem in errors:
                        severity_elem = error_elem.find('.//{urn:ebay:apis:eBLBaseComponents}SeverityCode')
                        code_elem = error_elem.find('.//{urn:ebay:apis:eBLBaseComponents}ErrorCode')
                        msg_elem = error_elem.find('.//{urn:ebay:apis:eBLBaseComponents}ShortMessage')
                        long_msg_elem = error_elem.find('.//{urn:ebay:apis:eBLBaseComponents}LongMessage')
                        
                        severity = severity_elem.text if severity_elem is not None else 'Unknown'
                        error_code = code_elem.text if code_elem is not None else 'Unknown'
                        short_msg = msg_elem.text if msg_elem is not None else ''
                        long_msg = long_msg_elem.text if long_msg_elem is not None else ''
                        
                        if severity == 'Error':
                            has_blocking_error = True
                        
                        detail = f"{error_code}: {short_msg}"
                        if long_msg and long_msg != short_msg:
                            detail += f" ({long_msg[:100]})"
                        error_details.append(detail)
                    
                    # If ANY error has SeverityCode=Error, treat as failure regardless of Ack
                    if has_blocking_error:
                        error_summary = '; '.join(error_details)
                        self.logger.error(f"❌ eBay Ack={ack_value} with blocking error for SKU {item.sku} (ItemID: {final_item_id}{variation_info}): {error_summary}")
                        return False, f"eBay API error (Ack={ack_value}): {error_summary}"
                    
                    # Success or Warning without blocking errors = actual success
                    if ack_elem is not None and ack_value in ['Success', 'Warning']:
                        if error_details:
                            self.logger.warning(f"⚠️ eBay Ack={ack_value} with non-blocking warnings for SKU {item.sku}: {'; '.join(error_details)}")
                        self.logger.info(f"✅ Successfully updated eBay listing {final_item_id}{variation_info}: qty={warehouse_qty} (Ack={ack_value})")
                        return True, f"Successfully synced {item.name} (SKU: {item.sku}, eBay ItemID: {final_item_id}{variation_info}) - qty={warehouse_qty}"
                    
                    # Ack is Failure or unknown
                    error_summary = '; '.join(error_details) if error_details else 'Unknown eBay API error'
                    self.logger.error(f"❌ eBay API error for SKU {item.sku} (ItemID: {final_item_id}{variation_info}): Ack={ack_value} - {error_summary}")
                    return False, f"eBay API error (Ack={ack_value}): {error_summary}"
                    
                except Exception as parse_error:
                    self.logger.error(f"Error parsing eBay response for SKU {item.sku}: {str(parse_error)}")
                    if 'Success' in response.text or 'Warning' in response.text:
                        return True, f"Successfully synced {item.name} (SKU: {item.sku}, eBay ItemID: {final_item_id}{variation_info})"
                    else:
                        return False, f"eBay API error: Failed to parse response"
            else:
                self.logger.error(f"HTTP error {response.status_code} for SKU {item.sku} (ItemID: {final_item_id}{variation_info})")
                return False, f"HTTP error {response.status_code}: {response.text[:200]}"
                
        except json.JSONDecodeError:
            return False, "Invalid API credentials format"
        except Exception as e:
            self.logger.error(f"Error syncing item {item.sku} to eBay: {str(e)}")
            return False, f"Sync error: {str(e)}"
    
    def get_ebay_inventory(self, store: Store) -> List[Dict]:
        """
        Retrieve current inventory from eBay
        Returns list of inventory items from eBay
        """
        try:
            if not store.api_key:
                return []
                
            creds = json.loads(store.api_key)
            
            # Use user_token as access_token if access_token is not available
            access_token = creds.get('access_token') or creds.get('user_token', '')
            if not access_token:
                return []
            
            headers = {
                'Authorization': f'Bearer {access_token}',
                'X-EBAY-API-COMPATIBILITY-LEVEL': '967',
                'X-EBAY-API-DEV-NAME': creds.get('dev_id', ''),
                'X-EBAY-API-APP-NAME': creds['app_id'],
                'X-EBAY-API-CERT-NAME': creds['cert_id'],
                'X-EBAY-API-CALL-NAME': 'GetMyeBaySelling',
                'X-EBAY-API-SITEID': creds.get('site_id', '0'),
                'Content-Type': 'text/xml'
            }
            
            # Get active listings
            xml_request = f"""<?xml version="1.0" encoding="utf-8"?>
            <GetMyeBaySellingRequest xmlns="urn:ebay:apis:eBLBaseComponents">
                <RequesterCredentials>
                    <eBayAuthToken>{access_token}</eBayAuthToken>
                </RequesterCredentials>
                <ActiveList>
                    <Include>true</Include>
                    <Pagination>
                        <EntriesPerPage>200</EntriesPerPage>
                        <PageNumber>1</PageNumber>
                    </Pagination>
                </ActiveList>
            </GetMyeBaySellingRequest>"""
            
            # CRITICAL FIX: Default to live API (sandbox=False) to prevent production from hitting sandbox
            # Previously defaulted to True, causing production with missing 'sandbox' flag to use sandbox API with 0 items
            api_url = self.sandbox_url if creds.get('sandbox') is True else self.base_url
            response = requests.post(
                f"{api_url}/ws/api.dll",
                data=xml_request,
                headers=headers,
                timeout=30
            )
            
            ebay_inventory = []
            if response.status_code == 200:
                # Parse XML response to extract inventory items
                import xml.etree.ElementTree as ET
                try:
                    root = ET.fromstring(response.text)
                    # Find all Item elements in the response
                    items = root.findall('.//{urn:ebay:apis:eBLBaseComponents}Item')
                    
                    for item in items:
                        item_id_elem = item.find('.//{urn:ebay:apis:eBLBaseComponents}ItemID')
                        title_elem = item.find('.//{urn:ebay:apis:eBLBaseComponents}Title')
                        quantity_elem = item.find('.//{urn:ebay:apis:eBLBaseComponents}Quantity')
                        sku_elem = item.find('.//{urn:ebay:apis:eBLBaseComponents}SKU')
                        
                        # Get SellingStatus for calculating available quantity
                        selling_status_elem = item.find('.//{urn:ebay:apis:eBLBaseComponents}SellingStatus')
                        quantity_sold_elem = selling_status_elem.find('.//{urn:ebay:apis:eBLBaseComponents}QuantitySold') if selling_status_elem is not None else None
                        
                        # Calculate available quantity: Total Quantity - Quantity Sold
                        total_quantity = int(quantity_elem.text) if quantity_elem is not None and quantity_elem.text else 0
                        quantity_sold = int(quantity_sold_elem.text) if quantity_sold_elem is not None and quantity_sold_elem.text else 0
                        available_quantity = max(0, total_quantity - quantity_sold)
                        
                        ebay_inventory.append({
                            'item_id': item_id_elem.text if item_id_elem is not None else '',
                            'sku': sku_elem.text if sku_elem is not None else '',
                            'title': title_elem.text if title_elem is not None else '',
                            'quantity': available_quantity,
                            'last_updated': datetime.utcnow()
                        })
                        
                except Exception as parse_error:
                    self.logger.error(f"Error parsing eBay response: {str(parse_error)}")
            
            self.logger.info(f"Retrieved {len(ebay_inventory)} items from eBay store: {store.name}")
            return ebay_inventory
            
        except Exception as e:
            self.logger.error(f"Error retrieving eBay inventory for store {store.name}: {str(e)}")
            return []
    
    def create_ebay_credentials_template(self) -> Dict:
        """
        Returns template for eBay API credentials
        """
        return {
            "app_id": "YOUR_APP_ID", 
            "cert_id": "YOUR_CERT_ID",
            "dev_id": "YOUR_DEV_ID",
            "access_token": "YOUR_ACCESS_TOKEN",
            "refresh_token": "YOUR_REFRESH_TOKEN",
            "site_id": "0",  # 0 = US, 3 = UK, etc.
            "sandbox": True,  # Set to False for production
            "user_token": "YOUR_USER_TOKEN"
        }
    
    def get_oauth_auth_url(self, client_id: str, redirect_uri: str, scopes: List[str]) -> str:
        """
        Generate eBay OAuth authorization URL for user consent
        """
        scope_string = " ".join(scopes)
        params = {
            'client_id': client_id,
            'response_type': 'code',
            'redirect_uri': redirect_uri,
            'scope': scope_string,
            'state': 'inventory_management'
        }
        
        query_string = "&".join([f"{k}={v}" for k, v in params.items()])
        return f"https://auth.ebay.com/oauth2/authorize?{query_string}"
    
    def sync_multiple_items_to_ebay(self, store: Store, items: List[InventoryItem]) -> Dict[str, Any]:
        """
        Sync multiple inventory items to eBay in batch
        Returns summary of results with success/failure counts and details
        """
        results = {
            'total_items': len(items),
            'successful_syncs': 0,
            'failed_syncs': 0,
            'sync_details': [],
            'errors': []
        }
        
        self.logger.info(f"Starting batch sync of {len(items)} items to eBay store: {store.name}")
        
        for item in items:
            try:
                success, message = self.sync_inventory_to_ebay(store, item)
                
                sync_detail = {
                    'sku': item.sku,
                    'name': item.name,
                    'quantity': item.quantity,
                    'success': success,
                    'message': message
                }
                
                results['sync_details'].append(sync_detail)
                
                if success:
                    results['successful_syncs'] += 1
                    self.logger.info(f"✓ Successfully synced SKU {item.sku}: {message}")
                else:
                    results['failed_syncs'] += 1
                    results['errors'].append(f"SKU {item.sku}: {message}")
                    self.logger.error(f"✗ Failed to sync SKU {item.sku}: {message}")
                    
            except Exception as e:
                error_msg = f"Exception syncing SKU {item.sku}: {str(e)}"
                results['failed_syncs'] += 1
                results['errors'].append(error_msg)
                results['sync_details'].append({
                    'sku': item.sku,
                    'name': item.name,
                    'quantity': item.quantity,
                    'success': False,
                    'message': error_msg
                })
                self.logger.error(error_msg)
        
        self.logger.info(f"Batch sync completed: {results['successful_syncs']}/{results['total_items']} items synced successfully")
        return results

    def exchange_code_for_tokens(self, client_id: str, client_secret: str, code: str, redirect_uri: str) -> Dict:
        """
        Exchange authorization code for access and refresh tokens
        """
        try:
            import base64
            
            # Create basic auth header
            credentials = f"{client_id}:{client_secret}"
            encoded_credentials = base64.b64encode(credentials.encode()).decode()
            
            headers = {
                'Authorization': f'Basic {encoded_credentials}',
                'Content-Type': 'application/x-www-form-urlencoded'
            }
            
            data = {
                'grant_type': 'authorization_code',
                'code': code,
                'redirect_uri': redirect_uri
            }
            
            response = requests.post(
                'https://api.ebay.com/identity/v1/oauth2/token',
                headers=headers,
                data=data,
                timeout=30
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                return {'error': f'Token exchange failed: {response.status_code}'}
                
        except Exception as e:
            return {'error': f'Token exchange error: {str(e)}'}

    def create_ebay_listing(self, store: Store, item: InventoryItem) -> Tuple[bool, str]:
        """
        Create a new eBay listing from local inventory item using AddFixedPriceItem API
        Returns (success, message_or_item_id)
        """
        try:
            if not store.api_key:
                return False, "No API credentials configured"
                
            creds = json.loads(store.api_key)
            
            # Use user_token as access_token if access_token is not available
            access_token = creds.get('access_token') or creds.get('user_token', '')
            if not access_token:
                return False, "Missing access token or user token"
            
            # Check if item already has an eBay listing
            existing_item_id = self.get_ebay_item_id_for_sku(item)
            if existing_item_id:
                return False, f"Item {item.sku} already has eBay listing with ItemID: {existing_item_id}"
            
            # Get price from MarketplaceListing if available (marketplace-specific pricing)
            from models import WarehouseStock, MarketplaceListing
            warehouse_stock = WarehouseStock.query.filter_by(sku=item.sku).first()
            listing_price = item.price  # Default fallback
            
            if warehouse_stock:
                marketplace_listing = MarketplaceListing.query.filter_by(
                    warehouse_stock_id=warehouse_stock.id,
                    store_id=store.id
                ).first()
                
                if marketplace_listing and marketplace_listing.price > 0:
                    listing_price = marketplace_listing.price
                    self.logger.info(f"Using marketplace price £{listing_price:.2f} for {item.sku} on eBay")
            
            # Ensure price meets eBay minimum (£0.99)
            if listing_price < 0.99:
                self.logger.warning(f"Price £{listing_price:.2f} below eBay minimum - using £0.99 for {item.sku}")
                listing_price = 0.99
            
            headers = {
                'Authorization': f'Bearer {access_token}',
                'X-EBAY-API-COMPATIBILITY-LEVEL': '967',
                'X-EBAY-API-DEV-NAME': creds.get('dev_id', ''),
                'X-EBAY-API-APP-NAME': creds['app_id'],
                'X-EBAY-API-CERT-NAME': creds['cert_id'],
                'X-EBAY-API-CALL-NAME': 'AddFixedPriceItem',
                'X-EBAY-API-SITEID': creds.get('site_id', '0'),
                'Content-Type': 'text/xml'
            }
            
            # Escape XML special characters in description and title
            description = item.description or item.name
            description = description.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            
            # Escape XML special characters in title
            title = item.name[:80]
            title = title.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            
            # Set default category (you may want to make this configurable)
            category_id = creds.get('default_category', '29792')  # Health & Beauty default
            
            # Create XML request using Business Policies (proven approach)
            # Get policy IDs from credentials (these should be created in eBay Seller Hub first)
            shipping_policy_id = creds.get('shipping_profile_id')
            payment_policy_id = creds.get('payment_profile_id') 
            return_policy_id = creds.get('return_profile_id')
            
            # Use Business Policies if available, otherwise fall back to direct configuration
            xml_request = f"""<?xml version="1.0" encoding="utf-8"?>
            <AddFixedPriceItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">
                <RequesterCredentials>
                    <eBayAuthToken>{access_token}</eBayAuthToken>
                </RequesterCredentials>
                <Item>
                    <Title>{title}</Title>
                    <Description><![CDATA[{description}]]></Description>
                    <SKU>{item.sku}</SKU>
                    <StartPrice>{listing_price:.2f}</StartPrice>
                    <Quantity>{item.quantity}</Quantity>
                    <ListingType>FixedPriceItem</ListingType>
                    <Currency>GBP</Currency>
                    <Country>GB</Country>
                    <Location>United Kingdom</Location>
                    <PrimaryCategory>
                        <CategoryID>{category_id}</CategoryID>
                    </PrimaryCategory>
                    <ListingDuration>GTC</ListingDuration>
                    <ConditionID>1000</ConditionID>
                    <PictureDetails>
                        <PictureURL>https://i.ebayimg.com/images/g/placeholder.jpg</PictureURL>
                    </PictureDetails>
                    <ItemSpecifics>
                        <NameValueList>
                            <Name>Brand</Name>
                            <Value>Unbranded</Value>
                        </NameValueList>
                    </ItemSpecifics>"""
            
            # Add Business Policies if available (proven approach)
            if shipping_policy_id and payment_policy_id and return_policy_id:
                xml_request += f"""
                    <SellerProfiles>
                        <SellerShippingProfile>
                            <ShippingProfileID>{shipping_policy_id}</ShippingProfileID>
                        </SellerShippingProfile>
                        <SellerPaymentProfile>
                            <PaymentProfileID>{payment_policy_id}</PaymentProfileID>
                        </SellerPaymentProfile>
                        <SellerReturnProfile>
                            <ReturnProfileID>{return_policy_id}</ReturnProfileID>
                        </SellerReturnProfile>
                    </SellerProfiles>"""
            else:
                # Proven fallback: minimal configuration to let eBay handle defaults
                xml_request += f"""
                    <PaymentMethods>PayPal</PaymentMethods>
                    <PaymentMethods>VisaMC</PaymentMethods>"""
                    
            xml_request += """
                </Item>
            </AddFixedPriceItemRequest>"""
            
            # CRITICAL FIX: Default to live API (sandbox=False) to prevent production from hitting sandbox
            # Previously defaulted to True, causing production with missing 'sandbox' flag to use sandbox API with 0 items
            api_url = self.sandbox_url if creds.get('sandbox') is True else self.base_url
            self.logger.info(f"Creating new eBay listing for SKU {item.sku}")
            
            response = requests.post(
                f"{api_url}/ws/api.dll",
                data=xml_request,
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 200:
                try:
                    import xml.etree.ElementTree as ET
                    root = ET.fromstring(response.content)
                    
                    # Check for success
                    ack_elem = root.find('.//{urn:ebay:apis:eBLBaseComponents}Ack')
                    if ack_elem is not None and ack_elem.text in ['Success', 'Warning']:
                        # Get the new ItemID
                        item_id_elem = root.find('.//{urn:ebay:apis:eBLBaseComponents}ItemID')
                        if item_id_elem is not None:
                            new_item_id = item_id_elem.text
                            
                            # Create external reference for the new listing
                            from sync_service import create_external_reference
                            if item.group_id:
                                group_id = item.group_id
                            else:
                                # Create a new group for this item
                                from models import ProductGroup
                                from app import db
                                import uuid
                                new_group = ProductGroup()
                                new_group.name = item.name
                                new_group.group_key = f"group_{uuid.uuid4().hex[:8]}"
                                db.session.add(new_group)
                                db.session.flush()
                                item.group_id = new_group.id
                                group_id = new_group.id
                                db.session.commit()
                            
                            # Create external reference
                            item_data = {
                                'sku': item.sku,
                                'name': item.name,
                                'quantity': item.quantity,
                                'price': float(item.price),
                                'description': 'eBay listing'
                            }
                            
                            create_external_reference(group_id, 'eBay', item.sku, item_data)
                            
                            self.logger.info(f"Successfully created eBay listing for SKU {item.sku} with ItemID: {new_item_id}")
                            return True, f"Created eBay listing with ItemID: {new_item_id}"
                        else:
                            return False, "eBay listing created but ItemID not found in response"
                    else:
                        # Handle errors
                        error_code = "Unknown"
                        error_msg = "Unknown error"
                        
                        errors = root.findall('.//{urn:ebay:apis:eBLBaseComponents}Errors')
                        if errors:
                            error_elem = errors[0]
                            code_elem = error_elem.find('.//{urn:ebay:apis:eBLBaseComponents}ErrorCode')
                            msg_elem = error_elem.find('.//{urn:ebay:apis:eBLBaseComponents}ShortMessage')
                            long_msg_elem = error_elem.find('.//{urn:ebay:apis:eBLBaseComponents}LongMessage')
                            
                            if code_elem is not None:
                                error_code = code_elem.text
                            if msg_elem is not None:
                                error_msg = msg_elem.text
                            if long_msg_elem is not None and long_msg_elem.text:
                                error_msg = long_msg_elem.text
                        
                        self.logger.error(f"eBay API error creating listing for SKU {item.sku}: {error_code} - {error_msg}")
                        return False, f"eBay API error: {error_code} - {error_msg}"
                        
                except Exception as parse_error:
                    self.logger.error(f"Error parsing eBay response for SKU {item.sku}: {str(parse_error)}")
                    return False, f"Error parsing eBay response: {str(parse_error)}"
            else:
                self.logger.error(f"HTTP error {response.status_code} creating listing for SKU {item.sku}")
                return False, f"HTTP error {response.status_code}: {response.text[:200]}"
                
        except json.JSONDecodeError:
            return False, "Invalid API credentials format"
        except Exception as e:
            self.logger.error(f"Error creating eBay listing for {item.sku}: {str(e)}")
            return False, f"Creation error: {str(e)}"
    
    def update_listing_quantity(self, item_id: str, quantity: int, sku: Optional[str] = None) -> Tuple[bool, str]:
        """
        Quantity-only update using ReviseInventoryStatus.
        Works in production or sandbox, logs full eBay response on failure.
        
        Args:
            item_id: eBay Item ID to update (must be numeric)
            quantity: New quantity to set (must be >= 0)
            sku: Optional SKU for multi-variation items (required for variations)
        Returns:
            Tuple of (success: bool, message: str)
        """
        # Safety checks
        if not item_id or not str(item_id).isdigit():
            return False, f"ItemID must be numeric, got '{item_id}'"
        if quantity is None or quantity < 0:
            return False, f"Quantity must be >= 0, got {quantity}"

        # Endpoints
        endpoint = "https://api.sandbox.ebay.com/ws/api.dll" if getattr(self, "use_sandbox", False) \
                   else "https://api.ebay.com/ws/api.dll"

        # SiteID=3 is UK. Change if you sell on a different site.
        SITE_ID = "3"
        # A conservative, widely-supported Trading API level
        COMPAT_LEVEL = "1199"

        # Headers
        headers = {
            "X-EBAY-API-CALL-NAME": "ReviseInventoryStatus",
            "X-EBAY-API-SITEID": SITE_ID,
            "X-EBAY-API-DEV-NAME": getattr(self, 'dev_id', ''),
            "X-EBAY-API-APP-NAME": getattr(self, 'app_id', ''),
            "X-EBAY-API-CERT-NAME": getattr(self, 'cert_id', ''),
            "X-EBAY-API-COMPATIBILITY-LEVEL": COMPAT_LEVEL,
            "Content-Type": "text/xml",
        }

        # Build ReviseInventoryStatus XML request with optional SKU for multi-variation items
        sku_xml = f"<SKU>{sku}</SKU>" if sku else ""
        body = f"""<?xml version="1.0" encoding="utf-8"?>
<ReviseInventoryStatusRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <RequesterCredentials>
    <eBayAuthToken>{getattr(self, 'auth_token', '')}</eBayAuthToken>
  </RequesterCredentials>
  <InventoryStatus>
    <ItemID>{item_id}</ItemID>
    {sku_xml}
    <Quantity>{quantity}</Quantity>
  </InventoryStatus>
</ReviseInventoryStatusRequest>"""

        try:
            resp = requests.post(endpoint, data=body.encode("utf-8"), headers=headers, timeout=45)
            text = resp.text or ""

            # Parse Ack
            ack_match = re.search(r"<Ack>([^<]+)</Ack>", text)
            ack = ack_match.group(1) if ack_match else None

            if ack in ("Success", "Warning"):
                self.logger.info(f"Successfully updated eBay listing {item_id} to quantity {quantity}")
                return True, f"Ack={ack}"

            # Extract a short error if present
            code = None
            short = None
            m = re.search(r"<Errors[^>]*>.*?<ErrorCode>(\d+)</ErrorCode>.*?<ShortMessage>(.*?)</ShortMessage>", text, re.S)
            if m:
                code, short = m.group(1), re.sub(r"\s+", " ", m.group(2)).strip()

            # Log a compact failure summary + snippet for debugging
            snippet = text[:800].replace("\n", " ")
            self.logger.error("ReviseInventoryStatus FAIL - HTTP %s Ack=%s Err=%s %s :: %s",
                              resp.status_code, ack, code, short, snippet)

            msg = f"HTTP {resp.status_code} Ack={ack or 'N/A'}"
            if code or short:
                msg += f" Err {code}: {short}"
            return False, msg

        except requests.RequestException as e:
            self.logger.exception("HTTP error calling eBay")
            return False, f"HTTP error: {e}"
    
    def update_listing_price(self, store: Store, item_id: str, new_price: float, sku: Optional[str] = None) -> Tuple[bool, str]:
        """
        Update the price of an eBay listing using ReviseFixedPriceItem API
        
        Args:
            store: Store object with eBay credentials
            item_id: eBay ItemID (numeric)
            new_price: New price to set (must be >= 0.99 for UK/US sites)
            sku: Optional SKU for variation listings
            
        Returns:
            Tuple of (success: bool, message: str)
        """
        try:
            # Validate price minimum
            if new_price < 0.99:
                return False, f"Price {new_price} is below eBay minimum (£0.99)"
            
            # Parse credentials
            if not store.api_key:
                return False, "No API credentials configured"
                
            creds = json.loads(store.api_key)
            access_token = creds.get('access_token') or creds.get('user_token', '')
            
            if not access_token:
                return False, "Missing access token"
            
            # Build SKU XML element if provided (for variations)
            sku_xml = f"<SKU>{sku}</SKU>" if sku else ""
            
            # Create XML request for ReviseFixedPriceItem
            xml_request = f"""<?xml version="1.0" encoding="utf-8"?>
<ReviseFixedPriceItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">
    <RequesterCredentials>
        <eBayAuthToken>{access_token}</eBayAuthToken>
    </RequesterCredentials>
    <Item>
        <ItemID>{item_id}</ItemID>
        {sku_xml}
        <StartPrice>{new_price:.2f}</StartPrice>
    </Item>
</ReviseFixedPriceItemRequest>"""
            
            headers = {
                'X-EBAY-API-COMPATIBILITY-LEVEL': '967',
                'X-EBAY-API-DEV-NAME': creds.get('dev_id', ''),
                'X-EBAY-API-APP-NAME': creds['app_id'],
                'X-EBAY-API-CERT-NAME': creds['cert_id'],
                'X-EBAY-API-CALL-NAME': 'ReviseFixedPriceItem',
                'X-EBAY-API-SITEID': creds.get('site_id', '0'),
                'Content-Type': 'text/xml'
            }
            
            # CRITICAL FIX: Default to live API (sandbox=False) to prevent production from hitting sandbox
            # Previously defaulted to True, causing production with missing 'sandbox' flag to use sandbox API with 0 items
            api_url = self.sandbox_url if creds.get('sandbox') is True else self.base_url
            
            self.logger.info(f"Updating eBay listing {item_id} price to £{new_price:.2f}")
            
            response = requests.post(
                f"{api_url}/ws/api.dll",
                data=xml_request,
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 200:
                import xml.etree.ElementTree as ET
                try:
                    root = ET.fromstring(response.text)
                    
                    # Check for success
                    ack_elem = root.find('.//{urn:ebay:apis:eBLBaseComponents}Ack')
                    if ack_elem is not None and ack_elem.text in ['Success', 'Warning']:
                        self.logger.info(f"✅ Successfully updated eBay listing {item_id} price to £{new_price:.2f}")
                        return True, f"Successfully updated price to £{new_price:.2f}"
                    
                    # Parse errors
                    errors = root.findall('.//{urn:ebay:apis:eBLBaseComponents}Errors')
                    if errors:
                        error_elem = errors[0]
                        error_code = error_elem.find('.//{urn:ebay:apis:eBLBaseComponents}ErrorCode')
                        error_msg = error_elem.find('.//{urn:ebay:apis:eBLBaseComponents}ShortMessage')
                        long_msg = error_elem.find('.//{urn:ebay:apis:eBLBaseComponents}LongMessage')
                        
                        code_text = error_code.text if error_code is not None else "Unknown"
                        msg_text = error_msg.text if error_msg is not None else "Unknown error"
                        long_text = long_msg.text if long_msg is not None else msg_text
                        
                        error_message = f"eBay API error {code_text}: {long_text}"
                        self.logger.error(f"❌ Failed to update {item_id} price: {error_message}")
                        return False, error_message
                    else:
                        return False, "eBay API call failed with unknown error"
                        
                except ET.ParseError as pe:
                    error_message = f"Error parsing eBay response: {str(pe)}"
                    self.logger.error(f"Error parsing response for {item_id}: {str(pe)}")
                    return False, error_message
            else:
                error_message = f"HTTP error {response.status_code}"
                self.logger.error(f"HTTP error {response.status_code} updating {item_id}")
                return False, error_message
                
        except Exception as e:
            error_message = f"Error updating price: {str(e)}"
            self.logger.error(f"Error updating eBay listing {item_id} price: {str(e)}")
            return False, error_message
    
    def push_quantity_only(self, sku: str, qty: int, store: Store) -> Tuple[bool, str]:
        """
        Push quantity-only update to eBay using ReviseInventoryStatus API
        Bypasses Business Policy requirements (21920303) by only updating quantity
        Supports both single listings AND multi-variation listings (Multi-SKU items)
        
        Args:
            sku: Warehouse SKU to push
            qty: Quantity to set
            store: eBay store
            
        Returns:
            Tuple of (success, message)
        """
        try:
            from models import MarketplaceListing, WarehouseStock
            
            if not store.api_key:
                return False, "No API credentials configured"
            
            creds = json.loads(store.api_key)
            access_token = creds.get('access_token') or creds.get('user_token', '')
            if not access_token:
                return False, "Missing access token or user token"
            
            listings = MarketplaceListing.query.join(WarehouseStock).filter(
                WarehouseStock.sku == sku,
                MarketplaceListing.store_id == store.id,
                MarketplaceListing.is_active == True
            ).all()
            
            if not listings:
                return False, f"No active eBay listings found for SKU {sku}"
            
            success_count = 0
            errors = []
            
            for listing in listings:
                variation_sku = None
                final_item_id = None
                
                if listing.parent_item_id and listing.parent_item_id.isdigit():
                    final_item_id = listing.parent_item_id
                    variation_sku = listing.external_sku or sku
                    self.logger.info(f"Variation detected: SKU {sku} → parent ItemID {final_item_id}, variation SKU {variation_sku}")
                elif listing.external_listing_id and listing.external_listing_id.isdigit():
                    final_item_id = listing.external_listing_id
                    if listing.external_sku:
                        variation_sku = listing.external_sku
                        self.logger.info(f"Multi-SKU listing: using external_sku {variation_sku} for SKU {sku}")
                
                if not final_item_id:
                    errors.append(f"{sku}: No valid numeric ItemID found")
                    self.logger.warning(f"Skipping SKU {sku}: no numeric ItemID (child: {listing.external_listing_id}, parent: {listing.parent_item_id})")
                    continue
                
                headers = {
                    'Authorization': f'Bearer {access_token}',
                    'X-EBAY-API-COMPATIBILITY-LEVEL': '967',
                    'X-EBAY-API-DEV-NAME': creds.get('dev_id', ''),
                    'X-EBAY-API-APP-NAME': creds['app_id'],
                    'X-EBAY-API-CERT-NAME': creds['cert_id'],
                    'X-EBAY-API-CALL-NAME': 'ReviseInventoryStatus',
                    'X-EBAY-API-SITEID': creds.get('site_id', '0'),
                    'Content-Type': 'text/xml'
                }
                
                sku_xml = f"<SKU>{variation_sku}</SKU>" if variation_sku else ""
                
                xml_request = f"""<?xml version="1.0" encoding="utf-8"?>
<ReviseInventoryStatusRequest xmlns="urn:ebay:apis:eBLBaseComponents">
    <RequesterCredentials>
        <eBayAuthToken>{access_token}</eBayAuthToken>
    </RequesterCredentials>
    <InventoryStatus>
        <ItemID>{final_item_id}</ItemID>
        {sku_xml}
        <Quantity>{qty}</Quantity>
    </InventoryStatus>
</ReviseInventoryStatusRequest>"""
                
                api_url = self.sandbox_url if creds.get('sandbox', False) else self.base_url
                variation_info = f", variation SKU: {variation_sku}" if variation_sku else ""
                self.logger.info(f"eBay qty-only push: SKU={sku}, ItemID={final_item_id}{variation_info}, Qty={qty}")
                
                response = requests.post(
                    f"{api_url}/ws/api.dll",
                    data=xml_request,
                    headers=headers,
                    timeout=30
                )
                
                if response.status_code == 200:
                    import xml.etree.ElementTree as ET
                    try:
                        root = ET.fromstring(response.text)
                        
                        ack_elem = root.find('.//{urn:ebay:apis:eBLBaseComponents}Ack')
                        ack_value = ack_elem.text if ack_elem is not None else 'Unknown'
                        
                        self.logger.info(f"eBay API Response: Ack={ack_value} for ItemID={final_item_id}{variation_info}")
                        
                        if ack_value in ['Success', 'Warning']:
                            success_count += 1
                            self.logger.info(f"✅ ReviseInventoryStatus SUCCESS: ItemID={final_item_id}{variation_info}, Qty={qty}")
                        else:
                            error_code = "Unknown"
                            error_msg = "Unknown error"
                            
                            errors_elem = root.findall('.//{urn:ebay:apis:eBLBaseComponents}Errors')
                            if errors_elem:
                                error_elem = errors_elem[0]
                                code_elem = error_elem.find('.//{urn:ebay:apis:eBLBaseComponents}ErrorCode')
                                msg_elem = error_elem.find('.//{urn:ebay:apis:eBLBaseComponents}LongMessage')
                                
                                if code_elem is not None:
                                    error_code = code_elem.text
                                if msg_elem is not None:
                                    error_msg = msg_elem.text
                            
                            error_str = f"{final_item_id}{variation_info}: Error {error_code} - {error_msg}"
                            errors.append(error_str)
                            self.logger.error(f"❌ ReviseInventoryStatus FAILED: {error_str}")
                            
                    except Exception as parse_error:
                        error_str = f"{final_item_id}{variation_info}: Parse error - {str(parse_error)}"
                        errors.append(error_str)
                        self.logger.error(f"Error parsing eBay response: {str(parse_error)}")
                else:
                    error_str = f"{final_item_id}{variation_info}: HTTP {response.status_code}"
                    errors.append(error_str)
                    self.logger.error(f"HTTP error {response.status_code} for ItemID={final_item_id}{variation_info}")
            
            # Build result message
            if success_count > 0 and not errors:
                return True, f"Successfully pushed quantity {qty} to {success_count} listing(s)"
            elif success_count > 0 and errors:
                error_summary = "; ".join(errors[:3])  # Limit to first 3 errors
                return True, f"Partially successful: {success_count} succeeded, {len(errors)} failed. Errors: {error_summary}"
            elif errors:
                error_summary = "; ".join(errors[:3])
                return False, f"All pushes failed. Errors: {error_summary}"
            else:
                return False, "No listings processed"
                
        except Exception as e:
            self.logger.error(f"Error in push_quantity_only for SKU {sku}: {str(e)}")
            return False, f"Push error: {str(e)}"

    def validate_credentials_format(self, api_key_json: str) -> Tuple[bool, str]:
        """
        Validate eBay API credentials format
        
        Args:
            api_key_json: JSON string containing eBay credentials
            
        Returns:
            Tuple of (is_valid: bool, message: str)
        """
        try:
            creds = json.loads(api_key_json)
            required_keys = ['app_id', 'cert_id', 'dev_id']
            
            missing = [key for key in required_keys if key not in creds]
            if missing:
                return False, f"Missing required credentials: {', '.join(missing)}"
            
            return True, "Credentials format is valid"
            
        except json.JSONDecodeError as e:
            return False, f"Invalid JSON format: {str(e)}"
        except Exception as e:
            return False, f"Validation error: {str(e)}"

# Module-level helper functions for health checks and testing
def get_ebay_time(store: Store) -> Optional[Dict]:
    """
    Simple eBay API test call to verify connectivity and credentials
    
    Args:
        store: eBay store object with credentials stored in api_key JSON field
        
    Returns:
        Dict with API response or None on failure
    """
    try:
        import xml.etree.ElementTree as ET
        
        # Parse credentials from JSON (credentials are stored in api_key field)
        if not store.api_key:
            return {'Ack': 'Failure', 'Errors': {'ShortMessage': 'No API credentials configured'}}
        
        creds = json.loads(store.api_key)
        
        # Extract credentials from JSON
        user_token = creds.get('user_token') or creds.get('auth_token', '')
        app_id = creds.get('app_id', '')
        dev_id = creds.get('dev_id', '')
        cert_id = creds.get('cert_id', '')
        sandbox = creds.get('sandbox', False)
        site_id = creds.get('site_id', '0')
        
        # Determine API endpoint based on sandbox flag
        api_url = "https://api.sandbox.ebay.com" if sandbox else "https://api.ebay.com"
        
        # Build XML request for GeteBayOfficialTime (simple test call)
        xml_request = f"""<?xml version="1.0" encoding="utf-8"?>
        <GeteBayOfficialTimeRequest xmlns="urn:ebay:apis:eBLBaseComponents">
            <RequesterCredentials>
                <eBayAuthToken>{user_token}</eBayAuthToken>
            </RequesterCredentials>
        </GeteBayOfficialTimeRequest>"""
        
        # Headers for eBay Trading API
        headers = {
            'X-EBAY-API-COMPATIBILITY-LEVEL': '967',
            'X-EBAY-API-DEV-NAME': dev_id,  # Dev ID
            'X-EBAY-API-APP-NAME': app_id,  # App ID  
            'X-EBAY-API-CERT-NAME': cert_id,  # Cert ID
            'X-EBAY-API-CALL-NAME': 'GeteBayOfficialTime',
            'X-EBAY-API-SITEID': str(site_id),
            'Content-Type': 'text/xml; charset=utf-8'
        }
        
        # Make API call
        response = requests.post(
            f"{api_url}/ws/api.dll",
            data=xml_request.encode('utf-8'),
            headers=headers,
            timeout=10
        )
        
        if response.status_code == 200:
            # Parse XML response
            root = ET.fromstring(response.content)
            ns = {'ebay': 'urn:ebay:apis:eBLBaseComponents'}
            
            # Extract Ack status
            ack_elem = root.find('.//ebay:Ack', ns)
            ack = ack_elem.text if ack_elem is not None else 'Unknown'
            
            result = {'Ack': ack}
            
            # If there are errors, include them
            errors_elem = root.find('.//ebay:Errors', ns)
            if errors_elem is not None:
                short_msg = errors_elem.find('.//ebay:ShortMessage', ns)
                long_msg = errors_elem.find('.//ebay:LongMessage', ns)
                error_code = errors_elem.find('.//ebay:ErrorCode', ns)
                
                result['Errors'] = {
                    'ShortMessage': short_msg.text if short_msg is not None else '',
                    'LongMessage': long_msg.text if long_msg is not None else '',
                    'ErrorCode': error_code.text if error_code is not None else ''
                }
            
            return result
        else:
            logging.error(f"eBay API returned HTTP {response.status_code}")
            return {'Ack': 'Failure', 'Errors': {'ShortMessage': f'HTTP {response.status_code}'}}
    
    except Exception as e:
        logging.error(f"eBay time check error: {str(e)}")
        return {'Ack': 'Failure', 'Errors': {'ShortMessage': str(e)}}


# ==============================
# Phase 1: Order Import for Auto-Sync Engine
# ==============================
def get_ebay_orders(store: Store, created_after: str = None, max_results: int = 100) -> Dict:
    """
    Fetch orders from eBay using Trading API GetOrders.
    
    Args:
        store: Store object with eBay credentials
        created_after: ISO 8601 timestamp to fetch orders after
        max_results: Maximum number of orders to fetch (default 100)
    
    Returns:
        Dict with 'success', 'orders' list, and optional 'error' message
    """
    from datetime import datetime, timedelta
    import xml.etree.ElementTree as ET
    
    try:
        if not store.api_key:
            return {"success": False, "orders": [], "error": "No API credentials configured"}
        
        creds = json.loads(store.api_key)
        access_token = creds.get('access_token') or creds.get('user_token', '')
        
        if not access_token:
            return {"success": False, "orders": [], "error": "Missing access token"}
        
        # Default to last 24 hours if no created_after specified
        if not created_after:
            created_after = (datetime.utcnow() - timedelta(hours=24)).strftime('%Y-%m-%dT%H:%M:%SZ')
        
        # Format for eBay API - use ModTime to catch dispatched/completed orders
        # EBAY-ORDER-FETCH-CORRECTION-001: Changed from CreateTime to ModTime
        mod_time_from = created_after.replace('Z', '.000Z')
        mod_time_to = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.000Z')
        
        # Build XML request for GetOrders
        # EBAY-ORDER-FETCH-CORRECTION-001: Use ModTimeFrom/ModTimeTo instead of CreateTimeFrom/CreateTimeTo
        # and remove OrderStatus=Active filter to include Completed/Shipped orders
        xml_request = f"""<?xml version="1.0" encoding="utf-8"?>
        <GetOrdersRequest xmlns="urn:ebay:apis:eBLBaseComponents">
            <RequesterCredentials>
                <eBayAuthToken>{access_token}</eBayAuthToken>
            </RequesterCredentials>
            <ModTimeFrom>{mod_time_from}</ModTimeFrom>
            <ModTimeTo>{mod_time_to}</ModTimeTo>
            <OrderRole>Seller</OrderRole>
            <Pagination>
                <EntriesPerPage>{min(max_results, 100)}</EntriesPerPage>
                <PageNumber>1</PageNumber>
            </Pagination>
        </GetOrdersRequest>"""
        
        headers = {
            'X-EBAY-API-COMPATIBILITY-LEVEL': '967',
            'X-EBAY-API-DEV-NAME': creds.get('dev_id', ''),
            'X-EBAY-API-APP-NAME': creds.get('app_id', ''),
            'X-EBAY-API-CERT-NAME': creds.get('cert_id', ''),
            'X-EBAY-API-CALL-NAME': 'GetOrders',
            'X-EBAY-API-SITEID': creds.get('site_id', '3'),  # 3 = UK
            'Content-Type': 'text/xml'
        }
        
        # Default to live API (not sandbox)
        base_url = "https://api.sandbox.ebay.com" if creds.get('sandbox') is True else "https://api.ebay.com"
        
        logging.info(f"Fetching eBay orders for store {store.name} (ModTime since {created_after})")
        
        response = requests.post(
            f"{base_url}/ws/api.dll",
            data=xml_request,
            headers=headers,
            timeout=60
        )
        
        if response.status_code == 200:
            # Parse XML response
            root = ET.fromstring(response.content)
            ns = {'ebay': 'urn:ebay:apis:eBLBaseComponents'}
            
            # Check Ack status
            ack_elem = root.find('.//ebay:Ack', ns)
            ack = ack_elem.text if ack_elem is not None else 'Unknown'
            
            if ack not in ['Success', 'Warning']:
                # Extract error message
                error_elem = root.find('.//ebay:Errors/ebay:LongMessage', ns)
                error_msg = error_elem.text if error_elem is not None else f'eBay API returned {ack}'
                return {"success": False, "orders": [], "error": error_msg}
            
            # Parse orders
            processed_orders = []
            orders = root.findall('.//ebay:Order', ns)
            
            for order in orders:
                order_id_elem = order.find('.//ebay:OrderID', ns)
                order_id = order_id_elem.text if order_id_elem is not None else ''
                
                order_status_elem = order.find('.//ebay:OrderStatus', ns)
                order_status = order_status_elem.text if order_status_elem is not None else ''
                
                # EBAY-ORDER-FETCH-CORRECTION-001: Skip cancelled orders (post-fetch filter)
                if order_status.lower() in ('cancelled', 'cancelrequested', 'cancelcomplete'):
                    logging.debug(f"Skipping cancelled eBay order {order_id} (status: {order_status})")
                    continue
                
                created_time_elem = order.find('.//ebay:CreatedTime', ns)
                created_time = created_time_elem.text if created_time_elem is not None else ''
                
                # Parse order line items (transactions)
                transactions = order.findall('.//ebay:TransactionArray/ebay:Transaction', ns)
                
                for txn in transactions:
                    item_id_elem = txn.find('.//ebay:Item/ebay:ItemID', ns)
                    item_id = item_id_elem.text if item_id_elem is not None else ''
                    
                    sku_elem = txn.find('.//ebay:Item/ebay:SKU', ns)
                    sku = sku_elem.text if sku_elem is not None else ''
                    
                    # Also check Variation SKU
                    if not sku:
                        var_sku_elem = txn.find('.//ebay:Variation/ebay:SKU', ns)
                        sku = var_sku_elem.text if var_sku_elem is not None else ''
                    
                    qty_elem = txn.find('.//ebay:QuantityPurchased', ns)
                    quantity = int(qty_elem.text) if qty_elem is not None and qty_elem.text else 0
                    
                    txn_id_elem = txn.find('.//ebay:TransactionID', ns)
                    txn_id = txn_id_elem.text if txn_id_elem is not None else ''
                    
                    price_elem = txn.find('.//ebay:TransactionPrice', ns)
                    item_price = float(price_elem.text) if price_elem is not None and price_elem.text else 0
                    
                    processed_orders.append({
                        'marketplace_order_id': order_id,
                        'marketplace_order_item_id': txn_id,
                        'sku': sku,
                        'external_item_id': item_id,
                        'quantity': quantity,
                        'item_price': item_price,
                        'currency': 'GBP',
                        'order_status': order_status,
                        'purchase_date': created_time,
                        'fulfillment_channel': 'SELLER'
                    })
            
            logging.info(f"Fetched {len(processed_orders)} eBay order items for store {store.name}")
            return {"success": True, "orders": processed_orders, "error": None}
            
        else:
            error_msg = f"eBay API returned HTTP {response.status_code}"
            logging.error(error_msg)
            return {"success": False, "orders": [], "error": error_msg}
            
    except Exception as e:
        logging.error(f"Error fetching eBay orders for store {store.name}: {str(e)}")
        return {"success": False, "orders": [], "error": str(e)}