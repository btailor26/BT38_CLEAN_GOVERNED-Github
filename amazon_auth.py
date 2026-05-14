"""
Amazon SP-API Authentication Module - Centralized Token Management

This module provides rock-solid Amazon OAuth token handling:
- Centralized ensure_access_token() for all SP-API operations
- In-memory token caching with automatic refresh
- Graceful error handling with clear AmazonAuthError exceptions
- Store auth status management (ok, auth_error, pending)

All Amazon API calls MUST go through ensure_access_token() - never handle tokens directly.
"""

import os
import json
import logging
import time
from datetime import datetime, timedelta
from threading import Lock
from typing import Dict, Optional, Tuple, Any

import requests

logger = logging.getLogger(__name__)

# ============================================================================
# EXCEPTIONS
# ============================================================================

class AmazonAuthError(Exception):
    """
    Exception raised when Amazon authentication fails.
    
    Attributes:
        error_code: Short error code (e.g., 'unauthorized_client', 'invalid_grant')
        message: Human-readable error message
        raw_response: Full raw response from Amazon (for debugging)
        is_retriable: Whether this error might succeed on retry
    """
    def __init__(self, error_code: str, message: str, raw_response: str = None, is_retriable: bool = False):
        self.error_code = error_code
        self.message = message
        self.raw_response = raw_response
        self.is_retriable = is_retriable
        super().__init__(f"[{error_code}] {message}")


class AmazonNonJsonResponseError(Exception):
    """
    Exception raised when Amazon returns HTML or non-JSON response.
    
    This typically indicates wrong endpoint or authentication redirect.
    
    Attributes:
        status_code: HTTP status code
        content_type: Response Content-Type header
        url: Request URL
        preview: First 200 chars of response body
    """
    def __init__(self, status_code: int, content_type: str, url: str, preview: str):
        self.status_code = status_code
        self.content_type = content_type
        self.url = url
        self.preview = preview
        super().__init__(f"AMAZON_NON_JSON_RESPONSE: status={status_code}, content_type={content_type}, url={url}")


# ============================================================================
# SAFE RESPONSE PARSING
# ============================================================================

def safe_parse_json(response, context: str = "Amazon API") -> dict:
    """
    Safely parse JSON from Amazon SP-API response with defensive validation.
    
    Checks Content-Type header before parsing and provides clear error messages
    when HTML or other non-JSON content is returned.
    
    Args:
        response: requests.Response object
        context: Description of the API call for logging
        
    Returns:
        Parsed JSON as dict
        
    Raises:
        AmazonNonJsonResponseError: If response is not JSON (e.g., HTML)
        json.JSONDecodeError: If JSON parsing fails despite correct Content-Type
    """
    content_type = response.headers.get('Content-Type', '')
    status_code = response.status_code
    url = response.url if hasattr(response, 'url') else 'unknown'
    
    # Log raw response info before parsing
    logger.debug(f"[AMAZON_RESPONSE] {context}: status={status_code}, content_type={content_type}, url={url}")
    
    # Check for HTML response (wrong endpoint or auth redirect)
    if 'text/html' in content_type or response.text.strip().startswith('<!DOCTYPE') or response.text.strip().startswith('<html'):
        preview = response.text[:200].replace('\n', ' ').strip()
        logger.error(f"[AMAZON_NON_JSON_RESPONSE] {context}: Received HTML instead of JSON. status={status_code}, content_type={content_type}, url={url}, preview={preview}")
        raise AmazonNonJsonResponseError(status_code, content_type, url, preview)
    
    # Check for non-JSON content types
    if content_type and 'application/json' not in content_type and 'application/x-amz-json' not in content_type:
        # Some Amazon responses don't have Content-Type but are still JSON - try parsing
        if response.text.strip().startswith('{') or response.text.strip().startswith('['):
            logger.warning(f"[AMAZON_RESPONSE] {context}: Unexpected content_type={content_type} but response looks like JSON, attempting parse")
        else:
            preview = response.text[:200].replace('\n', ' ').strip()
            logger.error(f"[AMAZON_NON_JSON_RESPONSE] {context}: Non-JSON content_type. status={status_code}, content_type={content_type}, url={url}, preview={preview}")
            raise AmazonNonJsonResponseError(status_code, content_type, url, preview)
    
    # Parse JSON
    try:
        return response.json()
    except json.JSONDecodeError as e:
        preview = response.text[:200].replace('\n', ' ').strip()
        logger.error(f"[AMAZON_JSON_PARSE_ERROR] {context}: JSON decode failed. status={status_code}, content_type={content_type}, error={str(e)}, preview={preview}")
        raise


