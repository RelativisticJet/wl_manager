# Requirements: Whitelist Manager v3.0

**Defined:** 2026-03-31
**Core Value:** SOC analysts can safely edit detection-rule whitelists with confidence that every change is tracked, reviewed, and reversible — and the codebase itself is maintainable, testable, and extensible by future developers.

## v1 Requirements

Requirements for the v3.0 modular rewrite. Each maps to roadmap phases.

### Backend Modularization

- [ ] **BMOD-01**: wl_handler.py split into thin REST router (~200 lines) that delegates to domain modules
- [x] **BMOD-02**: wl_constants.py extracts all magic numbers, regex patterns, role lists, and config defaults
- [x] **BMOD-03**: wl_validation.py provides input sanitization, filename checks, and cell limit enforcement
- [ ] **BMOD-04**: wl_rbac.py handles all role checking and permission enforcement
- [ ] **BMOD-05**: wl_presence.py manages user presence tracking and heartbeat logic
- [ ] **BMOD-06**: wl_csv.py handles CSV read/write, diff computation, and cell operations
- [ ] **BMOD-07**: wl_versions.py manages version snapshots, manifest tracking, and revert operations
- [ ] **BMOD-08**: wl_audit.py constructs structured audit events and posts to wl_audit index
- [x] **BMOD-09**: wl_rules.py manages detection rules registry and rule-to-CSV mapping
- [x] **BMOD-10**: wl_trash.py handles soft-delete, restore, and purge with retention
- [ ] **BMOD-11**: wl_limits.py provides daily usage tracking, reset scheduling, and enforcement
- [ ] **BMOD-12**: wl_approval.py manages approval queue CRUD, request processing, and conflict resolution
- [ ] **BMOD-13**: No function exceeds 100 lines or cyclomatic complexity of 15
- [ ] **BMOD-14**: Consistent error handling pattern (fail-closed with state rollback) across all modules
- [ ] **BMOD-15**: No duplicated logic across backend modules (DRY compliance)

### Frontend Modularization

- [ ] **FMOD-01**: whitelist_manager.js rewritten as thin AMD entry point (~100 lines) loading feature modules
- [ ] **FMOD-02**: wl_constants.js extracts all selectors, config values, and regex patterns
- [ ] **FMOD-03**: wl_rest.js provides shared REST helpers (restGet, restPost) used by all JS files
- [ ] **FMOD-04**: wl_state.js implements singleton state manager for all shared application state
- [ ] **FMOD-05**: Feature modules extracted: wl_table.js, wl_search.js, wl_modals.js, wl_versions.js, wl_approval_ui.js, wl_csv_io.js, wl_presence.js, wl_theme.js, wl_events.js
- [ ] **FMOD-06**: control_panel.js rewritten as thin AMD entry point loading 4 feature modules
- [ ] **FMOD-07**: Control panel modules extracted: wl_cp_queue.js, wl_cp_limits.js, wl_cp_trash.js, wl_cp_settings.js
- [ ] **FMOD-08**: notifications.js refactored to use shared wl_rest.js instead of duplicated helpers

### Testing

- [x] **TEST-01**: Unit test suite covering ≥80% of every backend module (pytest)
- [ ] **TEST-02**: Integration tests for all REST API action handlers against live container
- [ ] **TEST-03**: Security tests for XSS validation, CSRF protection, and input injection
- [ ] **TEST-04**: Concurrency tests for simultaneous saves, approval races, and file locking
- [ ] **TEST-05**: Browser E2E tests for key workflows (load CSV, save, approve, revert)
- [ ] **TEST-06**: Mock Splunk SDK fixtures for offline unit testing

### AppInspect & Documentation

- [ ] **PUBL-01**: AppInspect validation passes with 0 high/critical issues
- [ ] **PUBL-02**: Security architecture document (threat model, RBAC breakdown, data flow)
- [ ] **PUBL-03**: OpenAPI schema documenting all REST API actions, parameters, and responses
- [ ] **PUBL-04**: Backward compatibility verified — existing audit events, version manifests, and approval queues still parse correctly
- [ ] **PUBL-05**: Code maintainability metrics published (CC <15, avg function <100 lines, ≥80% coverage)

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Community & Ecosystem

- **COMM-01**: CONTRIBUTING.md with PR template and code style guide
- **COMM-02**: Published performance benchmarks (load times, bulk operation throughput)
- **COMM-03**: Splunk docs integration (links from official documentation)
- **COMM-04**: GitHub Actions CI/CD pipeline for automated AppInspect + test runs

## Out of Scope

| Feature | Reason |
|---------|--------|
| Framework migration (React, Vue, Alpine) | Violates AppInspect requirement for jQuery + AMD ecosystem |
| New user-facing features | This milestone is purely architectural rework of existing functionality |
| Database migration (PostgreSQL, SQLite) | CSV lookups are the correct Splunk convention for this scale |
| API contract changes | Audit dashboard and existing audit events depend on current request/response shapes |
| External build tools (Webpack, Vite) | AppInspect rejects bundled output; Splunk requires native AMD |
| Python 2 compatibility | Splunk 9.x ships Python 3 only |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| BMOD-01 | Phase 4 | Pending |
| BMOD-02 | Phase 1 | Complete |
| BMOD-03 | Phase 1 | Complete |
| BMOD-04 | Phase 1 | Pending |
| BMOD-05 | Phase 1 | Pending |
| BMOD-06 | Phase 2 | Pending |
| BMOD-07 | Phase 2 | Pending |
| BMOD-08 | Phase 2 | Pending |
| BMOD-09 | Phase 2 | Complete |
| BMOD-10 | Phase 2 | Complete |
| BMOD-11 | Phase 3 | Pending |
| BMOD-12 | Phase 3 | Pending |
| BMOD-13 | Phase 2, Phase 3 | Pending |
| BMOD-14 | Phase 2, Phase 3 | Pending |
| BMOD-15 | Phase 2, Phase 3 | Pending |
| FMOD-01 | Phase 5 | Pending |
| FMOD-02 | Phase 5 | Pending |
| FMOD-03 | Phase 5 | Pending |
| FMOD-04 | Phase 5 | Pending |
| FMOD-05 | Phase 5 | Pending |
| FMOD-06 | Phase 6 | Pending |
| FMOD-07 | Phase 6 | Pending |
| FMOD-08 | Phase 5 | Pending |
| TEST-01 | Phase 1, Phase 2, Phase 3, Phase 4 | Complete |
| TEST-02 | Phase 4 | Pending |
| TEST-03 | Phase 7 | Pending |
| TEST-04 | Phase 3, Phase 7 | Pending |
| TEST-05 | Phase 5, Phase 7 | Pending |
| TEST-06 | Phase 7 | Pending |
| PUBL-01 | Phase 8 | Pending |
| PUBL-02 | Phase 8 | Pending |
| PUBL-03 | Phase 8 | Pending |
| PUBL-04 | Phase 8 | Pending |
| PUBL-05 | Phase 8 | Pending |

**Coverage:**
- v1 requirements: 28 total
- Mapped to phases: 28 ✓
- Unmapped: 0 ✓

---
*Requirements defined: 2026-03-31*
*Last updated: 2026-03-31 after roadmap creation*
