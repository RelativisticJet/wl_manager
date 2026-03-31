---
phase: 01-backend-foundation
plan: 04
subsystem: backend
tags: [python, rate-limiting, rbac, presence-tracking, modularization, unit-testing]

# Dependency graph
requires:
  - phase: 01-backend-foundation
    provides: Layer 1 logging utilities (wl_logging.py)
provides:
  - Three Layer 2 utility modules: wl_ratelimit, wl_rbac, wl_presence
  - Comprehensive unit test suite (62 tests, 97% coverage)
  - Modularized backend architecture for easier maintenance and testing
affects:
  - 01-backend-foundation (handler refactoring depends on these)
  - Future backend features relying on rate limiting, RBAC, or presence tracking

# Tech tracking
tech-stack:
  added:
    - pytest with @pytest.mark.unit fixtures and mocking
    - coverage.py for code coverage analysis
    - unittest.mock.patch for dependency mocking
  patterns:
    - Tuple-based return pattern: (data_dict, error_string) for functional modules
    - Module-level state dictionaries for stateful tracking
    - Lazy imports for optional dependencies (splunk.rest)
    - Predicate functions for RBAC role checking
    - Sliding-window algorithm for rate limiting with automatic cleanup

key-files:
  created:
    - bin/wl_ratelimit.py - 66 lines, sliding-window rate limiter
    - bin/wl_rbac.py - 169 lines, role-based access control predicates and user discovery
    - bin/wl_presence.py - 157 lines, user presence tracking with per-CSV state
    - tests/unit/test_ratelimit.py - 230 lines, 11 test methods, 86% coverage
    - tests/unit/test_rbac.py - 280 lines, 17 test methods, 99% coverage
    - tests/unit/test_presence.py - 309 lines, 30+ test methods, 100% coverage
  modified:
    - bin/wl_handler.py - Removed ~150 lines of extracted logic, updated to use Layer 2 modules
    - .gitignore - Allow tests/ directory in git (exclude only caches)

key-decisions:
  - Modularized into separate Layer 2 files for better testability and maintainability
  - Used tuple returns (data, error) instead of raising exceptions for functional modules
  - Implemented rate limiting with sliding-window algorithm (auto-prunes old timestamps)
  - RBAC predicates use set intersection for flexible role checking
  - Presence tracking maintains per-CSV state dictionaries for isolation
  - Lazy import of splunk.rest to support offline testing without Splunk installed

patterns-established:
  - "Functional module pattern: functions return (data_dict, error_string) tuples"
  - "Stateful module pattern: module-level state dict with reset function for testing"
  - "RBAC pattern: role predicates use set.intersection with constants for flexibility"
  - "Rate limiting pattern: sliding-window with automatic stale-entry cleanup"
  - "Presence tracking pattern: per-CSV isolation with automatic user cleanup"

requirements-completed:
  - BMOD-04
  - BMOD-05
  - TEST-01

# Metrics
duration: ~45min (across multiple conversation segments)
completed: 2026-03-31
---

# Phase 1: Backend Foundation (Plan 04) Summary

**Three Layer 2 utility modules (rate limiting, RBAC, presence tracking) extracted from wl_handler.py with 62 comprehensive unit tests achieving 97% code coverage**

## Performance

- **Duration:** ~45 min (across multiple context segments)
- **Started:** 2026-03-31 (previous context)
- **Completed:** 2026-03-31
- **Tasks:** 5 (all completed)
- **Files created:** 6
- **Files modified:** 2
- **Test count:** 62 unit tests
- **Coverage:** 97% overall (100% presence, 86% ratelimit, 99% rbac)

## Accomplishments

- **Layer 2 modularization complete:** Extracted wl_ratelimit, wl_rbac, and wl_presence modules from wl_handler.py, reducing handler complexity by ~150 lines
- **Comprehensive test coverage:** Created 62 unit tests organized across three test files with @pytest.mark.unit markers, achieving 97% code coverage
- **Functional module pattern:** All three modules implement tuple-based return pattern (data_dict, error_string) for functional composition and error handling
- **Sliding-window rate limiting:** Implemented with automatic pruning of timestamps outside the window and stale-key cleanup
- **RBAC predicates:** Role checking functions (is_admin, is_editor, is_superadmin, can_approve, can_approve_own_requests) with Splunk REST API integration for user discovery
- **Presence tracking:** Per-CSV user presence with idle-minutes calculation, automatic cleanup of stale users, and per-file/per-user limits

## Task Commits

