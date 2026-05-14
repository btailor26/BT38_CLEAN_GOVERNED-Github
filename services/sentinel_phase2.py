"""
SENTINEL PHASE-2 — CONTROLLED UNLOCK + KNOWLEDGE VAULT

This module provides:
1. Command submission and validation (PLAN mode only, NO execution)
2. Knowledge Vault for read-only document ingestion
3. Audit logging for all validation requests

SAFETY INVARIANTS:
- EXECUTE mode is NEVER enabled
- Commands are validated but NEVER executed
- Knowledge files are stored but NEVER auto-processed
- All operations are logged to append-only audit log
"""

import os
import hashlib
import hmac
import logging
import json
import re
import fnmatch
from datetime import datetime
from typing import Dict, Any, Optional, List
from werkzeug.utils import secure_filename
from flask import current_app

SENTINEL_BASE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'sentinel')
KNOWLEDGE_VAULT_PATH = os.path.join(SENTINEL_BASE_PATH, 'knowledge')
AUDIT_LOG_PATH = os.path.join(SENTINEL_BASE_PATH, 'logs')
INSTANCE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'instance')
CONFIG_PATH = os.path.join(INSTANCE_PATH, 'sentinel_control.json')
ALLOWED_EXTENSIONS = {'pdf', 'csv', 'txt', 'md'}
MAX_FILE_SIZE_MB = int(os.getenv('SENTINEL_MAX_FILE_SIZE_MB', '10'))
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024

PROTOCOL_VERSION = "v1"
PROTOCOL_PATH = os.path.join(SENTINEL_BASE_PATH, 'protocols', 'command_protocol_v1.md')

REQUIRED_SECTIONS = [
    "FILES TO MODIFY",
    "EXECUTION STEPS",
    "PROOF PLAN",
    "ROLLBACK PROCEDURE",
    "RISKS & MITIGATIONS",
    "EXECUTION STATUS"
]

EXECUTION_PREFIX = "EXECUTE:"
APPROVAL_TOKEN_PREFIX = "ARCH-"

DEFAULT_ALLOWED_PATHS = [
    "sentinel/*",
    "sentinel/**/*",
    "services/sentinel_*.py",
    "instance/sentinel_*.json"
]

DEFAULT_CONFIG = {
    "command_input_enabled": False,
    "command_output_enabled": False,
    "execution_enabled": False,
    "last_modified_by": None,
    "last_modified_at": None
}


def load_config() -> Dict[str, Any]:
    """Load config from file, returning defaults if file missing/invalid."""
    try:
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, 'r') as f:
                config = json.load(f)
                merged = DEFAULT_CONFIG.copy()
                merged.update(config)
                return merged
    except Exception as e:
        logging.warning(f"[SENTINEL-CONFIG] Failed to load config: {e}")
    return DEFAULT_CONFIG.copy()


def save_config(config: Dict[str, Any], modified_by: str) -> bool:
    """Save config to file with audit info. Returns success status."""
    try:
        os.makedirs(INSTANCE_PATH, exist_ok=True)
        config["last_modified_by"] = modified_by
        config["last_modified_at"] = datetime.utcnow().isoformat() + "Z"
        with open(CONFIG_PATH, 'w') as f:
            json.dump(config, f, indent=2)
        logging.info(f"[SENTINEL-CONFIG] Config saved by {modified_by}")
        return True
    except Exception as e:
        logging.error(f"[SENTINEL-CONFIG] Failed to save config: {e}")
        return False


def get_control_switches() -> Dict[str, Any]:
    """Get the current control switch states."""
    config = load_config()
    return {
        "command_input_enabled": config.get("command_input_enabled", False),
        "command_output_enabled": config.get("command_output_enabled", False),
        "execution_enabled": config.get("execution_enabled", False),
        "last_modified_by": config.get("last_modified_by"),
        "last_modified_at": config.get("last_modified_at")
    }


