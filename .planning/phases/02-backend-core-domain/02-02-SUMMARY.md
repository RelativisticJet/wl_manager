---
phase: 02-backend-core-domain
plan: 02
subsystem: backend
tags: [module-extraction, unit-testing, pytest, rules-registry, trash-management]

requires:
  - phase: 02-backend-core-domain
    plan: 01
    provides: "wl_csv module with diff engine"
  - phase: 01-backend-foundation
    provides: "wl_constants, wl_validation, wl_logging"

provides:
  - "wl_rules.py module: detection rules registry and rule-to-CSV mapping operations (4 functions)"
  - "wl_trash.py module: soft-delete, restore, purge, and retention management (8 functions)"
  - "Unit test coverage ≥80% for both modules (39 tests total)"
  - "Decoupled rules and trash logic from REST handler for reuse in approval queue"

affects:
  - "02-03-approval-queue (will use wl_rules.read_csv_mapping, wl_trash functions)"
  - "02-04-approval-execution (will need trash/rules APIs)"

tech-stack:
  added: []
  patterns:
    - "Module extraction pattern: internal functions → public APIs with silent failure for reads"
    - "Type hints on all public functions"
    - "Atomic file operations (temp → rename) for writes"
    - "Deterministic trash IDs to prevent storage bloat"
    - "Testing with pytest, mocking, temporary files, freezegun for time-dependent tests"

key-files:
  created:
    - "bin/wl_rules.py (135 lines)"
    - "bin/wl_trash.py (270 lines)"
    - "tests/unit/test_rules.py (251 lines, 20 tests)"
    - "tests/unit/test_trash.py (378 lines, 19 tests)"
  modified:
    - "bin/wl_handler.py (-441 lines, integration commit)"

key-decisions:
  - "Used deterministic trash IDs (name__type__timestamp) to prevent accumulation on repeated delete→restore→delete cycles"
  - "Silent failures for read operations (return empty list/dict) vs exceptions for writes, matching Splunk patterns"
  - "Extracted helper functions (_get_trash_dir, _read_trash_config, _write_trash_config) into trash module"
  - "Included freezegun in test infrastructure for time-dependent cleanup tests"

requirements-completed:
  - BMOD-09
  - BMOD-10
  - TEST-01

duration: 45min
completed: 2026-03-31
---

# Phase 02: Backend Core Domain — Plan 02 Summary

**Extracted wl_rules and wl_trash modules with complete unit test coverage (≥80%), decoupling rule registry and trash management from REST handler for approval queue reuse**

## Performance

- **Duration:** 45 min
- **Started:** 2026-03-31T22:45:00Z
- **Completed:** 2026-03-31T23:30:00Z
- **Tasks:** 5
- **Files created:** 4
- **Files modified:** 1

## Accomplishments

- **wl_rules.py** — Extracted detection rules registry and rule-to-CSV mapping (4 public functions)
- **wl_trash.py** — Extracted soft-delete, restore, purge, retention operations (8 public functions)
- **Unit test coverage** — 39 tests with ≥80% coverage for both modules (pytest-cov verified)
- **Handler integration** — Removed ~420 lines of internal functions, wired handler to use module exports
- **Type safety** — All public functions fully type-hinted with proper docstrings

## Task Commits

1. **Task 1: Create wl_rules.py** - `3a3da9e` (feat(02-02): extract wl_rules and wl_trash modules)
2. **Task 2: Create wl_trash.py** - `3a3da9e` (feat(02-02): extract wl_rules and wl_trash modules) 
3. **Task 3: Unit tests for wl_rules.py** - `0f40603` (test(02-02): add ≥80% coverage for wl_rules and wl_trash)
4. **Task 4: Unit tests for wl_trash.py** - `0f40603` (test(02-02): add ≥80% coverage for wl_rules and wl_trash)
5. **Task 5: Integrate modules into wl_handler.py** - `a7999f9` (refactor(02-02): integrate wl_rules and wl_trash modules into wl_handler)

**Plan metadata:** `a7999f9` (refactor(02-02): integration complete)

## Files Created/Modified

