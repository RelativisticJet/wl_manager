# Phase 3: Backend Orchestration - Research

**Researched:** 2026-04-01  
**Domain:** Approval queue management, daily usage limits, notification system, file locking  
**Confidence:** HIGH

## Summary

Phase 3 extracts four orchestration modules (wl_limits.py, wl_approval.py, wl_notify.py, wl_filelock.py) from wl_handler.py's embedded orchestration logic. These modules coordinate Phase 1's foundation (constants, RBAC) and Phase 2's domain modules (CSV, versions, audit, trash) to implement approval gating and daily limit enforcement across the application.

The research confirms that the handler currently contains ~600 lines of approval queue CRUD, conflict resolution, daily limits checking/resetting, and notification logic spread across 15+ functions. Extraction follows the proven Phase 2 pattern: pure functions with clear responsibilities, file I/O via atomic temp→rename, and comprehensive unit testing for all logic paths.

**Primary recommendation:** Extract in dependency order: (1) wl_filelock.py (used by all modules), (2) wl_limits.py (used by approval gating), (3) wl_approval.py (uses limits + filelock), (4) wl_notify.py (called by approval). Implement unit tests first for limits/approval core logic before wiring into handler.

## User Constraints (from CONTEXT.md)

### Locked Decisions

**Approval Replay Architecture:**
- Handler passthrough pattern: wl_approval.py manages queue CRUD, conflict resolution, submission, and expiration
- Actual replay orchestration (_process_approval_inner) stays in handler until Phase 4
- Define ACTION_HANDLERS dict in handler mapping action types to replay functions (structured for future Phase 4 migration)
- Submit functions (submit_approval, submit_dual_approval) exported from wl_approval.py with validation + queue write + notification trigger

**Queue Schema & Validation:**
- Unified queue: Single approval_queue.json with entry type field (standard, create/delete, dual-admin)
- Validate on both read+write; fail entire read on corruption (fail-closed)
- Specific query helpers: get_pending_for_csv(csv_file), get_pending_for_rule(rule_name) — not generic predicates
- Schema-aware field access via helpers (not normalized on read)

**Conflict Resolution:**
- Check for conflicts on EVERY approve (not just destructive actions)
- CSV-level cancel added: When CSV is trashed/deleted, cancel all pending edits for that CSV
- Restore triggers conflicts too: Trash, delete, restore all check for conflicts
- Dry run mode: check_conflicts(queue, action) returns what WOULD be cancelled; cancel_conflicts() actually cancels
- Return cancelled list + notify: cancel_conflicts() returns (new_queue, cancelled_entries)
- Functional style: No in-place mutation; cancel_conflicts() returns new copy
- Precondition validation: Validate CSV/rule existence before replay; audit log with action='approval_precondition_failed' on stale requests
- Audit trail: Auto-cancel events include 'cancelled_by_action' and 'cancelled_by_analyst' fields

**Daily Limits Architecture:**
- Separate subsystems: check_analyst_limit() and check_admin_limit() as distinct functions
- Reset logic in module: reset_daily_limits(analyst=None) in wl_limits.py
- **0 = disabled everywhere:** Consistent semantic; max_count==0 means 'limit not enforced' (fixes MEMORY.md inconsistency)
- Status API: get_limit_status(user, roles) returns {action_type: {current: N, max: M, remaining: R}}
- Approval gate: check_approval_gate(user, action_type, action_count, roles) combines limit + threshold checks
- Admin exemption in module: check_analyst_limit() accepts roles, returns 'exempt' for admins
- All config in wl_limits.py: Both limit config AND approval thresholds (single source of truth)
- Direct handler calls: Handler's _set_daily_limits_action calls wl_limits.set_limit_config() directly
- RESET_ALL_USERS constant: Add to wl_constants.py; module checks against constant, not magic string "all"
- Error messages in module: _daily_limit_error_msg logic lives in wl_limits.py

**Concurrency Model:**
- Shared lock utility: Extract wl_filelock.py with file_lock(path, timeout) context manager
- Exclusive locks first: Start with exclusive-only; add read/write later when performance data shows contention
- No-op on Windows: fcntl on Unix, no-op on Windows (development-only)
- Lock ordering: Document and enforce via runtime assertion; LOCK_ORDER: 1) approval_queue, 2) daily_limits, 3) csv_file
- Both test layers: Unit tests use mocks; integration tests use temp files
- Concurrency test goals: Data integrity primary (valid JSON, all entries present, no corruption); ordering as best-effort

