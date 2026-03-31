# Phase 1: Backend Foundation - Context

**Gathered:** 2026-03-31
**Status:** Ready for planning

<domain>
## Phase Boundary

Extract 6 dependency-free backend modules from `wl_handler.py` (7,114 lines) with zero functional change. The app must work exactly as before after each extraction step. Establishes the foundation for all subsequent backend modularization (Phases 2-4).

Modules: `wl_constants.py`, `wl_logging.py`, `wl_validation.py`, `wl_ratelimit.py`, `wl_rbac.py`, `wl_presence.py`.

</domain>

<decisions>
## Implementation Decisions

### Module Boundaries

#### wl_constants.py
- Extract ALL constants from wl_handler.py in Phase 1 — not just constants consumed by Phase 1 modules. Includes Phase 2/3 domain constants (APPROVAL_QUEUE_FILE, TRASH_DIR, DEFAULT_LIMITS, DEFAULT_ADMIN_LIMITS, etc.)
- Role set definitions (EDIT_ROLES, ADMIN_ROLES, SUPERADMIN_ROLES) live here as static data
- Compiled regex patterns (_CONTROL_CHAR_RE, _SANITIZE_RE, _SAFE_COLNAME_RE) stored here; usage functions live in wl_validation.py
- Env vars lazy, derived paths eager: `get_splunk_home()` function (patchable in tests), derived constants (APPS_DIR, OWN_LOOKUPS, MAPPING_FILE) computed eagerly from it
- Path helper functions `get_detection_rules_path()` and `get_approval_queue_path()` included here (one-line os.path.join using constants)
- Audit-specific constants (AUDIT_INDEX, AUDIT_SOURCE, AUDIT_SOURCETYPE) included now

#### wl_logging.py
- Logger configuration + `get_audit_logger()` getter function only (~20 lines)
- Sets up RotatingFileHandler at import time
- No convenience log helpers — those overlap with Phase 2's wl_audit.py

#### wl_validation.py
- Functions: `sanitize_text`, `is_safe_filename` (generalized with `allowed_extensions` parameter), `safe_realpath`, `build_csv_path`, `resolve_csv_path`, `safe_filename` → renamed `is_safe_filename`
- Only security-critical path helpers — version/col-width path helpers deferred to Phase 2 modules
- Imports regex patterns from wl_constants.py; implements the functions that use them
- `_find_expire_column` and `_count_nonempty_cells` deferred to Phase 2 (wl_csv.py domain)

#### wl_ratelimit.py
- Stateful module owning `_rate_limits = {}` dict internally (consistent with wl_presence.py pattern)
- Exports `check_rate_limit(user, action_type) -> bool`
- Sliding window logic, per-user state, stale key cleanup all encapsulated

#### wl_rbac.py
- Predicate functions: `is_admin(roles)`, `is_editor(roles)`, `is_superadmin(roles)`, `can_edit(roles)`, `can_approve(roles)`
- Request parsing: `get_user(request)`, `get_roles(request)` — entry points for all auth context
- Admin discovery: `get_admin_users(session_key)` — discovers Splunk users with ADMIN_ROLES via REST API
- Accepts Splunk SDK dependency (`splunk.rest`) — "dependency-free" means no wl_* cross-dependencies, not no Splunk SDK
- `_notify_admins` stays in wl_handler.py until Phase 3 (depends on both rbac + notifications)

#### wl_presence.py
- Stateful module owning `_presence = {}` dict as module-level state
- Exports functions like `report_presence(csv_file, user, last_activity)` returning `(data_dict, error_string)` tuples
- Handler method becomes thin wrapper: calls module function, wraps result in `_resp()`
- HTTP-agnostic — no response formatting in the module

