# Whitelist Manager v3.0 — Modular Rewrite Roadmap

**Project:** Whitelist Manager for Splunk Enterprise Security (v3.0)  
**Core Value:** SOC analysts can safely edit whitelists with full audit trail — and the codebase is maintainable, testable, and ready for Splunkbase publication.

**Phases:** 8  
**Granularity:** Standard  
**Coverage:** 28/28 v1 requirements mapped ✓

---

## Phases

- [x] **Phase 1: Backend Foundation** - Extract dependency-free backend modules (constants, validation, RBAC, presence)
- [ ] **Phase 2: Backend Core Domain** - Extract data persistence layer (CSV, versions, audit, rules, trash)
- [ ] **Phase 3: Backend Orchestration** - Extract approval queue and daily limits management
- [ ] **Phase 4: Backend Integration** - Refactor wl_handler.py as thin REST router
- [ ] **Phase 5: Frontend Architecture** - Extract frontend modules and implement state manager
- [ ] **Phase 6: Admin Panel** - Modularize control_panel.js and associated feature modules
- [ ] **Phase 7: Test Coverage** - Unit, integration, E2E, concurrency, and security test suites
- [ ] **Phase 8: Splunkbase Readiness** - AppInspect validation, documentation, backward compatibility verification

---

## Phase Details

### Phase 1: Backend Foundation

**Goal:** Extract 5 dependency-free backend modules with zero inter-module dependencies, establishing the foundation for all subsequent backend work.

**Depends on:** None (foundational phase)

**Requirements:** BMOD-02, BMOD-03, BMOD-04, BMOD-05, TEST-01 (partial)

**Success Criteria** (what must be TRUE when phase completes):
1. User can load the app and use CSV editor/audit features without functional change (all features still work via existing REST API)
2. Six new Python modules exist in `bin/` and are imported by wl_handler.py: wl_constants.py, wl_logging.py, wl_validation.py, wl_ratelimit.py, wl_rbac.py, wl_presence.py
3. All magic numbers, regex patterns, role lists, and config defaults are defined in wl_constants.py and used throughout backend (no hardcoded values in other modules)
4. Every new module has ≥80% unit test coverage with mocked file I/O and Splunk SDK calls
5. Existing audit events, version manifests, and approval queues continue to function (no API contract change)

**Plans:** 4 plans in 2 waves

- [x] **01-01-PLAN.md** — Test infrastructure (pytest setup, conftest fixtures, Splunk SDK stub) — COMPLETED
  - Requirements: TEST-01
  - Files: tests/conftest.py, tests/pytest.ini, tests/stubs/splunk/rest.py, requirements-dev.txt
  - Tasks: 5 (requirements-dev.txt, pytest.ini, stubs, global fixtures, unit fixtures)

- [x] **01-02-PLAN.md** — Extract wl_constants.py (Layer 0) — COMPLETED
  - Requirements: BMOD-02
  - Files: bin/wl_constants.py, bin/wl_handler.py, tests/unit/test_constants.py
  - Tasks: 3 (create wl_constants.py, update wl_handler imports, create unit tests)
  - Depends on: 01-01

- [x] **01-03-PLAN.md** — Extract wl_logging.py and wl_validation.py (Layer 1-2) — COMPLETED
  - Requirements: BMOD-03
  - Files: bin/wl_logging.py, bin/wl_validation.py, bin/wl_handler.py, tests/unit/test_logging.py, tests/unit/test_validation.py
  - Tasks: 5 (create wl_logging, create wl_validation, update handler, test logging, test validation)
  - Status: 5/5 tasks completed, 33 tests (32 passed, 1 skipped), 93%+ coverage
  - Depends on: 01-02

- [x] **01-04-PLAN.md** — Extract wl_ratelimit.py, wl_rbac.py, wl_presence.py (Layer 2) — COMPLETED
  - Requirements: BMOD-04, BMOD-05, TEST-01
  - Files: bin/wl_ratelimit.py, bin/wl_rbac.py, bin/wl_presence.py, bin/wl_handler.py, tests/unit/test_*.py
  - Tasks: 5 (create ratelimit, create rbac, create presence, update handler, create 3x unit tests)
  - Status: 5/5 tasks completed, 62 tests, 97% coverage (100% presence, 99% rbac, 86% ratelimit)
  - Depends on: 01-03

