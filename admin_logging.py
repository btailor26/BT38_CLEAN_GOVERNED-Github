"""
Admin Reporting System - Logging Helpers
Provides automatic logging for config changes, sync jobs, API errors, and agent runs.

Usage:
    from admin_logging import log_config_change, log_api_error, log_sync_job, log_agent_run

All functions handle their own db session commits and are safe to call from anywhere.
"""

import logging
import json
import re
from datetime import datetime
from typing import Optional, Dict, Any
from flask_login import current_user

logger = logging.getLogger(__name__)


def _mask_sensitive_data(data: Any) -> Any:
    """Recursively mask sensitive fields in data"""
    if isinstance(data, dict):
        masked = {}
        sensitive_keys = {
            'password', 'secret', 'token', 'key', 'credential', 'auth',
            'refresh_token', 'access_token', 'api_key', 'client_secret',
            'lwa_client_secret', 'aws_secret_access_key'
        }
        for k, v in data.items():
            k_lower = k.lower()
            if any(s in k_lower for s in sensitive_keys):
                if isinstance(v, str) and len(v) > 8:
                    masked[k] = v[:4] + '****' + v[-4:]
                else:
                    masked[k] = '****'
            else:
                masked[k] = _mask_sensitive_data(v)
        return masked
    elif isinstance(data, list):
        return [_mask_sensitive_data(item) for item in data]
    elif isinstance(data, str):
        if len(data) > 100:
            return data[:100] + '...[truncated]'
        return data
    else:
        return data


def _get_actor_info():
    """Get current actor information"""
    try:
        if current_user and current_user.is_authenticated:
            return 'user', current_user.id
    except:
        pass
    return 'system', None


def log_config_change(
    entity_type: str,
    entity_id: Optional[int],
    summary: str,
    before_state: Optional[Dict] = None,
    after_state: Optional[Dict] = None,
    actor_type: str = None,
    actor_id: int = None
):
    """
    Log a configuration change with before/after snapshots.
    
    Args:
        entity_type: Type of entity changed ('store', 'push_settings', 'warehouse', etc.)
        entity_id: ID of the entity (if applicable)
        summary: Short description of the change
        before_state: State before the change (will be masked)
        after_state: State after the change (will be masked)
        actor_type: 'user', 'agent', or 'system' (auto-detected if not provided)
        actor_id: User ID if actor_type is 'user'
    """
    try:
        from extensions import db
        from models import ConfigChangeLog
        
        if actor_type is None:
            actor_type, actor_id = _get_actor_info()
        
        log_entry = ConfigChangeLog(
            changed_at=datetime.utcnow(),
            actor_type=actor_type,
            actor_id=actor_id,
            entity_type=entity_type,
            entity_id=entity_id,
            summary=summary[:500] if summary else 'Configuration changed',
            before_json=_mask_sensitive_data(before_state) if before_state else None,
            after_json=_mask_sensitive_data(after_state) if after_state else None
        )
        
        db.session.add(log_entry)
        db.session.commit()
        
        logger.info(f"[CONFIG_CHANGE] {entity_type}:{entity_id} - {summary}")
        return log_entry.id
        
    except Exception as e:
        logger.error(f"Failed to log config change: {str(e)}")
        return None


