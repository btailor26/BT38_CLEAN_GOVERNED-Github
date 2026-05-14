# COMMAND PROTOCOL v1

**Version:** 1.0  
**Status:** ACTIVE  
**Effective:** 2025-12-25  
**Author:** Sentinel System  

---

## 1. PURPOSE

This protocol defines the mandatory output format for all Sentinel PLAN-mode responses. Every command validated in PLAN mode must produce a structured task list that enables:

- Human review before any code execution
- Clear audit trail for proposed changes
- Predictable rollback procedures
- Risk assessment prior to implementation

---

## 2. OUTPUT FORMAT

All PLAN-mode outputs must conform to this structure:

```
╔══════════════════════════════════════════════════════════════════════════════╗
║  SENTINEL TASK LIST — [COMMAND SUMMARY]                                      ║
╠══════════════════════════════════════════════════════════════════════════════╣

### FILES TO MODIFY
| # | File Path                    | Action   | Description                |
|---|------------------------------|----------|----------------------------|
| 1 | path/to/file.py             | EDIT     | Brief description          |
| 2 | path/to/new.py              | CREATE   | Brief description          |
| 3 | path/to/old.py              | DELETE   | Brief description          |

### EXECUTION STEPS
1. [ ] Step description (file reference)
2. [ ] Step description (file reference)
3. [ ] Step description (file reference)

### PROOF PLAN
- [ ] Verification method (command, test, or manual check)
- [ ] Expected output or state
- [ ] Success criteria

### ROLLBACK PROCEDURE
```bash
# Commands to reverse all changes
git checkout HEAD -- file1.py file2.py
rm -rf new_directory/
```

### RISKS & MITIGATIONS
| Risk                    | Severity     | Mitigation                     |
|-------------------------|--------------|--------------------------------|
| Description             | LOW/MED/HIGH | Prevention or handling         |

### EXECUTION STATUS
⛔ EXECUTION DISABLED — Review only. Architect approval required.

╚══════════════════════════════════════════════════════════════════════════════╝
```

---

## 3. REQUIRED SECTIONS

| Section            | Required    | Description                                      |
|--------------------|-------------|--------------------------------------------------|
| FILES TO MODIFY    | YES         | Complete list of files affected                  |
| EXECUTION STEPS    | YES         | Ordered steps with checkboxes                    |
| PROOF PLAN         | YES         | How to verify success                            |
| ROLLBACK PROCEDURE | YES         | Commands to reverse changes                      |
| RISKS & MITIGATIONS| YES         | Potential issues and how to handle               |
| KNOWLEDGE COVERAGE | RECOMMENDED | Preflight check for sufficient knowledge         |
| DEPENDENCIES       | NO          | External requirements (APIs, services)           |
| ESTIMATED CHANGES  | NO          | Lines added/modified/deleted                     |
| EXECUTION STATUS   | YES         | Always shows DISABLED in PLAN mode               |

### KNOWLEDGE COVERAGE (RECOMMENDED)

Before proposing a task list, Sentinel should assess knowledge sufficiency:

```
┌─────────────────────────────────────────────────────────────┐
│ KNOWLEDGE COVERAGE: SUFFICIENT                              │
│ Coverage: 85%                                               │
│ Topics Covered: api, rollback, schema                       │
└─────────────────────────────────────────────────────────────┘
```

Or if insufficient:

```
┌─────────────────────────────────────────────────────────────┐
│ KNOWLEDGE COVERAGE: INSUFFICIENT                            │
│ Coverage: 40%                                               │
│ Missing Topics: security, auth                              │
│ Recommendation: Upload documentation covering these topics  │
└─────────────────────────────────────────────────────────────┘
```

NOTE: This section is RECOMMENDED, not REQUIRED. It helps prevent confident guessing.

### SCOPE LOCK (RECOMMENDED)

Before proposing file modifications, Sentinel should validate scope:

```
┌─────────────────────────────────────────────────────────────┐
│ SCOPE CHECK: VALID                                          │
│ Files: 3 allowed, 0 rejected                                │
│ Allowlist: sentinel/*, services/sentinel_*.py               │
└─────────────────────────────────────────────────────────────┘
```