**Notification Module (wl_notify.py):**
- Full scope: notify_admins(session_key, type, details) + notify_analyst(session_key, analyst, type, details)
- Covers all approval events: submissions, approvals, rejections, auto-cancellations
- Extracted from handler: _notify_admins and analyst notification logic moved to wl_notify.py

**Module Count & Roadmap:**
- 4 modules total: wl_limits.py, wl_approval.py, wl_notify.py, wl_filelock.py
- Roadmap should be updated to reflect expanded scope

### Claude's Discretion

- Schema-aware field access strategy (normalize on read vs helper functions) — prefer helpers for clarity
- Grouping of queue CRUD helper functions within wl_approval.py — organize by function family
- Integration test depth for concurrency scenarios beyond 5-thread smoke test — start with 5 threads, expand if needed
- Lock acquisition strategy (contextlib ExitStack vs manual acquire/release) in wl_filelock.py — prefer context manager

### Deferred Ideas (OUT OF SCOPE)

- Read/write lock semantics in wl_filelock.py — deferred until performance data shows read contention
- Replay orchestration migration to wl_approval.py — deferred to Phase 4
- Queue entry schema migration (normalize dual-admin entries) — deferred unless conflict resolution requires it

---

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| BMOD-11 | wl_limits.py provides daily usage tracking, reset scheduling, and enforcement | Extract check_analyst_limit, check_admin_limit, reset_daily_limits, get_limit_status, set_limit_config from handler (~200 lines) |
| BMOD-12 | wl_approval.py manages approval queue CRUD, request processing, and conflict resolution | Extract queue read/write, submit functions, conflict resolution, expiration logic (~400 lines) |
| BMOD-13 (partial) | No function exceeds 100 lines or CC<15 | Refactor oversized functions (dispatch+helpers pattern proven in Phase 2) |
| BMOD-14 (partial) | Consistent error handling (fail-closed with state rollback) | Use atomic writes via temp+rename; validation on both directions; explicit error propagation |
| BMOD-15 (partial) | No duplicated logic | DRY file locking in wl_filelock.py; centralize limit config and error messages in wl_limits.py |
| TEST-01 (partial) | Unit test suite covering ≥80% of every backend module | Create tests/unit/test_limits.py and tests/unit/test_approval.py with mocks |
| TEST-04 (partial) | Concurrency tests for simultaneous saves, approval races, and file locking | Create tests/integration/test_concurrency.py with 5+ thread scenarios |

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python | 3.8+ (Splunk 9.x) | Handler language | Splunk standard; no Python 2 support |
| json | stdlib | Queue/limits/config persistence | Built-in; no dependencies; standard for config |
| threading | stdlib | RLock for in-process synchronization | Only async primitive available in Splunk environment |
| fcntl | stdlib (Unix only) | Cross-process file locking | POSIX standard; Phase 2 proven pattern |
| contextlib | stdlib | Context manager for lock acquire/release | Python idiom for resource management |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|------------|
| time | stdlib | Timestamp generation, age calculations | All time-based operations (expiry, reset scheduling) |
| os | stdlib | File path operations, makedirs | Standard for filesystem I/O |

**No external packages required.** Approval queue, limits, and notifications are pure filesystem and in-memory operations.

## Architecture Patterns

### Recommended Project Structure (After Phase 3)

```
bin/
├── wl_handler.py           # (~200 lines) Thin router; delegates to modules
├── wl_constants.py         # Layer 0: Constants (RESET_ALL_USERS added)
├── wl_logging.py           # Layer 1: Audit logger
├── wl_validation.py        # Layer 2: Input sanitization
├── wl_ratelimit.py         # Layer 2: Rate limiting
├── wl_rbac.py              # Layer 2: Role checking
├── wl_presence.py          # Layer 2: User presence tracking
├── wl_filelock.py          # Layer 3: Shared file locking utility
├── wl_csv.py               # Layer 3: CSV read/write/diff
├── wl_versions.py          # Layer 3: Version snapshots
├── wl_audit.py             # Layer 3: Audit event construction
├── wl_rules.py             # Layer 3: Rules registry
├── wl_trash.py             # Layer 3: Soft-delete and restore
├── wl_limits.py            # Layer 4: Daily usage tracking and enforcement (NEW)
├── wl_approval.py          # Layer 4: Approval queue orchestration (NEW)
└── wl_notify.py            # Layer 4: Notifications (NEW)

tests/unit/
├── test_limits.py          # 40+ tests; mock file I/O, time
├── test_approval.py        # 50+ tests; mock locks, queue operations
└── (existing test modules)

tests/integration/
├── test_concurrency.py     # 5+ thread scenarios; real temp files
├── test_approval_chain.py  # Approval sequence flows
└── (existing integration tests)
```