### Extraction Approach
- Incremental: one module per commit in dependency order: constants → logging → validation → ratelimit → rbac → presence
- Each extraction commit: (1) create new module, (2) wire into handler (Claude's discretion on immediate vs staged wiring per module), (3) deploy to Docker, (4) verify via integration tests
- Test-first: build integration test harness against current monolith BEFORE any extraction. Baseline tests prove current behavior; each extraction must pass the same tests.
- Deploy + verify after each module extraction (not batched)
- Update MCP deploy tool file list with new `bin/*.py` modules
- Rollback: Claude's discretion — fix forward for trivial issues, git revert for complex failures
- Drop leading underscores for public API functions (e.g., `_sanitize_text` → `sanitize_text`)
- Add type hints to all extracted functions during extraction (not deferred)

### Test Strategy
- **Directory structure**: `tests/unit/` for pytest unit tests, `tests/integration/` for Docker-based tests
- **Test separation**: Both directory separation AND pytest markers (`@pytest.mark.unit`, `@pytest.mark.integration`)
- **Splunk SDK stub**: `tests/stubs/splunk/` package with stub `rest.py` (mock `simpleRequest`). Added to PYTHONPATH in conftest.py.
- **pytest config**: `conftest.py` + `pytest.ini` (no pyproject.toml)
- **Dev dependencies**: `requirements-dev.txt` (pytest, pytest-cov, freezegun)
- **Time mocking**: freezegun library for presence/ratelimit time-dependent tests
- **File I/O**: `tmp_path` fixture for real filesystem path operations; mock only Splunk-specific paths
- **Docker fixture**: conftest.py fixture checks container status, starts if needed, deploys current code before tests
- **Integration scope**: Tests hit both custom REST endpoint (`/custom/wl_manager`) AND imported module functions directly
- **Audit verification**: Integration tests verify audit events exist in `wl_audit` index with correct fields after save operations
- **Coverage**: pytest-cov configured from day one, coverage reported on every run
- **Test naming**: Claude's discretion following pytest conventions

### Import Wiring
- `sys.path.insert(0, os.path.dirname(__file__))` at top of wl_handler.py only — modules in same directory resolve automatically
- Selective `from wl_constants import MAX_ROWS, EDIT_ROLES, ...` (Claude's discretion on star vs selective per-module)
- Inter-module imports: `from wl_constants import ...` in validation/rbac/etc.; `from wl_logging import get_audit_logger` in rbac
- Strict layer dependency rule (established now, enforced in all phases):
  - Layer 0: wl_constants (no imports from wl_*)
  - Layer 1: wl_logging (no imports from wl_* except constants)
  - Layer 2: wl_validation, wl_ratelimit, wl_rbac, wl_presence (import from Layer 0-1 only, never reverse)
  - Phase 2+ modules can import from Phase 1 modules, never the reverse
- Every module defines `__all__` explicitly declaring its public API
- `_resp()` stays in wl_handler.py (REST handler response formatter, not utility)

### Claude's Discretion
- Import granularity per-module (star vs selective imports)
- Test naming conventions
- Wiring strategy per-module (immediate replacement vs staged)
- Rollback decision (fix forward vs revert) based on failure complexity

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project Architecture
- `.planning/PROJECT.md` — Core value, target module structure, constraints (jQuery+AMD, API frozen, zero downtime)
- `.planning/REQUIREMENTS.md` — BMOD-02 through BMOD-05 requirements, TEST-01 partial coverage target
- `.planning/ROADMAP.md` — Phase 1 success criteria, dependency chain, progress tracking
- `.planning/STATE.md` — Architecture decisions (sys.path.insert, layer dependencies, API contract frozen)

### Research
- `.planning/research/SUMMARY.md` — Dependency analysis, extraction order rationale
- `.planning/research/ARCHITECTURE.md` — Current module structure analysis
- `.planning/research/PITFALLS.md` — Known risks (circular imports, file locking, Windows fcntl)
- `.planning/research/STACK.md` — Splunk Python environment constraints

### Existing Code
- `bin/wl_handler.py` — Source monolith (7,114 lines). Lines 60-230 are constants/utilities to extract.
- `CLAUDE.md` — Deployment flow, Docker commands, Splunk quirks, audit event structure

</canonical_refs>

<code_context>
## Existing Code Insights

### Extraction Targets (line ranges in wl_handler.py)
- **Constants**: Lines 57-190 (~130 lines) — all MAX_*, role sets, DEFAULT_LIMITS, regex patterns, path constants
- **Logger setup**: Lines 192-209 (~18 lines) — RotatingFileHandler configuration
- **Validation**: Lines 228-306 (~80 lines) — `_sanitize_text`, `_safe_filename`, `_check_rate_limit`, `_safe_realpath`
- **Rate limiting**: Lines 268-294 (~27 lines) — sliding window `_check_rate_limit` + `_rate_limits` dict (line 79)
- **Path resolution**: Lines 297-360 (~64 lines) — `_safe_realpath`, `_build_csv_path`, `_resolve_csv_path`
- **Presence**: Lines 212-214 (state) + 2281-2367 (handler method, ~87 lines) — `_presence` dict + `_report_presence`
- **RBAC**: Lines 92-101 (role sets) + 7078-7106 (`_get_user`, `_get_roles`) + 794-813 (`_get_admin_users`) + ~30 inline `roles.intersection()` calls throughout handler

### Established Patterns
- Module-level global dicts for in-memory state (`_presence`, `_rate_limits`) — both new modules follow this pattern
- `@staticmethod` on handler utility methods — extracted functions become module-level functions instead
- `fcntl` conditional import (line 36-39) — Windows compatibility pattern to preserve
- Splunk REST API calls via `splunk.rest.simpleRequest` — used by `_get_roles` and `_get_admin_users`

### Integration Points
- wl_handler.py's `handle()` method is the entry point — calls `_handle_get` and `_handle_post`
- Every POST action checks `roles.intersection(EDIT_ROLES)` — will become `wl_rbac.is_editor(roles)`
- Every handler method calls `_check_rate_limit(user, "write")` — will become `wl_ratelimit.check_rate_limit(user, "write")`
- Logger used in `_get_roles` error handling — will import from `wl_logging.get_audit_logger()`

</code_context>

<specifics>
## Specific Ideas

- "Dependency-free" means no wl_* cross-dependencies, not no Splunk SDK. wl_rbac.py can import splunk.rest directly.
- Presence module returns (data, error) tuples — NOT exceptions, NOT HTTP responses. Handler wraps into _resp().
- Rate limiting is its own module because it has its own state and lifecycle, separate from both validation and RBAC.
- Role sets are data (constants), role checking is logic (rbac) — clean separation.
- `is_safe_filename` generalized with `allowed_extensions` parameter for future reuse with JSON config files.
- Integration tests verify the full chain including audit event creation — not just REST response codes.
- The integration test harness is the FIRST deliverable — baseline before any extraction begins.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 01-backend-foundation*
*Context gathered: 2026-03-31*