def log_api_error(
    provider: str,
    endpoint: str = None,
    http_status: int = None,
    error_code: str = None,
    message: str = None,
    raw_payload: Any = None,
    store_id: int = None
):
    """
    Log an API error from external services.
    
    Args:
        provider: 'amazon' or 'ebay'
        endpoint: API endpoint that was called
        http_status: HTTP status code
        error_code: Provider-specific error code
        message: Error message
        raw_payload: Raw error response (will be masked and truncated)
        store_id: Store ID if applicable
    """
    try:
        from extensions import db
        from models import APIErrorLog
        
        masked_payload = None
        if raw_payload:
            if isinstance(raw_payload, str):
                masked_payload = raw_payload[:2000] if len(raw_payload) > 2000 else raw_payload
            else:
                try:
                    masked_data = _mask_sensitive_data(raw_payload)
                    masked_payload = json.dumps(masked_data)[:2000]
                except:
                    masked_payload = str(raw_payload)[:2000]
        
        log_entry = APIErrorLog(
            created_at=datetime.utcnow(),
            store_id=store_id,
            provider=provider,
            endpoint=endpoint,
            http_status=http_status,
            error_code=error_code,
            message=message[:5000] if message else None,
            raw_payload=masked_payload
        )
        
        db.session.add(log_entry)
        db.session.commit()
        
        logger.warning(f"[API_ERROR] {provider} {endpoint}: {error_code} - {message}")
        return log_entry.id
        
    except Exception as e:
        logger.error(f"Failed to log API error: {str(e)}")
        return None


def log_auth_error(
    store_id: int,
    error_code: str,
    error_message: str,
    provider: str = 'amazon'
):
    """
    Log an authentication error for a store.
    
    This creates both an API error log entry and a sync log entry
    to ensure auth failures are visible in System Activity.
    
    Args:
        store_id: The store that failed authentication
        error_code: Short error code (e.g., 'unauthorized_client')
        error_message: Detailed error message
        provider: 'amazon' or 'ebay'
    """
    try:
        # Log as API error
        log_api_error(
            provider=provider,
            endpoint='oauth/token',
            http_status=401,
            error_code=error_code,
            message=f"Authentication failed: {error_message}",
            store_id=store_id
        )
        
        # Also log as a sync job that failed immediately
        from extensions import db
        from models import SyncLog
        
        sync_log = SyncLog(
            store_id=store_id,
            log_type='auth_error',
            status='error',
            message=f"Authentication failed: [{error_code}] {error_message}"[:500],
            items_imported=0,
            items_pushed=0,
            created_at=datetime.utcnow()
        )
        db.session.add(sync_log)
        db.session.commit()
        
        logger.warning(f"[AUTH_ERROR] {provider} store {store_id}: [{error_code}] {error_message}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to log auth error: {str(e)}")
        return False


class SyncJobLogger:
    """Context manager for sync job logging"""
    
    def __init__(self, store_id: int, job_type: str, message: str = None, triggered_by: str = None):
        self.store_id = store_id
        self.job_type = job_type
        self.message = message
        self.triggered_by = triggered_by or 'system'
        self.log_entry = None
        self.start_time = None
        self.items_imported = 0
        self.items_pushed = 0
        self.items_failed = 0
        self.error_details = []
        
    def __enter__(self):
        try:
            from extensions import db
            from models import SyncJobLog
            
            self.start_time = datetime.utcnow()
            
            self.log_entry = SyncJobLog(
                store_id=self.store_id,
                job_type=self.job_type,
                status='started',
                message=self.message or f'Starting {self.job_type}',
                started_at=self.start_time
            )
            
            db.session.add(self.log_entry)
            db.session.commit()
            
            logger.info(f"[SYNC_JOB_START] {self.job_type} for store {self.store_id}")
            
        except Exception as e:
            logger.error(f"Failed to start sync job log: {str(e)}")
            
        return self
    
    def update(self, imported: int = 0, pushed: int = 0, failed: int = 0, error: str = None):
        """Update job progress"""
        self.items_imported += imported
        self.items_pushed += pushed
        self.items_failed += failed
        if error:
            self.error_details.append(error)
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            from extensions import db
            
            if self.log_entry:
                end_time = datetime.utcnow()
                
                self.log_entry.finished_at = end_time
                self.log_entry.duration_seconds = (end_time - self.start_time).total_seconds()
                self.log_entry.items_imported = self.items_imported
                self.log_entry.items_pushed = self.items_pushed
                self.log_entry.items_failed = self.items_failed
                
                if exc_type:
                    self.log_entry.status = 'failed'
                    self.log_entry.message = str(exc_val)[:5000]
                    self.error_details.append(str(exc_val))
                elif self.items_failed > 0:
                    self.log_entry.status = 'partial'
                    self.log_entry.message = f'Completed with {self.items_failed} failures'
                else:
                    self.log_entry.status = 'completed'
                    self.log_entry.message = f'Imported {self.items_imported}, pushed {self.items_pushed}'
                
                if self.error_details:
                    self.log_entry.error_details = self.error_details[:50]
                
                db.session.commit()
                
                logger.info(f"[SYNC_JOB_END] {self.job_type} store {self.store_id}: {self.log_entry.status}")
                
        except Exception as e:
            logger.error(f"Failed to complete sync job log: {str(e)}")
        
        return False