# ============================================================================
# TOKEN CACHE
# ============================================================================

class TokenCache:
    """
    Thread-safe in-memory cache for Amazon access tokens.
    
    Tokens are cached per store_id with automatic expiry handling.
    """
    def __init__(self):
        self._cache: Dict[int, Dict[str, Any]] = {}
        self._lock = Lock()
        self._refresh_buffer_seconds = 60  # Refresh 60 seconds before expiry
    
    def get(self, store_id: int) -> Optional[str]:
        """Get cached access token if valid, None otherwise."""
        with self._lock:
            entry = self._cache.get(store_id)
            if not entry:
                return None
            
            # Check if token is still valid (with buffer)
            expires_at = entry.get('expires_at')
            if not expires_at or datetime.utcnow() >= expires_at:
                # Token expired, remove from cache
                del self._cache[store_id]
                logger.debug(f"Token expired for store {store_id}, removed from cache")
                return None
            
            return entry.get('access_token')
    
    def set(self, store_id: int, access_token: str, expires_in_seconds: int):
        """Cache an access token with expiry."""
        with self._lock:
            # Calculate expiry with buffer
            expires_at = datetime.utcnow() + timedelta(seconds=expires_in_seconds - self._refresh_buffer_seconds)
            
            self._cache[store_id] = {
                'access_token': access_token,
                'expires_at': expires_at,
                'cached_at': datetime.utcnow()
            }
            logger.debug(f"Token cached for store {store_id}, expires at {expires_at}")
    
    def invalidate(self, store_id: int):
        """Remove a token from cache (e.g., on auth failure)."""
        with self._lock:
            if store_id in self._cache:
                del self._cache[store_id]
                logger.debug(f"Token invalidated for store {store_id}")
    
    def clear_all(self):
        """Clear all cached tokens."""
        with self._lock:
            self._cache.clear()
            logger.info("All tokens cleared from cache")


# Global token cache instance
_token_cache = TokenCache()


# ============================================================================
# CREDENTIAL EXTRACTION
# ============================================================================

def extract_amazon_credentials(store) -> Dict[str, str]:
    """
    Extract Amazon credentials from a store's api_key JSON field.
    
    Args:
        store: Store model instance with api_key JSON field
        
    Returns:
        Dict with keys: refresh_token, lwa_app_id, lwa_client_secret, seller_id, 
                       marketplace_id, region, aws_access_key, aws_secret_key
                       
    Raises:
        AmazonAuthError: If credentials are missing or malformed
    """
    if not store or not store.api_key:
        raise AmazonAuthError(
            error_code='missing_credentials',
            message='Store has no API credentials configured'
        )
    
    try:
        creds = json.loads(store.api_key)
    except json.JSONDecodeError as e:
        raise AmazonAuthError(
            error_code='invalid_credentials',
            message=f'Store credentials are not valid JSON: {str(e)}'
        )
    
    # Extract required fields (check store-level first, then env vars as fallback)
    refresh_token = creds.get('refresh_token') or os.getenv('AMAZON_REFRESH_TOKEN')
    lwa_app_id = creds.get('lwa_app_id') or creds.get('client_id') or os.getenv('AMAZON_LWA_CLIENT_ID')
    lwa_client_secret = creds.get('lwa_client_secret') or creds.get('client_secret') or os.getenv('AMAZON_LWA_CLIENT_SECRET')
    seller_id = creds.get('seller_id') or os.getenv('AMAZON_SELLER_ID')
    
    # Region and marketplace
    marketplace_id = creds.get('marketplace_id', 'A1F83G8C2ARO7P')  # Default to UK
    region = creds.get('region', 'UK')
    
    # AWS credentials (optional for some operations)
    aws_access_key = creds.get('aws_access_key') or os.getenv('AWS_ACCESS_KEY_ID')
    aws_secret_key = creds.get('aws_secret_key') or os.getenv('AWS_SECRET_ACCESS_KEY')
    
    # Validate required fields
    missing = []
    if not refresh_token:
        missing.append('refresh_token')
    if not lwa_app_id:
        missing.append('lwa_app_id (or LWA Client ID)')
    if not lwa_client_secret:
        missing.append('lwa_client_secret (or LWA Client Secret)')
    
    if missing:
        raise AmazonAuthError(
            error_code='missing_credentials',
            message=f'Missing required credentials: {", ".join(missing)}'
        )
    
    return {
        'refresh_token': refresh_token,
        'lwa_app_id': lwa_app_id,
        'lwa_client_secret': lwa_client_secret,
        'seller_id': seller_id,
        'marketplace_id': marketplace_id,
        'region': region,
        'aws_access_key': aws_access_key,
        'aws_secret_key': aws_secret_key
    }


