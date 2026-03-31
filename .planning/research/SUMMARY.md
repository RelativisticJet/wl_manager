# Research Summary: Modular Splunk App Architecture

**Domain:** Production-grade Splunk app modularization  
**Researched:** 2026-03-31  
**Overall confidence:** HIGH (architecture patterns) → MEDIUM (Splunk-specific best practices)

## Executive Summary

The Whitelist Manager v3.0 rewrite targets a modular architecture to achieve test coverage, maintainability, and Splunkbase publication readiness. Current monolithic files (`wl_handler.py`: 7,078 lines, `whitelist_manager.js`: 6,786 lines) prevent unit testing and make bug fixes require changes across multiple code paths.

**Key findings:**

1. **Backend modularization is feasible and follows Python conventions** — split `wl_handler.py` into 12 focused modules in `bin/`, using `sys.path` insertion to enable inter-module imports. No circular dependencies if `wl_constants.py` is the single source of truth.

2. **Frontend AMD modularity is well-supported by Splunk's RequireJS infrastructure** — extract features into `modules/` directory, use a singleton state manager (`wl_state.js`) as the only shared data store, and communicate via jQuery event delegation.

3. **Build order matters for testability** — extract dependency-free modules first (constants, validation, RBAC), then core domain modules (CSV, versions, audit), then orchestration (approval, limits), finally the REST handler that ties them together.

4. **API contract must remain frozen** — all changes are internal; the REST endpoint request/response shapes stay unchanged to preserve audit.xml dashboard and existing audit events.

5. **Splunk `bin/` doesn't support packages** — all Python modules must live in the `bin/` directory (no subdirectories). Use absolute imports: `import wl_csv`, not `from . import wl_csv`.

## Key Findings

**Stack:** Python 3.8+ (Splunk 9.x), jQuery + AMD (Splunk Web framework), CSV file storage, JSON manifests for state

**Architecture:** Single REST handler routes to 12 focused domain modules (backend); thin entry point requires 12 AMD modules (frontend); state manager singleton for shared application state

