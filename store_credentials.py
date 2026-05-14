"""
Store Credential Accessor Layer

Provides a centralized, type-safe way to access marketplace credentials
stored as JSON in the Store.api_key field. This eliminates repeated JSON
parsing logic and provides a consistent interface for all services.

Usage:
    store = Store.query.get(1)
    ebay_creds = store.ebay_credentials  # Returns eBayCredentials object
    amazon_creds = store.amazon_credentials  # Returns AmazonCredentials object
    
    # Access credentials as attributes
    print(ebay_creds.user_token)
    print(amazon_creds.marketplace_id)
"""

import json
import logging
from dataclasses import dataclass
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


@dataclass
class eBayCredentials:
    """eBay Trading API credentials"""
    app_id: str
    dev_id: str
    cert_id: str
    user_token: str
    auth_token: str
    sandbox: bool
    site_id: str
    environment: str
    
    # Business policy IDs
    return_profile_id: Optional[str] = None
    payment_profile_id: Optional[str] = None
    shipping_profile_id: Optional[str] = None
    
    @classmethod
    def from_json(cls, api_key: Optional[str]) -> Optional['eBayCredentials']:
        """
        Parse eBay credentials from Store.api_key JSON
        
        Args:
            api_key: JSON string containing eBay credentials
            
        Returns:
            eBayCredentials object or None if parsing fails
        """
        if not api_key:
            logger.warning("No API key provided for eBay credentials")
            return None
        
        try:
            creds = json.loads(api_key)
            
            # Handle both 'user_token' and 'auth_token' naming
            user_token = creds.get('user_token') or creds.get('auth_token', '')
            
            return cls(
                app_id=creds.get('app_id', ''),
                dev_id=creds.get('dev_id', ''),
                cert_id=creds.get('cert_id', ''),
                user_token=user_token,
                auth_token=user_token,  # Alias
                sandbox=creds.get('sandbox', False),
                site_id=str(creds.get('site_id', '3')),  # Default to UK
                environment=creds.get('environment', 'production'),
                return_profile_id=creds.get('return_profile_id'),
                payment_profile_id=creds.get('payment_profile_id'),
                shipping_profile_id=creds.get('shipping_profile_id')
            )
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse eBay credentials JSON: {e}")
            return None
        except Exception as e:
            logger.error(f"Error creating eBay credentials: {e}")
            return None
    
    def is_valid(self) -> bool:
        """Check if all required credentials are present"""
        return bool(
            self.app_id and
            self.dev_id and
            self.cert_id and
            self.user_token
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary (for redacted logging)"""
        return {
            'app_id': self.app_id[:10] + '...' if self.app_id else '',
            'dev_id': 'present' if self.dev_id else 'missing',
            'cert_id': 'present' if self.cert_id else 'missing',
            'user_token': 'present' if self.user_token else 'missing',
            'sandbox': self.sandbox,
            'site_id': self.site_id,
            'environment': self.environment,
            'is_valid': self.is_valid()
        }


@dataclass
class AmazonCredentials:
    """
    Amazon SP-API credentials
    
    Supports two modes:
    1. LWA-only (for published apps) - requires only LWA fields
    2. AWS + LWA (for draft apps) - requires AWS IAM fields too
    """
    refresh_token: str
    lwa_app_id: str
    lwa_client_secret: str
    seller_id: str
    marketplace_id: str
    # AWS IAM User credentials (for Draft apps only - temporary until app published)
    aws_access_key_id: Optional[str] = None
    aws_secret_access_key: Optional[str] = None
    aws_user_arn: Optional[str] = None  # IAM User ARN (not Role ARN) - for reference only
    
    @classmethod
    def from_json(cls, api_key: Optional[str]) -> Optional['AmazonCredentials']:
        """
        Parse Amazon credentials from Store.api_key JSON
        
        Args:
            api_key: JSON string containing Amazon credentials
            
        Returns:
            AmazonCredentials object or None if parsing fails
        """
        if not api_key:
            logger.warning("No API key provided for Amazon credentials")
            return None
        
        try:
            creds = json.loads(api_key)
            
            return cls(
                refresh_token=creds.get('refresh_token', ''),
                lwa_app_id=creds.get('lwa_app_id', ''),
                lwa_client_secret=creds.get('lwa_client_secret', ''),
                seller_id=creds.get('seller_id', ''),
                marketplace_id=creds.get('marketplace_id', 'A1F83G8C2ARO7P'),
                aws_access_key_id=creds.get('aws_access_key_id'),
                aws_secret_access_key=creds.get('aws_secret_access_key'),
                aws_user_arn=creds.get('aws_user_arn') or creds.get('role_arn')  # Backward compat
            )
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Amazon credentials JSON: {e}")
            return None
        except Exception as e:
            logger.error(f"Error creating Amazon credentials: {e}")
            return None
    
    def has_aws_credentials(self) -> bool:
        """Check if AWS credentials are configured"""
        return bool(self.aws_access_key_id and self.aws_secret_access_key)
    
    def is_valid(self) -> bool:
        """Check if all required LWA credentials are present"""
        return bool(
            self.refresh_token and
            self.lwa_app_id and
            self.lwa_client_secret and
            self.seller_id and
            self.marketplace_id
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary (for redacted logging)"""
        result = {
            'refresh_token': 'present' if self.refresh_token else 'missing',
            'lwa_app_id': self.lwa_app_id[:10] + '...' if self.lwa_app_id else '',
            'lwa_client_secret': 'present' if self.lwa_client_secret else 'missing',
            'seller_id': self.seller_id if self.seller_id else '',
            'marketplace_id': self.marketplace_id,
            'is_valid': self.is_valid()
        }
        
        if self.has_aws_credentials():
            result['aws_mode'] = 'IAM User (Draft app - temporary)'
            result['aws_access_key'] = self.aws_access_key_id[:8] + '...' if self.aws_access_key_id else ''
            result['aws_user_arn'] = self.aws_user_arn if self.aws_user_arn else 'N/A'
        else:
            result['aws_mode'] = 'LWA-only (Published app - no AWS charges!)'
            
        return result


def add_credential_accessors_to_store(store_class):
    """
    Add credential accessor properties to the Store ORM model
    
    This is called during model initialization to add the accessor properties
    to the Store class. It's designed to be non-invasive and work with existing code.
    
    Args:
        store_class: The Store ORM model class
    """
    
    @property
    def ebay_credentials(self) -> Optional[eBayCredentials]:
        """Get parsed eBay credentials from api_key JSON field"""
        if not hasattr(self, '_ebay_creds_cache'):
            self._ebay_creds_cache = eBayCredentials.from_json(self.api_key)
        return self._ebay_creds_cache
    
    @property
    def amazon_credentials(self) -> Optional[AmazonCredentials]:
        """Get parsed Amazon credentials from api_key JSON field"""
        if not hasattr(self, '_amazon_creds_cache'):
            self._amazon_creds_cache = AmazonCredentials.from_json(self.api_key)
        return self._amazon_creds_cache
    
    # Add properties to the Store class
    store_class.ebay_credentials = ebay_credentials
    store_class.amazon_credentials = amazon_credentials
    
    logger.info("Credential accessor properties added to Store model")