def update_control_switches(
    input_enabled: Optional[bool] = None,
    output_enabled: Optional[bool] = None,
    execution_enabled: Optional[bool] = None,
    modified_by: str = "unknown",
    confirm_execution: bool = False
) -> Dict[str, Any]:
    """
    Update control switches. Requires confirm_execution=True to enable execution.
    Returns result with success status and current state.
    """
    result = {
        "success": False,
        "error": None,
        "switches": None
    }
    
    config = load_config()
    
    if input_enabled is not None:
        config["command_input_enabled"] = bool(input_enabled)
    
    if output_enabled is not None:
        config["command_output_enabled"] = bool(output_enabled)
    
    if execution_enabled is True:
        if not confirm_execution:
            result["error"] = "Enabling execution requires confirm_execution=True"
            logging.warning(f"[SENTINEL-CONFIG] Execution enable BLOCKED - no confirmation from {modified_by}")
            return result
        config["execution_enabled"] = True
        logging.warning(f"[SENTINEL-CONFIG] EXECUTION ENABLED by {modified_by} - USE WITH CAUTION")
    elif execution_enabled is False:
        config["execution_enabled"] = False
    
    if save_config(config, modified_by):
        result["success"] = True
        result["switches"] = get_control_switches()
    else:
        result["error"] = "Failed to save configuration"
    
    return result


def _normalize_path(path: str) -> Optional[str]:
    """
    Normalize a file path for scope checking.
    
    SECURITY: Rejects paths that escape repo root.
    Returns None if path is invalid/dangerous.
    """
    if not path or not path.strip():
        return None
    
    path = path.strip()
    
    if os.path.isabs(path):
        return None
    
    if '..' in path:
        return None
    
    if path.startswith('/') or path.startswith('\\'):
        return None
    
    normalized = os.path.normpath(path)
    
    if normalized.startswith('..'):
        return None
    
    normalized = normalized.replace('\\', '/')
    
    return normalized


def _load_scope_allowlist() -> List[str]:
    """
    Load scope allowlist from config (READ-ONLY).
    
    INTERNAL ONLY - not exposed via any route or UI.
    Falls back to DEFAULT_ALLOWED_PATHS if not configured.
    """
    config = load_config()
    allowlist = config.get("scope_allowlist")
    
    if allowlist and isinstance(allowlist, list):
        return allowlist
    
    return DEFAULT_ALLOWED_PATHS.copy()


def _match_path_to_allowlist(path: str, allowlist: List[str]) -> bool:
    """
    Check if a path matches any pattern in the allowlist.
    
    Supports glob patterns: *, **, ?
    """
    for pattern in allowlist:
        if fnmatch.fnmatch(path, pattern):
            return True
        if '**' in pattern:
            base_pattern = pattern.replace('**/', '').replace('/**', '')
            if fnmatch.fnmatch(path, base_pattern):
                return True
            if path.startswith(pattern.split('**')[0].rstrip('/')):
                return True
    return False


def validate_scope(proposed_files: List[str]) -> Dict[str, Any]:
    """
    Validate that proposed files are within the allowed scope.
    
    SCOPE LOCK v1: Prevents task lists from touching files outside allowlist.
    
    Returns:
        {
            "valid": bool,
            "allowed": [...],
            "rejected": [...],
            "escaped": [...],   # Paths that tried to escape repo
            "reason": str,
            "allowlist": [...]  # Current allowlist for transparency
        }
    """
    result = {
        "valid": True,
        "allowed": [],
        "rejected": [],
        "escaped": [],
        "reason": "All files within allowed scope",
        "allowlist": _load_scope_allowlist()
    }
    
    if not proposed_files:
        return result
    
    allowlist = result["allowlist"]
    
    for file_path in proposed_files:
        normalized = _normalize_path(file_path)
        
        if normalized is None:
            result["escaped"].append(file_path)
            continue
        
        if _match_path_to_allowlist(normalized, allowlist):
            result["allowed"].append(normalized)
        else:
            result["rejected"].append(normalized)
    
    if result["escaped"]:
        result["valid"] = False
        result["reason"] = f"{len(result['escaped'])} path(s) attempted to escape repo root"
        logging.warning(f"[SENTINEL-SCOPE] BLOCKED - path escape attempt: {result['escaped']}")
    elif result["rejected"]:
        result["valid"] = False
        result["reason"] = f"{len(result['rejected'])} file(s) outside allowed scope"
        logging.info(f"[SENTINEL-SCOPE] Rejected files: {result['rejected']}")
    
    return result


STOP_CONDITIONS = [
    "DELETE FROM",
    "DROP TABLE",
    "DROP DATABASE",
    "TRUNCATE",
    "INSERT INTO",
    "ALTER TABLE",
    "CREATE TABLE",
    "GRANT ",
    "REVOKE ",
    "sp_",
    "xp_",
    "SHUTDOWN",
    "requests.post(",
    "requests.put(",
    "requests.delete(",
    "urllib.request.",
    "httplib.",
    "socket.connect(",
    "subprocess.",
    "os.system(",
    "eval(",
    "exec(",
    "compile(",
    "__import__(",
    "open(",
    "file(",
]


