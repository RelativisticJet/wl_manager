# Plan 04-07 Summary: Extract Rules, Trash, and Limits Pipelines

**Phase:** 04-backend-integration
**Plan:** 07 (gap closure round 3)
**Status:** COMPLETE

## What Was Built

### Pipeline Functions Created
- `delete_rule_pipeline()` in `wl_rules.py` — orchestrates rule deletion with mapping removal, registry update, trash, and audit
- `delete_csv_pipeline()` in `wl_rules.py` — orchestrates CSV deletion with mapping removal, last-CSV-for-rule detection, trash, and audit
- `restore_from_trash_pipeline()` in `wl_trash.py` — wraps restore_from_trash with structured Dict return and audit posting

### Handler Refactoring
- `_action_remove_rule` expanded from 2-line pass-through to full wrapper: validation, RBAC, admin limits, dual-admin gate, pipeline call, approval queue cancellation
- `_action_remove_csv` expanded from 2-line pass-through to full wrapper: validation, RBAC, admin limits, pipeline call, approval queue cancellation
- `_action_restore_from_trash` updated to call `restore_from_trash_pipeline` (fixes bug: old code passed 2 args to 1-arg function)
- Dual-approval replay code updated to call `delete_rule_pipeline`/`delete_csv_pipeline` directly

### Deleted from Handler
- `_remove_rule` (~180 lines) — business logic moved to `delete_rule_pipeline`
- `_remove_csv` (~140 lines) — business logic moved to `delete_csv_pipeline`

### Verified (no changes needed)
- `set_limit_config` in `wl_limits.py` — already exists with correct signature, 4 tests passing

## Key Metrics

- Handler: 5,232 → 5,065 lines (−167 net; raw deletion ~320 lines offset by expanded wrappers)
- Pipeline functions: 7 total (save_csv, create_csv, revert_csv, create_rule, delete_rule, delete_csv, restore_from_trash)
- Tests: 388 unit passing (10 new pipeline tests)

## key-files

### created
- (none — functions added to existing modules)

### modified
- `bin/wl_rules.py` — added `delete_rule_pipeline`, `delete_csv_pipeline`, helper functions
- `bin/wl_trash.py` — added `restore_from_trash_pipeline`
- `bin/wl_handler.py` — refactored wrappers, deleted inline methods, updated imports
- `tests/unit/test_rules.py` — 10 new pipeline tests (5 delete_rule, 5 delete_csv)
- `tests/unit/test_trash.py` — 4 new pipeline tests (restore_from_trash_pipeline)

## Commits

| Hash | Message |
|------|---------|
| 69cca4f | refactor(04-07): extract delete_rule, delete_csv, restore_trash pipelines |

## Self-Check: PASSED

- [x] delete_rule_pipeline and delete_csv_pipeline created in wl_rules.py
- [x] restore_from_trash_pipeline created in wl_trash.py
- [x] set_limit_config verified in wl_limits.py (already correct)
- [x] Handler wrappers refactored to call pipelines
- [x] Old inline methods deleted (~320 lines)
- [x] 388 unit tests passing, 0 failures
- [x] No references to deleted methods remain in handler
