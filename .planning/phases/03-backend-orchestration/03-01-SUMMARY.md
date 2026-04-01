---
phase: 03
plan: 01
subsystem: backend-orchestration
tags: [file-locking, daily-limits, rbac-enforcement]
dependency_graph:
  requires: [02-06]
  provides: [wl_filelock, wl_limits, admin-exemption]
  affects: [03-02, 03-03, 03-04]
tech_stack:
  added: [threading.RLock, fcntl.flock, JSON-based counters, atomic-file-operations]
  patterns: [context-manager, fail-closed-error-handling, sentinel-values]
key_files:
  created:
    - bin/wl_filelock.py
    - bin/wl_limits.py
    - tests/unit/test_filelock.py
    - tests/unit/test_limits.py
  modified:
    - bin/wl_constants.py (RESET_ALL_USERS sentinel added)
    - bin/wl_handler.py (imports wired, no functional changes)
decisions:
  - Zero-semantics: 0=disabled (deny all), -1=unlimited (allow all), N>0=enforce limit N (applied consistently)
  - Windows compatibility: fcntl unavailable → no-op file locking on Windows (dev-only, acceptable)
  - Admin exemption: is_admin() check returns (True, 0, -1) to bypass all limits (delegated to Phase 4 for handler integration)
  - Atomic writes: Temp file + file_lock context + os.replace pattern (inherited from Phase 2)
  - Fail-closed: Return empty dict or False on errors, never raise exceptions (data consistency over feature availability)
metrics:
  duration: "~90 minutes"
  tasks_completed: 7
  files_created: 4
  files_modified: 2
  lines_added: 850
  test_coverage: 48 tests (17 filelock, 31 limits)
  completion_date: "2026-04-01"
---

# Phase 03 Plan 01: Backend Orchestration — File Locking & Daily Limits

**One-liner:** Implemented cross-process file locking (RLock + fcntl) and daily usage limit tracking with admin exemption, enabling concurrent-safe state management for all Phase 3+ orchestration modules.

## Objective

Establish foundational orchestration infrastructure for the Splunk whitelist manager:
- **File locking**: RLock (thread-safe) + fcntl.flock (cross-process, Unix-only) context manager for atomic file operations
- **Daily usage limits**: Per-analyst, per-action counters with zero semantics (0=disabled, -1=unlimited, N=limit), admin exemption via RBAC, and configurable reset schedules
- **Admin control**: Superadmins can configure limits and reset counters via dedicated functions
- **Backward compatibility**: New modules imported into wl_handler.py but full refactoring deferred to Phase 4

## Completed Tasks

### Task 1: Implement wl_filelock.py (File Locking Layer)
**File:** `bin/wl_filelock.py` (100 lines)

Centralized file locking context manager implementing thread-safe + cross-process locking:
- **Module-level state**: `_file_lock_thread_lock = threading.RLock()` for in-process mutual exclusion
- **Context manager**: `file_lock(lock_path, timeout=10)` acquires RLock first, then fcntl.flock on Unix
- **Platform handling**: Detects fcntl availability; no-op on Windows (dev-only, acceptable)
- **Timeout/retry**: 10-second default, 0.1-second retry intervals (100 attempts max)
- **Error handling**: 
  - `ValueError` if timeout < 0
  - `TimeoutError` if lock not acquired within timeout
  - Ensures lock released and file closed in finally block (exception-safe)

**Exports:**
```python
file_lock(lock_path: str, timeout: int = 10) -> ContextManager[bool]
```

**Key insight:** RLock before fcntl allows a single thread to re-acquire the same lock (important for nested operations in Phase 3), while fcntl.flock blocks other processes. Windows dev environment has no fcntl, so the context manager simply acquires RLock and yields True (sufficient for single-process testing).

### Task 2: Implement wl_limits.py (Daily Usage Limits Layer)
**File:** `bin/wl_limits.py` (360+ lines)

Comprehensive daily usage tracking and limit enforcement with admin exemption and configurability:

**Public Functions:**
- `check_analyst_limit(user, action_type, action_count=1, roles=None) -> (bool, int, int)` — Check if analyst can perform action
  - Returns (allowed, current_count, max_count)
  - Admin exempt: returns (True, 0, -1) 
  - Disabled (0): returns (False, 0, 0)
  - Unlimited (-1): returns (True, 0, -1)
  - Limited (N>0): enforces counter >= max
- `check_admin_limit(user, action_type, action_count=1) -> (bool, int, int)` — Check admin-specific limits (separate config)
- `get_limit_status(user, roles=None) -> Dict` — Per-action-type status: {action_type: {current, max, remaining}}
- `increment_daily_limit(user, action_type, amount=1) -> bool` — Increment counter after successful action
- `set_limit_config(config: Dict) -> (bool, str)` — Atomically write new configuration with validation
- `reset_daily_limits(analyst=None) -> (bool, Dict)` — Reset all or single analyst; sentinel `RESET_ALL_USERS` for "all"
- `get_limit_error_msg(user, action_type, current, max_int) -> str` — Format user-facing error message