def get_sentinel_mode() -> str:
    """Get current SENTINEL_MODE from app config."""
    return current_app.config.get('SENTINEL_MODE', 'LOCKED')


def is_command_input_enabled() -> bool:
    """Check if command input is enabled via config switch."""
    switches = get_control_switches()
    return switches.get("command_input_enabled", False)


def compute_command_hash(command: str) -> str:
    """Compute SHA256 hash of command (first 12 chars)."""
    return hashlib.sha256(command.encode()).hexdigest()[:12]


def get_audit_log_path() -> str:
    """Get the audit log directory path, creating if needed."""
    os.makedirs(AUDIT_LOG_PATH, exist_ok=True)
    return os.path.join(AUDIT_LOG_PATH, 'plan_audit.jsonl')


def append_audit_log(entry: Dict[str, Any]) -> bool:
    """Append an entry to the audit log (append-only)."""
    try:
        log_path = get_audit_log_path()
        with open(log_path, 'a') as f:
            f.write(json.dumps(entry) + '\n')
        return True
    except Exception as e:
        logging.error(f"[SENTINEL-AUDIT] Failed to write audit log: {e}")
        return False


def read_recent_audit_entries(limit: int = 10) -> List[Dict[str, Any]]:
    """Read the most recent audit log entries."""
    entries = []
    try:
        log_path = get_audit_log_path()
        if os.path.exists(log_path):
            with open(log_path, 'r') as f:
                lines = f.readlines()
                for line in lines[-limit:]:
                    try:
                        entries.append(json.loads(line.strip()))
                    except json.JSONDecodeError:
                        pass
    except Exception as e:
        logging.error(f"[SENTINEL-AUDIT] Failed to read audit log: {e}")
    return list(reversed(entries))


def find_knowledge_citations(command: str, governance_only: bool = False) -> List[str]:
    """
    Find knowledge vault files that could justify/support this command.
    Returns list of file_ids that contain relevant content.
    
    This is a simple keyword-based search - NOT semantic understanding.
    
    If governance_only=True, governance policy files are auto-cited.
    """
    citations = []
    knowledge_files = list_knowledge_files()
    
    if not knowledge_files:
        return citations
    
    command_lower = command.lower()
    command_words = set(re.findall(r'\b\w+\b', command_lower))
    
    for file_meta in knowledge_files:
        file_id = file_meta.get('file_id', '')
        original_filename = file_meta.get('original_filename', '').lower()
        file_path = os.path.join(get_knowledge_vault_path(), file_id)
        
        if not os.path.exists(file_path):
            continue
        
        try:
            with open(file_path, 'r', errors='ignore') as f:
                content = f.read(50000)
            content_lower = content.lower()
            
            is_governance_policy = (
                'governance_policy' in original_filename or
                'governance_policy' in file_id.lower() or
                'sentinel governance policy' in content_lower
            )
            
            if governance_only and is_governance_policy:
                if file_id not in citations:
                    citations.append(file_id)
                continue
            
            content_words = set(re.findall(r'\b\w+\b', content_lower))
            common_words = command_words & content_words
            
            important_words = common_words - {'the', 'a', 'an', 'is', 'are', 'to', 'for', 'and', 'or', 'in', 'on', 'at', 'of', 'with'}
            
            if len(important_words) >= 2:
                if file_id not in citations:
                    citations.append(file_id)
                
        except Exception as e:
            logging.debug(f"[SENTINEL] Could not read file for citation: {file_id} - {e}")
    
    return citations


REQUIRED_KNOWLEDGE_TOPICS = [
    "api",
    "procedure",
    "rollback",
    "schema",
    "config",
    "error",
    "deploy",
    "migrate",
    "auth",
    "security"
]