**Wave Structure:**
- **Wave 1:** 01-01 (test infrastructure), 01-02 (constants foundation)
- **Wave 2:** 01-03 (logging/validation), 01-04 (ratelimit/rbac/presence)

---

### Phase 2: Backend Core Domain

**Goal:** Extract 5 data persistence layer modules that depend on Phase 1, establishing the CSV I/O, versioning, auditing, and trash systems.

**Depends on:** Phase 1

**Requirements:** BMOD-06, BMOD-07, BMOD-08, BMOD-09, BMOD-10, BMOD-13 (partial), BMOD-14 (partial), BMOD-15 (partial), TEST-01 (partial)

**Success Criteria** (what must be TRUE when phase completes):
1. User can load a CSV and save changes with version snapshots recorded, all as before (no functional change)
2. Five new modules exist and are imported: wl_csv.py, wl_versions.py, wl_audit.py, wl_rules.py, wl_trash.py
3. No cyclomatic complexity in any module exceeds 15; no function exceeds 100 lines
4. CSV diff computation, version snapshots, audit event construction, and trash operations all have ≥80% unit test coverage
5. Integration tests verify end-to-end chain: CSV save → version snapshot → audit event posting → trash soft-delete (all work as before)
6. DRY compliance: no duplicated logic for version snapshots, diff computation, or audit field construction across modules

**Plans:** 4 plans in 3 waves

- [ ] **02-01-PLAN.md** — Extract wl_csv.py (Layer 3, Wave 1)
  - Requirements: BMOD-06
  - Files: bin/wl_csv.py, tests/unit/test_csv.py, bin/wl_handler.py (wire imports)
  - Tasks: 3 (create wl_csv.py, unit tests, wire handler calls)

- [ ] **02-02-PLAN.md** — Extract wl_rules.py and wl_trash.py (Layer 3, Wave 1)
  - Requirements: BMOD-09, BMOD-10
  - Files: bin/wl_rules.py, bin/wl_trash.py, tests/unit/test_rules.py, tests/unit/test_trash.py, bin/wl_handler.py
  - Tasks: 5 (create wl_rules, create wl_trash, unit tests for each, wire handler)
  - Depends on: 02-01

- [ ] **02-03-PLAN.md** — Extract wl_versions.py (Layer 3, Wave 2)
  - Requirements: BMOD-07
  - Files: bin/wl_versions.py, tests/unit/test_versions.py, bin/wl_handler.py
  - Tasks: 3 (create wl_versions, unit tests, wire handler)
  - Depends on: 02-01 (calls wl_csv.read_csv, write_csv)

- [ ] **02-04-PLAN.md** — Extract wl_audit.py and integration tests (Layer 3, Wave 3)
  - Requirements: BMOD-08, BMOD-13, BMOD-14, BMOD-15, TEST-01
  - Files: bin/wl_audit.py, tests/unit/test_audit.py, tests/integration/test_persistence.py, bin/wl_handler.py
  - Tasks: 5 (create wl_audit, unit tests, integration tests, wire handler, verify phase completion)
  - Depends on: 02-03 (imports from all Phase 2 modules)

**Wave Structure:**
- **Wave 1:** 02-01 (wl_csv), 02-02 (wl_rules, wl_trash) — independent extraction
- **Wave 2:** 02-03 (wl_versions) — depends on 02-01 for CSV operations
- **Wave 3:** 02-04 (wl_audit + integration) — depends on all Phase 2 modules, final wiring

---

### Phase 3: Backend Orchestration

**Goal:** Extract 2 complex orchestration modules with wide dependencies on Phase 1 and Phase 2, establishing approval queue and daily limits enforcement.

**Depends on:** Phase 1, Phase 2

**Requirements:** BMOD-11, BMOD-12, BMOD-13 (partial), BMOD-14 (partial), BMOD-15 (partial), TEST-01 (partial), TEST-04 (partial)

