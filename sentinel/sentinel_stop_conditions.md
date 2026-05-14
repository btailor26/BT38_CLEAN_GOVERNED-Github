# Sentinel Global STOP CONDITIONS

IMMEDIATE HALT IF:
- Any execution flag is enabled in PLAN mode.
- Any command attempts to run without approval.
- Any required disclosure field is missing.
- Any file outside scope is read or written.
- Any checksum, size, or validation fails.
- Any unexpected output appears.

ON STOP:
- Block all further actions.
- Record evidence.
- Require Architect review before retry.