**Critical pitfall:** File locking must stay per-module (don't centralize). Circular imports prevented by constants-first architecture. State mutations must flow through state manager, not direct DOM access.

## Implications for Roadmap

Based on research, the modularization follows this phase structure:

### Phase 1: Foundation (Modules with no inter-dependencies)

**Extract & test:**
- `wl_constants.py` — All magic numbers, config defaults, role lists
- `wl_validation.py` — Input sanitization, filename checks, cell limits
- `wl_rbac.py` — Role checking, permission enforcement
- `wl_presence.py` — User presence tracking, heartbeat logic
- `wl_notifications.py` — Admin notification queue

**Why this order:** These modules have zero dependencies on each other or other domain logic. Can be unit-tested in isolation with mocked file I/O.

**Deliverable:** 5 new modules + 50 unit tests, handler refactored to import and call these modules.

### Phase 2: Core Domain (Modules that depend on Phase 1)

**Extract & test:**
- `wl_csv.py` — CSV read/write, diff computation, cell operations
- `wl_versions.py` — Version snapshots, manifest management, revert
- `wl_audit.py` — Structured event building, index posting, fallback logging
- `wl_rules.py` — Detection rules registry, rule-to-CSV mapping
- `wl_trash.py` — Soft-delete, restore, purge with retention

**Why this order:** These form the data persistence layer. Versioning depends on CSV I/O, trash depends on both. Can be tested with mock Splunk SDK.

**Deliverable:** 5 new modules + 60 unit tests + integration tests for CSV save → version snapshot → audit event chain.

### Phase 3: Orchestration (Complex modules with wide dependencies)

**Extract & test:**
- `wl_limits.py` — Daily usage tracking, reset scheduling, enforcement
- `wl_approval.py` — Approval queue CRUD, request processing, conflict resolution

**Why this order:** These depend on rules, trash, and CSV logic. Approval can auto-cancel conflicting requests if rules/CSVs are deleted.

**Deliverable:** 2 new modules + 40 unit tests + concurrency tests for approval race conditions.

### Phase 4: REST Handler Refactor (Thin router layer)

**Refactor:**
- `wl_handler.py` — Extract action handlers into methods that call domain modules, reduce from 7,078 lines to ~200 lines

**Deliverable:** ~30 small action handler methods + integration tests against live container.

### Phase 5: Frontend Modularization (AMD modules)

**Extract in order:**
1. Create `modules/` directory structure
2. `wl_constants.js` — Selectors, config, regex (used everywhere)
3. `wl_rest.js` — Shared REST helpers (stops 6x duplication)
4. `wl_state.js` — Singleton state manager (all state flows through here)
5. Feature modules: `wl_table.js`, `wl_search.js`, `wl_modals.js`, `wl_versions.js`, `wl_approval_ui.js`, `wl_csv_io.js`, `wl_presence.js`, `wl_theme.js`
6. `wl_events.js` — Event binding and lifecycle
7. `whitelist_manager.js` → Rewrite as thin entry point

**Why this order:** Shared utilities first (rest, constants, state), then features that depend on state, then integration. Event module captures all listeners in one place.

**Deliverable:** 12 modules + rewritten entry point + QUnit tests for state manager and module interactions.

### Phase 6: Admin Panel Modularization

**Repeat for control_panel.js:**
- `modules/wl_cp_queue.js` — Approval queue UI
- `modules/wl_cp_limits.js` — Limits configuration
- `modules/wl_cp_trash.js` — Trash management
- `modules/wl_cp_settings.js` — Settings UI
- `control_panel.js` → Thin entry point (100 lines)

**Deliverable:** 4 modules + entry point refactor.

### Phase 7: Test Coverage & Validation

**Goals:**
- Unit tests: ≥80% coverage per module
- Integration tests: All API action handlers
- E2E tests: Key user workflows (load CSV, save, approve, revert)
- Concurrency tests: Simultaneous saves, approval races
- Security tests: XSS, CSRF, input injection

**Deliverable:** 100+ unit tests, 30+ integration tests, 10+ E2E tests.

### Phase 8: AppInspect & Splunkbase Readiness

**Goals:**
- Pass AppInspect validation (no high/critical issues)
- Backward compatibility verified (existing audit events still parse)
- Code maintainability metrics: Cyclomatic complexity <15, average function <200 lines
- Documentation: Module API docs, contribution guide

**Deliverable:** AppInspect report, documentation.

## Phase Ordering Rationale

**Dependency-first extraction:** Foundation modules → core domain → orchestration → handler ensures each phase can be unit-tested before moving to the next.

**Frontend after backend:** Frontend modules depend on backend API (unchanged) and local state manager. Wait for backend to stabilize.

**Tests integrated into each phase:** Don't defer testing to the end. Each phase ships with its own test suite.

**Migration strategy:** Each phase remains backward-compatible with the REST API contract. Deploy to production incrementally without downtime.

## Research Flags for Phase-Specific Investigation

- **Phase 1–2 (Backend):** Verify that file locking semantics hold when `_csv_file_lock()` is extracted to `wl_csv.py`. Test Windows (no fcntl) behavior.
- **Phase 3 (Approval):** Race condition testing for concurrent approvals. Test auto-cancellation when rules/CSVs are deleted during approval.
- **Phase 5 (Frontend):** Verify AMD module loading order and singleton state manager persistence across page navigation. Test Splunk's i18n cache clearing requirement.
- **Phase 7 (Tests):** Establish mock Splunk SDK patterns for unit tests. Ensure e2e tests don't pollute production Splunk instance.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| **Backend modularity pattern** | HIGH | Python conventions clear, Splunk `bin/` structure understood |
| **Frontend AMD modules** | HIGH | Splunk Web framework well-documented, current app already uses AMD |
| **State manager pattern** | HIGH | jQuery event delegation proven in current code |
| **Phase ordering** | MEDIUM | Inferred from function call graphs; no Splunk docs on large-app modularization |
| **Testing strategy** | MEDIUM | Splunk-specific mocking patterns need validation; test infrastructure works but scale untested |
| **File locking migration** | HIGH | Current code pattern clear; extraction straightforward |
| **Splunk SDK integration** | MEDIUM | Audit indexing and REST API calls must be mocked for unit tests; scope verified but not tested |

## Gaps to Address

1. **Splunk `bin/` module loading timing** — Verify that `sys.path.insert()` in handler doesn't race with other imports. Test in live container.

2. **AMD module circular dependencies** — Confirm that state manager can be required by all feature modules without circular requires (likely fine, but worth testing).

3. **Approval queue concurrency during modularization** — File locking works now, but refactoring approval logic into `wl_approval.py` might introduce subtle race conditions. Needs stress testing.

4. **Frontend module initialization order** — Does Splunk's RequireJS guarantee execution order? Test with slow network to catch async issues.

5. **Backward compatibility of audit events** — Ensure that changes to audit event structure don't break existing searches in audit.xml. Needs audit event validation tests.

## Next Steps

1. **Start Phase 1 research:** Verify file locking behavior when extraction happens. Confirm `sys.path` approach in Docker container.

2. **Create module templates:** Boilerplate for each backend + frontend module type (e.g., "module with file I/O", "module with Splunk SDK calls").

3. **Set up unit test infrastructure:** Pytest fixtures for mocking file I/O, Splunk SDK, JSON manifests.

4. **Build Phase 1 modules:** Implement 5 foundation modules, 50 unit tests, integration test of handler + foundation modules.

---

*Research completed: 2026-03-31 by Phase 6 researcher. Ready for roadmap creation.*