### Created
- `bin/wl_rules.py` (135 lines)
  - `read_rules_registry()` — Read detection rule names from JSON registry
  - `write_rules_registry(rules)` — Atomic write of rule list
  - `read_csv_mapping()` — Parse rule_csv_map.csv to dict {rule: csv_file}
  - `get_rule_csv_file(rule_name)` — Lookup single rule's CSV file

- `bin/wl_trash.py` (270 lines)
  - `get_trash_dir()` — Get/create trash directory
  - `read_trash_config()` — Read retention configuration
  - `write_trash_config(config)` — Atomically save config
  - `move_to_trash(item_type, name, user, comment, ...)` — Soft-delete with deterministic ID
  - `list_trash()` — List all trash items (newest first)
  - `restore_from_trash(trash_id)` — Restore item from trash
  - `purge_trash_item(trash_id)` — Permanently delete item
  - `auto_cleanup_trash()` — Purge items older than retention period

- `tests/unit/test_rules.py` (251 lines, 20 tests)
  - Tests: valid JSON, missing files, invalid JSON, empty lists, duplicate handling, CSV parsing
  - Mocks: OWN_LOOKUPS and MAPPING_FILE constants
  - Coverage: ≥80%

- `tests/unit/test_trash.py` (378 lines, 19 tests)
  - Tests: directory creation, config I/O, move/restore/purge, list with timestamps, auto-cleanup
  - Uses freezegun for time-dependent tests (auto_cleanup_trash with retention)
  - Mocks: OWN_LOOKUPS constant
  - Coverage: ≥80%

### Modified
- `bin/wl_handler.py` (-441 lines)
  - Added imports after wl_csv: `from wl_rules import ...`, `from wl_trash import ...`
  - Replaced ~12 calls to `_read_detection_rules()` with `read_rules_registry()`
  - Replaced ~8 calls to `_write_detection_rules()` with `write_rules_registry()`
  - Replaced ~4 calls to `_read_csv_mapping()` with `read_csv_mapping()`
  - Replaced all trash operation calls with module exports
  - Removed old function definitions (lines 751-1170 deleted)
  - Kept `_detection_rules_lock` and `_detection_rules_modify()` (used by approval queue)

## Decisions Made

1. **Deterministic Trash IDs** — Used `{name}__{type}__{timestamp}` pattern (EC3 mitigation) to prevent storage bloat when users repeatedly delete→restore→delete the same item. Old entries are automatically overwritten.

2. **Silent Failures for Reads** — `read_rules_registry()` and `read_csv_mapping()` return empty collections on missing/invalid files, matching Splunk app conventions. Writes raise exceptions for visibility.

3. **Extracted Helper Functions** — `_get_trash_dir()`, `_read_trash_config()`, `_write_trash_config()` became public functions in wl_trash.py for reuse in approval queue (Phase 3).

4. **Test Infrastructure** — Used freezegun to freeze time in `test_auto_cleanup_trash_expired`, enabling deterministic testing of 30-day retention without wait times.

5. **Type Hints on Public APIs** — All 12 public functions fully type-hinted with return types, enabling IDE support and future static analysis in approval queue code.

## Deviations from Plan

None - plan executed exactly as written. All 5 tasks completed with no auto-fixes required.

**Verification:**
- All 39 unit tests pass (20 for wl_rules, 19 for wl_trash)
- wl_handler.py compiles without errors after integration
- Coverage ≥80% confirmed for both modules
- No broken references to old function names

## Issues Encountered

**Git state confusion (previous session):** The revert commit `d891f44` undid the integration work from a prior attempt. Resolved by:
1. Verifying modules (wl_rules.py, wl_trash.py) and tests still existed on disk
2. Redoing Task 5 integration: added imports, replaced calls via sed, removed old definitions
3. Verified compilation and all tests pass

This was not a deviation from the current plan — it was recovery of prior work that had been reverted.

## Next Phase Readiness

- **Ready for approval queue (Phase 02-03):** wl_rules provides rule/CSV lookup, wl_trash provides soft-delete/restore APIs for approvers to manage pending requests
- **Ready for approval execution (Phase 02-04):** wl_trash.move_to_trash and auto_cleanup_trash enable deletion workflows with audit trail
- **No blockers:** All modules independent, no forward dependencies

---

*Phase: 02-backend-core-domain*
*Plan: 02*
*Completed: 2026-03-31*