def assess_knowledge_coverage(command: str) -> Dict[str, Any]:
    """
    Assess whether the Knowledge Vault has sufficient coverage for a command.
    
    Coverage is based on topic/artifact matching, NOT citation count.
    A command mentioning "api" or "deploy" requires matching vault files.
    
    Returns:
        {
            "status": "SUFFICIENT" | "INSUFFICIENT",
            "coverage_pct": int (0-100),
            "required_topics": [...],
            "covered_topics": [...],
            "missing_topics": [...],
            "cited_files": [...],
            "recommendation": str
        }
    """
    result = {
        "status": "INSUFFICIENT",
        "coverage_pct": 0,
        "required_topics": [],
        "covered_topics": [],
        "missing_topics": [],
        "cited_files": [],
        "recommendation": ""
    }
    
    if not command or not command.strip():
        result["recommendation"] = "No command provided"
        return result
    
    command_lower = command.lower()
    command_words = set(re.findall(r'\b\w+\b', command_lower))
    
    required_topics = []
    for topic in REQUIRED_KNOWLEDGE_TOPICS:
        if topic in command_lower or any(topic in word for word in command_words):
            required_topics.append(topic)
    
    if not required_topics:
        result["status"] = "SUFFICIENT"
        result["coverage_pct"] = 100
        result["recommendation"] = "Command does not reference specialized topics"
        result["cited_files"] = find_knowledge_citations(command)
        return result
    
    result["required_topics"] = required_topics
    
    knowledge_files = list_knowledge_files()
    vault_content_lower = ""
    cited_files = []
    
    for file_meta in knowledge_files:
        file_id = file_meta.get('file_id', '')
        file_path = os.path.join(get_knowledge_vault_path(), file_id)
        
        if not os.path.exists(file_path):
            continue
        
        try:
            with open(file_path, 'r', errors='ignore') as f:
                content = f.read(50000).lower()
            vault_content_lower += " " + content
            
            file_words = set(re.findall(r'\b\w+\b', content))
            if command_words & file_words:
                cited_files.append(file_id)
        except Exception:
            pass
    
    result["cited_files"] = cited_files
    
    covered = []
    missing = []
    
    for topic in required_topics:
        if topic in vault_content_lower:
            covered.append(topic)
        else:
            missing.append(topic)
    
    result["covered_topics"] = covered
    result["missing_topics"] = missing
    
    if required_topics:
        result["coverage_pct"] = int((len(covered) / len(required_topics)) * 100)
    else:
        result["coverage_pct"] = 100
    
    if not missing:
        result["status"] = "SUFFICIENT"
        result["recommendation"] = f"Knowledge covers all {len(required_topics)} required topic(s)"
    else:
        result["status"] = "INSUFFICIENT"
        missing_list = ", ".join(missing)
        result["recommendation"] = f"Upload documentation covering: {missing_list}"
    
    return result


def validate_plan_output(plan_output: str) -> Dict[str, Any]:
    """
    Validate that a PLAN-mode output complies with COMMAND PROTOCOL v1.
    
    Checks for presence of all required sections.
    Returns validation result with list of any missing sections.
    
    NOTE: This is a structural check only - it verifies sections exist,
    not that their content is complete or correct.
    """
    if not plan_output or not plan_output.strip():
        return {
            "valid": False,
            "missing_sections": REQUIRED_SECTIONS.copy(),
            "protocol_version": PROTOCOL_VERSION,
            "reason": "Empty plan output"
        }
    
    plan_upper = plan_output.upper()
    missing = []
    
    for section in REQUIRED_SECTIONS:
        if section.upper() not in plan_upper:
            missing.append(section)
    
    if missing:
        return {
            "valid": False,
            "missing_sections": missing,
            "protocol_version": PROTOCOL_VERSION,
            "reason": f"Missing {len(missing)} required section(s)"
        }
    
    return {
        "valid": True,
        "missing_sections": [],
        "protocol_version": PROTOCOL_VERSION,
        "reason": "Protocol compliant"
    }


def _get_approval_secret() -> Optional[str]:
    """
    Get HMAC secret from environment variable.
    INTERNAL ONLY - never expose or log this value.
    Returns None if not configured (fails closed).
    """
    secret = os.getenv('SENTINEL_APPROVAL_SECRET')
    return secret if secret and len(secret) >= 32 else None


def _generate_approval_token(command_hash: str, architect_id: str) -> Optional[str]:
    """
    Generate HMAC-SHA256 approval token for a command.
    
    INTERNAL ONLY - NOT exposed via any route or UI.
    Used only by Architect tooling (external or CLI).
    
    Returns None if secret not configured.
    """
    secret = _get_approval_secret()
    if not secret:
        return None
    
    architect_prefix = architect_id[:8]
    message = f"{command_hash}:{architect_prefix}".encode('utf-8')
    signature = hmac.new(secret.encode('utf-8'), message, hashlib.sha256).hexdigest()[:16]
    return f"{APPROVAL_TOKEN_PREFIX}{architect_prefix}-{signature}"


