# Phase 7: Test Coverage & Validation - Context

**Gathered:** 2026-04-02
**Status:** Ready for planning

<domain>
## Phase Boundary

Implement comprehensive test suites (unit, integration, E2E, concurrency, security) achieving >=80% coverage for all backend and key frontend modules. Fix existing test failures, audit and migrate legacy tests, extend QUnit frontend tests, and produce a documented test infrastructure with coverage reports. This phase validates the entire v3.0 modular rewrite before Splunkbase readiness (Phase 8).

</domain>

<decisions>
## Implementation Decisions

### E2E Browser Testing

- **Tool**: Playwright (Python bindings, `playwright-python`) — integrates with existing pytest infrastructure
- **Workflows covered**: All four — Core CRUD, Approval workflow (approve + reject paths), Version revert, Admin panel
- **Test count target**: 20-30 comprehensive tests including edge cases (empty CSV, wide CSV, error states, search/filter)
- **Container mode**: Dual — default assumes `wl_manager_test` container is running; `--start-container` CI flag triggers auto-start via docker-compose
- **Browser mode**: Headless by default, `--headed` flag for debugging
- **Diagnostics**: Screenshot + Playwright trace on failure (DOM snapshots, network requests, console logs)
- **Test data**: API setup/teardown via REST API in pytest fixtures. Per-test isolation (each test creates its own CSV/rule, cleans up after)
- **Multi-user testing**: Two browser contexts in one test for approval workflow (analyst context + admin context). Both approve and reject paths tested
- **Page object model**: `SplunkPage` base class handles iframe navigation, element waiting, panel location. `WhitelistManagerPage`, `ControlPanelPage`, `AuditPage` extend it
- **Splunk UI concerns**: Custom handling for Splunk dropdowns (custom components, not native selects) AND custom `wl-modal-overlay` modals with `<span>` buttons (not `<button>`) — both encapsulated in page objects
- **Wait strategy**: Claude's discretion — determine best approach based on observed Splunk load behavior during implementation
- **Login handling**: Claude's discretion — determine best approach (reusable auth state vs per-test login) based on Splunk session behavior
- **File location**: `tests/e2e/` directory with dedicated `conftest.py`
- **Retries**: 1 retry on failure via Playwright `--retries 1`
- **Performance assertions**: Hard thresholds — Claude calibrates by running a baseline timing pass first, then sets thresholds at 2x observed P95
- **Stress test**: One E2E test loads `DR_STRESS_2000x100.csv`, verifies table renders, scrolls horizontally, edits a cell, saves
- **Audit verification**: After save/revert/approve actions, query `wl_audit` index via REST API to confirm correct audit event logged
- **Notification verification**: Verify toast appears with correct message after approval/rejection, badge count updates on Queue tab
- **Theme test**: One basic test — toggle theme, verify CSS class changes, verify no JS errors
- **Markers**: `@pytest.mark.crud`, `@pytest.mark.approval`, `@pytest.mark.revert`, `@pytest.mark.admin`, `@pytest.mark.slow`, `@pytest.mark.stress`
- **Config**: Playwright config in `tests/e2e/conftest.py` (base URL, auth state, page fixtures)
- **Test matrix**: Documented matrix (workflow x role x expected outcome) as docstring or separate file — feeds Phase 8 AppInspect documentation

### Security Test Scope

- **Attack vectors**: All four — XSS in CSV cells, path traversal in filenames, input injection in REST params, RBAC bypass attempts
- **Approach**: Both targeted payloads AND property-based fuzzing (Hypothesis)
- **Test layers**: Both — unit-level with mocks (fast, offline) AND integration-level against live Docker container (validates full stack)
- **Location**: `tests/security/` dedicated directory (test_xss.py, test_path_traversal.py, test_rbac_bypass.py, test_injection.py)
- **Payloads**: Separate data files — `tests/security/fixtures/xss_payloads.json`, `path_traversal_payloads.json`, etc. Sourced from OWASP cheat sheets
- **RBAC matrix**: Full — every POST action tested with every role tier (viewer, editor, admin, superadmin). ~60-80 test cases
- **Hypothesis**: Fixed 100 examples per test (default). Deterministic seeds for reproducibility
- **Info leak tests**: Verify error responses contain only user-friendly messages — no Python tracebacks, file paths, or module names
- **Reserved prefix (_) enforcement**: Test both frontend AND backend reject user-created `_` prefix columns
- **CSRF protection**: Verify POST requests without valid Splunk session token are rejected
- **Optimistic locking bypass**: Regression test — send NaN, missing, empty string, and future timestamps for `expected_mtime`. Verify all rejected
- **Client trust bypass**: Regression test — send manipulated `_bulk_edit_count`, verify server computes from actual data (not client-provided values)

