"""
Admin Reporting Routes - System Activity Dashboard
Admin-only access to agent runs, config changes, sync jobs, and API errors.
"""

import logging
import json
import csv
import io
from datetime import datetime, timedelta
from functools import wraps
from flask import Blueprint, render_template, request, jsonify, Response, stream_with_context, flash, redirect, url_for
from flask_login import login_required, current_user
from extensions import db
from models import (
    ConfigChangeLog, AgentRunLog, APIErrorLog, SyncJobLog,
    SyncLog, SystemLog, Store, User, SystemEvent
)

logger = logging.getLogger(__name__)

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


def admin_required(f):
    """Decorator to require admin role"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('auth.login'))
        if current_user.role != 'admin':
            flash('You do not have permission to access this page.', 'danger')
            return redirect(url_for('bp.dashboard'))
        return f(*args, **kwargs)
    return decorated_function


def parse_date_filter(date_str, end_of_day=False):
    """Parse date string and optionally set to end of day"""
    if not date_str:
        return None
    try:
        dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        if end_of_day:
            dt = dt.replace(hour=23, minute=59, second=59, microsecond=999999)
        return dt
    except:
        try:
            dt = datetime.strptime(date_str, '%Y-%m-%d')
            if end_of_day:
                dt = dt.replace(hour=23, minute=59, second=59, microsecond=999999)
            return dt
        except:
            return None


def apply_date_filter(query, date_column, date_from=None, date_to=None, default_hours=24):
    """Apply date filtering to a query with sensible defaults"""
    from_dt = parse_date_filter(date_from)
    to_dt = parse_date_filter(date_to, end_of_day=True)
    
    if from_dt:
        query = query.filter(date_column >= from_dt)
    elif not date_to:
        default_start = datetime.utcnow() - timedelta(hours=default_hours)
        query = query.filter(date_column >= default_start)
    
    if to_dt:
        query = query.filter(date_column <= to_dt)
    
    return query


@admin_bp.route('/system-activity')
@login_required
@admin_required
def system_activity():
    """Main admin reporting dashboard"""
    return render_template('admin/system_activity.html')


@admin_bp.route('/api/agent-runs')
@login_required
@admin_required
def api_agent_runs():
    """API endpoint for agent run logs"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    status_filter = request.args.get('status')
    agent_filter = request.args.get('agent')
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    
    query = AgentRunLog.query
    
    query = apply_date_filter(query, AgentRunLog.started_at, date_from, date_to, default_hours=168)
    
    if status_filter:
        query = query.filter(AgentRunLog.status == status_filter)
    if agent_filter:
        query = query.filter(AgentRunLog.agent_name.ilike(f'%{agent_filter}%'))
    
    query = query.order_by(AgentRunLog.started_at.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    
    return jsonify({
        'items': [item.to_dict() for item in pagination.items],
        'total': pagination.total,
        'pages': pagination.pages,
        'page': page
    })


@admin_bp.route('/api/config-changes')
@login_required
@admin_required
def api_config_changes():
    """API endpoint for config change logs"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    entity_type = request.args.get('entity_type')
    actor_type = request.args.get('actor_type')
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    
    query = ConfigChangeLog.query
    
    query = apply_date_filter(query, ConfigChangeLog.changed_at, date_from, date_to, default_hours=168)
    
    if entity_type:
        query = query.filter(ConfigChangeLog.entity_type == entity_type)
    if actor_type:
        query = query.filter(ConfigChangeLog.actor_type == actor_type)
    
    query = query.order_by(ConfigChangeLog.changed_at.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    
    return jsonify({
        'items': [item.to_dict() for item in pagination.items],
        'total': pagination.total,
        'pages': pagination.pages,
        'page': page
    })


@admin_bp.route('/api/sync-jobs')
@login_required
@admin_required
def api_sync_jobs():
    """API endpoint for sync job logs"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    store_id = request.args.get('store_id', type=int)
    status_filter = request.args.get('status')
    job_type = request.args.get('job_type')
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    
    query = SyncJobLog.query
    
    query = apply_date_filter(query, SyncJobLog.started_at, date_from, date_to, default_hours=24)
    
    if store_id:
        query = query.filter(SyncJobLog.store_id == store_id)
    if status_filter:
        query = query.filter(SyncJobLog.status == status_filter)
    if job_type:
        query = query.filter(SyncJobLog.job_type == job_type)
    
    query = query.order_by(SyncJobLog.started_at.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    
    return jsonify({
        'items': [item.to_dict() for item in pagination.items],
        'total': pagination.total,
        'pages': pagination.pages,
        'page': page
    })


@admin_bp.route('/api/api-errors')
@login_required
@admin_required
def api_api_errors():
    """API endpoint for API error logs"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    provider = request.args.get('provider')
    error_code = request.args.get('error_code')
    store_id = request.args.get('store_id', type=int)
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    
    query = APIErrorLog.query
    
    query = apply_date_filter(query, APIErrorLog.created_at, date_from, date_to, default_hours=24)
    
    if provider:
        query = query.filter(APIErrorLog.provider == provider)
    if error_code:
        query = query.filter(APIErrorLog.error_code.ilike(f'%{error_code}%'))
    if store_id:
        query = query.filter(APIErrorLog.store_id == store_id)
    
    query = query.order_by(APIErrorLog.created_at.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    
    return jsonify({
        'items': [item.to_dict() for item in pagination.items],
        'total': pagination.total,
        'pages': pagination.pages,
        'page': page
    })


@admin_bp.route('/api/system-events')
@login_required
@admin_required
def api_system_events():
    """API endpoint for unified system events"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    category = request.args.get('category')
    actor = request.args.get('actor')
    entity_type = request.args.get('entity_type')
    entity_id = request.args.get('entity_id', type=int)
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    
    query = SystemEvent.query
    
    query = apply_date_filter(query, SystemEvent.timestamp, date_from, date_to, default_hours=24)
    
    if category:
        query = query.filter(SystemEvent.category == category)
    if actor:
        query = query.filter(SystemEvent.actor == actor)
    if entity_type:
        query = query.filter(SystemEvent.entity_type == entity_type)
    if entity_id:
        query = query.filter(SystemEvent.entity_id == entity_id)
    
    query = query.order_by(SystemEvent.timestamp.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    
    return jsonify({
        'items': [item.to_dict() for item in pagination.items],
        'total': pagination.total,
        'pages': pagination.pages,
        'page': page
    })


@admin_bp.route('/api/export/<log_type>')
@login_required
@admin_required
def export_logs(log_type):
    """Export logs in various formats"""
    export_format = request.args.get('format', 'csv')
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    
    model_map = {
        'agent_runs': AgentRunLog,
        'config_changes': ConfigChangeLog,
        'sync_jobs': SyncJobLog,
        'api_errors': APIErrorLog,
        'system_events': SystemEvent
    }
    
    if log_type not in model_map:
        return jsonify({'error': 'Invalid log type'}), 400
    
    Model = model_map[log_type]
    
    query = Model.query
    
    if log_type == 'sync_jobs':
        query = apply_date_filter(query, SyncJobLog.started_at, date_from, date_to, default_hours=24*30)
        store_id = request.args.get('store_id', type=int)
        status = request.args.get('status')
        job_type = request.args.get('job_type')
        if store_id:
            query = query.filter(SyncJobLog.store_id == store_id)
        if status:
            query = query.filter(SyncJobLog.status == status)
        if job_type:
            query = query.filter(SyncJobLog.job_type == job_type)
        query = query.order_by(SyncJobLog.started_at.desc())
    elif log_type == 'api_errors':
        query = apply_date_filter(query, APIErrorLog.created_at, date_from, date_to, default_hours=24*30)
        provider = request.args.get('provider')
        error_code = request.args.get('error_code')
        if provider:
            query = query.filter(APIErrorLog.provider == provider)
        if error_code:
            query = query.filter(APIErrorLog.error_code.ilike(f'%{error_code}%'))
        query = query.order_by(APIErrorLog.created_at.desc())
    elif log_type == 'agent_runs':
        query = apply_date_filter(query, AgentRunLog.started_at, date_from, date_to, default_hours=24*30)
        status = request.args.get('status')
        agent = request.args.get('agent')
        if status:
            query = query.filter(AgentRunLog.status == status)
        if agent:
            query = query.filter(AgentRunLog.agent_name.ilike(f'%{agent}%'))
        query = query.order_by(AgentRunLog.started_at.desc())
    elif log_type == 'system_events':
        query = apply_date_filter(query, SystemEvent.timestamp, date_from, date_to, default_hours=24*30)
        category = request.args.get('category')
        actor = request.args.get('actor')
        entity_type = request.args.get('entity_type')
        if category:
            query = query.filter(SystemEvent.category == category)
        if actor:
            query = query.filter(SystemEvent.actor == actor)
        if entity_type:
            query = query.filter(SystemEvent.entity_type == entity_type)
        query = query.order_by(SystemEvent.timestamp.desc())
    else:
        query = apply_date_filter(query, ConfigChangeLog.changed_at, date_from, date_to, default_hours=24*30)
        entity_type = request.args.get('entity_type')
        actor_type = request.args.get('actor_type')
        if entity_type:
            query = query.filter(ConfigChangeLog.entity_type == entity_type)
        if actor_type:
            query = query.filter(ConfigChangeLog.actor_type == actor_type)
        query = query.order_by(ConfigChangeLog.changed_at.desc())
    
    items = query.limit(10000).all()
    
    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M')
    filename = f'{log_type}_{timestamp}'
    
    if export_format == 'json':
        data = [item.to_dict() for item in items]
        return Response(
            json.dumps(data, indent=2, default=str),
            mimetype='application/json',
            headers={'Content-Disposition': f'attachment; filename={filename}.json'}
        )
    
    elif export_format == 'csv':
        if not items:
            return Response(
                '',
                mimetype='text/csv',
                headers={'Content-Disposition': f'attachment; filename={filename}.csv'}
            )
        
        output = io.StringIO()
        first_item = items[0].to_dict()
        fieldnames = list(first_item.keys())
        
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for item in items:
            writer.writerow(item.to_dict())
        
        return Response(
            output.getvalue(),
            mimetype='text/csv',
            headers={'Content-Disposition': f'attachment; filename={filename}.csv'}
        )
    
    elif export_format == 'txt':
        lines = []
        for item in items:
            d = item.to_dict()
            line = ' | '.join(f'{k}: {v}' for k, v in d.items() if v is not None)
            lines.append(line)
        
        return Response(
            '\n'.join(lines),
            mimetype='text/plain',
            headers={'Content-Disposition': f'attachment; filename={filename}.txt'}
        )
    
    return jsonify({'error': 'Invalid format'}), 400


@admin_bp.route('/api/dashboard-stats')
@login_required
@admin_required
def dashboard_stats():
    """Get dashboard statistics"""
    now = datetime.utcnow()
    day_ago = now - timedelta(days=1)
    week_ago = now - timedelta(days=7)
    
    sync_jobs_24h = SyncJobLog.query.filter(SyncJobLog.started_at >= day_ago).count()
    sync_failed_24h = SyncJobLog.query.filter(
        SyncJobLog.started_at >= day_ago,
        SyncJobLog.status == 'failed'
    ).count()
    
    api_errors_24h = APIErrorLog.query.filter(APIErrorLog.created_at >= day_ago).count()
    
    config_changes_7d = ConfigChangeLog.query.filter(ConfigChangeLog.changed_at >= week_ago).count()
    
    agent_runs_24h = AgentRunLog.query.filter(AgentRunLog.started_at >= day_ago).count()
    
    system_events_24h = SystemEvent.query.filter(SystemEvent.timestamp >= day_ago).count()
    system_events_total = SystemEvent.query.count()
    
    stores = Store.query.filter_by(is_active=True).all()
    
    categories = db.session.query(
        SystemEvent.category, 
        db.func.count(SystemEvent.id)
    ).filter(SystemEvent.timestamp >= day_ago).group_by(SystemEvent.category).all()
    
    return jsonify({
        'sync_jobs_24h': sync_jobs_24h,
        'sync_failed_24h': sync_failed_24h,
        'api_errors_24h': api_errors_24h,
        'config_changes_7d': config_changes_7d,
        'agent_runs_24h': agent_runs_24h,
        'system_events_24h': system_events_24h,
        'system_events_total': system_events_total,
        'event_categories': {cat: count for cat, count in categories},
        'stores': [{'id': s.id, 'name': s.name} for s in stores]
    })


@admin_bp.route('/api/backfill', methods=['POST'])
@login_required
@admin_required
def backfill_logs():
    """Backfill logs from existing tables"""
    from admin_logging import backfill_from_sync_logs, backfill_from_system_logs, run_comprehensive_backfill
    
    sync_count = backfill_from_sync_logs()
    error_count = backfill_from_system_logs()
    
    comprehensive_result = run_comprehensive_backfill()
    
    return jsonify({
        'success': True,
        'sync_logs_backfilled': sync_count,
        'error_logs_backfilled': error_count,
        'system_events_backfill': comprehensive_result
    })