def log_sync_job_start(store_id: int, job_type: str, message: str = None) -> Optional[int]:
    """Start a sync job log entry and return its ID"""
    try:
        from extensions import db
        from models import SyncJobLog
        
        log_entry = SyncJobLog(
            store_id=store_id,
            job_type=job_type,
            status='started',
            message=message or f'Starting {job_type}',
            started_at=datetime.utcnow()
        )
        
        db.session.add(log_entry)
        db.session.commit()
        
        return log_entry.id
        
    except Exception as e:
        logger.error(f"Failed to start sync job log: {str(e)}")
        return None


def log_sync_job_complete(
    job_id: int,
    status: str = 'completed',
    items_imported: int = 0,
    items_pushed: int = 0,
    items_failed: int = 0,
    message: str = None,
    error_details: list = None
):
    """Complete a sync job log entry"""
    try:
        from extensions import db
        from models import SyncJobLog
        
        log_entry = db.session.get(SyncJobLog, job_id)
        if log_entry:
            log_entry.finished_at = datetime.utcnow()
            log_entry.status = status
            log_entry.items_imported = items_imported
            log_entry.items_pushed = items_pushed
            log_entry.items_failed = items_failed
            log_entry.message = message
            log_entry.error_details = error_details
            
            if log_entry.started_at:
                log_entry.duration_seconds = (log_entry.finished_at - log_entry.started_at).total_seconds()
            
            db.session.commit()
            
    except Exception as e:
        logger.error(f"Failed to complete sync job log: {str(e)}")


def log_agent_run_start(agent_name: str, scope: str = None) -> Optional[int]:
    """Start an agent run log entry"""
    try:
        from extensions import db
        from models import AgentRunLog
        
        log_entry = AgentRunLog(
            started_at=datetime.utcnow(),
            agent_name=agent_name,
            scope=scope,
            status='running'
        )
        
        db.session.add(log_entry)
        db.session.commit()
        
        return log_entry.id
        
    except Exception as e:
        logger.error(f"Failed to start agent run log: {str(e)}")
        return None


def log_agent_run_complete(
    run_id: int,
    status: str = 'success',
    summary: str = None,
    details: Dict = None
):
    """Complete an agent run log entry"""
    try:
        from extensions import db
        from models import AgentRunLog
        
        log_entry = db.session.get(AgentRunLog, run_id)
        if log_entry:
            log_entry.finished_at = datetime.utcnow()
            log_entry.status = status
            log_entry.summary = summary
            log_entry.details_json = details
            
            db.session.commit()
            
    except Exception as e:
        logger.error(f"Failed to complete agent run log: {str(e)}")


def backfill_from_sync_logs():
    """Backfill SyncJobLog from existing sync_logs table"""
    try:
        from extensions import db
        from models import SyncLog, SyncJobLog
        
        existing_count = SyncJobLog.query.count()
        if existing_count > 0:
            logger.info(f"SyncJobLog already has {existing_count} entries, skipping backfill")
            return 0
        
        sync_logs = SyncLog.query.order_by(SyncLog.created_at.asc()).all()
        
        backfilled = 0
        for log in sync_logs:
            job_log = SyncJobLog(
                store_id=log.store_id,
                job_type='legacy_sync',
                status=log.status,
                items_pushed=log.items_synced or 0,
                message=log.message,
                started_at=log.created_at,
                finished_at=log.created_at
            )
            db.session.add(job_log)
            backfilled += 1
        
        db.session.commit()
        logger.info(f"Backfilled {backfilled} entries from sync_logs to sync_job_log")
        return backfilled
        
    except Exception as e:
        logger.error(f"Failed to backfill from sync_logs: {str(e)}")
        return 0