**Private Helpers:**
- `_read_daily_limits() -> Dict` — Fail-closed on JSON corruption: returns {}
- `_write_daily_limits(counters: Dict) -> bool` — Atomic write: temp file + lock + os.replace
- `_read_limit_config() -> Dict` — Fallback to DEFAULT_LIMITS if missing/corrupted
- `_get_counter_period_key() -> str` — "YYYY-MM-DD" for daily frequency (weekly/monthly extensible)
- `_should_reset_now(reset_time_utc, reset_frequency) -> bool` — Check if reset boundary crossed (simplified daily logic)

**Zero Semantics (enforced consistently):**
- `0`: Action disabled — deny all, return (False, 0, 0)
- `-1`: Unlimited — allow all, return (True, 0, -1)
- `N > 0`: Limit enforced — allow if (current + action_count) <= N

**Admin Exemption:**
- `is_admin(roles_set)` predicate exempts users with `admin`, `sc_admin`, `wl_admin`, `wl_superadmin` roles
- Returns (True, 0, -1) to bypass all checks
- Admins control approvals, so they shouldn't be rate-limited themselves

**File Storage:**
- `_daily_limits.json`: `{period_key: {user: {action_type: count}}}`
- `_limit_config.json`: Configuration mirroring DEFAULT_LIMITS (bump build number when structure changes)

**Key insight:** Daily limits need to persist across restarts, be modifiable by superadmins, and handle concurrent writes atomically. The temp file + lock + replace pattern (inherited from wl_versions.py) ensures no data loss even if multiple processes attempt writes simultaneously. Fail-closed semantics (return False on write error rather than raising) prioritize data consistency over feature availability.

### Task 3: Update wl_constants.py (Sentinel Value)
**File:** `bin/wl_constants.py`

Added `RESET_ALL_USERS = "__all__"` constant after SUPERADMIN_ROLES definition and updated `__all__` exports:
```python
RESET_ALL_USERS: str = "__all__"
"""Sentinel constant for reset_daily_limits(analyst=RESET_ALL_USERS) meaning 'reset all analysts'.

Used instead of magic string "all" to prevent sentinel value bugs (e.g., checking `if analyst:`
treats "all" as truthy, then code looks up user named "all" and fails silently).
This named constant makes intent explicit and prevents typos."""
```

**Motivation:** Prevents the bug `if analyst:` check treating "all" as truthy, then looking up a nonexistent user "all". Using a named constant explicitly signals "this is a sentinel, not a username" and prevents typos.

### Task 4: Create test_filelock.py Unit Tests
**File:** `tests/unit/test_filelock.py` (310 lines, 17 tests)

Comprehensive offline unit tests with mocked file I/O and fcntl:

**Test coverage:**
1. Lock acquisition/release (test_lock_acquire_success_unix, test_lock_release_on_exception)
2. Windows no-op fallback (test_lock_windows_noop) — fcntl unavailable, yields True
3. Timeout handling (3 tests):
   - Negative timeout raises ValueError
   - Zero timeout allowed (immediate fail if unavailable)
   - Timeout exception raised on IOError after all retries
4. Timeout behavior (2 tests):
   - Default 10-second timeout applied
   - Custom timeout respected
5. RLock semantics (2 tests):
   - RLock acquired and released properly
   - RLock timeout raises TimeoutError
6. Sequential locking (1 test) — acquire/release/re-acquire all succeed
7. File creation (1 test) — lock file created if doesn't exist
8. Exception handling (2 tests):
   - Lock released on exception
   - Lock file closed on exception
9. Concurrency smoke test (1 test) — 3 threads contend for lock
10. Integration (2 tests) — real file system (no mocks)

**All tests use @patch decorators to mock fcntl and file operations for deterministic, offline testing.**

### Task 5: Create test_limits.py Unit Tests
**File:** `tests/unit/test_limits.py` (620 lines, 31 tests)

Comprehensive offline unit tests covering all public and private functions:

**Test coverage by function:**

**check_analyst_limit (8 tests):**
- Under max, at boundary, over max
- Disabled (0) and unlimited (-1) semantics
- Admin exemption
- Multiple action counts
- Missing user (zero count)

**check_admin_limit (3 tests):**
- Separate from analyst limits
- Zero and unlimited semantics
- No admin exemption (admins track their own usage)

**get_limit_status (4 tests):**
- All action types iterated
- Current count calculation
- Remaining calculation (max - current)
- Admin exempt returns remaining=-1

**increment_daily_limit (4 tests):**
- New user creation
- Existing user increment
- Default amount (1)
- Custom amount

**set_limit_config (4 tests):**
- Valid config written atomically
- Required keys validation
- Value type validation (int, bool, str)
- Fail-closed on write error

