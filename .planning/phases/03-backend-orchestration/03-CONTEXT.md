# Phase 3: Backend Orchestration — Phase Context

**Phase:** 03-backend-orchestration  
**Goals:** Extract 2 complex orchestration modules implementing approval queue management and daily limits enforcement.  
**Depends on:** Phase 1 (constants, logging, validation, RBAC), Phase 2 (CSV, versions, audit, rules, trash)  
**User:** Oleh | **Date:** 2026-03-31

---

## Phase Scope & Decisions

### What This Phase Accomplishes

Phase 3 extracts the 2 orchestration modules that coordinate approvals and enforce daily limits across all user operations from the monolithic `wl_handler.py`:

- **wl_limits.py** — Daily usage tracking, per-role limit enforcement, daily reset scheduling, admin limit gating
- **wl_approval.py** — Approval queue CRUD, request submission, approval/rejection/cancellation, destructive action auto-cancellation, approval expiry, request replay

These modules build on Phase 1–2 infrastructure and handle the most complex business logic in the system:
- State machine transitions (pending → approved/rejected/cancelled/expired/failed)
- File locking on shared queue data
- Auto-cancellation of conflicting requests (delete rule while edits pending)
- Replay of Phase 2 operations (save_csv, revert_csv, add_rule, etc.) with original analyst as context
- Concurrency safety under 5+ simultaneous requests
- Daily counter reset with timezone awareness

### Locked Decisions (from discussion)

**Module Boundaries:**
- wl_limits.py exports: `get_limit_config()`, `set_limit_config(config)`, `read_daily_limits()`, `write_daily_limits(counters)`, `get_counter_period_key(tz_offset_minutes=0)`, `check_daily_limit(user, action_type, action_count=1)`, `check_admin_daily_limit(admin_user, action_type, action_count=1)`, `increment_daily_limit(user, action_type, count=1)`, `increment_admin_daily_limit(admin_user, action_type, count=1)`, `reset_daily_usage(analyst, admin_user)`, `get_daily_limit_status(user)`
- wl_approval.py exports: `read_approval_queue()`, `write_approval_queue(queue)`, `get_approval_queue_path()`, `submit_approval_request(action_type, analyst, **kwargs)`, `get_approval_request(request_id)`, `process_approval_decision(request_id, decision, admin_user, rejection_reason="", cancellation_reason="", admin_comment="")`, `auto_cancel_conflicting_requests(csv_file, action_type)`, `expire_pending_approvals()`, `get_pending_for_csv(csv_file)`, `replay_approved_request(queue_item, admin_user)`

**Error Handling Pattern:**
- Both modules: return (data, error_msg) tuples for file operations; raise exceptions on system errors (import failures, etc.)
- Daily limits: (allowed_bool, current_int, max_int) tuple pattern maintained from monolith
- Approval queue: JSON parse errors logged + fallback to empty queue (non-breaking)

**File Locking:**
- Approval queue: single RLock for entire queue; acquired during read-modify-write cycles
- Daily limits: separate RLock for counters file
- Lock timeouts: 10 seconds with 3 retries, 100ms backoff
- Both use contextlib.contextmanager for guaranteed release

**Concurrency Patterns:**
- Approval replay must be atomic: lock queue → validate preconditions (CSV exists, rule exists) → call Phase 2 functions → update queue status → post audit event → unlock
- Daily limits check-then-increment must be atomic: read counters → validate against limit → log the use → write counters
- Race condition: two simultaneous requests for same user hitting same daily limit → serialize via lock

**Auto-Cancellation Strategy:**
When a destructive action (delete CSV, delete rule) is APPROVED:
1. Find all pending requests for same CSV/rule
2. For each pending request:
   - If action_type is incompatible (edit on deleted CSV), auto-cancel
   - Mark with status="auto_cancelled", rejection_reason="CSV/rule deleted by approved request"
   - Post audit event: action="request_auto_cancelled"

**Test Structure:**
- Unit tests in `tests/unit/test_limits.py`, `tests/unit/test_approval.py`
- Concurrency tests in `tests/integration/test_concurrency.py` (5+ simultaneous threads, approval races, limit enforcement)
- Integration tests in `tests/integration/test_approval_chain.py` (submit → approve → replay → audit)
- Coverage target: ≥80% per module

**No Functional Change Principle:**
- Every limit/approval function has a direct counterpart in wl_handler.py (~1-to-1 mapping)
- Handler passes through to modules without business logic changes
- API contracts frozen: request/response shapes unchanged
- Audit event structure unchanged

### Claude's Discretion

- Lock acquisition strategy (RLock vs separate Locks) — preferring single RLock per file for simplicity
- Timezone handling for daily reset (offset_minutes param) — implement ISO 8601 date-based keys
- Auto-cancellation priority (delete rule vs edit rule) — implement full cascade logic
- Queue item schema versioning (old/new request formats) — handle gracefully during replay
- Request replay validation (re-verify all preconditions) — validate CSV exists, rule exists, analyst still has permissions

### Deferred Ideas (OUT OF SCOPE)

- Advanced approval workflows (multi-level, weighted approval) — single-level approval only
- Machine learning-based anomaly detection for limits — static thresholds only
- Distributed approval queue (Redis/database backend) — single-file JSON only
- Webhook notifications for approval events — notifications table only (existing system)
- Approval history audit dashboards — requires Phase 8

---

## Requirements Coverage

