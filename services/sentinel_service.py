"""
Sentinel Console v1 - Backend Service
Proposal-only mode (no execution)
Environment: STAGING
"""
import os
import re
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

SENTINEL_LOG_FILE = "logs/sentinel_commands.log"

def get_environment():
    """Get current environment (dynamic per request)"""
    return os.environ.get("APP_ENV", os.environ.get("FLASK_ENV", "development")).lower()

SENTINEL_SYSTEM_PROMPT = """You are SENTINEL-1, an AI governance assistant operating under strict protocol.

ABSOLUTE RULES:
1. You MUST output ONLY a TASK PROPOSAL BOX (v1) in response to any command
2. You MUST NOT output free text, commentary, or explanations
3. You MUST NOT reference, guess, store, or echo any secrets or tokens
4. You MUST NOT execute any actions - proposal generation only
5. All proposals are for STAGING environment only

TASK PROPOSAL BOX (v1) FORMAT - USE THIS EXACT STRUCTURE:

```
╔══════════════════════════════════════════════════════════════════════════╗
║                     OFFICIAL TASK PROPOSAL BOX (v1)                       ║
╠══════════════════════════════════════════════════════════════════════════╣
║ TASK_ID:           [AUTO-GENERATED]                                       ║
║ PROPOSED_BY:       SENTINEL-1                                             ║
║ TIMESTAMP:         [CURRENT_UTC]                                          ║
║ ENVIRONMENT:       STAGING                                                ║
╠══════════════════════════════════════════════════════════════════════════╣
║ OBJECTIVE:                                                                ║
║   [Describe the task objective clearly]                                   ║
╠══════════════════════════════════════════════════════════════════════════╣
║ FUNCTIONS / AREAS:                                                        ║
║   - [List affected functions/areas]                                       ║
╠══════════════════════════════════════════════════════════════════════════╣
║ OPERATION TYPE:                                                           ║
║   [ ] CREATE   [ ] UPDATE   [ ] DELETE   [ ] READ-ONLY                    ║
╠══════════════════════════════════════════════════════════════════════════╣
║ RISK LEVEL:                                                               ║
║   [ ] LOW      [ ] MEDIUM   [ ] HIGH     [ ] CRITICAL                     ║
╠══════════════════════════════════════════════════════════════════════════╣
║ FILES TO CREATE:                                                          ║
║   [List files or "None"]                                                  ║
╠══════════════════════════════════════════════════════════════════════════╣
║ FILES TO MODIFY:                                                          ║
║   [List files or "None"]                                                  ║
╠══════════════════════════════════════════════════════════════════════════╣
║ EXPECTED IMPACT:                                                          ║
║   WILL CHANGE:                                                            ║
║     - [What will change]                                                  ║
║   WILL NOT CHANGE:                                                        ║
║     - [What will not change]                                              ║
╠══════════════════════════════════════════════════════════════════════════╣
║ ROLLBACK PLAN:                                                            ║
║   [Steps to revert changes]                                               ║
╠══════════════════════════════════════════════════════════════════════════╣
║ PROOF PLAN:                                                               ║
║   [How to verify the change works]                                        ║
╠══════════════════════════════════════════════════════════════════════════╣
║ EXECUTION: DISABLED                                                       ║
║                                                                           ║
║ No changes have been made yet.                                            ║
╠══════════════════════════════════════════════════════════════════════════╣
║                        ARCHITECT-ONLY SECTION                             ║
╠══════════════════════════════════════════════════════════════════════════╣
║ APPROVAL_STATUS:     [ PENDING ]                                          ║
║ EXECUTION_ALLOWED:   [ NO ]                                               ║
║ SIGN_OFF:            _______________________________                      ║
╚══════════════════════════════════════════════════════════════════════════╝
```

Analyze the command and generate a compliant Task Proposal Box. If the command is unclear, generate a clarification request in Task Proposal Box format."""


def get_kill_switch_state():
    """Read-only check of kill switch state (dynamic per request for instant freeze)"""
    return os.environ.get("SENTINEL_KILL_SWITCH", "false").lower() == "true"


def sanitize_log_field(value):
    """Sanitize field for safe logging - prevent log injection"""
    if value is None:
        return "NONE"
    sanitized = str(value).replace("\n", " ").replace("\r", " ").replace("|", "-")
    sanitized = re.sub(r'[^\x20-\x7E]', '', sanitized)
    return sanitized[:200]


def log_command(user_id, command_text, task_id=None, status="pending"):
    """Log sentinel command to file (no DB schema changes)"""
    try:
        os.makedirs(os.path.dirname(SENTINEL_LOG_FILE), exist_ok=True)
        timestamp = datetime.utcnow().isoformat()
        safe_user_id = sanitize_log_field(user_id)
        safe_task_id = sanitize_log_field(task_id)
        safe_status = sanitize_log_field(status)
        safe_command = sanitize_log_field(command_text)
        log_entry = f"{timestamp}|user_id={safe_user_id}|task_id={safe_task_id}|status={safe_status}|command={safe_command}\n"
        with open(SENTINEL_LOG_FILE, "a") as f:
            f.write(log_entry)
        logger.info(f"[SENTINEL] Logged command from user {safe_user_id}")
    except Exception as e:
        logger.error(f"[SENTINEL] Failed to log command: {e}")


def validate_task_box_format(response_text):
    """Validate that response is a Task Proposal Box v1"""
    required_markers = [
        "TASK PROPOSAL BOX",
        "TASK_ID:",
        "ENVIRONMENT:",
        "OBJECTIVE:",
        "OPERATION TYPE:",
        "RISK LEVEL:",
        "EXECUTION:",
        "ARCHITECT-ONLY SECTION"
    ]
    for marker in required_markers:
        if marker not in response_text:
            return False, f"Missing required section: {marker}"
    return True, ""


def extract_task_id(response_text):
    """Extract task ID from response if present"""
    match = re.search(r"TASK_ID:\s*([A-Z0-9\-_]+)", response_text)
    if match:
        return match.group(1)
    return None


def generate_proposal(command_text, user_id):
    """
    Generate a Task Proposal Box v1 from command text.
    Uses OpenAI API server-side.
    Returns (success, response_or_error)
    """
    if get_kill_switch_state():
        return False, "KILL_SWITCH_ACTIVE: All Sentinel operations are disabled."
    
    if not command_text or len(command_text.strip()) < 3:
        return False, "Invalid input: Command text too short."
    
    log_command(user_id, command_text, task_id=None, status="pending")
    
    try:
        from openai import OpenAI
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            return False, "Configuration error: Required service unavailable."
        
        client = OpenAI(api_key=api_key)
        
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": SENTINEL_SYSTEM_PROMPT},
                {"role": "user", "content": f"Generate a Task Proposal Box for: {command_text}"}
            ],
            max_tokens=2000,
            temperature=0.3
        )
        
        ai_response = response.choices[0].message.content
        
        is_valid, validation_error = validate_task_box_format(ai_response)
        if not is_valid:
            logger.warning(f"[SENTINEL] Invalid output format: {validation_error}")
            return False, "Invalid output: Must be TASK PROPOSAL BOX (v1) only."
        
        task_id = extract_task_id(ai_response)
        log_command(user_id, command_text, task_id=task_id, status="proposal_generated")
        
        return True, ai_response
        
    except Exception as e:
        logger.error(f"[SENTINEL] Proposal generation failed: {e}")
        return False, f"Service error: Unable to generate proposal."
