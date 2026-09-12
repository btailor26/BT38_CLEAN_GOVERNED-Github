# BT38 Operational Governance Rules

BT38 must follow one clear path:

Settings Control Center
→ BT38 Command Center
→ Governance Guard
→ Queue / Scheduler
→ Runtime Services
→ Logging + Audit

No deploy without approval.
Production code and deployment context must come only from an exact GitHub
commit. Never clone, copy, overlay, build, test, or deploy application files
from an operator's PC. The operator's PC may open GitHub Actions and inspect
Fly, but it is never a BT38 source or build machine.
All production deployments must use the manually approved GitHub Actions
workflow and Fly remote builder. Direct `fly deploy` from an operator PC is
prohibited.

## Production-only commercial runtime

BT38 is a live commercial production system. **Do not use a test/staging runtime, test Fly app, test database, test marketplace account, test deployment, or non-production clone as the authority for runtime behaviour or release decisions.**

The production system contains commercial state, integrations, secrets, subscriptions, marketplace identities and operational history that are not guaranteed to exist in any test environment. A failure caused by missing/non-equivalent test state must never be treated as proof that the production application is broken.

When runtime proof is required, audit the exact GitHub source and the existing production configuration/data path, then use the governed production deployment workflow only after explicit user approval of the exact commit. Never route a commercial change through a test deployment first.

GitHub source-level checks such as compile, syntax, static contract assertions and deployment-source guards are allowed because they do not create or use a test runtime. They must not be described as a test deployment or substitute for production evidence.

No production secrets changed.
No duplicate routes.
No direct marketplace push/sync/import from pages long term.
Warehouse is source of truth.
FBA is read-only.
FBM is warehouse-authoritative.
Reverse sync is disabled by default.
Use existing logging: SystemEvent, ConfigChangeLog, SystemConfig, SystemLog.
Every change must follow: audit, backup, replace full block, verify, syntax check, git diff, no deploy, approval.

## Mandatory change alignment and enhancement workflow

Every BT38 change must be treated as part of the existing system, not as an isolated feature. A change is not complete merely because its own code works.

Every change must follow this lifecycle:

`CHANGE -> ALIGNMENT -> ENHANCEMENT -> PROOF`

### Change

Implement the requested behaviour through the existing BT38 authorities, services, models, routes, projections and governed paths wherever they already exist. Preserve functionality that is already working and do not replace a proven authority simply to make a new feature easier to implement.

### Alignment

After every change, audit the connected system boundaries affected by it. This includes, where relevant: application startup and import order; existing services and authorities; database/schema contracts; API and route contracts; UI/layout and session behaviour; marketplace/provider authority; governed sync/write rules; Warehouse/Product Linking/FBA/FBM boundaries; workers, queues and schedulers; logging/audit paths; runtime configuration; deployment contracts; and existing regression checks.

A feature that works in isolation but is not aligned with the assembled BT38 system is **incomplete**.

### Enhancement

When a change exposes an outdated assumption, weak integration, missing handoff or obsolete connected behaviour, enhance the existing connected path as part of completing the change. Prefer strengthening the existing authority over adding a workaround.

Enhancement is controlled. Improve only the connected components required to leave the changed path better aligned and more robust. Do not expand into unrelated areas merely because they could also be improved.

Do not create duplicate systems, parallel authorities, unnecessary tables, workers, pollers, routes, event transports, notification systems or workaround layers when an existing BT38 path should be extended or corrected.

### Proof

Every change must prove both the requested behaviour and preservation of connected existing behaviour. Regression proof must cover the affected boundaries, not only the new function.

Before production deployment, the exact candidate GitHub commit must receive the applicable whole-system source-level proof, including startup/import compatibility, compile/syntax, static contracts, database compatibility, UI/API contracts and governed-runtime boundaries. Missing, stale, mismatched or unclear evidence means **NOT PROVEN** and must never be treated as a pass.

Production deployment still requires explicit approval of the exact GitHub commit. After deployment, verify the actual production image/runtime and the affected end-to-end functions before declaring the change complete. A successful workflow or machine start alone is not proof that the application behaviour is healthy.

## Mandatory event-driven/session-driven workflow

All improvement and alignment work must follow `docs/EVENT_DRIVEN_SESSION_WORKFLOW.md`.

BT38 UI/runtime freshness is **zero polling**. Do not introduce timers, long polling, heartbeat reads/writes, wake hydration, recurring notification reads or background page refreshes to discover changes.

After canonical truth commits, use the existing governed event/handoff system. The event must carry the exact affected record identity and the already-known fields required by the visible projection. The receiving browser keeps its existing session and changes only that exact record/projection.

Do not respond to a normal event by reloading/refetching the page, rebuilding a table, rerunning the initial page query, loading a broad snapshot, recreating an open workspace/modal, or discarding browser-local tab/search/filter/page/selection/scroll state.

Same-page actions and cross-page events obey the same path:

`canonical action/event -> DB commit -> exact affected-record event/response -> existing handoff -> exact record update in current session -> sleep`

No second EventSource/SSE transport, event bus, notification system, browser watcher, refresh controller or parallel handoff path may be added.

No event means no UI-driven work. Pages, bell and handoff remain asleep with zero presentation-driven DB activity.

The notification bell is informational only and must remain **zero-query**. It consumes already-published in-memory event information and must never query Neon, marketplace/provider APIs, orders, shipments, listings, Warehouse or audit logs to determine what happened.

Every change touching UI freshness, events, marketplace handoff, shipping/dispatch, notifications or session behaviour must include a regression contract proving: zero polling; no broad event-triggered reread/rebuild; no parallel transport; exact affected identity; session preservation; exact-record update only.

Current approved branch scope for `fix/full-system-release-alignment` includes the governed event-driven Amazon/eBay order and webhook execution, Warehouse/Product Linking authority alignment, MCF/FBA read-only handling, FBM/Packlink shipping, exact marketplace destination hydration, marketplace dispatch confirmation, shipment/bell audit visibility, tracking journey display from provider/platform data, and standalone manual shipping. This approval is for audit and GitHub source-level verification only. It does **not** authorize a test/staging deployment, merge, or an unreviewed production source change. Any production deployment still requires explicit approval of the exact GitHub commit.