**reset_daily_limits (5 tests):**
- Reset all analysts
- Reset single analyst
- Nonexistent analyst (no-op)
- Summary dict return format
- All vs. single analyst behavior

**get_limit_error_msg (3 tests):**
- Format string correctness
- Disabled (0) message
- Remaining count in message

**All tests are deterministic and offline (no Splunk SDK required).**

### Task 6: Wire Imports into wl_handler.py
**File:** `bin/wl_handler.py`

Added imports after existing wl_audit imports:
```python
from wl_limits import (
    check_analyst_limit, check_admin_limit, get_limit_status,
    increment_daily_limit, set_limit_config, reset_daily_limits,
    get_limit_error_msg
)
from wl_filelock import file_lock
```

**Status:** Imports only — no functional refactoring yet. Handler continues using inline limit functions. Full integration (remove old functions, use new modules) deferred to Phase 4-01 for batch refactoring.

**Rationale:** Keeps this phase focused on module creation + testing. Phase 4-01 will refactor the handler to use these new modules exclusively, removing duplication.

### Task 7: Verification — Run Full Test Suite
**Command:** `python3 -m pytest tests/unit/test_filelock.py tests/unit/test_limits.py -v`

**Result:**
```
============================= 48 passed in 0.78s ==============================

Test Summary:
- test_filelock.py: 17/17 PASSED
- test_limits.py: 31/31 PASSED
- Total: 48/48 PASSED (100%)
- Duration: 0.78 seconds
- No failures, no skips (within Phase 03 scope)
```

All tests pass. Ready for Phase 4.

## Deviations from Plan

None — plan executed exactly as written.

## Blockers for Phase 03-02

None identified. The modules are complete, tested, and ready for integration.

Phase 03-02 will consume these exports:
- `file_lock()` context manager for atomic operations in approval queue, trash, and version modules
- `check_analyst_limit()`, `get_limit_status()`, etc. for enforcement points in the REST handler
- `set_limit_config()` for control panel administrative endpoints

## Key Technical Decisions

**1. RLock + fcntl Pattern**
- Thread-safe via RLock (multiple threads in same process)
- Cross-process safe via fcntl.flock (multiple Splunk Python processes)
- Windows has no fcntl → no-op fallback (acceptable for dev-only platform)
- Learned from wl_versions.py (Phase 2) which implemented same pattern

**2. Zero Semantics Enforcement**
- Enforced consistently across all limit-checking functions
- 0 = disabled (deny all)
- -1 = unlimited (allow all)
- N > 0 = enforce limit N
- Prevents the bug where "zero" had different meanings in different functions

**3. Admin Exemption via RBAC**
- `is_admin()` predicate checks roles against ADMIN_ROLES
- Returns (True, 0, -1) for admins across all check functions
- Admins control approvals and limits, so they shouldn't be rate-limited
- Aligned with RBAC design from Phase 2 (wl_rbac.py)

**4. Fail-Closed Error Handling**
- _read_daily_limits() returns {} on corruption (don't crash, allow read operation)
- _write_daily_limits() returns False on error (log and retry at caller's discretion)
- Prioritizes data consistency and feature availability over failing fast
- Caller responsible for detecting False return and handling appropriately

**5. Sentinel Value (RESET_ALL_USERS)**
- Named constant `"__all__"` instead of magic string `"all"`
- Prevents typo bugs and makes intent explicit in code
- Aligns with best practice documented in MEMORY.md

## Testing Approach

**Offline unit testing** with mocked I/O:
- No Splunk SDK required
- No Docker container required
- All file I/O mocked with @patch decorators
- Time-dependent code mocked
- Both Happy path and error paths tested
- Edge cases (empty data, zero limits, missing keys) covered

**Integration notes for Phase 4:**
- `increment_daily_limit()` must be called AFTER action succeeds (not before)
- `check_analyst_limit()` called BEFORE action to enforce gate
- `get_limit_status()` called on status/dashboard endpoints for frontend progress display
- Daily reset triggered by scheduled searches or cron job (deferred to Phase 3-03 or later)

## Phase 3-01 Complete

All 7 tasks executed. Two new orchestration modules created (wl_filelock, wl_limits) with 48 unit tests covering both modules. Imports wired into wl_handler.py. Ready for Phase 3-02 (approval queue refactoring).

**Commit chain (6 commits):**
1. feat(03-01): implement wl_filelock.py context manager
2. test(03-01): add 17 unit tests for wl_filelock
3. feat(03-01): implement wl_limits.py with 7 public functions
4. test(03-01): add 31 unit tests for wl_limits
5. chore(03-01): update wl_constants with RESET_ALL_USERS sentinel
6. feat(03-01): wire imports into wl_handler.py

Files in `.planning/phases/03-backend-orchestration/`:
- `03-01-PLAN.md` — Plan definition (7 tasks)
- `03-01-SUMMARY.md` — This file (execution results)
- `03-CONTEXT.md` — Phase 3 context from planning phase
