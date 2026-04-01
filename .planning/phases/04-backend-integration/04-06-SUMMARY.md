# Plan 04-06 Summary: Extract CSV Operations to Domain Pipelines

**Phase:** 04-backend-integration
**Plan:** 06 (gap closure round 2)
**Status:** COMPLETE

## What Was Built

### Pipeline Functions Created
- `save_csv_pipeline()` in `wl_csv.py` — orchestrates CSV save with diff + version snapshot + audit
- `create_csv_pipeline()` in `wl_csv.py` — orchestrates CSV creation with mapping + version + audit
- `revert_csv_pipeline()` in `wl_versions.py` — orchestrates version revert with diff + audit

### Handler Consolidation
- Merged `_save_csv` + `_save_csv_locked` + `_save_csv_inner` 3-tier architecture into single `_save_csv`
- `_create_csv` now calls `create_csv_pipeline` for core operations
- `_revert_csv` now calls `revert_csv_pipeline` for core operations

### Adapter Function Cleanup
- Deleted module-level `read_csv`, `write_csv`, `get_expire_column` (shadowed imports from wl_csv)
- Deleted module-level `read_rules_registry`, `write_rules_registry`, `_get_detection_rules_path` (shadowed imports from wl_rules)
- Kept `_detection_rules_modify` lock context manager (still has 3 callers in handler)

## Key Metrics

- Handler: 5,746 → 5,232 lines (−514 total across sessions)
- Pipeline functions: 4 (save_csv, create_csv, revert_csv, create_rule)
- Tests: 390 passing (374 unit + 16 Docker smoke)

## Commits

| Hash | Message |
|------|---------|
| 290aeae | feat(04-06-task1): extract save_csv_pipeline from handler |
| 0a7bc2b | feat(04-06-task4): update imports to include extracted pipelines |
| bd33a87 | feat(04-06): refactor _save_csv_inner to call save_csv_pipeline |
| f94c0c1 | feat(04-06): refactor _create_csv to call create_csv_pipeline |
| 967e856 | feat(04-06): refactor _revert_csv to call revert_csv_pipeline |
| 676478c | refactor(04-04): consolidate _save_csv by merging validation + execution |
| 25831b2 | refactor(04-06): delete shadowing adapter functions for CSV and rules |

## Remaining Work (04-07, 04-08)

- Extract rule/trash operations (04-07): _remove_rule, _remove_csv → wl_rules, wl_trash pipelines
- Extract approval operations (04-08): _process_approval_inner bulk actions → wl_replay
- Delete remaining pre-class adapter functions (~600 lines)
- Handler target: ~900-1200 lines (thin wrappers + infrastructure)
