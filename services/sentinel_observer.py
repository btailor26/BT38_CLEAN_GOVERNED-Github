"""
Sentinel Observer v1 - Pure Read-Only Observation Module
Environment: DEVELOPMENT B / STAGING
Mode: OBSERVATION ONLY
Guarantees: NO DB, NO NETWORK, NO FILE WRITES
"""
import os
import time
from datetime import datetime, timezone

_observation_cache = {
    "last_run": 0,
    "last_report": None
}
CACHE_TTL_SECONDS = 60


def _get_environment():
    """Read environment from env vars only"""
    return os.environ.get("APP_ENV", os.environ.get("FLASK_ENV", "development")).lower()


def _get_kill_switch():
    """Read kill switch state from env var only"""
    return os.environ.get("SENTINEL_KILL_SWITCH", "false").lower() == "true"


def _get_feature_flag(flag_name):
    """Read feature flag from env var only"""
    return os.environ.get(flag_name, "false").lower() == "true"


def _classify_file(filename):
    """Classify file by extension only (no content read)"""
    lower = filename.lower()
    if lower.endswith(".csv"):
        return "CSV"
    elif lower.endswith(".pdf"):
        return "PDF"
    else:
        return "OTHER"


def _scan_directory(path):
    """Scan directory for files - read-only filesystem operation"""
    result = {
        "exists": False,
        "files": [],
        "count": 0,
        "by_type": {"CSV": 0, "PDF": 0, "OTHER": 0}
    }
    
    if not os.path.exists(path):
        return result
    
    if not os.path.isdir(path):
        return result
    
    result["exists"] = True
    
    try:
        entries = os.listdir(path)
        for entry in entries:
            full_path = os.path.join(path, entry)
            if os.path.isfile(full_path):
                file_type = _classify_file(entry)
                result["files"].append({
                    "name": entry,
                    "type": file_type
                })
                result["by_type"][file_type] += 1
        result["count"] = len(result["files"])
    except (PermissionError, OSError):
        pass
    
    return result


def _determine_status(kill_switch, environment, scan_result):
    """Determine observation status based on conditions"""
    stop_conditions = []
    
    if kill_switch:
        stop_conditions.append("SENTINEL_KILL_SWITCH is ACTIVE")
        return "BLOCKED", stop_conditions
    
    if environment == "production":
        stop_conditions.append("Environment is PRODUCTION (observation disabled)")
        return "BLOCKED", stop_conditions
    
    if not scan_result["exists"]:
        stop_conditions.append("attached_assets/ebay/ directory does not exist")
        return "BLOCKED", stop_conditions
    
    if scan_result["count"] == 0:
        stop_conditions.append("attached_assets/ebay/ is empty (0 files)")
        return "BLOCKED", stop_conditions
    
    csv_count = scan_result["by_type"]["CSV"]
    pdf_count = scan_result["by_type"]["PDF"]
    
    if csv_count == 0 and pdf_count == 0:
        stop_conditions.append("No CSV or PDF files detected")
        return "BLOCKED", stop_conditions
    
    if csv_count > 0 and pdf_count > 0:
        return "STABLE", []
    
    if csv_count > 0 or pdf_count > 0:
        stop_conditions.append(f"Partial files: {csv_count} CSV, {pdf_count} PDF")
        return "DEGRADED", stop_conditions
    
    return "STABLE", []


def observe(force_refresh=False):
    """
    Pure observation function - returns JSON-serializable dict.
    
    Reads ONLY:
    - os.environ (environment, kill switch, feature flags)
    - filesystem (directory listing for attached_assets/ebay/)
    
    NO:
    - Database access
    - Network calls
    - File writes
    - Parser imports
    - Model imports
    """
    global _observation_cache
    
    now = time.time()
    if not force_refresh and _observation_cache["last_report"] is not None:
        if (now - _observation_cache["last_run"]) < CACHE_TTL_SECONDS:
            return _observation_cache["last_report"]
    
    timestamp = datetime.now(timezone.utc).isoformat()
    environment = _get_environment()
    kill_switch = _get_kill_switch()
    
    scan_target = "attached_assets/ebay/"
    scan_result = _scan_directory(scan_target)
    
    status, stop_conditions = _determine_status(kill_switch, environment, scan_result)
    
    report = {
        "timestamp": timestamp,
        "environment": environment,
        "mode": "OBSERVATION ONLY",
        "dry_run": True,
        "status": status,
        "scan_target": scan_target,
        "files_detected": {
            "count": scan_result["count"],
            "files": scan_result["files"],
            "by_type": scan_result["by_type"]
        },
        "stop_conditions": stop_conditions,
        "confirmations": {
            "db_writes": "NONE",
            "network_calls": "NONE",
            "state_changes": "NONE"
        }
    }
    
    _observation_cache["last_run"] = now
    _observation_cache["last_report"] = report
    
    return report


def get_cached_report():
    """Return cached report without triggering new observation"""
    return _observation_cache.get("last_report")


def clear_cache():
    """Clear observation cache (for testing)"""
    global _observation_cache
    _observation_cache = {
        "last_run": 0,
        "last_report": None
    }