**Success Criteria** (what must be TRUE when phase completes):
1. User can submit an edit for approval and admin can approve/reject with correct audit trail, all as before (no functional change)
2. Two new modules exist and are imported: wl_limits.py, wl_approval.py
3. Approval queue auto-cancels conflicting pending requests when a destructive action (delete rule/CSV) is approved
4. Daily limits check passes for all role tiers; reset scheduling works across phase boundaries
5. Concurrency tests pass for simultaneous CSV saves, approval races, and file locking under contention (5+ concurrent threads)
6. Every module has ≥80% unit test coverage; no function >100 lines; CC <15 for all

**Plans:** 2 plans in 2 waves

- [ ] **03-01-PLAN.md** — Extract wl_limits.py (Layer 4, Wave 1)
  - Requirements: BMOD-11, BMOD-13, BMOD-14, BMOD-15, TEST-01
  - Files: bin/wl_limits.py, tests/unit/test_limits.py, bin/wl_handler.py
  - Tasks: 3 (create wl_limits.py, unit tests, wire handler)

- [ ] **03-02-PLAN.md** — Extract wl_approval.py and concurrency tests (Layer 4, Wave 2)
  - Requirements: BMOD-12, BMOD-13, BMOD-14, BMOD-15, TEST-01, TEST-04
  - Files: bin/wl_approval.py, tests/unit/test_approval.py, tests/integration/test_approval_chain.py, tests/integration/test_concurrency.py, bin/wl_handler.py
  - Tasks: 6 (create wl_approval.py, unit tests, integration tests, concurrency tests, wire handler, verify phase completion)
  - Depends on: 03-01 (approval gating checks daily limits)

**Wave Structure:**
- **Wave 1:** 03-01 (wl_limits) — foundation for approval gating
- **Wave 2:** 03-02 (wl_approval + tests) — depends on wl_limits for daily limit checks

---

### Phase 4: Backend Integration

**Goal:** Refactor wl_handler.py as a thin REST router that delegates to Phase 1–3 modules, completing backend modularization.

**Depends on:** Phase 1, Phase 2, Phase 3

**Requirements:** BMOD-01, TEST-01 (partial), TEST-02

**Success Criteria** (what must be TRUE when phase completes):
1. User can perform all CSV operations (load, edit, save, revert, add rule, delete rule, approve) with zero functional change
2. wl_handler.py is rewritten as a thin router (~200 lines): action dispatchers call domain modules instead of monolithic inline code
3. All 15+ REST action handlers (get_csv, save_csv, add_rule, delete_rule, process_approval, etc.) are tested with live Splunk container
4. Integration tests verify all action → module call → audit event chain works end-to-end
5. Existing API contract preserved: no request/response shape changes; audit.xml dashboard continues working

**Plans:** TBD

---

### Phase 5: Frontend Architecture

**Goal:** Extract frontend into 12 AMD modules with a centralized state manager, establishing modular component architecture and eliminating REST helper duplication.

**Depends on:** Phase 4 (backend must be stable)

**Requirements:** FMOD-01, FMOD-02, FMOD-03, FMOD-04, FMOD-05, FMOD-08, TEST-05 (partial)

**Success Criteria** (what must be TRUE when phase completes):
1. User can load the whitelist manager dashboard and use all features (table, search, modals, versions, approvals) with zero functional change
2. 12 new frontend AMD modules exist in `appserver/static/modules/` and are required by whitelist_manager.js entry point
3. wl_rest.js shared REST helpers are used by whitelist_manager.js, control_panel.js, and notifications.js (no more 6x duplication)
4. wl_state.js singleton manages all shared state (currentRows, originalRows, selectedRows, etc.); all state mutations flow through it
5. whitelist_manager.js is rewritten as thin entry point (~100 lines) that requires feature modules
6. QUnit tests verify state manager transitions, module interactions, and AMD module loading order (including slow network scenarios)

**Plans:** TBD

---

### Phase 6: Admin Panel

**Goal:** Modularize control_panel.js into 4 feature modules, completing frontend architecture.

**Depends on:** Phase 5

**Requirements:** FMOD-06, FMOD-07

