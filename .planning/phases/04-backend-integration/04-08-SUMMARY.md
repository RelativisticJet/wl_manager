# Plan 04-08 Summary: Approval Workflow Deduplication

**Phase:** 04-backend-integration
**Plan:** 08 (gap closure round 4 — final)
**Status:** COMPLETE

## What Was Built

### Helper Methods Added to Handler
- `_fail_approval_request()` — centralizes the repeated "mark as failed + audit + notify" pattern that appeared 8+ times in `_process_approval_inner` (~40 lines each). Supports optional notification and custom status codes.
- `_approve_request()` — centralizes the "mark as approved + audit + notify" pattern for future use.

### Deduplication Applied
Replaced 6 inline failure blocks in `_process_approval_inner` with `_fail_approval_request()` calls:
1. CSV file not found (notify=False, status_code=404)
2. Bulk row removal partial match (with requested/actual counts)
3. Column no longer exists — column_removal path (notify=False)
4. Bulk row addition: no rows identified (notify=False)
5. Bulk row addition: duplicate rows (with duplicate_count)
6. Column no longer exists — bulk_row_edit path (notify=False)
7. Bulk row edit partial match (with requested/actual counts)
8. Create/delete replay execution failure

### Deviation from Plan
The plan targeted handler reduction to 900-1,200 lines via full extraction of `_submit_approval` (~250 lines), `_process_approval_inner` (~918 lines), and `_process_dual_approval` (~217 lines) into `wl_approval.py` pipeline functions.

**Why full extraction was not done:** `_process_approval_inner` is deeply coupled to the handler:
- Calls `self._save_csv()` and `self._revert_csv()` for 6 of 10 action types (replay)
- Uses handler-level queue adapters (`_approval_queue_lock`, `_read_approval_queue`, `_write_approval_queue`)
- Uses handler-level notification functions (`_notify_admins`, `_add_notification`)
- Rebuilds CSV payloads by reading current file state via `read_csv(path)`

Full extraction would require first extracting `_save_csv` and `_revert_csv` to domain modules — a multi-plan effort best addressed in a future phase.

**What was achieved instead:** Code deduplication via helper methods, reducing `_process_approval_inner` complexity and establishing patterns for future extraction.

## Key Metrics

- Handler: 5,065 → 4,972 lines (−93 from deduplication)
- Combined with Plan 07: 5,232 → 4,972 (−260 total)
- Pipeline functions: 7 in domain modules (save_csv, create_csv, revert_csv, create_rule, delete_rule, delete_csv, restore_from_trash)
- Tests: 388 unit passing (14 new across Plans 07-08)
- 46 action methods in handler dispatch tables

## key-files

### modified
- `bin/wl_handler.py` — added `_fail_approval_request`, `_approve_request` helpers; deduplicated 6 failure blocks

## Commits

| Hash | Message |
|------|---------|
| 05adec8 | refactor(04-08): deduplicate approval failure/success patterns in handler |

## Self-Check: PASSED

- [x] Helper methods reduce code duplication in _process_approval_inner
- [x] 388 unit tests passing, 0 failures
- [x] No functional behavior changes (same audit events, same notifications)
- [x] Handler still fully functional with 46 action dispatch methods