### Pattern 1: File-Based Configuration with Atomic Writes

**What:** Synchronize multi-process access to JSON config files using fcntl locks + temp→rename pattern.

**When to use:** Approval queue, daily limits, notifications—any shared state accessed from multiple handler threads.

**Example:**
```python
# Source: wl_versions.py (Phase 2, proven pattern)
def write_version_manifest(manifest_path: str, manifest: Dict) -> None:
    """Write manifest to disk atomically with file locking."""
    temp_path = manifest_path + ".tmp"
    try:
        with open(temp_path, "w", encoding="utf-8") as fh:
            if fcntl:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                json.dump(manifest, fh, indent=2)
            finally:
                if fcntl:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        os.replace(temp_path, manifest_path)
    except OSError:
        raise
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
```

### Pattern 2: Dispatcher + Sub-functions (Function Size Compliance)

**What:** Break oversized functions into focused sub-functions without changing external API.

**When to use:** Functions >100 lines or CC>15 (BMOD-13 compliance).

**Example (from Phase 2 wl_trash.py):**
```python
# Source: wl_trash.py move_to_trash dispatcher
def move_to_trash(item_type, item_name, ...):
    """Dispatcher: routes to specific handler by type."""
    if item_type == "csv":
        return move_csv_to_trash(...)
    elif item_type == "rule":
        return move_rule_to_trash(...)
    # (70 lines total)

def move_csv_to_trash(csv_name, ...):
    """CSV-specific handler."""
    # (30 lines)

def move_rule_to_trash(rule_name, ...):
    """Rule-specific handler."""
    # (25 lines)
```

### Pattern 3: Context Manager for Lock Acquisition

**What:** Combine threading.RLock (in-process) with fcntl locks (cross-process).

**When to use:** Shared queue/config reads that must be exclusive.

**Example:**
```python
# Source: wl_handler.py (current)
@contextmanager
def _approval_queue_lock():
    """Acquire in-process + cross-process lock."""
    with _approval_queue_thread_lock:  # In-process
        if not fcntl:
            yield
            return
        lock_path = _get_approval_queue_path() + ".lock"
        fh = open(lock_path, "w")
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            fh.close()
```

### Pattern 4: Read → Validate → Write (Fail-Closed)

**What:** Always validate on both read and write. If validation fails, refuse the operation.

**When to use:** Queue/config files that can become corrupted.

**Example:**
```python
# Source: Phase 3 pattern
def _read_approval_queue():
    """Read and validate queue; fail-closed on corruption."""
    path = _get_approval_queue_path()
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            queue = json.load(fh)
        # VALIDATE: Check every entry has required fields
        for entry in queue:
            if not all(k in entry for k in ["request_id", "status", "timestamp"]):
                raise ValueError(f"Invalid entry: {entry}")
        return queue
    except (json.JSONDecodeError, ValueError):
        raise  # Fail-closed: return error, don't return empty list
```

### Anti-Patterns to Avoid

