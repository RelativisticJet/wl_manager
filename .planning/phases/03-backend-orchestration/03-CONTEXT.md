# Phase 3: Backend Orchestration - Context

**Gathered:** 2026-04-01
**Status:** Ready for planning

<domain>
## Phase Boundary

Extract 4 orchestration modules from wl_handler.py: wl_limits.py (daily usage tracking and enforcement), wl_approval.py (approval queue CRUD, conflict resolution, submission), wl_notify.py (admin and analyst notifications), and wl_filelock.py (shared file locking utility). These modules orchestrate Phase 2's data persistence modules and Phase 1's foundation. Replay orchestration (_process_approval_inner) stays in handler until Phase 4.

</domain>

<decisions>
## Implementation Decisions

### Approval Replay Architecture
- **Handler passthrough pattern**: wl_approval.py manages queue CRUD, conflict resolution, submission, and expiration. Actual replay orchestration (_process_approval_inner, which calls _save_csv/_revert_csv with _from_approval=True) stays in handler until Phase 4.
- **Action registry preparation**: Define ACTION_HANDLERS dict in handler mapping action types to replay functions. Phase 4 will migrate this to the module. Structured for future migration.
- **Submit functions exported**: wl_approval.py exports submit_approval() and submit_dual_approval() — encapsulate validation + queue write + notification trigger.
- **Expiration in module**: expire_pending_approvals() belongs in wl_approval.py (pure queue manipulation, no handler dependency).
- **Validation split**: RBAC checks stay in handler (owns request context). Payload validation (required fields, reason length) moves to wl_approval.py.
- **Module triggers notifications**: wl_approval.py calls wl_notify functions directly for submission and cancellation events.

### Queue Schema & Validation
- **Unified queue**: Single approval_queue.json file with entry type field distinguishing standard, create/delete, and dual-admin entries. Single lock, single file.
- **Validate on read+write**: Schema validation on both directions. Catches corrupted queue files and legacy entries.
- **Fail entire read on corruption**: If validation finds corrupted/invalid entry, return error and refuse to process queue. Fail-closed — admin must manually fix. Consistent with project error handling pattern.
- **Specific query helpers**: get_pending_for_csv(csv_file), get_pending_for_rule(rule_name) — not generic predicate-based API. Self-documenting, matches current usage patterns.
- **Schema-aware field access**: Claude's discretion on whether to normalize entries on read or use get_csv_file(entry) helpers.

### Conflict Resolution
- **Trigger on every approve**: Check for conflicts on every approval processing, not just destructive actions. Catches edge cases like approving an edit after CSV was modified by another approved edit.
- **CSV-level cancel added**: When a CSV is trashed/deleted, cancel all pending edits for that CSV. Extends current rule-level cancel.
- **Restore triggers conflicts too**: Trash + delete + restore all trigger conflict checks. Restoring cancels pending 'create CSV' requests for the same name.
- **Dry run mode**: check_conflicts(queue, action) returns what WOULD be cancelled without side effects. cancel_conflicts() actually cancels. Useful for testing and future UI preview.
- **Return cancelled list + notify**: cancel_conflicts() returns (new_queue, cancelled_entries). Module also triggers notifications to affected analysts via wl_notify.
- **Functional style**: No in-place mutation. cancel_conflicts() returns a new queue copy + cancelled entries list. Caller writes if they want.
- **Precondition validation**: When processing an approved action, validate preconditions (CSV exists, rule exists) before replay. Fail + audit log with action='approval_precondition_failed' on stale requests.
- **Audit trail for cancellations**: Auto-cancel audit events include 'cancelled_by_action' and 'cancelled_by_analyst' fields for full traceability.

### Daily Limits Architecture
- **Separate subsystems**: check_analyst_limit() and check_admin_limit() as distinct functions. Matches current code structure. Explicit about which system is being checked.
- **Reset logic in module**: reset_daily_limits(analyst=None) in wl_limits.py. Handler's scheduled search action just calls the module function.
- **0 = disabled everywhere**: Consistent semantic across both analyst and admin limit systems. max_count==0 means 'this limit is not enforced'. Fixes documented inconsistency from MEMORY.md.
- **Status API**: get_limit_status(user, roles) returns {action_type: {current: N, max: M, remaining: R}} for all action types. Enables frontend progress display.
- **Approval gate in wl_approval.py**: check_approval_gate(user, action_type, action_count, roles) combines limit check (calls wl_limits) + threshold check. Single function for 'does this action need approval?'.
- **Admin exemption in module**: check_analyst_limit() accepts roles parameter, returns 'exempt' for admin roles. Module knows about RBAC exemptions.
- **All config in wl_limits.py**: Both limit config AND approval thresholds read/written by wl_limits.py. Single source of truth for 'when do actions get gated'.
- **Direct handler calls for admin actions**: Handler's _set_daily_limits_action calls wl_limits.set_limit_config() directly. Simple, matches Phase 2 pattern.
- **RESET_ALL_USERS constant**: Add RESET_ALL_USERS = '__all__' to wl_constants.py. Module checks against constant, not magic string 'all'. Prevents sentinel value bug permanently.
- **Error messages in module**: _daily_limit_error_msg logic lives in wl_limits.py. Module returns formatted error string, handler passes to response.