### Integration Test Strategy

- **Approach**: Extend existing 6 integration test files where logical, create new files only for uncovered areas
- **Backend**: Both Docker container AND mock Splunk SDK — some integration tests use mocks for speed, others hit Docker for realism
- **REST action coverage**: All 15+ actions in `wl_handler.py` dispatch tables — no gaps
- **Audit chain**: Full verification — after each mutating action, query `wl_audit` index, verify correct action type, fields, diff data
- **Concurrency tests**: Stay in `tests/integration/` (extend existing `test_concurrency.py`). Four scenarios:
  1. Simultaneous CSV saves (5+ threads, verify no corruption, version manifest consistent)
  2. Approval race conditions (two admins approve same request, verify only one succeeds)
  3. File lock contention (5+ threads, verify no deadlocks, no stale locks, correct timeout)
  4. Mixed operations (concurrent save + revert + delete on overlapping CSVs)
- **Test data isolation**: Per-test — each test creates own CSV/rule via API, cleans up after
- **Execution**: Sequential (no pytest-xdist) — Docker tests are inherently stateful
- **Backward compatibility**: Include compat tests for existing audit events (Phase 8 PUBL-04 prep) — feed pre-rewrite audit events through audit.xml queries
- **Mock Splunk SDK (TEST-06)**: Full read/write mock — supports `simpleRequest` (GET/POST), `service.indexes['wl_audit'].submit()`, input parsing, session token validation
- **Failing tests**: Fix 10 existing failures in `test_limits.py` as first Phase 7 task (clean baseline before adding new tests)
- **Markers**: `@pytest.mark.docker` (skip if no container), `@pytest.mark.slow` (concurrency, stress)
- **Handler coverage**: Run integration tests with `--cov=bin/wl_handler` to verify 100% dispatch table entry coverage

### Legacy Test Cleanup

- **Strategy**: Audit, migrate, delete — review each of ~15 legacy files at `tests/` root. Migrate unique coverage into `tests/unit/` or `tests/integration/`. Delete originals. Goal: zero test files at root level
- **Timing**: First task in Phase 7 — clean baseline before writing new tests
- **Conftest consolidation**: Refactor `tests/conftest.py` and `tests/unit/conftest.py` — eliminate duplication, ensure Docker fixtures properly scoped, register all markers
- **Pytest config**: Single `tests/pytest.ini` — register all markers, configure test discovery, set default options

### QUnit Frontend Tests

- **Extend scope**: Add QUnit tests for 4 frontend modules:
  1. `wl_rest.js` — extend existing `test_rest_helpers.js` with edge cases (network errors, malformed responses, timeout)
  2. `wl_table.js` — cell editing, pagination, syncInputs/refreshTable contract, row selection logic
  3. `wl_modals.js` — modal show/hide, form validation, button state management
  4. `wl_state.js` — extend existing tests with batch operations, isDirty() computation, reset behavior, validation rejection

### Deliverables

- **Coverage report**: HTML report (`htmlcov/`) + summary table in Phase 7 VERIFICATION.md (feeds Phase 8 PUBL-05)
- **Test documentation**: `tests/README.md` — how to run each suite (unit/integration/e2e/security), marker usage, Docker setup, Playwright installation, troubleshooting

### Claude's Discretion

- Playwright wait strategy (smart waits vs fixed timeouts) — based on observed Splunk behavior
- Login handling approach (reusable auth state vs per-test) — based on Splunk session behavior
- Performance threshold calibration — data-driven from baseline timing pass
- Legacy file-by-file migrate/delete decisions — based on coverage gap analysis
- QUnit test file organization (extend existing vs new files)
- Exact test count per category (within target ranges)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Test requirements
- `.planning/REQUIREMENTS.md` -- TEST-01 through TEST-06 requirement definitions
- `.planning/ROADMAP.md` section "Phase 7" -- Success criteria, requirement mapping

### Backend source (test targets)
- `bin/wl_handler.py` -- REST router with GET_ACTIONS/POST_ACTIONS dispatch tables (integration test target)
- `bin/wl_validation.py` -- sanitize_text(), is_safe_filename(), safe_realpath() (security test targets)
- `bin/wl_rbac.py` -- Role checking and permission enforcement (RBAC bypass test target)
- `bin/wl_csv.py` -- CSV read/write/diff, _compute_diff() (unit test coverage target)
- `bin/wl_versions.py` -- Version snapshots and manifest tracking (integration test target)
- `bin/wl_audit.py` -- Audit event construction (audit chain verification target)
- `bin/wl_approval.py` -- Approval queue CRUD, conflict resolution (concurrency test target)
- `bin/wl_filelock.py` -- File locking with RLock+fcntl (concurrency test target)
- `bin/wl_limits.py` -- Daily limits (10 failing tests to fix first)

