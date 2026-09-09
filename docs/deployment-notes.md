# Deployment notes

## 2026-09-09 — Superseded FBM presentation contract removed

`tests/test_fbm_promise_tracking_presentation_alignment_contract.py` was removed from the repository and from the governed Fly deployment contract list.

Reason: the test referenced the removed `services/fbm_current_queue_health_alignment.py` implementation and required `install_fbm_current_queue_health_alignment`, while the current governed runtime uses `services/governed_fbm_all_orders_health_alignment.py` together with `services/governed_fbm_overdue_alert_alignment.py`.

The removed test was therefore stale implementation coupling, not a valid production deployment requirement. Do not recreate `fbm_current_queue_health_alignment.py` merely to satisfy this historical contract.

Current authority remains the existing governed DB/session-snapshot FBM health path. This note does not waive current deployment checks; the exact candidate SHA must still pass the active deployment contracts and required CI before production deployment.