# ============================================================================
# TOKEN REFRESH
# ============================================================================

def _refresh_access_token(refresh_token: str, lwa_app_id: str, lwa_client_secret: str) -> Dict[str, Any]:
    """
    Call Amazon's LWA OAuth endpoint to refresh the access token.
    
    Args:
        refresh_token: Amazon refresh token
        lwa_app_id: LWA application client ID
        lwa_client_secret: LWA application client secret
        
    Returns:
        Dict with 'access_token' and 'expires_in' on success
        
    Raises:
        AmazonAuthError: On authentication failure
    """
    try:
        response = requests.post(
            'https://api.amazon.com/auth/o2/token',
            data={
                'grant_type': 'refresh_token',
                'refresh_token': refresh_token,
                'client_id': lwa_app_id,
                'client_secret': lwa_client_secret
            },
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
            timeout=30
        )
        
        if response.status_code == 200:
            data = response.json()
            access_token = data.get('access_token')
            expires_in = data.get('expires_in', 3600)  # Default 1 hour
            
            if not access_token:
                raise AmazonAuthError(
                    error_code='empty_token',
                    message='Amazon returned success but no access token',
                    raw_response=response.text
                )
            
            logger.info("Successfully refreshed Amazon access token")
            return {
                'access_token': access_token,
                'expires_in': expires_in
            }
        
        # Handle error response
        try:
            error_data = response.json()
            error_code = error_data.get('error', 'unknown_error')
            error_description = error_data.get('error_description', response.text)
        except:
            error_code = f'http_{response.status_code}'
            error_description = response.text
        
        # Map common error codes to user-friendly messages
        user_messages = {
            'unauthorized_client': 'Your Amazon SP-API app needs role approval. Check "Inventory and Order Management" and "Amazon Fulfillment" roles in Seller Central.',
            'invalid_grant': 'Your Amazon refresh token is invalid or expired. Re-authorize the app in Seller Central to generate a new token.',
            'invalid_client': 'The LWA Client ID or Client Secret is incorrect. Verify your app credentials in Seller Central.',
            'access_denied': 'Access denied by Amazon. Your app may have been revoked or not properly authorized.',
        }
        
        message = user_messages.get(error_code, f'Amazon authentication failed: {error_description}')
        
        # Determine if retriable (network issues vs. credential issues)
        is_retriable = response.status_code >= 500 or error_code in ['server_error', 'temporarily_unavailable']
        
        raise AmazonAuthError(
            error_code=error_code,
            message=message,
            raw_response=response.text,
            is_retriable=is_retriable
        )
        
    except requests.RequestException as e:
        # Network error - retriable
        raise AmazonAuthError(
            error_code='network_error',
            message=f'Network error connecting to Amazon: {str(e)}',
            is_retriable=True
        )


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

def ensure_access_token(store, force_refresh: bool = False) -> str:
    """
    Get a valid access token for Amazon SP-API calls.
    
    This is the SINGLE ENTRY POINT for all Amazon authentication.
    Every SP-API call MUST use this function.
    
    Process:
    1. Check in-memory cache for valid token
    2. If no valid token, refresh from Amazon OAuth
    3. Cache the new token
    4. Return the access token
    
    On auth failure:
    - Raises AmazonAuthError with clear error code and message
    - Does NOT retry in a loop (caller decides retry strategy)
    - Does NOT update store.auth_status (caller should do that)
    
    Args:
        store: Store model instance with api_key JSON credentials
        force_refresh: If True, skip cache and always refresh from Amazon
        
    Returns:
        Valid access token string
        
    Raises:
        AmazonAuthError: On any authentication failure
    """
    store_id = store.id if hasattr(store, 'id') else 0
    
    # Check cache first (unless force refresh)
    if not force_refresh:
        cached_token = _token_cache.get(store_id)
        if cached_token:
            logger.debug(f"Using cached token for store {store_id}")
            return cached_token
    
    # Extract credentials
    creds = extract_amazon_credentials(store)
    
    # Refresh token from Amazon
    logger.info(f"Refreshing access token for store {store_id} ({store.name if hasattr(store, 'name') else 'Unknown'})")
    
    try:
        result = _refresh_access_token(
            refresh_token=creds['refresh_token'],
            lwa_app_id=creds['lwa_app_id'],
            lwa_client_secret=creds['lwa_client_secret']
        )
        
        access_token = result['access_token']
        expires_in = result['expires_in']
        
        # Cache the token
        _token_cache.set(store_id, access_token, expires_in)
        
        return access_token
        
    except AmazonAuthError:
        # Invalidate any cached token on auth failure
        _token_cache.invalidate(store_id)
        raise