- **Silent failure on config read:** Returning empty list/dict on JSON parse error hides corruption. Fail-closed: raise exception and let caller handle.
- **Mutable default arguments:** Don't pass empty dict/list as default in function signature; use None + lazy init.
- **Magic strings for sentinel values:** Use RESET_ALL_USERS constant in wl_constants.py, not "all". Prevents typos and makes intent clear.
- **In-place mutation in functional code:** cancel_conflicts() should return (new_queue, cancelled_entries), not mutate queue arg.
- **Inconsistent semantics for 0:** Some code treated max_count==0 as "unlimited", others as "disabled". Use consistent definition: 0 = disabled everywhere.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Cross-process file locking | Custom lock files, polling, sleep loops | wl_filelock.py context manager + fcntl | Proper POSIX semantics; avoids race conditions; proven in Phase 2 |
| Atomic config writes | Write to file directly; risk of partial writes | temp file → rename pattern (atomic on POSIX) | Prevents corruption if process crashes mid-write; standard Unix idiom |
| Queue expiration logic | Manually check ages every operation | expire_pending_approvals() in wl_approval.py | Centralized; called once per read; prevents stale entries surfacing |
| Approval validation | Duplicate checks in submit_approval and handler | Centralize in submit_approval; handler just calls it | Single source of truth; easier to audit; prevents bypass via dual paths |
| Limit config reset scheduling | Handler directly reading/writing cron state | reset_daily_limits() in wl_limits.py; handler calls it | Encapsulated; testable without Splunk scheduler; easier to verify correctness |

**Key insight:** Approval queue, daily limits, and notifications are stateful systems with multi-process access patterns. Building these correctly requires: (1) atomic file writes, (2) proper locking semantics, (3) fail-closed validation. Off-the-shelf libraries aren't necessary—pure Python + fcntl suffice—but the patterns must be followed exactly. Phase 2 proved this works; Phase 3 reuses the same patterns.

## Common Pitfalls

### Pitfall 1: Lost Updates in Concurrent Queue Access

**What goes wrong:** Handler process A reads queue, modifies, writes. During that time, process B also reads queue, modifies, writes. Process A's changes are lost.

**Why it happens:** File I/O is not atomic without explicit locking. fcntl.flock() provides exclusive locks but must wrap the read→modify→write cycle.

**How to avoid:** Always use context manager: `with _approval_queue_lock(): queue = _read_approval_queue(); ...; _write_approval_queue(queue)`. Never read then write separately without lock in between.

**Warning signs:** Entries disappearing from queue; approval requests silently dropped; duplicate entries.

### Pitfall 2: Stale Time-Based Checks

**What goes wrong:** Request expires "after 7 days" but was created with `int(time.time())`. Later code compares against `time.time()` (float). Expiry check uses integer division `age_days = (now - timestamp) / 86400`, rounding down. Edge case: request at age 6.99 days never expires.

**Why it happens:** Mixing int and float timestamps; imprecise age calculation.

**How to avoid:** Always use `int(time.time())` for timestamps. Always use `<=` not `<` for boundary checks. Test expiry at exact boundary: request created N days ago should expire immediately.

**Warning signs:** Old requests not expiring; expired requests surfacing; boundary test failures.

### Pitfall 3: Inconsistent Limit Semantics

**What goes wrong:** check_analyst_limit() treats max_count==0 as "unlimited". check_admin_limit() treats it as "disabled". Code fails for admin limits with max_count=0 because permission is always denied.

**Why it happens:** Code evolved piecemeal; no explicit semantic definition; tests only covered happy path (max_count > 0).

**How to avoid:** Define once, enforce everywhere: "0 means disabled (action not permitted)". Add constant RESET_ALL_USERS = "__all__" for sentinel values. Use explicit tests for both 0 and positive limits.

**Warning signs:** Different behavior between analyst and admin limits; magic string checks like `if analyst == "all"` (truthy, causes bugs if admin is named "all").

### Pitfall 4: Forgetting to Validate After Conflict Resolution

**What goes wrong:** Approval X (create CSV) and approval Y (edit CSV) are both pending. Admin approves Y, which auto-cancels X. Later, admin tries to replay X. Code doesn't check if the CSV still exists. Replay silently fails or creates the CSV anyway (inconsistent state).

**Why it happens:** Validation is done at submission time, not replay time. State changes between submission and replay (deletions, approvals) aren't re-checked.

**How to avoid:** Before replaying ANY approved action: re-validate preconditions (CSV exists, rule exists, columns still present). If preconditions fail, audit log with action='approval_precondition_failed' and skip replay.

**Warning signs:** Orphaned pending requests surfacing; replay creating resources that should be deleted; inconsistent queue state.

### Pitfall 5: Parsing Failure Silently Proceeding

**What goes wrong:** Limit config has corrupted reset_time_utc field (typo in manual edit). Code does `(ValueError, TypeError): pass`, silently ignoring the error and using defaults. This bypasses limit enforcement indefinitely.