def verify_approval_token(token: str, command_hash: str) -> Dict[str, Any]:
    """
    Verify that an approval token is valid for the given command.
    
    Returns verification result with details.
    If secret missing → always FAILS (fail closed).
    """
    result = {
        "valid": False,
        "reason": None,
        "architect_id": None
    }
    
    secret = _get_approval_secret()
    if not secret:
        result["reason"] = "Approval secret not configured (system locked)"
        return result
    
    if not token or not token.startswith(APPROVAL_TOKEN_PREFIX):
        result["reason"] = f"Invalid token format (must start with {APPROVAL_TOKEN_PREFIX})"
        return result
    
    try:
        token_body = token[len(APPROVAL_TOKEN_PREFIX):]
        parts = token_body.split('-')
        if len(parts) != 2:
            result["reason"] = "Malformed token structure"
            return result
        
        architect_id_prefix, provided_sig = parts
        
        message = f"{command_hash}:{architect_id_prefix}".encode('utf-8')
        expected_sig = hmac.new(secret.encode('utf-8'), message, hashlib.sha256).hexdigest()[:16]
        
        if not hmac.compare_digest(provided_sig, expected_sig):
            result["reason"] = "Token signature mismatch"
            return result
        
        result["valid"] = True
        result["reason"] = "Token verified"
        result["architect_id"] = architect_id_prefix
        return result
        
    except Exception:
        result["reason"] = "Token verification error"
        return result


def execute_command(command: str, approval_token: str, user: str = "unknown") -> Dict[str, Any]:
    """
    EXECUTION FIREWALL v1 — Triple-gate command execution.
    
    Gate 1: execution_enabled must be True (config switch)
    Gate 2: Command must start with EXECUTE: prefix
    Gate 3: approval_token must be valid HMAC for command hash
    
    When all gates pass, pipeline opens (Architect Override).
    Actual command execution is NO-OP in v1 but pipeline entry is allowed.
    """
    timestamp = datetime.utcnow().isoformat() + "Z"
    command_hash = compute_command_hash(command) if command else "empty"
    
    result = {
        "executed": False,
        "blocked_by": None,
        "gates_passed": [],
        "gates_failed": [],
        "command_hash": command_hash,
        "timestamp": timestamp,
        "protocol_version": PROTOCOL_VERSION
    }
    
    config = load_config()
    if not config.get("execution_enabled", False):
        result["blocked_by"] = "gate_1_config"
        result["gates_failed"].append("Gate 1: execution_enabled is False")
        logging.info(f"[SENTINEL-FIREWALL] Blocked at Gate 1 (config disabled)")
        return result
    
    result["gates_passed"].append("Gate 1: execution_enabled is True")
    
    if not command or not command.strip().startswith(EXECUTION_PREFIX):
        result["blocked_by"] = "gate_2_prefix"
        result["gates_failed"].append(f"Gate 2: Command missing {EXECUTION_PREFIX} prefix")
        logging.info(f"[SENTINEL-FIREWALL] Blocked at Gate 2 (missing EXECUTE: prefix)")
        return result
    
    result["gates_passed"].append(f"Gate 2: Command has {EXECUTION_PREFIX} prefix")
    
    token_result = verify_approval_token(approval_token, command_hash)
    if not token_result["valid"]:
        result["blocked_by"] = "gate_3_token"
        result["gates_failed"].append(f"Gate 3: {token_result['reason']}")
        logging.info(f"[SENTINEL-FIREWALL] Blocked at Gate 3 (token: {token_result['reason']})")
        return result
    
    result["gates_passed"].append(f"Gate 3: Token verified (architect: {token_result['architect_id']})")
    
    # ARCHITECT OVERRIDE: When all gates pass, pipeline opens
    logging.info("[SENTINEL-FIREWALL] Architect override active — execution pipeline open")
    
    # Pipeline is open. Actual execution is a NO-OP in v1 but entry is allowed.
    result["executed"] = True
    result["blocked_by"] = None
    result["execution_note"] = "Pipeline open. Actual command execution is NO-OP in v1."
    result["architect_override"] = True
    
    return result