Or if scope violation detected:

```
┌─────────────────────────────────────────────────────────────┐
│ SCOPE CHECK: REJECTED                                       │
│ Allowed: sentinel/phase2.py                                 │
│ Rejected: routes.py, models.py                              │
│ Reason: 2 file(s) outside allowed scope                     │
│ Action: Request Architect to expand allowlist               │
└─────────────────────────────────────────────────────────────┘
```

NOTE: This section is RECOMMENDED, not REQUIRED. It prevents scope creep in task lists.

---

## 4. ACTION TYPES

Valid actions for FILES TO MODIFY:

| Action  | Description                              |
|---------|------------------------------------------|
| CREATE  | New file will be created                 |
| EDIT    | Existing file will be modified           |
| DELETE  | File will be removed                     |
| RENAME  | File will be renamed (specify old→new)   |
| MOVE    | File will be relocated                   |

---

## 5. SEVERITY LEVELS

Risk severity classification:

| Level | Criteria                                              |
|-------|-------------------------------------------------------|
| LOW   | Easily reversible, no data loss, no service impact    |
| MED   | Requires careful rollback, potential brief disruption |
| HIGH  | Data migration, service downtime, or breaking changes |

---

## 6. PROTOCOL RULES

1. **NO EXECUTION IN PLAN MODE**  
   Task lists are proposals only. Code is never executed.

2. **ARCHITECT APPROVAL REQUIRED**  
   Human must explicitly approve before implementation begins.

3. **ROLLBACK ALWAYS DEFINED**  
   Every proposal must include complete reversal procedure.

4. **PROOF IS MANDATORY**  
   Every change must have verification steps defined.

5. **PROTOCOL IS SOURCE OF TRUTH**  
   This document in `sentinel/protocols/` is authoritative.  
   Knowledge Vault copies are convenience only.

6. **VERSION REFERENCE**  
   All outputs must reference protocol version in header.

---

## 7. APPROVAL WORKFLOW

```
┌─────────────────┐
│ Command Input   │
└────────┬────────┘
         ▼
┌─────────────────┐
│ Sentinel PLAN   │──→ Outputs TASK LIST (Protocol v1)
└────────┬────────┘
         ▼
┌─────────────────┐
│ Architect Review│──→ APPROVE / REJECT / REQUEST CHANGES
└────────┬────────┘
         ▼
┌─────────────────┐
│ Implementation  │──→ Only after explicit approval
└─────────────────┘
```

---

## 8. VERSIONING

- **v1.0** (2025-12-25): Initial protocol specification
- Future versions will use semantic versioning (v1.1, v2.0)
- Breaking changes require major version increment
- Protocol changes require Architect approval

---

## 9. EXAMPLES

### Example: Simple File Edit

```
╔══════════════════════════════════════════════════════════════════════════════╗
║  SENTINEL TASK LIST — UPDATE CONFIG DEFAULT                                  ║
╠══════════════════════════════════════════════════════════════════════════════╣

### FILES TO MODIFY
| # | File Path        | Action | Description               |
|---|------------------|--------|---------------------------|
| 1 | config/app.py    | EDIT   | Change timeout from 30→60 |

### EXECUTION STEPS
1. [ ] Edit config/app.py line 42: TIMEOUT = 60

### PROOF PLAN
- [ ] grep "TIMEOUT = 60" config/app.py returns match
- [ ] App restarts without errors

### ROLLBACK PROCEDURE
```bash
git checkout HEAD -- config/app.py
```

### RISKS & MITIGATIONS
| Risk              | Severity | Mitigation                |
|-------------------|----------|---------------------------|
| Longer wait times | LOW      | Monitor user feedback     |

### EXECUTION STATUS
⛔ EXECUTION DISABLED — Review only. Architect approval required.

╚══════════════════════════════════════════════════════════════════════════════╝
```

---

## 10. COMPLIANCE

Non-compliant outputs are invalid and must be regenerated.  
Architect may reject task lists that do not follow this protocol.

---

**END OF PROTOCOL v1**
