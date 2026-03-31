# Whitelist Manager v3.0 — Full Rewrite

## What This Is

A Splunk app that lets SOC analysts manage detection-rule CSV whitelists through a web UI with full audit trail, approval workflows, version control, and RBAC. Currently at v2.0 (Build 482) with all features shipped and production-ready from a security standpoint. This milestone is a full architectural rewrite to achieve production-grade maintainability, modularity, test coverage, and code quality — targeting Splunkbase publication.

## Core Value

SOC analysts can safely edit detection-rule whitelists with confidence that every change is tracked, reviewed, and reversible — and the codebase itself is maintainable, testable, and extensible by future developers.

## Requirements

### Validated

- ✓ CSV viewing/editing with inline cell editing — existing
- ✓ Row add/remove with per-row or bulk operations and required reasons — existing
- ✓ Search bar with clear button (Detection Rule and CSV search) — existing
- ✓ Horizontal scroll for wide CSVs (tested 100 columns) — existing
- ✓ CSV version control with revert dropdown (last 5 versions) — existing
- ✓ Full audit trail with similarity-based diff detection — existing
- ✓ Revert with reason popup, version traceability, `*back` prefixed audit fields — existing
- ✓ Auto-expiration of rows with Expires column — existing
- ✓ Dark/light theme support — existing
- ✓ 4-tier RBAC (viewer, editor, admin, superadmin) — existing
- ✓ Approval workflow with daily limits — existing
- ✓ Dual-admin approval for destructive operations — existing
- ✓ Control panel for admin settings (trash, limits, approval queue) — existing
- ✓ Notification system (toast notifications for approvals/rejections) — existing
- ✓ Detection rules registry with create/remove — existing
- ✓ Trash/restore for deleted rules and CSVs — existing
- ✓ Presence tracking (who's editing) — existing
- ✓ Optimistic locking (mtime-based conflict detection) — existing

### Active

- [ ] Modular backend architecture (split wl_handler.py into focused modules)
- [ ] Modular frontend architecture (split JS into AMD modules via RequireJS)
- [ ] Shared REST helper module (eliminate 6x duplication across JS files)
- [ ] Named constants for all magic numbers and configuration values
- [ ] Comprehensive unit test suite (every backend module)
- [ ] Comprehensive integration test suite (all API actions)
- [ ] Browser E2E tests for key workflows
- [ ] Concurrency test coverage (concurrent writes, approval races)
- [ ] Security test coverage (XSS validation, CSRF, input injection)
- [ ] Reduced cyclomatic complexity (no function >100 lines, CC <15)
- [ ] DRY compliance (no duplicated logic across modules)
- [ ] Consistent error handling patterns across all modules
- [ ] AppInspect compliance for Splunkbase publication
- [ ] Splunk ecosystem compatibility (jQuery + AMD, no external build tools)

### Out of Scope

- Framework migration (React, Preact, Alpine.js) — must stay within Splunk's jQuery + AMD ecosystem for AppInspect compliance
- New features — this milestone is purely architectural rework of existing functionality
- Database migration — CSV lookups remain the data store (Splunk convention)
- API contract changes — frontend/backend API shape stays the same to preserve audit dashboard compatibility

## Context

### Pre-Production Audit Results (2026-03-31)

Three independent security auditors confirmed production readiness:
- Security Reviewer: APPROVED (0 critical, 1 high — error message wording, fixed)
- OWASP Auditor: Grade A (36 checks, all low severity)
- Contract Auditor: READY (all actions, parameters, responses match)

### Code Quality Audit Findings

- 43 findings (12 high, 18 medium, 13 low) — all maintainability, not security
- Top issues: monolithic files, REST helper duplication, high cyclomatic complexity
- Dead code audit: clean (no unused functions, imports, or commented-out blocks)

### Concurrency Audit — 2 High-Severity Fixed

- Approval queue: `_approval_queue_lock()` now used consistently (threading.RLock + file lock)
- Detection rules registry: `_detection_rules_modify()` context manager added for all write paths

### Current Architecture Pain Points

| Issue | Impact |
|-------|--------|
| `wl_handler.py` (7,078 lines) | Cannot test individual modules, hard to navigate |
| `whitelist_manager.js` (6,786 lines) | No component reuse, tangled state |
| `control_panel.js` (2,025 lines) | Duplicates REST helpers from main JS |
| `_save_csv_inner` CC=28 | Combines validation, execution, audit, versioning |
| `_process_approval_inner` 960 lines | Monolithic approval dispatcher |
| 6 identical restGet/restPost | Bug fix requires 3 file updates |

### Target Module Structure (Backend)

```
bin/
  wl_handler.py          → Thin REST router (~200 lines)
  wl_csv.py              → CSV read/write/diff operations
  wl_versions.py         → Version control and snapshots
  wl_approval.py         → Approval queue and workflow
  wl_rbac.py             → Role checking and permissions
  wl_audit.py            → Audit event construction and indexing
  wl_limits.py           → Daily limits and rate limiting
  wl_trash.py            → Trash management
  wl_rules.py            → Detection rules registry
  wl_presence.py         → Presence tracking
  wl_validation.py       → Input sanitization and validation
  wl_constants.py        → All magic numbers, regex patterns, config
```

### Target Module Structure (Frontend)

```
appserver/static/
  whitelist_manager.js   → Entry point, AMD loader (~100 lines)
  modules/
    wl_rest.js           → Shared REST helpers (restGet, restPost)
    wl_table.js          → Table rendering, inline editing, cell tracking
    wl_search.js         → Search/filter functionality
    wl_modals.js         → All modal dialogs (add row, remove, revert, etc.)
    wl_versions.js       → Version dropdown and revert UI
    wl_approval_ui.js    → Approval gate checks, submission, status display
    wl_csv_io.js         → CSV import/export, file operations
    wl_presence.js       → Presence tracking UI
    wl_state.js          → State management (currentRows, originalRows, etc.)
    wl_events.js         → Event binding and delegation
    wl_theme.js          → Dark/light theme toggle
    wl_constants.js      → Magic numbers, selectors, config
  control_panel.js       → Entry point for admin panel
  modules/
    wl_cp_queue.js       → Approval queue management UI
    wl_cp_limits.js      → Daily limits management UI
    wl_cp_trash.js       → Trash management UI
    wl_cp_settings.js    → Admin settings UI
  notifications.js       → Notification system (uses wl_rest.js)
```

## Constraints

- **Splunk ecosystem**: Must use jQuery + AMD (RequireJS). No npm, no bundlers, no external frameworks. AppInspect must pass.
- **API stability**: REST API contract (actions, parameters, response shapes) must not change — audit.xml dashboard and existing audit events depend on it.
- **Zero downtime**: Each phase must produce a working app. No "big bang" switch.
- **Backward compatibility**: Existing CSV data, version manifests, approval queues, and audit events must continue working.
- **Python 3 only**: Splunk 9.x ships Python 3. No Python 2 compatibility needed.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Full rewrite over incremental refactor | User preference — highest quality outcome, willing to accept risk | — Pending |
| Stay within Splunk ecosystem (jQuery + AMD) | AppInspect compliance for Splunkbase publication | — Pending |
| Comprehensive test suite | Fill all gaps identified in audit (concurrency, security, integration, E2E) | — Pending |
| Maintain API contract | Preserve audit dashboard, existing events, version manifests | — Pending |

---
*Last updated: 2026-03-31 after initialization*