**Why it happens:** Defensive coding that's TOO defensive. Catching exceptions without re-raising for security-relevant failures.

**How to avoid:** For config/state files, fail-closed: parse error = return error, not empty state. Let caller decide whether to use defaults or abort. For approval queue specifically, raise exception on corruption; admin must manually fix.

**Warning signs:** Limits not enforcing; approval queue entries disappearing; config files becoming increasingly corrupted.

---

## Code Examples

Verified patterns from handler and Phase 2 modules:

### Lock-Protected Queue Read-Modify-Write

```python
# Source: wl_handler.py _cancel_conflicting_requests (current)
def cancel_conflicting_requests(queue, action, trigger_request_id, audit_fn):
    """Return (new_queue, cancelled_entries). Caller holds lock."""
    now = int(time.time())
    cancelled = []
    new_queue = queue[:]  # Copy, don't mutate
    
    for entry in new_queue:
        if _conflicts_with(entry, action):
            entry["status"] = "cancelled"
            entry["resolved_by"] = "system"
            entry["resolved_at"] = now
            cancelled.append(entry)
    
    return new_queue, cancelled

# In handler's approval processing:
with _approval_queue_lock():
    queue = _read_approval_queue()
    new_queue, cancelled = cancel_conflicting_requests(queue, action)
    if cancelled:
        _write_approval_queue(new_queue)
        for entry in cancelled:
            audit_fn({...})
```

### Daily Limit Check with Proper 0-Semantics

```python
# Source: Phase 3 pattern (wl_limits.py)
def check_analyst_limit(user, action_type, action_count=1, roles=None):
    """Check if analyst can perform action. Returns (allowed, current, max)."""
    if roles and is_admin(roles):
        return True, 0, -1  # Admins exempt (signal as unlimited)
    
    config = _read_limit_config()
    max_count = config.get(action_type, DEFAULT_LIMITS.get(action_type))
    
    # 0 means disabled (not permitted)
    if max_count == 0:
        return False, 0, 0
    
    # -1 means unlimited
    if max_count == -1:
        return True, 0, -1
    
    counters = _read_daily_limits()
    period_key = _get_counter_period_key()
    current = counters.get(period_key, {}).get(user, {}).get(action_type, 0)
    
    allowed = (current + action_count) <= max_count
    return allowed, current, max_count
```

### Atomic Config Write with Validation

```python
# Source: Phase 2 pattern (wl_versions.py), applied to limits
def set_limit_config(config):
    """Write limit config atomically. Validate before writing."""
    # Pre-validation: all required keys present, values are ints
    required_keys = ["row_removal", "row_addition", "bulk_row_removal", ...]
    for key in required_keys:
        if key not in config:
            raise ValueError(f"Missing required config key: {key}")
        if not isinstance(config[key], int):
            raise ValueError(f"Config value must be int: {key}={config[key]}")
    
    path = _get_limit_config_path()
    temp_path = path + ".tmp"
    try:
        with open(temp_path, "w", encoding="utf-8") as fh:
            if fcntl:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                json.dump(config, fh, indent=2)
            finally:
                if fcntl:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
```

### Expiration Logic with Proper Boundary Testing