# ============================================================================
# STORE AUTH STATUS MANAGEMENT
# ============================================================================

def mark_store_auth_error(store, error: AmazonAuthError) -> None:
    """
    Mark a store as having an authentication error.
    
    This should be called when any Amazon operation fails due to auth issues.
    
    Args:
        store: Store model instance to update
        error: AmazonAuthError with error details
    """
    from app import db
    
    store.auth_status = 'auth_error'
    store.auth_error_code = error.error_code
    store.auth_error_message = error.message[:500] if error.message else None  # Truncate if too long
    store.auth_error_at = datetime.utcnow()
    
    db.session.commit()
    
    logger.warning(f"Store {store.id} ({store.name}) marked as auth_error: [{error.error_code}] {error.message}")
    
    # Invalidate cached token
    _token_cache.invalidate(store.id)
    
    # Log to System Activity
    try:
        from admin_logging import log_auth_error
        log_auth_error(
            store_id=store.id,
            error_code=error.error_code,
            error_message=error.message,
            provider='amazon'
        )
    except Exception as log_error:
        logger.error(f"Failed to log auth error to System Activity: {log_error}")


def clear_store_auth_error(store) -> None:
    """
    Clear authentication error status for a store.
    
    This should be called after successful reconnection.
    
    Args:
        store: Store model instance to update
    """
    from app import db
    
    store.auth_status = 'ok'
    store.auth_error_code = None
    store.auth_error_message = None
    store.auth_error_at = None
    
    db.session.commit()
    
    logger.info(f"Store {store.id} ({store.name}) auth_status cleared to 'ok'")


def is_store_auth_ok(store) -> bool:
    """
    Check if a store has valid authentication status.
    
    Returns False if store is in auth_error state.
    """
    if not store:
        return False
    return getattr(store, 'auth_status', 'ok') != 'auth_error'


def should_skip_amazon_sync(store) -> Tuple[bool, Optional[str]]:
    """
    Check if Amazon sync should be skipped for a store.
    
    Returns:
        Tuple of (should_skip: bool, reason: Optional[str])
    """
    if not store:
        return (True, "Store not found")
    
    if not store.is_active:
        return (True, "Store is inactive")
    
    if getattr(store, 'auth_status', 'ok') == 'auth_error':
        return (True, f"Auth error: {store.auth_error_code or 'unknown'}")
    
    return (False, None)


# ============================================================================
# AUTH FAILURE DETECTION HELPERS
# ============================================================================

def is_auth_failure(error_message: str = None, status_code: int = None, response_text: str = None) -> bool:
    """
    Detect if an error indicates an authentication failure.
    
    Used to determine if a store should be marked as auth_error.
    
    Returns True if the error appears to be an auth failure.
    """
    auth_status_codes = {400, 401, 403}
    auth_error_patterns = [
        'unauthorized_client',
        'invalid_grant',
        'invalid_client',
        'access_denied',
        'authentication_failed',
        'auth failed',
        'not authorized',
        'authorization failed',
        'token expired',
        'invalid token',
        'missing required roles'
    ]
    
    # Check status code
    if status_code in auth_status_codes:
        return True
    
    # Check error message
    if error_message:
        error_lower = error_message.lower()
        for pattern in auth_error_patterns:
            if pattern in error_lower:
                return True
    
    # Check response text
    if response_text:
        response_lower = response_text.lower()
        for pattern in auth_error_patterns:
            if pattern in response_lower:
                return True
    
    return False


def extract_auth_error_code(error_message: str = None, response_text: str = None) -> str:
    """
    Extract the auth error code from an error message or response.
    
    Returns a standardized error code.
    """
    patterns = {
        'unauthorized_client': 'unauthorized_client',
        'invalid_grant': 'invalid_grant',
        'invalid_client': 'invalid_client',
        'access_denied': 'access_denied',
        'token expired': 'token_expired',
        'missing required roles': 'missing_roles',
    }
    
    combined = f"{error_message or ''} {response_text or ''}".lower()
    
    for pattern, code in patterns.items():
        if pattern in combined:
            return code
    
    return 'auth_failed'