### Frontend source (test targets)
- `appserver/static/modules/wl_state.js` -- State manager (QUnit extension target)
- `appserver/static/modules/wl_rest.js` -- REST helpers (QUnit extension target)
- `appserver/static/modules/wl_table.js` -- Table rendering/editing (QUnit + E2E target)
- `appserver/static/modules/wl_modals.js` -- Modal dialogs (QUnit + E2E target)
- `appserver/static/whitelist_manager.js` -- Entry point orchestrator (E2E target)
- `appserver/static/control_panel.js` -- Admin panel entry point (E2E target)

### Existing test infrastructure
- `tests/conftest.py` -- Global fixtures (consolidation target)
- `tests/unit/conftest.py` -- Unit test fixtures (consolidation target)
- `tests/stubs/splunk/rest.py` -- Splunk SDK stubs (TEST-06 extension target)
- `tests/qunit/test_state_manager.js` -- Existing QUnit state tests (extension target)
- `tests/qunit/test_rest_helpers.js` -- Existing QUnit REST tests (extension target)

### Project conventions
- `CLAUDE.md` -- Deployment flow, audit event structure, Docker container setup
- `.planning/PROJECT.md` section "Constraints" -- jQuery + AMD, no bundlers, Python 3 only

### Bug pattern memory (regression test sources)
- `~/.claude/projects/c--Users-PC-wl-manager/memory/MEMORY.md` -- Documented vulnerabilities and patterns that need regression tests: optimistic locking bypass (NaN mtime), client trust bypass (_bulk_edit_count), reserved prefix convention, set-vs-counter, syncInputs/refreshTable contract

### Prior phase testing context
- `.planning/phases/05-frontend-architecture/05-CONTEXT.md` section "QUnit" -- QUnit infrastructure decisions, vendored in app, test_runner.xml dashboard
- `.planning/phases/04-backend-integration/04-CONTEXT.md` -- Backend dispatch pattern, integration test approach

### Stress test data
- `lookups/DR_STRESS_2000x100.csv` -- 2000-row, 100-column CSV for stress E2E test

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **pytest infrastructure**: `tests/conftest.py` with Splunk SDK stubs, mock handler factory, temp directory fixtures — foundation for all new tests
- **QUnit infrastructure**: `tests/qunit/` with 4 test files + `test_runner.xml` dashboard — extend for frontend module tests
- **Splunk SDK stubs**: `tests/stubs/splunk/rest.py` — extend for full read/write mock (TEST-06)
- **Docker smoke tests**: `tests/integration/test_docker_handler_smoke.py` — pattern for live container REST API testing
- **Concurrency test base**: `tests/integration/test_concurrency.py` — extend with 4 new scenarios
- **Stress test CSV**: `lookups/DR_STRESS_2000x100.csv` — ready for E2E stress test

### Established Patterns
- **Unit test pattern**: Mock file I/O and Splunk SDK, test pure logic. 389 tests, 97% coverage on extracted modules
- **Integration test pattern**: REST API calls to Docker container, verify response shape and audit events
- **QUnit test pattern**: AMD module loading, State.get/set assertions, event firing verification
- **Conftest scoping**: Session-scoped Docker fixtures, function-scoped test data isolation

### Integration Points
- **Docker container**: `wl_manager_test` on ports 8000 (Web UI) / 8089 (REST API). Playwright E2E connects to 8000, integration tests to 8089
- **Splunk REST API**: `https://localhost:8089/servicesNS/nobody/wl_manager/...` for test data setup/teardown
- **wl_audit index**: `index=wl_audit` for audit chain verification via Splunk search API
- **app.conf build number**: Must bump for E2E tests after deploying test code changes
- **i18n cache**: Must clear before E2E tests if JS was changed

</code_context>

<specifics>
## Specific Ideas

- Fix 10 failing `test_limits.py` tests as very first task — establishes clean green baseline
- Legacy test audit before new test writing — prevents duplicate effort and reveals coverage gaps
- MEMORY.md documented vulnerabilities become explicit regression tests (optimistic locking NaN, client trust bypass, reserved prefix, set-vs-counter)
- Page object model encapsulates Splunk iframe quirks and custom span-button modals — future-proofs E2E tests against Splunk DOM changes
- Performance thresholds calibrated from actual baseline measurements, not guesswork — accounts for Docker overhead
- Test matrix document serves dual purpose: Phase 7 coverage tracking AND Phase 8 AppInspect documentation
- Full RBAC bypass matrix (~60-80 tests) is the most valuable security investment — RBAC is the primary security gate

</specifics>

<deferred>
## Deferred Ideas

None -- discussion stayed within phase scope

</deferred>

---

*Phase: 07-test-coverage-validation*
*Context gathered: 2026-04-02*