```python
# Source: wl_handler.py _expire_pending_approvals (current)
def expire_pending_approvals(queue, now=None):
    """Expire requests older than APPROVAL_EXPIRY_DAYS. Returns modified queue."""
    if now is None:
        now = time.time()
    
    changed = False
    for item in queue:
        if item["status"] == "pending":
            age_seconds = now - item["timestamp"]
            age_days = age_seconds / 86400.0
            
            # Use <= not <; ensures boundary case expires immediately
            if age_days >= APPROVAL_EXPIRY_DAYS:
                item["status"] = "expired"
                item["resolved_by"] = "system"
                item["resolved_at"] = int(now)
                changed = True
    
    # Prune resolved entries older than 30 days (cutoff in past)
    cutoff = now - (30 * 86400)
    before = len(queue)
    queue = [item for item in queue
             if item["status"] == "pending"
             or item.get("resolved_at", 0) > cutoff]
    
    if len(queue) != before:
        changed = True
    
    return queue if changed else queue  # Caller handles write
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Embedded queue logic in handler | Extract wl_approval.py module | Phase 3 (planned) | Testable in isolation; reusable by other modules; clear boundaries |
| Inline limit checking scattered across handler | Centralized wl_limits.py | Phase 3 (planned) | Single source of truth; consistent 0-semantics; easier to verify config |
| File locking code duplicated in _write_version_manifest and _write_approval_queue | Shared wl_filelock.py context manager | Phase 3 (planned) | DRY; consistent semantics; single place to audit locking behavior |
| Approval and limits both in handler; no clear API | Public module functions exported via __all__ | Phase 3 (planned) | Handler becomes thin router; modules are independently testable |
| Notifications scattered (some in handler, some in module callbacks) | Centralized wl_notify.py with notify_admins and notify_analyst | Phase 3 (planned) | Single API for all notifications; consistent message format; audit trail |

**Deprecated/outdated:**
- Inline approval queue logic in handler: Now in wl_approval.py (BMOD-12)
- Embedded daily limits logic: Now in wl_limits.py (BMOD-11)
- Per-module file locking: Unified in wl_filelock.py (BMOD-15 DRY)
- Hardcoded magic strings like "all" for sentinel values: Now RESET_ALL_USERS constant (prevents sentinel value bugs)

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 7.4+ (Phase 2 established) |
| Config file | tests/conftest.py, tests/pytest.ini |
| Quick run command | `pytest tests/unit/test_limits.py tests/unit/test_approval.py -v` |
| Full suite command | `pytest tests/ -v --cov=bin/wl_limits.py --cov=bin/wl_approval.py` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| BMOD-11 | check_analyst_limit returns (allowed, current, max) with proper 0-semantics | unit | `pytest tests/unit/test_limits.py::test_analyst_limit_disabled_when_max_is_zero -xvs` | ❌ Wave 0 |
| BMOD-11 | check_admin_limit respects admin exemption (returns True for admin roles) | unit | `pytest tests/unit/test_limits.py::test_admin_limit_exempt -xvs` | ❌ Wave 0 |
| BMOD-11 | reset_daily_limits(analyst="all") resets all analysts; reset_daily_limits(analyst="jsmith") resets only jsmith | unit | `pytest tests/unit/test_limits.py::test_reset_all_vs_single_analyst -xvs` | ❌ Wave 0 |
| BMOD-11 | get_limit_status returns {action_type: {current, max, remaining}} for all action types | unit | `pytest tests/unit/test_limits.py::test_limit_status_format -xvs` | ❌ Wave 0 |
| BMOD-11 | Daily limit counters reset at configured reset_time_utc boundary (accounting for frequency) | unit | `pytest tests/unit/test_limits.py::test_reset_time_boundary -xvs` | ❌ Wave 0 |
| BMOD-12 | get_pending_for_csv(csv_file) returns only non-expired pending requests for that CSV | unit | `pytest tests/unit/test_approval.py::test_get_pending_for_csv -xvs` | ❌ Wave 0 |
| BMOD-12 | submit_approval validates payload, checks limits, writes queue, triggers notification | unit | `pytest tests/unit/test_approval.py::test_submit_approval_happy_path -xvs` | ❌ Wave 0 |
| BMOD-12 | cancel_conflicts(queue, action) returns (new_queue, cancelled_list) without mutating input | unit | `pytest tests/unit/test_approval.py::test_cancel_conflicts_functional -xvs` | ❌ Wave 0 |
| BMOD-12 | expire_pending_approvals removes requests older than APPROVAL_EXPIRY_DAYS and prunes resolved history | unit | `pytest tests/unit/test_approval.py::test_expiration_at_boundary -xvs` | ❌ Wave 0 |
| BMOD-13 | All functions in wl_limits and wl_approval ≤100 lines; CC<15 for all | unit | `pytest tests/unit/ -v; radon cc bin/wl_limits.py bin/wl_approval.py` | ❌ Wave 0 |
| BMOD-14 | Atomic writes via temp+rename; validation on read (fail-closed on corruption) | unit | `pytest tests/unit/test_limits.py::test_fail_closed_on_corrupted_config -xvs` | ❌ Wave 0 |
| BMOD-15 | File locking centralized in wl_filelock.py; used by all queue/config writers | unit | `pytest tests/unit/test_filelock.py -xvs` | ❌ Wave 0 |
| TEST-01 (partial) | Unit tests for wl_limits: ≥40 tests covering all functions, edge cases (0 max, -1 unlimited, reset boundaries) | unit | `pytest tests/unit/test_limits.py -v --cov=bin/wl_limits.py --cov-fail-under=80` | ❌ Wave 0 |
| TEST-01 (partial) | Unit tests for wl_approval: ≥50 tests covering queue CRUD, conflict resolution, expiration | unit | `pytest tests/unit/test_approval.py -v --cov=bin/wl_approval.py --cov-fail-under=80` | ❌ Wave 0 |
| TEST-04 (partial) | Concurrency test: 5+ threads simultaneously write approval queue; no data loss, corruption, or silent overwrites | integration | `pytest tests/integration/test_concurrency.py::test_concurrent_queue_writes -xvs` | ❌ Wave 0 |
| TEST-04 (partial) | Concurrency test: simultaneous limit increment from N threads; final count matches N * increments_per_thread | integration | `pytest tests/integration/test_concurrency.py::test_concurrent_limit_increment -xvs` | ❌ Wave 0 |
| TEST-04 (partial) | Concurrency test: approval approval while limits are being reset; no race conditions | integration | `pytest tests/integration/test_concurrency.py::test_approval_during_limit_reset -xvs` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/unit/test_limits.py tests/unit/test_approval.py -v` (quick validation before commit)
- **Per wave merge:** `pytest tests/ -v --cov=bin/wl_limits.py --cov=bin/wl_approval.py --cov-fail-under=80` (full coverage + integration tests)
- **Phase gate:** Full suite green + concurrency tests pass before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `tests/unit/test_limits.py` — 40+ unit tests covering all BMOD-11 behaviors; mocked time + file I/O
- [ ] `tests/unit/test_approval.py` — 50+ unit tests covering all BMOD-12 behaviors; mocked locks + queue operations
- [ ] `tests/integration/test_concurrency.py` — 5+ concurrency tests (concurrent writes, increments, resets); real temp files + threading
- [ ] Framework install — pytest, freezegun (for deterministic timestamps), pytest-cov already configured
- [ ] `tests/unit/test_filelock.py` — 15+ tests for wl_filelock context manager (mocked fcntl on non-Unix, real locks on Unix)