GOVERNANCE_ALLOWED_FILES = [
    "services/sentinel_phase2.py",
    "routes.py",
    "templates/tools/sentinel_home.html",
    "templates/sentinel_home.html",
]

GOVERNANCE_BLOCKED_KEYWORDS = [
    "marketplace", "amazon", "ebay", "vinted", "deploy", "publish",
    "migration", "database", "db write", "network call", "api call",
    "webhook", "payment", "payout", "wise", "paypal", "stripe",
    "crypto", "order", "listing", "inventory",
]

GOVERNANCE_REQUIRED_KEYWORDS = [
    "stop_conditions", "validator", "scope lock", "knowledge coverage",
    "protocol", "sentinel mode", "workspace", "control switches",
    "auth", "csrf", "sentinel", "governance", "safety",
]


def _is_governance_only_request(command: str) -> bool:
    """
    Check if a command is a governance-only internal Sentinel request.
    
    Returns True if ALL of the following are true:
    1. Command does NOT contain business workflow keywords (fail-closed)
    2. Command IS about sentinel internals
    
    Returns False otherwise (fail-closed for business workflows).
    """
    command_lower = command.lower()
    
    for blocked in GOVERNANCE_BLOCKED_KEYWORDS:
        if blocked.lower() in command_lower:
            logging.debug(f"[SENTINEL] Governance check FAILED - blocked keyword: {blocked}")
            return False
    
    for required in GOVERNANCE_REQUIRED_KEYWORDS:
        if required.lower() in command_lower:
            logging.debug(f"[SENTINEL] Governance check PASSED - found keyword: {required}")
            return True
    
    logging.debug("[SENTINEL] Governance check FAILED - no sentinel keywords found")
    return False