def backfill_from_system_logs():
    """Backfill APIErrorLog from existing system_logs table (error types)"""
    try:
        from extensions import db
        from models import SystemLog, APIErrorLog
        
        existing_count = APIErrorLog.query.count()
        if existing_count > 0:
            logger.info(f"APIErrorLog already has {existing_count} entries, skipping backfill")
            return 0
        
        error_logs = SystemLog.query.filter(
            SystemLog.log_type.in_(['route_failure', 'api_error', 'amazon_error', 'ebay_error'])
        ).order_by(SystemLog.created_at.asc()).all()
        
        backfilled = 0
        for log in error_logs:
            provider = 'unknown'
            if 'amazon' in log.message.lower():
                provider = 'amazon'
            elif 'ebay' in log.message.lower():
                provider = 'ebay'
            
            error_log = APIErrorLog(
                created_at=log.created_at,
                provider=provider,
                error_code=log.log_type,
                message=log.message,
                raw_payload=log.details
            )
            db.session.add(error_log)
            backfilled += 1
        
        db.session.commit()
        logger.info(f"Backfilled {backfilled} entries from system_logs to api_error_log")
        return backfilled
        
    except Exception as e:
        logger.error(f"Failed to backfill from system_logs: {str(e)}")
        return 0


# ============================================================================
# SYSTEM EVENT EMITTERS - Unified Event Logging
# ============================================================================

def emit_system_event(
    category: str,
    description: str,
    actor: str = 'system',
    actor_id: int = None,
    entity_type: str = None,
    entity_id: int = None,
    details: Dict = None
) -> Optional[int]:
    """
    Emit a system event to the unified system_events table.
    
    Categories: sync_job, api_error, config_change, agent_run, auth_failure, 
                queue_event, store_update, fba_import, fbm_push
    Actors: user, admin, agent, system, scheduler
    """
    try:
        from extensions import db
        from models import SystemEvent
        
        if actor_id is None:
            detected_actor, detected_id = _get_actor_info()
            if actor == 'system':
                actor = detected_actor
            if detected_id:
                actor_id = detected_id
        
        event = SystemEvent(
            timestamp=datetime.utcnow(),
            actor=actor,
            actor_id=actor_id,
            category=category,
            entity_type=entity_type,
            entity_id=entity_id,
            description=description[:2000] if description else 'Event logged',
            details_json=_mask_sensitive_data(details) if details else None
        )
        
        db.session.add(event)
        db.session.commit()
        
        logger.info(f"[SYSTEM_EVENT] {category}: {description[:100]}")
        return event.id
        
    except Exception as e:
        logger.error(f"Failed to emit system event: {str(e)}")
        return None


def emit_sync_started(store_id: int, job_type: str, store_name: str = None):
    """Emit sync job started event"""
    return emit_system_event(
        category='sync_job',
        description=f'Sync started: {job_type} for store {store_name or store_id}',
        actor='scheduler',
        entity_type='store',
        entity_id=store_id,
        details={'job_type': job_type, 'store_id': store_id, 'status': 'started'}
    )


def emit_sync_completed(store_id: int, job_type: str, imported: int = 0, pushed: int = 0, 
                        failed: int = 0, store_name: str = None):
    """Emit sync job completed event"""
    return emit_system_event(
        category='sync_job',
        description=f'Sync completed: {job_type} for store {store_name or store_id} - imported={imported}, pushed={pushed}, failed={failed}',
        actor='scheduler',
        entity_type='store',
        entity_id=store_id,
        details={
            'job_type': job_type, 
            'store_id': store_id, 
            'status': 'completed',
            'items_imported': imported,
            'items_pushed': pushed,
            'items_failed': failed
        }
    )


