"""
Queue Manager for Sync Jobs
Provides thread-safe job enqueueing and processing to enable concurrent background sync and manual pushes
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from sqlalchemy import and_, or_
from extensions import db
from models import SyncJob, Store

# Priority constants
PRIORITY_LOW = 1  # Background sync
PRIORITY_MEDIUM = 5  # Scheduled sync
PRIORITY_HIGH = 10  # Manual push

# Job type constants
JOB_FULL_SYNC = 'full_sync'
JOB_PUSH_ITEM = 'push_item'
JOB_IMPORT_LISTINGS = 'import_listings'
JOB_ORDER_IMPORT = 'order_import'  # Phase 1: Auto-Sync order import
JOB_AUTO_PUSH_DRY_RUN = 'auto_push_dry_run'  # Phase 2: Auto-Sync dry-run push (no real API calls)

def enqueue_sync_job(
    store_id: int,
    job_type: str,
    payload: Optional[Dict[str, Any]] = None,
    priority: int = PRIORITY_MEDIUM
) -> SyncJob:
    """
    Enqueue a new sync job for a store
    
    Args:
        store_id: Store ID to sync
        job_type: Type of job (JOB_FULL_SYNC, JOB_PUSH_ITEM, JOB_IMPORT_LISTINGS)
        payload: Optional job-specific data (e.g., {'item_id': 123})
        priority: Job priority (1=low/background, 10=high/manual)
    
    Returns:
        SyncJob: Created job instance
    """
    try:
        # [STAGE8 B3] ENV TAGGING: Add environment markers for forensic visibility
        import os
        from app import APP_ENV
        tagged_payload = payload.copy() if payload else {}
        tagged_payload['_env'] = APP_ENV
        tagged_payload['_pid'] = os.getpid()
        
        job = SyncJob(
            store_id=store_id,
            job_type=job_type,
            payload=tagged_payload,
            priority=priority,
            status='pending'
        )
        db.session.add(job)
        db.session.commit()
        
        logging.info(f"Enqueued {job_type} job (ID: {job.id}) for store {store_id} with priority {priority}")
        return job
        
    except Exception as e:
        db.session.rollback()
        logging.error(f"Failed to enqueue job for store {store_id}: {str(e)}")
        raise

def get_next_pending_job(store_id: int) -> Optional[SyncJob]:
    """
    Get the next pending job for a specific store, ordered by priority (high to low) then FIFO
    
    Args:
        store_id: Store ID to get job for
    
    Returns:
        SyncJob or None if no pending jobs
    """
    try:
        job = db.session.query(SyncJob).filter(
            and_(
                SyncJob.store_id == store_id,
                SyncJob.status == 'pending',
                or_(
                    SyncJob.retry_at.is_(None),
                    SyncJob.retry_at <= datetime.utcnow()
                )
            )
        ).order_by(
            SyncJob.priority.desc(),  # High priority first
            SyncJob.enqueued_at.asc()  # Then FIFO
        ).with_for_update(skip_locked=True).first()  # Row-level lock with skip
        
        return job
        
    except Exception as e:
        logging.error(f"Failed to get next job for store {store_id}: {str(e)}")
        return None

def mark_job_running(job_id: int) -> bool:
    """
    Mark a job as running with lock token and heartbeat
    
    Args:
        job_id: Job ID to mark
    
    Returns:
        True if successful, False otherwise
    """
    try:
        import uuid
        job = db.session.query(SyncJob).filter_by(id=job_id).first()
        if not job:
            logging.error(f"Job {job_id} not found")
            return False
        
        now = datetime.utcnow()
        job.status = 'running'
        job.started_at = now
        job.heartbeat_at = now
        job.lock_token = str(uuid.uuid4())
        db.session.commit()
        
        logging.info(f"Marked job {job_id} as running with lock token {job.lock_token[:8]}...")
        return True
        
    except Exception as e:
        db.session.rollback()
        logging.error(f"Failed to mark job {job_id} as running: {str(e)}")
        return False

def mark_job_complete(job_id: int) -> bool:
    """
    Mark a job as successfully completed
    
    Args:
        job_id: Job ID to mark
    
    Returns:
        True if successful, False otherwise
    """
    try:
        job = db.session.query(SyncJob).filter_by(id=job_id).first()
        if not job:
            logging.error(f"Job {job_id} not found")
            return False
        
        # [STAGE8B] Guard: Don't overwrite if already finalized (skipped/cancelled/failed)
        if job.status in ('skipped', 'cancelled', 'failed'):
            logging.info(f"Job {job_id} already finalized as '{job.status}' - skipping mark_complete")
            return True
        
        job.status = 'success'
        job.completed_at = datetime.utcnow()
        job.lock_token = None
        
        # Clear stale error messages from watchdog if job actually succeeded
        if job.error_message and 'auto-cleanup' in job.error_message:
            job.error_message = None
            logging.info(f"Marked job {job_id} as complete (cleared false watchdog error)")
        else:
            logging.info(f"Marked job {job_id} as complete")
        
        db.session.commit()
        return True
        
    except Exception as e:
        db.session.rollback()
        logging.error(f"Failed to mark job {job_id} as complete: {str(e)}")
        return False

def mark_job_failed(job_id: int, error_message: str, retry_in_minutes: Optional[int] = None) -> bool:
    """
    Mark a job as failed with optional retry
    
    Args:
        job_id: Job ID to mark
        error_message: Error description
        retry_in_minutes: If specified, schedule retry after this many minutes
    
    Returns:
        True if successful, False otherwise
    """
    try:
        job = db.session.query(SyncJob).filter_by(id=job_id).first()
        if not job:
            logging.error(f"Job {job_id} not found")
            return False
        
        job.status = 'failed'
        job.completed_at = datetime.utcnow()
        job.error_message = error_message
        job.retry_count += 1
        job.lock_token = None
        
        if retry_in_minutes and job.retry_count < 3:  # Max 3 retries
            job.retry_at = datetime.utcnow() + timedelta(minutes=retry_in_minutes)
            job.status = 'pending'  # Move back to pending for retry
            logging.info(f"Marked job {job_id} for retry in {retry_in_minutes} minutes (attempt {job.retry_count + 1}/3)")
        else:
            logging.error(f"Job {job_id} failed: {error_message}")
        
        db.session.commit()
        return True
        
    except Exception as e:
        db.session.rollback()
        logging.error(f"Failed to mark job {job_id} as failed: {str(e)}")
        return False

def get_pending_jobs_count(store_id: int) -> int:
    """
    Get count of pending jobs for a store
    
    Args:
        store_id: Store ID to check
    
    Returns:
        Count of pending jobs
    """
    try:
        count = db.session.query(SyncJob).filter(
            and_(
                SyncJob.store_id == store_id,
                SyncJob.status == 'pending'
            )
        ).count()
        return count
    except Exception as e:
        logging.error(f"Failed to get pending jobs count for store {store_id}: {str(e)}")
        return 0

def has_active_job(store_id: int) -> bool:
    """
    Check if a store has any active (pending or running) jobs
    
    Args:
        store_id: Store ID to check
    
    Returns:
        True if there are pending or running jobs, False otherwise
    """
    try:
        count = db.session.query(SyncJob).filter(
            and_(
                SyncJob.store_id == store_id,
                SyncJob.status.in_(['pending', 'running'])
            )
        ).count()
        return count > 0
    except Exception as e:
        logging.error(f"Failed to check active jobs for store {store_id}: {str(e)}")
        return False

def reset_stuck_jobs(timeout_minutes: int = 10) -> Dict[int, int]:
    """
    Watchdog: Reset jobs stuck in 'running' status past a timeout threshold
    
    Jobs get stuck when worker threads crash or the process restarts mid-job.
    This prevents them from blocking the entire store queue indefinitely.
    
    Args:
        timeout_minutes: Reset jobs running longer than this (default: 10 minutes)
    
    Returns:
        Dict mapping store_id to count of reset jobs for that store
    """
    try:
        cutoff_time = datetime.utcnow() - timedelta(minutes=timeout_minutes)
        
        # Find all jobs stuck in 'running' status
        stuck_jobs = db.session.query(SyncJob).filter(
            and_(
                SyncJob.status == 'running',
                SyncJob.started_at < cutoff_time
            )
        ).all()
        
        if not stuck_jobs:
            return {}
        
        # Track which stores had stuck jobs
        stores_with_stuck_jobs = {}
        
        # Reset each stuck job to failed
        for job in stuck_jobs:
            runtime = datetime.utcnow() - job.started_at if job.started_at else timedelta(0)
            job.status = 'failed'
            job.error_message = f'Job stuck in running status for {runtime.total_seconds():.0f} seconds - auto-cleanup'
            job.completed_at = datetime.utcnow()
            
            # Track store IDs with stuck jobs
            stores_with_stuck_jobs[job.store_id] = stores_with_stuck_jobs.get(job.store_id, 0) + 1
        
        db.session.commit()
        
        reset_count = len(stuck_jobs)
        logging.warning(f"🔧 Watchdog: Reset {reset_count} stuck jobs (running > {timeout_minutes} min)")
        
        return stores_with_stuck_jobs
        
    except Exception as e:
        db.session.rollback()
        logging.error(f"Failed to reset stuck jobs: {str(e)}")
        return 0

def reset_stuck_sync_logs(timeout_minutes: int = 30) -> int:
    """
    Watchdog for SyncLog: Mark sync logs stuck in 'started' status as failed
    
    SyncLogs get stuck in 'started' when an exception occurs before completion
    and the error handler fails to update the original log.
    
    Args:
        timeout_minutes: Mark logs 'started' longer than this as failed (default: 30 minutes)
    
    Returns:
        Number of logs marked as failed
    """
    try:
        from models import SyncLog
        cutoff_time = datetime.utcnow() - timedelta(minutes=timeout_minutes)
        
        # Find all sync logs stuck in 'started' status
        stuck_logs = db.session.query(SyncLog).filter(
            and_(
                SyncLog.status == 'started',
                SyncLog.created_at < cutoff_time
            )
        ).all()
        
        if not stuck_logs:
            return 0
        
        # Mark each stuck log as failed
        for log in stuck_logs:
            runtime = datetime.utcnow() - log.created_at if log.created_at else timedelta(0)
            log.status = 'failed'
            log.message = f'{log.message} [FAILED: Stuck in started status for {runtime.total_seconds():.0f} seconds - auto-cleanup]'
        
        db.session.commit()
        
        reset_count = len(stuck_logs)
        logging.warning(f"🔧 SyncLog Watchdog: Marked {reset_count} stuck sync logs as failed (started > {timeout_minutes} min)")
        
        return reset_count
        
    except Exception as e:
        db.session.rollback()
        logging.error(f"Failed to reset stuck sync logs: {str(e)}")
        return 0

def cancel_stale_push_jobs_for_warehouse(warehouse_stock_id: int) -> int:
    """
    Cancel all pending push jobs for a specific warehouse_stock_id.
    
    CRITICAL: This prevents stale jobs with old quantities from executing after
    a fresh Adjust & Push. For example, if a job was enqueued with qty=22 
    before the user adjusted to qty=14, that stale job would overwrite the
    correct push if allowed to execute.
    
    Uses SELECT FOR UPDATE to atomically lock rows before cancellation,
    preventing race conditions with the dispatcher.
    
    Args:
        warehouse_stock_id: The warehouse stock ID to cancel jobs for
        
    Returns:
        Number of jobs cancelled
    """
    try:
        pending_jobs = db.session.query(SyncJob).filter(
            and_(
                SyncJob.status == 'pending',
                SyncJob.job_type == JOB_PUSH_ITEM
            )
        ).with_for_update(skip_locked=True).all()
        
        cancelled_count = 0
        for job in pending_jobs:
            payload = job.payload or {}
            if payload.get('warehouse_stock_id') == warehouse_stock_id:
                old_qty = payload.get('quantity', 'unknown')
                job.status = 'cancelled'
                job.completed_at = datetime.utcnow()
                job.error_message = f'Cancelled by fresh Adjust & Push (stale qty={old_qty})'
                cancelled_count += 1
                logging.info(f"[STALE_JOB_CANCELLED] Job {job.id} cancelled - had stale qty={old_qty} for warehouse_stock_id={warehouse_stock_id}")
        
        db.session.commit()
        
        if cancelled_count > 0:
            logging.warning(f"[STALE_JOB_CLEANUP] Cancelled {cancelled_count} stale pending push jobs for warehouse_stock_id={warehouse_stock_id}")
        
        return cancelled_count
        
    except Exception as e:
        db.session.rollback()
        logging.error(f"Failed to cancel stale push jobs: {str(e)}")
        return 0


def cleanup_old_jobs(days_old: int = 7) -> int:
    """
    Clean up completed/failed jobs older than specified days
    
    Args:
        days_old: Delete jobs completed more than this many days ago
    
    Returns:
        Number of jobs deleted
    """
    try:
        cutoff_date = datetime.utcnow() - timedelta(days=days_old)
        
        deleted = db.session.query(SyncJob).filter(
            and_(
                SyncJob.completed_at < cutoff_date,
                or_(
                    SyncJob.status == 'success',
                    SyncJob.status == 'failed'
                )
            )
        ).delete()
        
        db.session.commit()
        logging.info(f"Cleaned up {deleted} old jobs")
        return deleted
        
    except Exception as e:
        db.session.rollback()
        logging.error(f"Failed to cleanup old jobs: {str(e)}")
        return 0