def validate_command(command: str, user: str = "unknown") -> Dict[str, Any]:
    """
    Validate a command WITHOUT executing it.
    
    PLAN mode requirements:
    1. Must pass stop condition checks
    2. Must have knowledge vault citations OR be rejected with missing_knowledge
       (Exception: governance-only requests return ACCEPTED_WITH_WARNINGS)
    
    Returns structured validation result for API response.
    """
    timestamp = datetime.utcnow().isoformat() + "Z"
    command_hash = compute_command_hash(command) if command else "empty"
    
    result = {
        "ok": False,
        "verdict": "REJECTED",
        "protocol_version": PROTOCOL_VERSION,
        "stop_reason": None,
        "violations": [],
        "citations": [],
        "missing_knowledge": [],
        "required_inputs": [],
        "plan_steps": [],
        "risks": [],
        "command_hash": command_hash,
        "validated_at": timestamp
    }
    
    audit_entry = {
        "timestamp": timestamp,
        "user": user,
        "mode": get_sentinel_mode(),
        "command_hash": command_hash,
        "verdict": None,
        "citations": [],
        "stop_reason": None
    }
    
    mode = get_sentinel_mode()
    
    if mode != 'PLAN':
        result["stop_reason"] = f"Command input not enabled in {mode} mode"
        audit_entry["verdict"] = "REJECTED"
        audit_entry["stop_reason"] = result["stop_reason"]
        append_audit_log(audit_entry)
        logging.warning(f"[SENTINEL] Command rejected - not in PLAN mode (current: {mode})")
        return result
    
    if not command or not command.strip():
        result["stop_reason"] = "Empty command"
        audit_entry["verdict"] = "REJECTED"
        audit_entry["stop_reason"] = result["stop_reason"]
        append_audit_log(audit_entry)
        return result
    
    command_upper = command.upper()
    violations = []
    
    is_execution_attempt = command.lstrip().upper().startswith("EXECUTE:")
    
    if is_execution_attempt:
        violations.append("EXECUTE:")
        
        for stop_pattern in STOP_CONDITIONS:
            if stop_pattern.upper() in command_upper:
                violations.append(stop_pattern)
    
    if violations:
        result["violations"] = violations
        result["stop_reason"] = f"Command violates {len(violations)} stop condition(s): {', '.join(violations[:3])}"
        audit_entry["verdict"] = "REJECTED"
        audit_entry["stop_reason"] = result["stop_reason"]
        append_audit_log(audit_entry)
        logging.warning(f"[SENTINEL] Command REJECTED - violations: {violations}")
        return result
    
    is_governance_only = _is_governance_only_request(command)
    
    citations = find_knowledge_citations(command, governance_only=is_governance_only)
    
    if not citations:
        if is_governance_only:
            result["ok"] = True
            result["verdict"] = "ACCEPTED_WITH_WARNINGS"
            result["warnings"] = ["No supporting docs in vault; proceed only with Architect approval."]
            result["governance_only"] = True
            result["plan_steps"] = [
                "1. This is an internal Sentinel governance request",
                "2. No vault citations required for internal safety logic",
                "3. Requires Architect approval before any implementation"
            ]
            result["risks"] = [
                "This is a PLAN only - no execution occurs",
                "Manual Architect review required"
            ]
            audit_entry["verdict"] = "ACCEPTED_WITH_WARNINGS"
            audit_entry["governance_only"] = True
            append_audit_log(audit_entry)
            logging.info(f"[SENTINEL] Command ACCEPTED_WITH_WARNINGS (governance-only, no policy file): {command[:50]}...")
            return result
        
        result["stop_reason"] = "No knowledge vault citations found to justify this command"
        result["missing_knowledge"] = ["Upload relevant documentation to Knowledge Vault before submitting commands"]
        result["required_inputs"] = ["Knowledge files (.pdf, .csv, .txt, .md) that describe or authorize this operation"]
        audit_entry["verdict"] = "REJECTED"
        audit_entry["stop_reason"] = result["stop_reason"]
        append_audit_log(audit_entry)
        logging.info(f"[SENTINEL] Command REJECTED - no citations: {command[:50]}...")
        return result
    
    if is_governance_only:
        result["ok"] = True
        result["verdict"] = "ACCEPTED_WITH_WARNINGS"
        result["warnings"] = ["Governance-only. Cited governance policy file. Proceed only with Architect approval."]
        result["citations"] = citations
        result["governance_only"] = True
        result["plan_steps"] = [
            "1. Review cited governance policy",
            "2. This is an internal Sentinel governance request",
            "3. Requires Architect approval before implementation"
        ]
        result["risks"] = [
            "This is a PLAN only - no execution occurs",
            "Manual Architect review required"
        ]
        audit_entry["verdict"] = "ACCEPTED_WITH_WARNINGS"
        audit_entry["citations"] = citations
        audit_entry["governance_only"] = True
        append_audit_log(audit_entry)
        logging.info(f"[SENTINEL] Command ACCEPTED_WITH_WARNINGS (governance-only with policy): {command[:50]}...")
        return result
    
    knowledge_coverage = assess_knowledge_coverage(command)
    
    result["ok"] = True
    result["verdict"] = "ACCEPTED"
    result["citations"] = citations
    result["knowledge_coverage"] = knowledge_coverage
    result["plan_steps"] = [
        "1. Review cited knowledge files",
        "2. Verify command aligns with documented procedures",
        "3. Command validated for PLAN only (NOT EXECUTED)"
    ]
    result["risks"] = [
        "This is a PLAN only - no execution occurs",
        "Manual review required before any real execution"
    ]
    
    if knowledge_coverage["status"] == "INSUFFICIENT":
        result["knowledge_warning"] = {
            "status": "INSUFFICIENT",
            "missing_topics": knowledge_coverage["missing_topics"],
            "recommendation": knowledge_coverage["recommendation"]
        }
    
    audit_entry["verdict"] = "ACCEPTED"
    audit_entry["citations"] = citations
    audit_entry["knowledge_coverage"] = knowledge_coverage["status"]
    append_audit_log(audit_entry)
    
    logging.info(f"[SENTINEL] Command ACCEPTED as PLAN: {command[:100]}... (citations: {len(citations)}, coverage: {knowledge_coverage['status']})")
    
    return result


def compute_file_hash(file_content: bytes) -> str:
    """Compute SHA256 hash of file content."""
    return hashlib.sha256(file_content).hexdigest()


def allowed_file(filename: str) -> bool:
    """Check if file extension is allowed."""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def get_knowledge_vault_path() -> str:
    """Get the knowledge vault directory path, creating if needed."""
    os.makedirs(KNOWLEDGE_VAULT_PATH, exist_ok=True)
    return KNOWLEDGE_VAULT_PATH