def emit_sync_failed(store_id: int, job_type: str, error: str, store_name: str = None):
    """Emit sync job failed event"""
    return emit_system_event(
        category='sync_job',
        description=f'Sync failed: {job_type} for store {store_name or store_id} - {error[:200]}',
        actor='scheduler',
        entity_type='store',
        entity_id=store_id,
        details={'job_type': job_type, 'store_id': store_id, 'status': 'failed', 'error': error}
    )


def emit_auth_success(store_id: int, provider: str, store_name: str = None, scopes: list = None):
    """Emit authentication success event"""
    return emit_system_event(
        category='auth_success',
        description=f'Auth success: {provider} for store {store_name or store_id}',
        actor='system',
        entity_type='store',
        entity_id=store_id,
        details={'provider': provider, 'store_id': store_id, 'scopes': scopes}
    )


def emit_auth_failure(store_id: int, provider: str, error: str, endpoint: str = None, store_name: str = None):
    """Emit authentication failure event"""
    return emit_system_event(
        category='auth_failure',
        description=f'Auth failure: {provider} for store {store_name or store_id} - {error[:200]}',
        actor='system',
        entity_type='store',
        entity_id=store_id,
        details={
            'provider': provider, 
            'store_id': store_id, 
            'error': error,
            'endpoint': endpoint
        }
    )


def emit_fba_import_started(store_id: int, store_name: str = None):
    """Emit FBA inventory import started event"""
    return emit_system_event(
        category='fba_import',
        description=f'FBA import started for store {store_name or store_id}',
        actor='scheduler',
        entity_type='store',
        entity_id=store_id,
        details={'store_id': store_id, 'status': 'started'}
    )


def emit_fba_import_completed(store_id: int, skus_imported: int, store_name: str = None):
    """Emit FBA inventory import completed event"""
    return emit_system_event(
        category='fba_import',
        description=f'FBA import completed for store {store_name or store_id}: {skus_imported} SKUs imported',
        actor='scheduler',
        entity_type='store',
        entity_id=store_id,
        details={'store_id': store_id, 'status': 'completed', 'skus_imported': skus_imported}
    )


def emit_fba_import_failed(store_id: int, error: str, store_name: str = None):
    """Emit FBA inventory import failed event"""
    return emit_system_event(
        category='fba_import',
        description=f'FBA import failed for store {store_name or store_id}: {error[:200]}',
        actor='scheduler',
        entity_type='store',
        entity_id=store_id,
        details={'store_id': store_id, 'status': 'failed', 'error': error}
    )


def emit_fbm_push_started(store_id: int, store_name: str = None, sku_count: int = 0):
    """Emit FBM push started event"""
    return emit_system_event(
        category='fbm_push',
        description=f'FBM push started for store {store_name or store_id}: {sku_count} SKUs queued',
        actor='scheduler',
        entity_type='store',
        entity_id=store_id,
        details={'store_id': store_id, 'status': 'started', 'sku_count': sku_count}
    )


def emit_fbm_push_completed(store_id: int, pushed: int, skipped: int, failed: int, store_name: str = None):
    """Emit FBM push completed event"""
    return emit_system_event(
        category='fbm_push',
        description=f'FBM push completed for store {store_name or store_id}: pushed={pushed}, skipped={skipped}, failed={failed}',
        actor='scheduler',
        entity_type='store',
        entity_id=store_id,
        details={
            'store_id': store_id, 
            'status': 'completed',
            'pushed': pushed,
            'skipped': skipped,
            'failed': failed
        }
    )