### Concurrency Model
- **Shared lock utility**: Extract wl_filelock.py providing file_lock(path, timeout) context manager. Used by wl_approval, wl_versions, and any module needing file locking. DRY for file locking.
- **Exclusive locks first**: Start with exclusive-only file locks. Add read/write lock semantics later when performance data shows contention on reads. YAGNI until measured.
- **No-op on Windows**: fcntl on Unix, no-op on Windows. Matches Phase 2's wl_versions pattern. Windows is dev-only, production is always Linux.
- **Lock ordering**: Document and enforce with runtime assertion. LOCK_ORDER: 1) approval_queue, 2) daily_limits, 3) csv_file. Raises LockOrderViolation if locks acquired out of order.
- **Both test layers**: Unit tests use mocks for logic (deterministic). Integration tests use temp files for real I/O (realistic). Matches Phase 2 testing strategy.
- **Concurrency test goals**: Data integrity as primary (must pass: valid JSON, all entries present, no corruption). Ordering guarantees as best-effort (log violations but don't fail test).

### Notification Module (wl_notify.py)
- **Full scope**: notify_admins(session_key, type, details) + notify_analyst(session_key, analyst, type, details). Covers all approval events: submissions, approvals, rejections, auto-cancellations.
- **Extracted from handler**: _notify_admins and analyst notification logic moved to wl_notify.py. Both handler and wl_approval.py can import it.

### Module Count & Roadmap
- **4 modules total**: wl_limits.py, wl_approval.py, wl_notify.py, wl_filelock.py. Roadmap should be updated to reflect expanded scope.

### Claude's Discretion
- Schema-aware field access strategy (normalize on read vs helper functions)
- Grouping of queue CRUD helper functions within wl_approval.py
- Integration test depth for concurrency scenarios beyond 5-thread smoke test
- Lock acquisition strategy (contextlib ExitStack vs manual acquire/release) in wl_filelock.py

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Handler source code
- `bin/wl_handler.py` — Contains all approval queue, daily limits, conflict resolution, and notification logic to be extracted (lines 228-800 for queue/limits functions, lines 2463-5804 for handler methods)

### Phase 2 modules (dependencies)
- `bin/wl_csv.py` — CSV read/write/diff (called during approval replay)
- `bin/wl_versions.py` — Version snapshots (called during approval replay)
- `bin/wl_audit.py` — Audit event construction (called for approval audit trail)
- `bin/wl_rules.py` — Rules registry (checked during conflict resolution)
- `bin/wl_trash.py` — Trash operations (called during approved delete/restore)

### Phase 1 modules (dependencies)
- `bin/wl_constants.py` — Constants including APPROVAL_QUEUE_FILE, DEFAULT_LIMITS, DEFAULT_ADMIN_LIMITS, role sets
- `bin/wl_rbac.py` — Role checking functions (is_admin, can_approve, get_user, get_roles)
- `bin/wl_validation.py` — Input sanitization (used in approval payload validation)

### Memory & patterns
- `CLAUDE.md` — Project architecture, deployment flow, audit event structure, version control system, diff algorithm
- `~/.claude/projects/c--Users-PC-wl-manager/memory/MEMORY.md` — Critical bug patterns: sentinel value bugs, set-vs-counter, precondition validation, dual UI paths, role inference
- `~/.claude/projects/c--Users-PC-wl-manager/memory/feedback_precondition_validation.md` — Queued operation precondition pattern
- `~/.claude/projects/c--Users-PC-wl-manager/memory/feedback_sentinel_values.md` — Sentinel value truthy-check lesson

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **wl_versions.py file locking pattern**: Context manager with fcntl/no-op Windows fallback, 10s timeout, 3 retries — direct template for wl_filelock.py
- **Phase 2 dispatcher pattern**: Proven refactoring approach for oversized functions (compute_diff, move_to_trash, restore_from_trash)
- **wl_audit.build_audit_event()**: Ready-to-use for building approval/cancellation/precondition-failure audit events
- **wl_rbac role predicates**: is_admin(), can_approve(), can_approve_own_requests() — used by approval gate and limit exemptions

### Established Patterns
- **Error handling**: Fail-closed with state rollback (Phase 2 convention)
- **Module structure**: __all__ exports, type hints on all signatures, selective imports from Phase 1
- **Test structure**: tests/unit/test_{module}.py for unit, tests/integration/ for cross-module
- **File I/O**: Atomic writes via temp file + rename for JSON config files

### Integration Points
- **Handler → wl_approval**: submit_approval, submit_dual_approval, get_pending_for_csv, expire_pending_approvals, check_approval_gate
- **Handler → wl_limits**: check_analyst_limit, check_admin_limit, get_limit_status, set_limit_config, reset_daily_limits, increment_daily_limit
- **wl_approval → wl_limits**: check_approval_gate calls wl_limits internally
- **wl_approval → wl_notify**: submit and cancel functions trigger notifications
- **wl_approval → wl_filelock**: Queue lock acquired via shared file_lock utility
- **wl_approval → wl_audit**: Cancellation and precondition-failure audit events

</code_context>

<specifics>
## Specific Ideas

- Lock ordering enforcement via runtime assertion — fail-fast approach, catches ordering bugs in development
- Functional conflict resolution (return new copy, don't mutate in-place) — safer for testing, no side-effect surprises
- RESET_ALL_USERS constant in wl_constants.py prevents the documented sentinel value bug permanently
- Action registry dict in handler (ACTION_HANDLERS) prepares for Phase 4 migration without blocking Phase 3

</specifics>

<deferred>
## Deferred Ideas

- Read/write lock semantics in wl_filelock.py — deferred until performance data shows read contention. Start with exclusive-only.
- Replay orchestration migration to wl_approval.py — deferred to Phase 4 (thin router refactoring)
- Queue entry schema migration (normalize dual-admin entries) — deferred unless conflict resolution requires it

</deferred>

---

*Phase: 03-backend-orchestration*
*Context gathered: 2026-04-01*