| ID | Description | This Phase | Module |
|----|-------------|-----------|--------|
| BMOD-11 | wl_limits.py enforces per-role daily limits with role-aware thresholds | **Core** | wl_limits |
| BMOD-12 | wl_approval.py manages approval queue, request submission, approval/rejection/cancellation | **Core** | wl_approval |
| BMOD-13 | No function exceeds 100 lines or cyclomatic complexity of 15 | **Applied to all modules** | all |
| BMOD-14 | Consistent error handling pattern (fail-closed with state rollback) | **Applied to all modules** | all |
| BMOD-15 | No duplicated logic across backend modules (DRY compliance) | **Applied to Phase 3** | all |
| TEST-01 (partial) | Unit test suite covering ≥80% of Phase 3 modules | **Embedded in each plan** | all |
| TEST-04 (partial) | Concurrency tests for simultaneous CSV saves, approval races, file locking (5+ threads) | **Integration tests** | all |

---

## Architecture Patterns (Phase 1-2 Dependencies)

### Layer Hierarchy
```
Layer 0 (Phase 1): wl_constants (APPROVAL_EXPIRY_DAYS, MAX_TRACKED_ANALYSTS, etc.)
                    ↓
Layer 1 (Phase 1): wl_logging
                    ↓
Layer 2 (Phase 1): wl_validation, wl_rbac
                    ↓
Layer 3 (Phase 2): wl_csv, wl_versions, wl_audit, wl_rules, wl_trash
                    ↓
Layer 4 (Phase 3): wl_limits, wl_approval (orchestration)
```

All Phase 3 modules import from Layers 0-3 only. No circular imports. No forward dependencies.

### Type Hints & Exports

Every Phase 3 module:
- Exports explicit `__all__` with public API functions
- Uses type hints on all function signatures
- Imports Phase 1-2 modules selectively

### Lock Management

Approval queue and daily limits require file locks:
- Approval queue lock: single RLock held during read-modify-write of queue file
- Daily limits lock: separate RLock held during read-modify-write of counters file
- Lock failures on write: logged but don't crash (reads proceed without lock)
- Lock acquisitions: via context managers (contextlib.contextmanager)

### Approval State Machine

```
[pending] ──approve→ [approved] ──replay→ [succeeded|failed]
          ──reject→  [rejected]
          ──cancel→  [cancelled]
          ──expire→  [expired]
          ──auto_cancel→ [auto_cancelled]
```

Each transition:
- Updates queue item status, resolved_by, resolved_at
- Posts audit event with action=`request_[status]`
- Notifies analyst via notifications table (existing system)

### Request Replay Logic

When approval is processed with `decision="approve"`:
1. Validate preconditions (CSV exists, rule exists, analyst still has permission)
2. Re-read current CSV state (analyst's old state may be stale)
3. Call Phase 2 function with original analyst as context (e.g., `save_csv(path, headers, rows, analyst=target['analyst'])`)
4. Update queue item status="approved" (or "failed" if replay fails)
5. Post audit event with action="request_approved" or "request_failed"
6. Notify analyst

Precondition validation (before replay):
- `action_type not in _no_csv_actions` → verify CSV file exists at expected path
- `action_type in {"add_rule", "remove_rule", "edit_rule"}` → verify rule exists in registry
- `action_type == "remove_csv"` → verify CSV exists (about to be deleted)
- All actions → verify analyst role still has permission (re-check RBAC)

### Daily Limits Constants

From wl_constants (Phase 1 imports):
```python
DEFAULT_LIMITS = {
    "row_removal": 50,
    "row_addition": 50,
    "row_edit": 100,
    "bulk_row_removal": 10,
    "bulk_row_edit": 10,
    "column_removal": 5,
    "revert": 5,
    "rule_deletion": 2,
    "csv_deletion": 1,
    "approval_count": 20,  # Admin-specific
}

APPROVAL_EXPIRY_DAYS = 30
MAX_TRACKED_ANALYSTS = 1000  # Prevent unbounded memory in counters file
MAX_RESOLVED_HISTORY = 5000  # Keep only newest 5000 resolved entries
```

---

## Phase Success Criteria

When Phase 3 completes, ALL of the following must be TRUE:

1. **Functional Preservation**: User can submit edits for approval, admin can approve/reject with correct audit trail, limits are enforced, all as before (no functional change)
2. **Module Extraction**: Two new modules exist in `bin/` and are imported by wl_handler.py: wl_limits, wl_approval
3. **Complexity Control**: No function exceeds 100 lines; no module exceeds CC=15; visible complexity reduced
4. **Test Coverage**: ≥80% unit test coverage per module; concurrency tests with 5+ threads; approval chain integration tests
5. **Auto-Cancellation**: Destructive actions (delete CSV/rule) auto-cancel conflicting pending requests
6. **Concurrency Safety**: 5+ simultaneous CSV saves, approval races, and file locking under contention all pass
7. **Daily Limits**: Check passes for all role tiers; reset scheduling works; admin limits gate approval counts

---

## Deliverables

- 2 new Python modules in `bin/`: wl_limits.py, wl_approval.py
- 2 unit test files in `tests/unit/`: test_limits.py, test_approval.py
- 2 integration test files: test_approval_chain.py, test_concurrency.py
- Updated `bin/wl_handler.py`: imports new modules, calls extracted functions instead of inline logic
- Updated ROADMAP.md with Phase 3 plan details
- Coverage reports showing ≥80% per module
- Git commits: one module per commit (wl_limits, wl_approval)

---

## Next Phase: Phase 4

Phase 4 depends on Phase 3 completion:
- wl_handler.py becomes thin REST router (remaining ~200 lines)
- All action handlers (get_csv, save_csv, process_approval, etc.) delegate to Phase 1-3 modules
- No business logic remains in handler itself

---

*Context created: 2026-03-31*
*Last updated: 2026-03-31*