def emit_fbm_push_failed(store_id: int, error: str, store_name: str = None):
    """Emit FBM push failed event"""
    return emit_system_event(
        category='fbm_push',
        description=f'FBM push failed for store {store_name or store_id}: {error[:200]}',
        actor='scheduler',
        entity_type='store',
        entity_id=store_id,
        details={'store_id': store_id, 'status': 'failed', 'error': error}
    )


def emit_api_error_event(provider: str, endpoint: str, error_code: str, message: str, 
                         store_id: int = None, http_status: int = None):
    """Emit API error event"""
    return emit_system_event(
        category='api_error',
        description=f'API Error: {provider} {endpoint} - {error_code}: {message[:200]}',
        actor='system',
        entity_type='store' if store_id else None,
        entity_id=store_id,
        details={
            'provider': provider,
            'endpoint': endpoint,
            'error_code': error_code,
            'http_status': http_status,
            'message': message
        }
    )


def emit_store_update(store_id: int, action: str, changes: Dict = None, store_name: str = None):
    """Emit store update event"""
    return emit_system_event(
        category='store_update',
        description=f'Store updated: {store_name or store_id} - {action}',
        entity_type='store',
        entity_id=store_id,
        details={'store_id': store_id, 'action': action, 'changes': changes}
    )


def emit_config_change_event(entity_type: str, entity_id: int, summary: str, 
                              before: Dict = None, after: Dict = None):
    """Emit configuration change event"""
    return emit_system_event(
        category='config_change',
        description=f'Config changed: {entity_type}:{entity_id} - {summary[:200]}',
        entity_type=entity_type,
        entity_id=entity_id,
        details={'summary': summary, 'before': before, 'after': after}
    )


def emit_agent_run_event(agent_name: str, scope: str, status: str, summary: str = None, 
                         files_changed: list = None):
    """Emit agent execution event"""
    return emit_system_event(
        category='agent_run',
        description=f'Agent run: {agent_name} ({status}) - {scope[:100] if scope else "general"}',
        actor='agent',
        details={
            'agent_name': agent_name,
            'scope': scope,
            'status': status,
            'summary': summary,
            'files_changed': files_changed
        }
    )


def emit_queue_event(queue_name: str, action: str, job_count: int = 0, details: Dict = None):
    """Emit queue event"""
    return emit_system_event(
        category='queue_event',
        description=f'Queue event: {queue_name} - {action} ({job_count} jobs)',
        actor='scheduler',
        details={'queue_name': queue_name, 'action': action, 'job_count': job_count, **(details or {})}
    )


# ============================================================================
# COMPREHENSIVE BACKFILL - Populate SystemEvent from all existing tables
# ============================================================================

def run_comprehensive_backfill():
    """
    Run comprehensive backfill to populate SystemEvent table from all existing data sources.
    This should run once automatically on system restart.
    """
    try:
        from extensions import db
        from models import SystemEvent
        
        existing_count = SystemEvent.query.count()
        if existing_count > 100:
            logger.info(f"SystemEvent already has {existing_count} entries, skipping backfill")
            return {'skipped': True, 'existing_count': existing_count}
        
        total_backfilled = 0
        results = {}
        
        # 1. Backfill from SyncLog
        sync_count = _backfill_sync_logs_to_events()
        results['sync_logs'] = sync_count
        total_backfilled += sync_count
        
        # 2. Backfill from SystemLog (errors, route failures)
        system_count = _backfill_system_logs_to_events()
        results['system_logs'] = system_count
        total_backfilled += system_count
        
        # 3. Backfill from SyncJobLog
        job_count = _backfill_sync_job_logs_to_events()
        results['sync_job_logs'] = job_count
        total_backfilled += job_count
        
        # 4. Backfill from APIErrorLog
        api_count = _backfill_api_error_logs_to_events()
        results['api_error_logs'] = api_count
        total_backfilled += api_count
        
        # 5. Backfill from ConfigChangeLog
        config_count = _backfill_config_change_logs_to_events()
        results['config_change_logs'] = config_count
        total_backfilled += config_count
        
        # 6. Backfill from AgentRunLog
        agent_count = _backfill_agent_run_logs_to_events()
        results['agent_run_logs'] = agent_count
        total_backfilled += agent_count
        
        results['total'] = total_backfilled
        logger.info(f"Comprehensive backfill completed: {total_backfilled} events created")
        
        return results
        
    except Exception as e:
        logger.error(f"Comprehensive backfill failed: {str(e)}")
        return {'error': str(e)}