**Success Criteria** (what must be TRUE when phase completes):
1. Admin user can access Control Panel and manage approval queue, daily limits, trash, and settings with zero functional change
2. 4 new admin panel modules exist: wl_cp_queue.js, wl_cp_limits.js, wl_cp_trash.js, wl_cp_settings.js
3. control_panel.js is rewritten as thin entry point (~100 lines) that requires admin feature modules
4. All modules use shared wl_rest.js helpers (no duplicated REST logic)
5. QUnit tests verify approval queue display, limit enforcement UI, trash restore/purge, and settings persistence

**Plans:** TBD

---

### Phase 7: Test Coverage & Validation

**Goal:** Implement comprehensive test suites (unit, integration, E2E, concurrency, security) achieving ≥80% coverage and validating all edge cases.

**Depends on:** Phase 4 (backend), Phase 6 (frontend complete)

**Requirements:** TEST-01, TEST-02, TEST-03, TEST-04, TEST-05, TEST-06

**Success Criteria** (what must be TRUE when phase completes):
1. Unit test suite passes: ≥80% coverage for all backend modules, ≥80% for state manager and key frontend modules
2. Integration tests pass: all REST action handlers tested against live Splunk container (get_csv, save_csv, add_rule, approve, revert, etc.)
3. Security tests pass: XSS validation, CSRF protection, input injection attacks all blocked at frontend and backend
4. Concurrency tests pass: simultaneous CSV saves, approval races, file locking under 5+ thread contention
5. E2E browser tests pass: load CSV, save changes, request approval, admin approves, revert to previous version (using Playwright or Puppeteer)
6. Mock Splunk SDK fixtures created for offline unit testing (no container required for unit tests)

**Plans:** TBD

---

### Phase 8: Splunkbase Readiness

**Goal:** Validate production readiness, AppInspect compliance, backward compatibility, and complete documentation for Splunkbase publication.

**Depends on:** Phase 7

**Requirements:** PUBL-01, PUBL-02, PUBL-03, PUBL-04, PUBL-05

**Success Criteria** (what must be TRUE when phase completes):
1. AppInspect validation passes with 0 high/critical issues; all warnings documented
2. Security architecture document published: threat model, RBAC breakdown, data flow diagram, audit event structure
3. OpenAPI schema published documenting all REST API actions (get_csv, save_csv, etc.), parameters, responses, and error codes
4. Backward compatibility verified: existing audit events parse correctly in audit.xml, version manifests load, approval queues process as before
5. Code maintainability metrics published: all modules with CC <15, average function <100 lines, ≥80% test coverage per module

**Plans:** TBD

---

## Progress Tracking

| Phase | Plans | Status | Started | Completed |
|-------|-------|--------|---------|-----------|
| 1. Backend Foundation | 4 plans | Planning complete | — | — |
| 2. Backend Core Domain | 4 plans | Planning complete | — | — |
| 3. Backend Orchestration | 2 plans | Planning complete | — | — |
| 4. Backend Integration | TBD | Not started | — | — |
| 5. Frontend Architecture | TBD | Not started | — | — |
| 6. Admin Panel | TBD | Not started | — | — |
| 7. Test Coverage & Validation | TBD | Not started | — | — |
| 8. Splunkbase Readiness | TBD | Not started | — | — |

---

## Notes

- **Research-driven structure:** Phase ordering derived from dependency analysis in research/SUMMARY.md (dependency-first extraction pattern)
- **Backward compatibility critical:** Each phase maintains the REST API contract — no request/response shape changes
- **Zero downtime:** Each phase produces a working app; can deploy incrementally
- **Testing integrated:** Every phase includes its own test suite (not deferred to Phase 7)
- **Frontend depends on backend:** Phase 5 starts only after Phase 4 completes to ensure stable API
- **Phase 1 planning complete:** 4 executable plans with 2-wave structure, ≥80% coverage targets, ready for execution
- **Phase 2 planning complete:** 4 executable plans with 3-wave structure, 5 modules extracted, integration tests for persistence chain, ready for execution
- **Phase 3 planning complete:** 2 executable plans with 2-wave structure, wl_limits + wl_approval with concurrency tests (5+ threads), ready for execution
