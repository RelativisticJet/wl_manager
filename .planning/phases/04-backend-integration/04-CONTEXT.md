# Phase 4: Backend Integration - Context

**Gathered:** 2026-04-01
**Status:** Ready for planning

<domain>
## Phase Boundary

Refactor wl_handler.py (5,909 lines) into a thin REST router that delegates all business logic to the 16 modules extracted in Phases 1-3, plus a new wl_replay.py module for approval replay orchestration. Also update wl_expiration_cleanup.py and wl_expiring_soon.py to use extracted modules. Merge or remove wl_wrapper.py. Update MCP deploy tool and CLAUDE.md documentation.

</domain>

<decisions>
## Implementation Decisions

### Router Dispatch Pattern
- **Dict dispatch tables** at class level using string method names; _dispatch() resolves via getattr(self, method_name)
- **Separate tables**: GET_ACTIONS and POST_ACTIONS as distinct class-level dicts
- **All actions in tables**, including no-RBAC actions (with None as required_roles); auto-generate valid_actions from table keys
- **Handlers are bound methods** on the class with `_action_` prefix (e.g., `_action_save_csv`)
- **Shared _dispatch()** method handles: table lookup -> auth check (reject "unknown" users for ALL actions) -> RBAC check -> call handler -> structured access log
- **Router passes parsed query** to GET handlers; POST handlers receive payload directly
- **Handler functions receive** (self, request, payload/query, user, roles) and parse their own params
- **Special pre-processing** (ownership checks, superadmin injection) handled inside handler functions, not in dispatch
- **Rate limiting stays in handle()** (before dispatch); payload size check stays in _handle_post (before dispatch)
- **_resp() and _parse_query() remain instance methods** on the class
- **Zero standalone functions** in handler after Phase 4 — everything is a class method or imported from a module
- **Error responses standardized** to {error: msg}; success responses include {success: true} only when no other data

### Structured Access Log
- **All requests** logged to Python rotating log file with structured JSON: {type, action, user, method, status, duration_ms, payload_bytes, ts}
- **Write operations** also create existing business audit events (no separate api_access event type)
- **Full traceback** logged for all errors (client and server) to aid debugging

### Layered Error Handling
- **In _dispatch()**: catch ValueError->400, FileNotFoundError->404, PermissionError->403, IOError->500 with specific message; catch-all Exception->500 in handle()
- **Standard Python exceptions** used (no custom exception hierarchy)
- **Replay failure responses** include context: request_id, original_analyst, action_type, and specific error detail

### Approval Replay Migration
- **New wl_replay.py module** (Layer 5): dedicated replay module that executes approved actions via domain module pipelines
- **Dict dispatch** internally: REPLAY_HANDLERS maps action_type to replay functions; fixed set, add as needed
- **Replay calls domain modules directly** — no _from_approval flag needed; the module IS the approval path
- **ReplayContext dict**: {original_analyst, approving_admin, second_admin, is_dual_admin, request_id, action_type, session_key, approved_at}
- **Unified replay** for both standard and dual-admin approvals; is_dual_admin flag in context
- **Replay validates preconditions** (CSV exists, rule exists) before executing — key lesson from MEMORY.md
- **Replay posts audit events directly** (receives session_key in context)
- **Notification message templates** live in wl_notify.py (SSOT for message formatting)
- **Replay returns structured result** dict (not HTTP response): {success, message, data, error, error_type}
- **Error pattern**: exceptions for primary operations, log+continue for secondary (audit, notification, version snapshot)
- **Relaxed BMOD-13**: replay functions allowed up to 150 lines (orchestration complexity)
- **Own test file**: tests/unit/test_replay.py with mocked domain modules

### Approval Flow Split
- **wl_approval.py handles queue logic** (check, update status, manage dual-admin flow)
- **wl_replay.py handles execution** (called by wl_approval when both admins approve)
- **wl_approval.process_approval()** handles both approve and reject decisions; handler stays thin
- **Call chain accepted**: handler -> wl_approval -> wl_replay -> domain modules (depth of 4 is normal)
- **Direct import**: wl_approval imports wl_replay at module level; fail-fast on import errors
- **cancel_conflicts fully in wl_approval.py** — handler wrapper removed

### Inline Logic Extraction
- **Action-by-action rewrite** in waves: GET handlers (Wave 1) -> Simple POST (Wave 2) -> Complex POST + admin (Wave 3)
- **Pipeline functions** shared between handler and replay:
  - `wl_csv.py`: save_csv_pipeline(), create_csv_pipeline()
  - `wl_versions.py`: revert_csv_pipeline()
  - `wl_rules.py`: create_rule_pipeline()
  - `wl_trash.py`: remove_rule_pipeline(), remove_csv_pipeline()