def _backfill_sync_logs_to_events() -> int:
    """Backfill from sync_logs table"""
    try:
        from extensions import db
        from models import SyncLog, SystemEvent, Store
        
        sync_logs = SyncLog.query.order_by(SyncLog.created_at.asc()).limit(5000).all()
        
        backfilled = 0
        for log in sync_logs:
            store_name = None
            if log.store:
                store_name = log.store.name
            
            category = 'sync_job'
            if log.status == 'failed' or log.status == 'error':
                category = 'sync_job'
            
            event = SystemEvent(
                timestamp=log.created_at,
                actor='scheduler',
                category=category,
                entity_type='store',
                entity_id=log.store_id,
                description=f'Legacy sync: {log.status} - {log.message[:200] if log.message else "No message"}',
                details_json={
                    'source': 'sync_logs',
                    'original_id': log.id,
                    'status': log.status,
                    'items_synced': log.items_synced,
                    'direction': log.direction
                }
            )
            db.session.add(event)
            backfilled += 1
        
        db.session.commit()
        logger.info(f"Backfilled {backfilled} events from sync_logs")
        return backfilled
        
    except Exception as e:
        logger.error(f"Failed to backfill sync_logs: {str(e)}")
        db.session.rollback()
        return 0


def _backfill_system_logs_to_events() -> int:
    """Backfill from system_logs table"""
    try:
        from extensions import db
        from models import SystemLog, SystemEvent
        
        system_logs = SystemLog.query.order_by(SystemLog.created_at.asc()).limit(2000).all()
        
        backfilled = 0
        for log in system_logs:
            category = 'api_error'
            if 'auth' in log.log_type.lower():
                category = 'auth_failure'
            elif 'route' in log.log_type.lower():
                category = 'api_error'
            
            event = SystemEvent(
                timestamp=log.created_at,
                actor='system',
                category=category,
                description=f'{log.log_type}: {log.message[:300] if log.message else "No message"}',
                details_json={
                    'source': 'system_logs',
                    'original_id': log.id,
                    'log_type': log.log_type,
                    'details': log.details
                }
            )
            db.session.add(event)
            backfilled += 1
        
        db.session.commit()
        logger.info(f"Backfilled {backfilled} events from system_logs")
        return backfilled
        
    except Exception as e:
        logger.error(f"Failed to backfill system_logs: {str(e)}")
        db.session.rollback()
        return 0


def _backfill_sync_job_logs_to_events() -> int:
    """Backfill from sync_job_log table"""
    try:
        from extensions import db
        from models import SyncJobLog, SystemEvent
        
        job_logs = SyncJobLog.query.order_by(SyncJobLog.started_at.asc()).limit(5000).all()
        
        backfilled = 0
        for log in job_logs:
            store_name = log.store.name if log.store else None
            
            category = 'sync_job'
            if 'fba' in log.job_type.lower():
                category = 'fba_import'
            elif 'fbm' in log.job_type.lower() or 'push' in log.job_type.lower():
                category = 'fbm_push'
            
            event = SystemEvent(
                timestamp=log.started_at,
                actor='scheduler',
                category=category,
                entity_type='store',
                entity_id=log.store_id,
                description=f'{log.job_type} {log.status}: imported={log.items_imported}, pushed={log.items_pushed}, failed={log.items_failed}',
                details_json={
                    'source': 'sync_job_log',
                    'original_id': log.id,
                    'job_type': log.job_type,
                    'status': log.status,
                    'items_imported': log.items_imported,
                    'items_pushed': log.items_pushed,
                    'items_failed': log.items_failed,
                    'duration_seconds': log.duration_seconds
                }
            )
            db.session.add(event)
            backfilled += 1
        
        db.session.commit()
        logger.info(f"Backfilled {backfilled} events from sync_job_log")
        return backfilled
        
    except Exception as e:
        logger.error(f"Failed to backfill sync_job_log: {str(e)}")
        db.session.rollback()
        return 0