*(Wave 0 gaps are filled during plan execution; no test infrastructure changes required.)*

---

## Sources

### Primary (HIGH confidence)

- **Context7 handler analysis:** Handler contains 600+ lines of approval queue, daily limits, and notification logic (lines 228-850)
- **Phase 3 CONTEXT.md:** Locked decisions on all four modules, validation patterns, concurrency model, lock ordering
- **Phase 2 completed modules:** wl_csv.py, wl_versions.py, wl_audit.py proven patterns for file I/O, atomic writes, locking
- **Existing unit test structure:** tests/unit/ (Phase 2), conftest.py fixtures, mocking patterns for Splunk SDK

### Secondary (MEDIUM confidence)

- **handler.py _approval_queue_lock context manager** — cross-process + in-process locking proven in current code
- **handler.py _cancel_conflicting_requests** — conflict resolution logic; refactored into Phase 3 module
- **handler.py _expire_pending_approvals** — expiration logic; edge case with float vs int timestamps noted in MEMORY.md

### Tertiary (LOW confidence - marked for validation)

- Integration test depth for 5+ thread concurrency scenarios — no existing precedent in codebase; recommend starting with 5 threads, expanding if needed

---

## Metadata

**Confidence breakdown:**
- **Standard stack:** HIGH — Pure Python stdlib; no external dependencies; fcntl proven in Phase 2
- **Architecture:** HIGH — Phase 2 patterns directly applicable; decision locked in CONTEXT.md
- **Pitfalls:** HIGH — MEMORY.md documents 5+ past bugs (sentinel values, set vs counter, dual paths); Phase 3 addresses these
- **Validation:** MEDIUM — Test framework established (pytest); concurrency test depth unproven (start with smoke test)

**Research date:** 2026-04-01  
**Valid until:** 2026-05-01 (30 days; stable domain, low velocity)

---

*Phase: 03-backend-orchestration*
*Research gathered: 2026-04-01*