1. **Task 1: Create wl_ratelimit module** - `6e41c57` (feat, part of earlier multi-task commit)
2. **Task 2: Create wl_rbac module** - `6e41c57` (feat, part of earlier multi-task commit)
3. **Task 3: Create wl_presence module** - `6e41c57` (feat, part of earlier multi-task commit)
4. **Task 4: Refactor wl_handler.py to use Layer 2 modules** - `6e41c57` (feat, part of earlier multi-task commit)
5. **Task 5: Create comprehensive unit tests** - `2e896bb` (test: add 62 unit tests with 97% coverage)

**Plan metadata:** `2e896bb` (includes .gitignore update)

## Files Created/Modified

### Created
- `bin/wl_ratelimit.py` - Sliding-window rate limiter with per-user, per-action-type tracking (66 lines)
- `bin/wl_rbac.py` - RBAC predicates and user discovery via Splunk REST API (169 lines)
- `bin/wl_presence.py` - User presence tracking with per-CSV state and cleanup (157 lines)
- `tests/unit/test_ratelimit.py` - 11 unit tests for rate limiting (230 lines)
- `tests/unit/test_rbac.py` - 17 unit tests for RBAC (280 lines)
- `tests/unit/test_presence.py` - 30+ unit tests for presence tracking (309 lines)

### Modified
- `bin/wl_handler.py` - Removed ~150 lines of extracted logic, updated to import and use Layer 2 modules instead of internal methods
- `.gitignore` - Removed `tests/` directory from exclusion to allow test source files in git (pytest cache still excluded)

## Decisions Made

1. **Functional module return pattern:** Chose (data_dict, error_string) tuple returns instead of exceptions for easier functional composition and error handling in the handler routing layer
2. **Tuple-based RBAC:** Used role set intersection predicates (is_admin, is_editor, etc.) for flexible role checking that works with any role set
3. **Stateful module pattern:** Implemented module-level state dictionaries (_rate_limits, _presence) with reset functions for test isolation
4. **Lazy Splunk imports:** Deferred splunk.rest imports to function scope to support offline testing without Splunk SDK
5. **Test isolation via mocking:** Used unittest.mock.patch to mock time.time, splunk.rest.simpleRequest, and constants for deterministic testing
6. **Coverage target:** 97% overall coverage exceeds the ≥80% requirement, with presence at 100%, rbac at 99%, and ratelimit at 86% (missing edge case in cleanup)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed test mocking for constants and Splunk REST imports**
- **Found during:** Task 5 (Unit test execution)
- **Issue:** Tests were trying to patch constants (RATE_MAX_WRITES, RATE_WINDOW, MAX_PRESENCE_FILES, MAX_PRESENCE_USERS) and splunk module attributes where they don't exist at module level because they're imported from wl_constants or lazily imported inside functions
- **Fix:** 
  - For constants: Changed patch targets from wl_ratelimit.RATE_MAX_WRITES to wl_constants.RATE_MAX_WRITES (and similar for other modules)
  - For splunk.rest: Changed from trying to patch wl_rbac.splunk.rest.simpleRequest to using patch.dict('sys.modules', ...) to mock the splunk module entirely before function execution
- **Files modified:** tests/unit/test_ratelimit.py (2 test methods), tests/unit/test_rbac.py (8 test methods), tests/unit/test_presence.py (2 test methods)
- **Verification:** All 62 tests now pass with 97% coverage
- **Committed in:** `2e896bb` (test task commit)

---

**Total deviations:** 1 auto-fixed (mocking strategy corrections)
**Impact on plan:** All tests now pass. No scope creep. Auto-fix was necessary for test suite functionality.

## Issues Encountered

None - all tests pass, coverage exceeds requirements, no blocking issues during execution.

## Code Quality Metrics

- **Test organization:** 7 test classes across 3 files with @pytest.mark.unit decorators
- **Mocking strategy:** Proper isolation of time-dependent code and external API calls
- **Edge cases covered:**
  - Rate limiting: sliding window cleanup, stale-key cleanup, per-user separation, per-action separation
  - RBAC: role predicates with empty/multiple roles, user extraction from session/headers, API failures with fallback, malformed responses
  - Presence: per-CSV isolation, multiple users, cleanup of idle users, idle-minutes calculation, None/zero edge cases

## User Setup Required

None - no external service configuration required. All tests are offline (use mocks) and can run in any environment with Python 3.8+.

## Next Phase Readiness

- **Layer 2 modules complete and tested:** wl_ratelimit, wl_rbac, wl_presence are production-ready
- **wl_handler.py refactoring:** Handler now imports and uses these modules; all functionality preserved
- **Test infrastructure ready:** 62 passing tests with 97% coverage; reusable test patterns established
- **Ready for Phase 2:** Authorization service and approval queue features can now safely build on these modularized, tested utilities

---

*Phase: 01-backend-foundation / Plan: 04*
*Completed: 2026-03-31*