def _backfill_api_error_logs_to_events() -> int:
    """Backfill from api_error_log table"""
    try:
        from extensions import db
        from models import APIErrorLog, SystemEvent
        
        error_logs = APIErrorLog.query.order_by(APIErrorLog.created_at.asc()).limit(2000).all()
        
        backfilled = 0
        for log in error_logs:
            event = SystemEvent(
                timestamp=log.created_at,
                actor='system',
                category='api_error',
                entity_type='store' if log.store_id else None,
                entity_id=log.store_id,
                description=f'{log.provider} API error: {log.error_code} - {log.message[:200] if log.message else "No message"}',
                details_json={
                    'source': 'api_error_log',
                    'original_id': log.id,
                    'provider': log.provider,
                    'endpoint': log.endpoint,
                    'http_status': log.http_status,
                    'error_code': log.error_code
                }
            )
            db.session.add(event)
            backfilled += 1
        
        db.session.commit()
        logger.info(f"Backfilled {backfilled} events from api_error_log")
        return backfilled
        
    except Exception as e:
        logger.error(f"Failed to backfill api_error_log: {str(e)}")
        db.session.rollback()
        return 0


def _backfill_config_change_logs_to_events() -> int:
    """Backfill from config_change_log table"""
    try:
        from extensions import db
        from models import ConfigChangeLog, SystemEvent
        
        config_logs = ConfigChangeLog.query.order_by(ConfigChangeLog.changed_at.asc()).limit(1000).all()
        
        backfilled = 0
        for log in config_logs:
            event = SystemEvent(
                timestamp=log.changed_at,
                actor=log.actor_type,
                actor_id=log.actor_id,
                category='config_change',
                entity_type=log.entity_type,
                entity_id=log.entity_id,
                description=log.summary[:500] if log.summary else 'Configuration changed',
                details_json={
                    'source': 'config_change_log',
                    'original_id': log.id,
                    'before': log.before_json,
                    'after': log.after_json
                }
            )
            db.session.add(event)
            backfilled += 1
        
        db.session.commit()
        logger.info(f"Backfilled {backfilled} events from config_change_log")
        return backfilled
        
    except Exception as e:
        logger.error(f"Failed to backfill config_change_log: {str(e)}")
        db.session.rollback()
        return 0


def _backfill_agent_run_logs_to_events() -> int:
    """Backfill from agent_run_log table"""
    try:
        from extensions import db
        from models import AgentRunLog, SystemEvent
        
        agent_logs = AgentRunLog.query.order_by(AgentRunLog.started_at.asc()).limit(500).all()
        
        backfilled = 0
        for log in agent_logs:
            event = SystemEvent(
                timestamp=log.started_at,
                actor='agent',
                category='agent_run',
                description=f'{log.agent_name}: {log.status} - {log.scope[:100] if log.scope else "general"}',
                details_json={
                    'source': 'agent_run_log',
                    'original_id': log.id,
                    'agent_name': log.agent_name,
                    'scope': log.scope,
                    'status': log.status,
                    'summary': log.summary
                }
            )
            db.session.add(event)
            backfilled += 1
        
        db.session.commit()
        logger.info(f"Backfilled {backfilled} events from agent_run_log")
        return backfilled
        
    except Exception as e:
        logger.error(f"Failed to backfill agent_run_log: {str(e)}")
        db.session.rollback()
        return 0