- **Handler calls pipeline** (not individual module functions) for complex actions
- **Optimistic locking (mtime) stays in handler** — HTTP-level concern, not pipeline's job
- **Nested functions (_save_csv_locked, _save_csv_inner) eliminated** — replaced by pipeline calls
- **_index_audit removed entirely** — all callers use wl_audit.post_audit_event directly
- **All standalone functions migrated**: _read_notifications/_write_notifications -> wl_notify.py; _get_pending_for_csv -> call wl_approval directly; all path helpers -> respective modules
- **Mapping logic consolidated** in wl_rules.py (including reverse lookup get_rule_for_csv)
- **Daily limits handlers stay thin** — business logic already in wl_limits.py from Phase 3
- **Config handlers (save_as_default, reset_factory) stay in handler** — simple file I/O, not worth a module
- **Simple handlers stay in handler**: check_csv_status (aggregation), log_event (audit passthrough)
- **Unused imports cleaned up** after extraction
- **File organized with clear sections**: Imports -> Logger -> Dispatch Tables -> Class (Core -> GET -> POST)
- **Remove all Phase 3 adapters** and call modules directly

### Module Dependency Graph
- **Layer 5 added**: wl_replay.py imports Layer 3-4 modules
- **Peer-level pipeline cross-imports accepted**: wl_csv -> wl_versions/wl_audit, wl_versions -> wl_csv/wl_audit, etc.
- **Lazy import in wl_trash** for wl_approval (breaks circular: trash -> approval -> replay -> trash pipelines)
- **Explicit dependency-order imports** in handler (Layer 0 first, then 1, 2, 3, 4, 5)
- **Selective imports** from wl_constants (no star imports)
- **Final count**: 16 wl_*.py modules + wl_handler.py + 2 scripts (wl_expiration_cleanup, wl_expiring_soon)
- **Import cycle test** added to verify no circular dependencies

