# Phase 2: Backend Core Domain — Phase Context

**Phase:** 02-backend-core-domain  
**Goals:** Extract 5 data persistence layer modules establishing CSV I/O, versioning, auditing, and trash systems.  
**Depends on:** Phase 1 (test infrastructure, constants, logging, validation, RBAC, presence, rate limiting)  
**User:** Oleh | **Date:** 2026-03-31

---

## Phase Scope & Decisions

### What This Phase Accomplishes

Phase 2 extracts the 5 core domain modules that handle data persistence, versioning, auditing, and trash operations from the monolithic `wl_handler.py`:

- **wl_csv.py** — CSV read/write, diff computation, cell operations, column width tracking
- **wl_versions.py** — Version snapshots, manifest tracking, version list, revert operations
- **wl_audit.py** — Structured audit event construction, event posting to wl_audit index
- **wl_rules.py** — Detection rules registry, rule-to-CSV mapping, rule CRUD
- **wl_trash.py** — Soft-delete, restore, purge operations with retention tracking

These modules build directly on Phase 1's foundation (constants, logging, validation, RBAC) and provide the core business logic that the approval queue and daily limits (Phase 3) will orchestrate.

### Locked Decisions (from discussion)

**Module Boundaries:**
- wl_csv.py exports: `read_csv(path)`, `write_csv(path, headers, rows)`, `get_column_widths(path)`, `set_column_widths(path, widths)`, `compute_diff(old_headers, old_rows, new_headers, new_rows)`, `get_expire_column(headers)`, `remove_expired_rows(headers, rows, tz_offset_minutes)`
- wl_versions.py exports: `get_versions_dir(csv_path)`, `read_version_manifest(csv_path)`, `write_version_manifest(csv_path, manifest)`, `snapshot_version(csv_path, analyst, action_label)`, `get_versions_list(csv_path)`
- wl_audit.py exports: `build_audit_event(action, analyst, detection_rule, csv_file, **kwargs)`, `post_audit_event(session_key, event)`, `get_audit_logger()`
- wl_rules.py exports: `read_rules_registry()`, `write_rules_registry(rules)`, `read_csv_mapping()`, `get_rule_csv_file(rule_name)`
- wl_trash.py exports: `move_to_trash(item_type, name, user, comment, ...)`, `list_trash()`, `restore_from_trash(trash_id)`, `purge_trash_item(trash_id)`, `auto_cleanup_trash()`, `get_trash_dir()`, `read_trash_config()`, `write_trash_config(config)`

**Error Handling Pattern:**
- CSV functions: raise exceptions on I/O errors (file not found, permission denied); validation errors handled upstream by caller
- Version/audit/rules/trash: return (data, error_msg) tuples OR raise exceptions — Claude's discretion per module (consistency preferred)
- All file operations wrapped in try/except with audit logging on failures

**File Locking:**
- Version snapshots acquire lock via context manager (contextlib); held during read/write/snapshot
- Trash operations acquire lock; approval queue has its own separate lock (Phase 3)
- Lock timeouts: 10 seconds with retry logic (max 3 retries, 100ms backoff)

**Test Structure:**
- Tests in `tests/unit/test_csv.py`, `tests/unit/test_versions.py`, `tests/unit/test_audit.py`, `tests/unit/test_rules.py`, `tests/unit/test_trash.py`
- Integration tests in `tests/integration/test_persistence.py` verifying end-to-end CSV save → snapshot → audit chain
- Coverage target: ≥80% per module

**No Functional Change Principle:**
- Every extracted function has a direct counterpart in wl_handler.py (~1-to-1 mapping from `_function_name` → `function_name`)
- Handler passes through to modules without business logic changes
- API contracts frozen: request/response shapes unchanged
- Audit event structure unchanged (existing dashboard and queries must continue working)

### Claude's Discretion

- Grouping of diff helper functions (edge detection, similarity matching) into wl_csv.py
- Error return style per module (exceptions vs tuples) — preferring consistency across all Phase 2 modules
- Lock acquisition strategy (contextlib ExitStack vs manual acquire/release)
- Integration test depth (single happy path per module vs multiple scenarios)

### Deferred Ideas (OUT OF SCOPE)

- Streaming CSV processing (load-on-demand for huge files) — deferred to optimization phase
- SQLite/database backend — CSV is the correct Splunk convention
- Async file operations — Splunk's threading model doesn't support async
- CSV diff visualization in UI — planned for Phase 5 (frontend)

---

## Requirements Coverage

