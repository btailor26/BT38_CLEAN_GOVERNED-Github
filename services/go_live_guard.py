"""
Go-Live Guard - Central enforcement for marketplace write operations.

Rule:
  - If store cannot be resolved → BLOCK with "STORE_UNRESOLVED"
  - If store.store_mode != 'live' → BLOCK with "SAFE_MODE_BLOCKED"
  - Otherwise → ALLOW

Fail-safe: Any exception or uncertainty → BLOCK
"""

import logging
from typing import Tuple, Optional
from extensions import db
from models import Store


def guard_marketplace_write(store_id: Optional[int], context: str = "") -> Tuple[bool, str]:
    """
    Central guard for all marketplace write operations.
    
    Args:
        store_id: The store ID to check (can be None if unresolved)
        context: Description of the operation for logging
    
    Returns:
        Tuple[bool, str]: (allowed, block_reason)
        - allowed=True, block_reason="" if write is permitted
        - allowed=False, block_reason="..." if write is blocked
    """
    try:
        if store_id is None:
            reason = f"STORE_UNRESOLVED: store_id is None, context={context}"
            logging.warning(f"[GO_LIVE_GUARD] BLOCKED - {reason}")
            return (False, "STORE_UNRESOLVED")
        
        store = db.session.get(Store, store_id)
        
        if store is None:
            reason = f"STORE_UNRESOLVED: store_id={store_id} not found, context={context}"
            logging.warning(f"[GO_LIVE_GUARD] BLOCKED - {reason}")
            return (False, "STORE_UNRESOLVED")
        
        store_mode = getattr(store, 'store_mode', 'safe')
        
        if store_mode != 'live':
            reason = f"SAFE_MODE_BLOCKED: store_id={store_id}, store_mode={store_mode}, context={context}"
            logging.warning(f"[GO_LIVE_GUARD] BLOCKED - {reason}")
            return (False, "SAFE_MODE_BLOCKED")
        
        logging.debug(f"[GO_LIVE_GUARD] ALLOWED: store_id={store_id}, store_mode={store_mode}, context={context}")
        return (True, "")
        
    except Exception as e:
        reason = f"GUARD_EXCEPTION: store_id={store_id}, error={str(e)}, context={context}"
        logging.error(f"[GO_LIVE_GUARD] BLOCKED (fail-safe) - {reason}")
        return (False, "GUARD_EXCEPTION")


def guard_store_object(store: Optional[Store], context: str = "") -> Tuple[bool, str]:
    """
    Guard variant that accepts a Store object directly.
    
    Args:
        store: The Store object to check (can be None)
        context: Description of the operation for logging
    
    Returns:
        Tuple[bool, str]: (allowed, block_reason)
    """
    try:
        if store is None:
            reason = f"STORE_UNRESOLVED: store object is None, context={context}"
            logging.warning(f"[GO_LIVE_GUARD] BLOCKED - {reason}")
            return (False, "STORE_UNRESOLVED")
        
        store_mode = getattr(store, 'store_mode', 'safe')
        
        if store_mode != 'live':
            reason = f"SAFE_MODE_BLOCKED: store_id={store.id}, name={store.name}, store_mode={store_mode}, context={context}"
            logging.warning(f"[GO_LIVE_GUARD] BLOCKED - {reason}")
            return (False, "SAFE_MODE_BLOCKED")
        
        logging.debug(f"[GO_LIVE_GUARD] ALLOWED: store_id={store.id}, store_mode={store_mode}, context={context}")
        return (True, "")
        
    except Exception as e:
        store_id = getattr(store, 'id', 'unknown') if store else 'None'
        reason = f"GUARD_EXCEPTION: store_id={store_id}, error={str(e)}, context={context}"
        logging.error(f"[GO_LIVE_GUARD] BLOCKED (fail-safe) - {reason}")
        return (False, "GUARD_EXCEPTION")
