"""
Direct REST API client for Amazon SP-API
Supports two modes:
1. LWA-only (for published apps) - No AWS required!
2. AWS + LWA (for draft apps) - Uses IAM credentials temporarily
"""
from __future__ import annotations

import requests
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Try to import AWS4Auth for Draft app support
try:
    from requests_aws4auth import AWS4Auth
    AWS_AUTH_AVAILABLE = True
except ImportError:
    AWS_AUTH_AVAILABLE = False
    logger.warning("requests-aws4auth not available - AWS mode disabled")

class AmazonRestAPIClient:
    """
    Direct REST API client for Amazon SP-API
    Supports two modes:
    1. LWA-only (for published apps) - No AWS credentials needed
    2. AWS + LWA (for draft apps) - Uses AWS IAM credentials
    """
    
    # SP-API Endpoints by region
    ENDPOINTS = {
        'EU': 'https://sellingpartnerapi-eu.amazon.com',
        'NA': 'https://sellingpartnerapi-na.amazon.com',
        'FE': 'https://sellingpartnerapi-fe.amazon.com'
    }
    
    # Marketplace to Region mapping
    MARKETPLACE_REGION = {
        "A1F83G8C2ARO7P": "EU",   # UK
        "A1PA6795UKMFR9": "EU",   # DE
        "APJ6JRA9NG5V4": "EU",    # FR
        "A13V1IB3VIYZZH": "EU",   # ES
        "A1RKKUPIHCS9HS": "EU",   # IT
        "ATVPDKIKX0DER": "NA",    # US
        "A2EUQ1WTGCTBG2": "NA",   # CA
        "A1AM78C64UM0Y8": "NA",   # MX
    }
    
    # AWS region for each marketplace region
    AWS_REGIONS = {
        'EU': 'eu-west-1',
        'NA': 'us-east-1',
        'FE': 'us-west-2'
    }
    
    def __init__(self, credentials: Dict, marketplace_id: str):
        """
        Initialize Amazon REST API client
        
        Args:
            credentials: Dict with LWA credentials and optional AWS credentials
            marketplace_id: Amazon marketplace ID (e.g., A1F83G8C2ARO7P for UK)
        """
        self.credentials = credentials
        self.marketplace_id = marketplace_id
        self.region = self.MARKETPLACE_REGION.get(marketplace_id, 'NA')
        self.aws_region = self.AWS_REGIONS[self.region]
        self.endpoint = self.ENDPOINTS[self.region]
        self.access_token = None
        self.token_expires_at = None
        
        # Check if AWS credentials are provided (for Draft apps)
        self.use_aws_auth = bool(
            credentials.get('aws_access_key_id') and 
            credentials.get('aws_secret_access_key')
        )
        
        if self.use_aws_auth:
            logger.info(f"🔐 Initialized Amazon REST API client (AWS MODE - Draft app): marketplace={marketplace_id}, region={self.region}")
        else:
            logger.info(f"✨ Initialized Amazon REST API client (LWA-ONLY MODE - Published app): marketplace={marketplace_id}, region={self.region}")
    
    def get_access_token(self) -> Optional[str]:
        """
        Get fresh LWA access token
        
        Returns:
            Access token string or None if failed
        """
        # Check if we have a valid cached token
        if self.access_token and self.token_expires_at:
            if datetime.now() < self.token_expires_at:
                return self.access_token
        
        # Request new token
        try:
            response = requests.post(
                'https://api.amazon.com/auth/o2/token',
                data={
                    'grant_type': 'refresh_token',
                    'refresh_token': self.credentials['refresh_token'],
                    'client_id': self.credentials['lwa_app_id'],
                    'client_secret': self.credentials['lwa_client_secret']
                },
                headers={'Content-Type': 'application/x-www-form-urlencoded'}
            )
            
            if response.status_code == 200:
                from amazon_auth import safe_parse_json, AmazonNonJsonResponseError
                try:
                    token_data = safe_parse_json(response, "LWA token (REST API)")
                except AmazonNonJsonResponseError as e:
                    logger.error(f"[AMAZON_NON_JSON_RESPONSE] LWA token: {e}")
                    self.last_token_error = 'NON_JSON_RESPONSE'
                    self.last_token_error_desc = e.preview
                    return None
                self.access_token = token_data['access_token']
                # Token expires in 1 hour, refresh 5 minutes early
                expires_in = token_data.get('expires_in', 3600)
                self.token_expires_at = datetime.now() + timedelta(seconds=expires_in - 300)
                logger.info("Successfully obtained LWA access token")
                return self.access_token
            else:
                logger.error(f"Failed to get access token: {response.status_code} - {response.text}")
                # Store detailed error info for better error messages
                from amazon_auth import safe_parse_json, AmazonNonJsonResponseError
                try:
                    error_data = safe_parse_json(response, "LWA token error (REST API)")
                    self.last_token_error = error_data.get('error', 'unknown')
                    self.last_token_error_desc = error_data.get('error_description', response.text)
                except (AmazonNonJsonResponseError, Exception):
                    self.last_token_error = 'unknown'
                    self.last_token_error_desc = response.text[:200]
                return None
                
        except Exception as e:
            logger.error(f"Error getting access token: {str(e)}")
            return None
    
    def _make_request(self, method: str, path: str, params: Dict = None, data: Dict = None, 
                     json_data: Dict = None, headers: Dict = None) -> Tuple[bool, Optional[Dict], str]:
        """
        Make authenticated request to SP-API
        Supports both LWA-only and AWS+LWA authentication
        
        Args:
            method: HTTP method (GET, POST, PUT, PATCH, DELETE)
            path: API path (e.g., '/feeds/2021-06-30/documents')
            params: Query parameters
            data: Form data
            json_data: JSON body data
            headers: Additional headers
            
        Returns:
            Tuple of (success, response_data, error_message)
        """
        access_token = self.get_access_token()
        if not access_token:
            return False, None, "Failed to obtain access token"
        
        url = f"{self.endpoint}{path}"
        
        # Prepare headers
        request_headers = {
            'x-amz-access-token': access_token,
            'Content-Type': 'application/json'
        }
        if headers:
            request_headers.update(headers)
        
        # Prepare auth (AWS signing for Draft apps, LWA-only for published apps)
        auth = None
        if self.use_aws_auth and AWS_AUTH_AVAILABLE:
            auth = AWS4Auth(
                self.credentials['aws_access_key_id'],
                self.credentials['aws_secret_access_key'],
                self.aws_region,
                'execute-api'
            )
            logger.debug(f"🔐 Using AWS SigV4 signing for {method} {path}")
        else:
            logger.debug(f"✨ Using LWA-only auth for {method} {path}")
        
        try:
            response = requests.request(
                method=method,
                url=url,
                params=params,
                data=data,
                json=json_data,
                headers=request_headers,
                auth=auth,  # AWS signing when available
                timeout=30
            )
            
            # Log request details
            logger.info(f"SP-API Request: {method} {path} - Status: {response.status_code}")
            
            if response.status_code in [200, 201, 202]:
                from amazon_auth import safe_parse_json, AmazonNonJsonResponseError
                try:
                    data = safe_parse_json(response, f"SP-API {method} {path}")
                    return True, data, ""
                except AmazonNonJsonResponseError as e:
                    logger.error(f"[AMAZON_NON_JSON_RESPONSE] {method} {path}: {e}")
                    return False, None, f"AMAZON_NON_JSON_RESPONSE: {e.preview[:100]}"
                except Exception:
                    return True, {'raw': response.text}, ""
            else:
                error_msg = f"SP-API error {response.status_code}: {response.text[:500]}"
                logger.error(error_msg)
                return False, None, error_msg
                
        except Exception as e:
            error_msg = f"Request exception: {str(e)}"
            logger.error(error_msg)
            return False, None, error_msg
    
    def test_connection(self) -> Tuple[bool, str]:
        """
        Test API connection using Feeds API (works with "Inventory and Order Tracking" role)
        
        Returns:
            Tuple of (success, message)
        """
        # Test with Feeds API - use create feed document which is what we actually use for inventory
        logger.info(f"Testing connection with Feeds API (Inventory and Order Tracking role)...")
        
        # Test by creating a feed document (this is what we use for inventory sync)
        # This is a lightweight operation that just creates a document placeholder
        success, data, error = self._make_request(
            'POST',
            '/feeds/2021-06-30/documents',
            json_data={
                'contentType': 'text/xml; charset=utf-8'
            }
        )
        
        if success:
            logger.info(f"✅ Connection successful! Feeds API is accessible (can create feed documents)")
            return True, "Connection successful! Your app has the correct permissions for inventory sync."
        else:
            logger.error(f"❌ Feeds API test failed: {error}")
            
            # Check for token-level authorization error (unauthorized_client)
            if hasattr(self, 'last_token_error') and self.last_token_error == 'unauthorized_client':
                return False, "Amazon SP-API authorization failed: Your app is missing required roles. Please go to Amazon Seller Central > Developer Console and add 'Inventory and Order Tracking' and 'Feeds' roles to your application."
            
            # Check for "Failed to obtain access token" which indicates token-level issues
            if "Failed to obtain access token" in error:
                return False, "Amazon SP-API authorization failed: Your app lacks required roles. Update roles in Amazon Seller Central > Developer Console (add 'Inventory and Order Tracking' and 'Feeds' roles)."
            
            # Check for other permission errors
            if "403" in error or "Unauthorized" in error or "Forbidden" in error:
                return False, "Permission denied. Please verify 'Inventory and Order Tracking' and 'Feeds' roles are enabled in your Amazon Developer Console."
            else:
                return False, f"Connection test failed: {error}"
    
    def create_feed_document(self, content_type: str = 'text/xml; charset=utf-8') -> Tuple[bool, Optional[Dict], str]:
        """
        Create a feed document
        
        Args:
            content_type: Content type of the feed
            
        Returns:
            Tuple of (success, response_data, error_message)
            response_data contains: feedDocumentId, url, encryptionDetails
        """
        json_data = {
            'contentType': content_type
        }
        
        success, data, error = self._make_request(
            'POST',
            '/feeds/2021-06-30/documents',
            json_data=json_data
        )
        
        return success, data, error
    
    def upload_feed_content(self, upload_url: str, content: str, content_type: str = 'text/xml; charset=utf-8') -> Tuple[bool, str]:
        """
        Upload content to feed document URL
        
        Args:
            upload_url: URL from create_feed_document response
            content: XML content to upload
            content_type: Content type
            
        Returns:
            Tuple of (success, error_message)
        """
        try:
            response = requests.put(
                upload_url,
                data=content.encode('utf-8'),
                headers={'Content-Type': content_type},
                timeout=30
            )
            
            if response.status_code in [200, 201]:
                logger.info("Successfully uploaded feed content")
                return True, ""
            else:
                error_msg = f"Upload failed: {response.status_code} - {response.text}"
                logger.error(error_msg)
                return False, error_msg
                
        except Exception as e:
            error_msg = f"Upload exception: {str(e)}"
            logger.error(error_msg)
            return False, error_msg
    
    def create_feed(self, feed_document_id: str, feed_type: str = 'POST_INVENTORY_AVAILABILITY_DATA') -> Tuple[bool, Optional[str], str]:
        """
        Create a feed
        
        Args:
            feed_document_id: ID from create_feed_document
            feed_type: Type of feed
            
        Returns:
            Tuple of (success, feed_id, error_message)
        """
        json_data = {
            'feedType': feed_type,
            'marketplaceIds': [self.marketplace_id],
            'inputFeedDocumentId': feed_document_id
        }
        
        success, data, error = self._make_request(
            'POST',
            '/feeds/2021-06-30/feeds',
            json_data=json_data
        )
        
        if success and data:
            feed_id = data.get('feedId')
            return True, feed_id, ""
        else:
            return False, None, error
    
    def get_feed(self, feed_id: str) -> Tuple[bool, Optional[Dict], str]:
        """
        Get feed processing status
        
        Args:
            feed_id: Feed ID to check
            
        Returns:
            Tuple of (success, feed_data, error_message)
            feed_data contains: feedId, feedType, processingStatus, etc.
        """
        success, data, error = self._make_request(
            'GET',
            f'/feeds/2021-06-30/feeds/{feed_id}'
        )
        
        return success, data, error
    
    def update_inventory_quantity(self, sku: str, quantity: int, seller_id: str) -> Tuple[bool, str]:
        """
        Update inventory quantity for a SKU using feeds
        
        Args:
            sku: Seller SKU
            quantity: New quantity
            seller_id: Amazon seller ID
            
        Returns:
            Tuple of (success, message)
        """
        # Generate inventory feed XML
        xml_content = f"""<?xml version="1.0" encoding="utf-8"?>
<AmazonEnvelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="amzn-envelope.xsd">
    <Header>
        <DocumentVersion>1.01</DocumentVersion>
        <MerchantIdentifier>{seller_id}</MerchantIdentifier>
    </Header>
    <MessageType>Inventory</MessageType>
    <Message>
        <MessageID>1</MessageID>
        <Inventory>
            <SKU>{sku}</SKU>
            <Quantity>{quantity}</Quantity>
        </Inventory>
    </Message>
</AmazonEnvelope>"""
        
        logger.info(f"Generated inventory feed XML for SKU {sku}: {xml_content}")
        
        # Step 1: Create feed document
        success, doc_data, error = self.create_feed_document()
        if not success:
            return False, f"Failed to create feed document: {error}"
        
        feed_document_id = doc_data.get('feedDocumentId')
        upload_url = doc_data.get('url')
        
        logger.info(f"Created feed document: {feed_document_id}")
        
        # Step 2: Upload content
        success, error = self.upload_feed_content(upload_url, xml_content)
        if not success:
            return False, f"Failed to upload feed content: {error}"
        
        logger.info(f"Uploaded feed content to document {feed_document_id}")
        
        # Step 3: Create feed
        success, feed_id, error = self.create_feed(feed_document_id)
        if not success:
            return False, f"Failed to create feed: {error}"
        
        logger.info(f"Created feed: {feed_id}")
        
        return True, f"Successfully submitted inventory update feed {feed_id} for SKU {sku}"
    
    def update_quantity_listings_api(self, sku: str, quantity: int, seller_id: str) -> Tuple[bool, str]:
        """
        Update inventory quantity using Listings Items API (direct update, no feed needed)
        This bypasses feed submission and may work for Draft apps
        
        Args:
            sku: Seller SKU
            quantity: New quantity
            seller_id: Amazon seller ID
            
        Returns:
            Tuple of (success, message)
        """
        logger.info(f"Attempting Listings Items API update for SKU {sku}: quantity={quantity}")
        
        json_data = {
            "productType": "PRODUCT",
            "patches": [
                {
                    "op": "replace",
                    "path": "/attributes/fulfillment_availability",
                    "value": [
                        {
                            "fulfillment_channel_code": "DEFAULT",
                            "quantity": quantity
                        }
                    ]
                }
            ]
        }
        
        success, data, error = self._make_request(
            'PATCH',
            f'/listings/2021-08-01/items/{seller_id}/{sku}',
            params={'marketplaceIds': self.marketplace_id},
            json_data=json_data
        )
        
        if success and data:
            # Parse Amazon's response for status and issues
            status = data.get('status', 'UNKNOWN')
            submission_id = data.get('submissionId', '')
            issues = data.get('issues', [])
            
            # Check for any issues (even on 200 response, Amazon may report problems)
            if issues:
                error_issues = [i for i in issues if i.get('severity') == 'ERROR']
                warning_issues = [i for i in issues if i.get('severity') == 'WARNING']
                
                if error_issues:
                    error_msgs = [f"{i.get('code', 'UNKNOWN')}: {i.get('message', 'Unknown error')}" for i in error_issues]
                    logger.error(f"❌ Amazon rejected SKU {sku}: {error_msgs}")
                    return False, f"Amazon rejected update: {'; '.join(error_msgs)}"
                
                if warning_issues:
                    warning_msgs = [f"{i.get('code', 'UNKNOWN')}: {i.get('message', 'Unknown warning')}" for i in warning_issues]
                    logger.warning(f"⚠️ Amazon warnings for SKU {sku}: {warning_msgs}")
            
            if status == 'ACCEPTED':
                logger.info(f"✅ Amazon ACCEPTED SKU {sku} qty={quantity} (submissionId: {submission_id})")
                return True, f"ACCEPTED: qty={quantity} (submissionId: {submission_id})"
            elif status == 'INVALID':
                logger.error(f"❌ Amazon INVALID for SKU {sku}: {data}")
                return False, f"Amazon marked update as INVALID"
            else:
                logger.info(f"✅ Updated SKU {sku} via Listings API, status={status}")
                return True, f"Updated quantity for SKU {sku} to {quantity}, status={status}"
        elif success:
            logger.info(f"✅ Successfully updated SKU {sku} via Listings Items API")
            return True, f"Successfully updated quantity for SKU {sku} to {quantity}"
        else:
            logger.error(f"❌ Listings Items API failed for SKU {sku}: {error}")
            return False, f"Listings Items API update failed: {error}"
    
    def create_report(self, report_type: str = 'GET_MERCHANT_LISTINGS_ALL_DATA') -> Tuple[bool, Optional[str], str]:
        """
        Create a report to export all listings
        
        Args:
            report_type: Type of report (default: GET_MERCHANT_LISTINGS_ALL_DATA)
            
        Returns:
            Tuple of (success, report_id, error_message)
        """
        json_data = {
            'reportType': report_type,
            'marketplaceIds': [self.marketplace_id]
        }
        
        success, data, error = self._make_request(
            'POST',
            '/reports/2021-06-30/reports',
            json_data=json_data
        )
        
        if success and data:
            report_id = data.get('reportId')
            logger.info(f"Created report: {report_id} (type: {report_type})")
            return True, report_id, ""
        else:
            return False, None, error
    
    def get_report(self, report_id: str) -> Tuple[bool, Optional[Dict], str]:
        """
        Get report processing status
        
        Args:
            report_id: Report ID to check
            
        Returns:
            Tuple of (success, report_data, error_message)
            report_data contains: processingStatus, reportDocumentId, etc.
        """
        success, data, error = self._make_request(
            'GET',
            f'/reports/2021-06-30/reports/{report_id}'
        )
        
        return success, data, error
    
    def get_report_document(self, report_document_id: str) -> Tuple[bool, Optional[str], str]:
        """
        Download report document content
        
        Args:
            report_document_id: Report document ID from get_report response
            
        Returns:
            Tuple of (success, report_content, error_message)
        """
        # Step 1: Get document details
        success, data, error = self._make_request(
            'GET',
            f'/reports/2021-06-30/documents/{report_document_id}'
        )
        
        if not success:
            return False, None, f"Failed to get document details: {error}"
        
        download_url = data.get('url')
        if not download_url:
            return False, None, "No download URL in response"
        
        # Step 2: Download the document
        try:
            response = requests.get(download_url, timeout=60)
            
            if response.status_code == 200:
                logger.info(f"Downloaded report document: {len(response.text)} bytes")
                return True, response.text, ""
            else:
                error_msg = f"Download failed: {response.status_code}"
                logger.error(error_msg)
                return False, None, error_msg
                
        except Exception as e:
            error_msg = f"Download exception: {str(e)}"
            logger.error(error_msg)
            return False, None, error_msg
    
    def get_all_listings(self) -> Tuple[bool, List[Dict], str]:
        """
        Get all listings for this marketplace
        Uses Reports API to fetch GET_MERCHANT_LISTINGS_ALL_DATA
        
        Returns:
            Tuple of (success, listings_list, error_message)
            Each listing dict contains: sku, asin, price, quantity, etc.
        """
        import time
        import csv
        import io
        
        # Step 1: Request report
        logger.info("Requesting Amazon listings report...")
        success, report_id, error = self.create_report('GET_MERCHANT_LISTINGS_ALL_DATA')
        if not success:
            return False, [], f"Failed to create report: {error}"
        
        # Step 2: Wait for report to complete (poll every 5 seconds, max 2 minutes)
        max_attempts = 24
        for attempt in range(max_attempts):
            time.sleep(5)
            
            success, report_data, error = self.get_report(report_id)
            if not success:
                return False, [], f"Failed to check report status: {error}"
            
            status = report_data.get('processingStatus')
            logger.info(f"Report status: {status} (attempt {attempt + 1}/{max_attempts})")
            
            if status == 'DONE':
                report_document_id = report_data.get('reportDocumentId')
                if not report_document_id:
                    return False, [], "Report completed but no document ID"
                
                # Step 3: Download report
                success, content, error = self.get_report_document(report_document_id)
                if not success:
                    return False, [], f"Failed to download report: {error}"
                
                # Step 4: Parse TSV content
                try:
                    listings = []
                    reader = csv.DictReader(io.StringIO(content), delimiter='\t')
                    for row in reader:
                        listings.append({
                            'sku': row.get('seller-sku', ''),
                            'asin': row.get('asin1', ''),
                            'price': float(row.get('price', 0) or 0),
                            'quantity': int(row.get('quantity', 0) or 0),
                            'item_name': row.get('item-name', ''),
                            'item_description': row.get('item-description', ''),
                            'fulfillment_channel': row.get('fulfillment-channel', ''),
                            'status': row.get('status', ''),
                            'listing_id': row.get('listing-id', '')
                        })
                    
                    logger.info(f"Successfully parsed {len(listings)} listings from Amazon report")
                    return True, listings, ""
                    
                except Exception as e:
                    error_msg = f"Failed to parse report content: {str(e)}"
                    logger.error(error_msg)
                    return False, [], error_msg
            
            elif status in ['FATAL', 'CANCELLED']:
                return False, [], f"Report processing failed with status: {status}"
        
        return False, [], "Report processing timed out after 2 minutes"
    
    def validate_asin(self, asin: str) -> Tuple[bool, Optional[Dict], str]:
        """
        Validate ASIN exists in Amazon catalog
        Uses Catalog Items API to check if ASIN is valid
        
        Args:
            asin: Amazon Standard Identification Number (10 characters)
            
        Returns:
            Tuple of (valid, item_data, error_message)
            item_data contains: asin, title, productTypes, etc.
        """
        if not asin or len(asin) != 10:
            return False, None, f"Invalid ASIN format: {asin} (must be 10 characters)"
        
        logger.info(f"Validating ASIN: {asin}")
        
        success, data, error = self._make_request(
            'GET',
            f'/catalog/2022-04-01/items/{asin}',
            params={
                'marketplaceIds': self.marketplace_id,
                'includedData': 'summaries,attributes,identifiers'
            }
        )
        
        if success and data:
            summaries = data.get('summaries', [])
            if summaries:
                item_info = {
                    'asin': data.get('asin', asin),
                    'title': summaries[0].get('itemName', ''),
                    'product_type': summaries[0].get('productType', ''),
                    'brand': summaries[0].get('brand', ''),
                    'marketplace_id': summaries[0].get('marketplaceId', self.marketplace_id)
                }
                logger.info(f"✅ ASIN {asin} validated: {item_info['title'][:50]}...")
                return True, item_info, ""
            else:
                return True, {'asin': asin}, ""
        else:
            if '404' in str(error) or 'NOT_FOUND' in str(error):
                logger.warning(f"❌ ASIN {asin} not found in catalog")
                return False, None, f"ASIN {asin} not found in Amazon catalog"
            logger.error(f"Error validating ASIN {asin}: {error}")
            return False, None, error
    
    def get_listing_by_sku(self, sku: str, seller_id: str) -> Tuple[bool, Optional[Dict], str]:
        """
        Get listing details by seller SKU
        Uses Listings Items API to fetch listing info
        
        Args:
            sku: Seller SKU
            seller_id: Amazon seller ID
            
        Returns:
            Tuple of (success, listing_data, error_message)
        """
        logger.info(f"Fetching listing for SKU: {sku}")
        
        success, data, error = self._make_request(
            'GET',
            f'/listings/2021-08-01/items/{seller_id}/{sku}',
            params={
                'marketplaceIds': self.marketplace_id,
                'includedData': 'summaries,attributes,offers,fulfillmentAvailability'
            }
        )
        
        if success and data:
            listing_info = {
                'sku': data.get('sku', sku),
                'asin': data.get('summaries', [{}])[0].get('asin', ''),
                'title': data.get('summaries', [{}])[0].get('itemName', ''),
                'product_type': data.get('summaries', [{}])[0].get('productType', ''),
                'fulfillment_channel': data.get('fulfillmentAvailability', [{}])[0].get('fulfillmentChannelCode', 'DEFAULT'),
                'status': data.get('summaries', [{}])[0].get('status', [])
            }
            logger.info(f"✅ Found listing for SKU {sku}: ASIN={listing_info['asin']}")
            return True, listing_info, ""
        else:
            if '404' in str(error) or 'NOT_FOUND' in str(error):
                logger.warning(f"❌ SKU {sku} not found in listings")
                return False, None, f"SKU {sku} not found in Amazon listings"
            logger.error(f"Error fetching listing for SKU {sku}: {error}")
            return False, None, error