| ID | Description | This Phase | Module |
|----|-------------|-----------|--------|
| BMOD-06 | wl_csv.py extracts all CSV read/write, diff computation, cell operations | **Core** | wl_csv |
| BMOD-07 | wl_versions.py manages version snapshots, manifest tracking, revert operations | **Core** | wl_versions |
| BMOD-08 | wl_audit.py constructs structured audit events and posts to wl_audit index | **Core** | wl_audit |
| BMOD-09 | wl_rules.py manages detection rules registry and rule-to-CSV mapping | **Core** | wl_rules |
| BMOD-10 | wl_trash.py handles soft-delete, restore, purge with retention | **Core** | wl_trash |
| BMOD-13 | No function exceeds 100 lines or cyclomatic complexity of 15 | **Applied to all modules** | all |
| BMOD-14 | Consistent error handling pattern (fail-closed with state rollback) | **Applied to all modules** | all |
| BMOD-15 | No duplicated logic across backend modules (DRY compliance) | **Central to this phase** | all |
| TEST-01 (partial) | Unit test suite covering ≥80% of Phase 2 modules | **Embedded in each plan** | all |

---

## Architecture Patterns (Phase 1 Dependencies)

### Layer Hierarchy
```
Layer 0 (Phase 1): wl_constants
                    ↓
Layer 1 (Phase 1): wl_logging
                    ↓
Layer 2 (Phase 1): wl_validation, wl_ratelimit, wl_rbac, wl_presence
                    ↓
Layer 3 (Phase 2): wl_csv, wl_versions, wl_audit, wl_rules, wl_trash
```

All Phase 2 modules import from Layers 0-2 only. No circular imports. No forward dependencies.

### Type Hints & Exports

Every Phase 2 module:
- Exports explicit `__all__` with public API functions
- Uses type hints on all function signatures (params and return types)
- Imports Phase 1 modules selectively (not `from wl_constants import *`)

### Lock Management

CSV and trash operations require file locks to prevent concurrent modifications:
- Locks stored in same directory as data files (e.g., `{csv_path}.lock`)
- Acquired with timeout (10 seconds) and retry (3 attempts, 100ms backoff)
- All lock acquisitions via context managers to ensure release on exception
- Lock failures logged but don't block read operations (only writes)

### Diff Algorithm Details

The diff engine in wl_csv.py uses similarity-based row matching:
1. **Counter-based comparison** (not sets) to preserve duplicate row counts
2. **Common headers** extracted to avoid false edits when columns are added/removed
3. **Reverse iteration** on added rows because frontend appends at end (picks actually-new rows, not pre-existing duplicates from front)
4. **Edit detection** via field overlap scoring (require >50% fields unchanged to pair as edit vs separate add/remove)
5. **Skip edit detection threshold** if either side exceeds MAX_DIFF_ROWS (configurable, default 1000) to avoid O(n²×m) explosion

---

## Phase Success Criteria

When Phase 2 completes, ALL of the following must be TRUE:

1. **Functional Preservation**: User can load CSV, save changes, revert versions, access audit log with ZERO functional change
2. **Module Extraction**: Five new modules exist in `bin/` and are imported by wl_handler.py: wl_csv, wl_versions, wl_audit, wl_rules, wl_trash
3. **Complexity Control**: No function exceeds 100 lines; no module exceeds CC=15; visible complexity reduced by ~40% from monolith
4. **Test Coverage**: ≥80% unit test coverage per module (measured by pytest-cov); integration test chain verifies full CSV save → version → audit flow
5. **DRY Compliance**: No duplicated logic for version snapshots, diff computation, or audit field construction across modules
6. **API Stability**: REST API contract unchanged; existing audit events and queries continue working
7. **Phase 1 Integration**: All modules correctly import Phase 1 foundation; no circular dependencies

---

## Deliverables

- 5 new Python modules in `bin/`: wl_csv.py, wl_versions.py, wl_audit.py, wl_rules.py, wl_trash.py
- 5 unit test files in `tests/unit/`: test_csv.py, test_versions.py, test_audit.py, test_rules.py, test_trash.py
- 1 integration test file: `tests/integration/test_persistence.py`
- Updated `bin/wl_handler.py`: imports new modules, calls extracted functions instead of inline logic
- Updated ROADMAP.md with Phase 2 plan details
- Coverage reports showing ≥80% per module
- Git commits: one module per commit (wl_csv, wl_versions, wl_audit, wl_rules, wl_trash)

---

## Next Phase: Phase 3

Phase 3 depends on Phase 2 completion:
- wl_limits.py and wl_approval.py orchestrate CSV operations using Phase 2 modules
- Approval queue replays Phase 2 functions (save_csv, revert_csv, etc.)
- Daily limits gates Phase 2 operations based on counts tracked in Phase 3

---

*Context created: 2026-03-31*
*Last updated: 2026-03-31*