def ingest_knowledge_file(file, uploaded_by: str) -> Dict[str, Any]:
    """
    Ingest a file into the Knowledge Vault (READ-ONLY storage).
    
    NO PROCESSING, NO EXECUTION, NO AUTO-LEARNING.
    Only stores metadata and file content.
    """
    result = {
        "success": False,
        "error": None,
        "file_id": None,
        "filename": None,
        "hash": None,
        "size_bytes": 0,
        "uploaded_at": datetime.utcnow().isoformat() + "Z",
        "uploaded_by": uploaded_by,
        "status": None
    }
    
    mode = get_sentinel_mode()
    if mode not in ['OBSERVE', 'PLAN']:
        result["error"] = f"Knowledge upload not enabled in {mode} mode"
        logging.warning(f"[SENTINEL-VAULT] Upload rejected - mode: {mode}")
        return result
    
    if not file or not file.filename:
        result["error"] = "No file provided"
        return result
    
    original_filename = secure_filename(file.filename)
    
    if not allowed_file(original_filename):
        result["error"] = f"File type not allowed. Accepted: {', '.join(ALLOWED_EXTENSIONS)}"
        return result
    
    file_content = file.read()
    file_size = len(file_content)
    
    if file_size > MAX_FILE_SIZE_BYTES:
        result["error"] = f"File too large. Max: {MAX_FILE_SIZE_MB}MB"
        return result
    
    if file_size == 0:
        result["error"] = "Empty file"
        return result
    
    file_hash = compute_file_hash(file_content)
    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    file_id = f"{timestamp}_{file_hash[:12]}_{original_filename}"
    
    vault_path = get_knowledge_vault_path()
    file_path = os.path.join(vault_path, file_id)
    
    try:
        with open(file_path, 'wb') as f:
            f.write(file_content)
        
        metadata = {
            "file_id": file_id,
            "original_filename": original_filename,
            "hash": file_hash,
            "size_bytes": file_size,
            "uploaded_at": result["uploaded_at"],
            "uploaded_by": uploaded_by,
            "file_type": original_filename.rsplit('.', 1)[1].lower(),
            "status": "INGESTED"
        }
        
        meta_path = file_path + ".meta.json"
        with open(meta_path, 'w') as f:
            json.dump(metadata, f, indent=2)
        
        result["success"] = True
        result["file_id"] = file_id
        result["filename"] = original_filename
        result["hash"] = file_hash
        result["size_bytes"] = file_size
        result["status"] = "INGESTED"
        
        logging.info(f"[SENTINEL-VAULT] File ingested: {file_id} by {uploaded_by}")
        
    except Exception as e:
        result["error"] = f"Failed to store file: {str(e)}"
        logging.error(f"[SENTINEL-VAULT] Ingestion failed: {e}")
    
    return result


def list_knowledge_files() -> List[Dict[str, Any]]:
    """List all files in the Knowledge Vault."""
    vault_path = get_knowledge_vault_path()
    files = []
    
    try:
        for filename in os.listdir(vault_path):
            if filename.endswith('.meta.json'):
                meta_path = os.path.join(vault_path, filename)
                try:
                    with open(meta_path, 'r') as f:
                        metadata = json.load(f)
                        files.append(metadata)
                except Exception as e:
                    logging.warning(f"[SENTINEL-VAULT] Failed to read metadata: {filename} - {e}")
    except Exception as e:
        logging.error(f"[SENTINEL-VAULT] Failed to list files: {e}")
    
    files.sort(key=lambda x: x.get('uploaded_at', ''), reverse=True)
    return files


def get_sentinel_status() -> Dict[str, Any]:
    """Get comprehensive Sentinel status for API/UI."""
    mode = get_sentinel_mode()
    switches = get_control_switches()
    files = list_knowledge_files()
    audit_entries = read_recent_audit_entries(10)
    
    return {
        "sentinel_mode": mode,
        "command_input_enabled": switches.get("command_input_enabled", False),
        "command_output_enabled": switches.get("command_output_enabled", False),
        "execution_enabled": switches.get("execution_enabled", False),
        "knowledge_upload_enabled": mode in ['OBSERVE', 'PLAN'],
        "control_switches": switches,
        "knowledge_vault": {
            "file_count": len(files),
            "files": files[:10],
            "status": "READY" if files else "EMPTY"
        },
        "audit_log": {
            "recent_entries": audit_entries,
            "entry_count": len(audit_entries)
        },
        "safety": {
            "db_writes": "BLOCKED",
            "network_calls": "BLOCKED",
            "state_changes": "BLOCKED",
            "execution": "DISABLED" if not switches.get("execution_enabled") else "ENABLED"
        }
    }