### Integration Test Strategy
- **Full coverage including replay**: happy path + edge cases + full approval replay chain
- **Both test layers**: mock REST harness (offline, fast) + Docker smoke tests (all actions)
- **RBAC matrix test**: parametrized test verifying every action x role combination
- **Dispatch completeness test**: verify all table entries resolve to methods and all _action_* methods are in tables
- **Audit event verification**: search wl_audit index via docker exec + splunk search CLI
- **Backward compatibility tests**: run audit.xml SPL queries after refactored actions
- **Access log tests**: verify structured log entries for each action
- **Full regression suite**: run ALL prior phase tests after each refactoring step
- **Pipeline unit tests**: each pipeline function tested in its module's test file with mocked sub-calls
- **Replay unit tests**: mocked domain modules, verify correct function calls and arguments
- **Basic latency benchmark**: time 5 most common actions, ensure no >10% regression
- **Docker test management**: setup/teardown per test with unique names; @pytest.mark.docker marker; auto-skip when container not running; deploy all wl_*.py before testing
- **Tests in tests/integration/**: test_handler_*.py for mock harness, test_docker_*.py for Docker
- **Test count**: whatever it takes to cover all actions and flows
- **Canary after each wave**: deploy to Docker and run full Docker test suite between waves

### Migration Safety
- **No dual mode** — each handler rewrite is atomic; git history is the rollback
- **Automated tests sufficient** per commit; full manual smoke test at end of Phase 4
- **No external consumers** of handler functions — API contract is the stability boundary
- **Rollback**: git revert Phase 4 commits to Phase 3 completion state
- **wl_expiration_cleanup.py and wl_expiring_soon.py in scope** — update to use extracted modules
- **wl_wrapper.py in scope** — merge into handler or eliminate
- **One commit per wave** (not per handler): 3-6 commits total
- **Deploy ALL wl_*.py files** to Docker (wildcard copy, not selective)
- **Fail-fast imports** — no lazy import guards for internal modules (except wl_trash -> wl_approval for circular dep)

### Documentation & Deployment
- **CLAUDE.md full update**: project structure, architecture decisions, module dependency hierarchy, current state
- **Docstrings on all public functions** (pipeline functions, wl_replay exports, handler methods)
- **Dispatch tables grouped with section comments** by domain
- **MCP deploy tool updated** to include wl_replay.py and all new files
- **Module dependency hierarchy diagram** in CLAUDE.md

### Claude's Discretion
- Exact handler function implementation details within the pipeline pattern
- Number of waves and grouping of handler rewrites
- Integration test helper fixture design
- Whether wl_wrapper.py is merged into handler or deleted outright
- Exact line count for final handler (no target — quality over size)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Handler source (primary refactoring target)
- `bin/wl_handler.py` — 5,909-line monolith to be refactored into thin router; contains all action handlers, inline business logic, adapters
- `bin/wl_wrapper.py` — 362-line file to be merged or removed

### Phase 1-3 modules (dependencies for pipeline functions)
- `bin/wl_constants.py` — Layer 0: all constants, role sets, config defaults
- `bin/wl_logging.py` — Layer 1: audit logger factory
- `bin/wl_validation.py` — Layer 2: input sanitization, path security
- `bin/wl_ratelimit.py` — Layer 2: sliding-window rate limiter
- `bin/wl_rbac.py` — Layer 2: role predicates, user discovery
- `bin/wl_presence.py` — Layer 2: user presence tracking
- `bin/wl_csv.py` — Layer 3: CSV read/write/diff (gets save_csv_pipeline, create_csv_pipeline)
- `bin/wl_versions.py` — Layer 3: version snapshots/manifest (gets revert_csv_pipeline)
- `bin/wl_audit.py` — Layer 3: audit event construction/posting
- `bin/wl_rules.py` — Layer 3: detection rules registry (gets create_rule_pipeline, get_rule_for_csv)
- `bin/wl_trash.py` — Layer 3: trash CRUD (gets remove_rule_pipeline, remove_csv_pipeline)
- `bin/wl_filelock.py` — Layer 4: file locking context manager
- `bin/wl_limits.py` — Layer 4: daily limits enforcement
- `bin/wl_approval.py` — Layer 4: approval queue CRUD, conflict resolution
- `bin/wl_notify.py` — Layer 4: admin/analyst notifications (gets notification CRUD, message templates)

### Scripts to update
- `bin/wl_expiration_cleanup.py` — Scheduled search script with inline CSV/audit logic
- `bin/wl_expiring_soon.py` — Scheduled search script with inline logic

### Memory & patterns
- `CLAUDE.md` — Project architecture, deployment flow, audit event structure, MCP deploy tool
- `~/.claude/projects/c--Users-PC-wl-manager/memory/MEMORY.md` — Critical bug patterns: precondition validation, set-vs-counter, dual UI paths
- `~/.claude/projects/c--Users-PC-wl-manager/memory/feedback_precondition_validation.md` — Queued operation precondition pattern

### Prior phase context
- `.planning/phases/02-backend-core-domain/02-CONTEXT.md` — Module boundaries, error handling, file locking, test structure decisions
- `.planning/phases/03-backend-orchestration/03-CONTEXT.md` — Approval replay architecture, queue schema, conflict resolution, concurrency model, notification module decisions

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **Phase 3 adapter functions**: Pattern for backward-compatible module wiring; will be REMOVED in Phase 4
- **wl_audit.build_audit_event() + post_audit_event()**: Ready for direct use by all handler actions and replay functions
- **wl_approval.cancel_conflicts()**: Functional-style conflict resolution (returns new queue, no mutation)
- **wl_versions.snapshot_version()**: Atomic versioning with collision detection
- **Splunk PersistentServerConnectionApplication**: Base class provides handle() entry point

### Established Patterns
- **Error handling**: Exceptions for primary ops, log+continue for secondary (Phase 2-3 convention)
- **Module structure**: __all__ exports, type hints, selective imports, sys.path.insert for bin/ imports
- **Test structure**: tests/unit/test_{module}.py, tests/integration/ for cross-module, @pytest.mark.docker for container tests
- **File I/O**: Atomic writes via temp file + os.replace (Phase 2 pattern)
- **Fail-fast imports**: No try/except guards on internal module imports

### Integration Points
- **Handler dispatches to**: all 16 modules via dispatch table + _action_* methods
- **wl_approval -> wl_replay**: process_approval calls execute_approved_action on approve
- **wl_replay -> Layer 3 pipelines**: replay functions call save_csv_pipeline, revert_csv_pipeline, etc.
- **Pipeline functions -> wl_versions + wl_audit**: cross-module peer imports for orchestration
- **wl_trash -> wl_approval**: lazy import for cancel_conflicts in remove pipelines

</code_context>

<specifics>
## Specific Ideas

- Dispatch tables as class-level constants with string method names (avoids per-instance rebuild since Splunk creates new handler per request)
- Structured access log with payload_bytes for monitoring oversized requests
- RBAC matrix test as the primary security verification for the dispatch table refactoring
- Dispatch completeness test to catch orphaned handlers or stale table entries
- Import cycle test to catch circular dependencies early
- Canary deployment after each wave to catch Docker-specific issues
- Deploy ALL wl_*.py via wildcard (not selective) to prevent version mismatch bugs

</specifics>

<deferred>
## Deferred Ideas

- Read/write lock semantics in wl_filelock.py — deferred until performance data shows read contention
- Custom exception hierarchy (WLError, WLValidationError) — standard Python exceptions sufficient
- Plugin/registration API for replay handlers — fixed set sufficient, YAGNI
- Performance profiling and optimization — Phase 4 is refactoring, not optimization
- Frontend integration testing — deferred to Phase 5-7

</deferred>

---

*Phase: 04-backend-integration*
*Context gathered: 2026-04-01*
