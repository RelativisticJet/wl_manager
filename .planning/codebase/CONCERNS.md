# Codebase Concerns

## Technical Debt

### TD-01: Non-Atomic File I/O
**Severity:** High | **Location:** `bin/wl_handler.py` — CSV write operations
**Description:** CSV saves read-then-write without file locking. Concurrent saves from two analysts could produce corrupted data. Optimistic locking via `expected_mtime` mitigates but doesn't eliminate the race window.
**Impact:** Data loss under concurrent writes.
**Remediation:** Use file locks (`fcntl.flock` on Linux) or Splunk KV store for atomic operations.

### TD-02: Monolithic Backend File
**Severity:** Medium | **Location:** `bin/wl_handler.py` (7,078 lines)
**Description:** All server logic — RBAC, diff engine, version control, approval workflow, trash management, admin limits, audit logging — lives in a single file. No module separation.
**Impact:** Difficult to navigate, test individual components, or onboard new developers.
**Remediation:** Split into modules (e.g., `wl_rbac.py`, `wl_diff.py`, `wl_versions.py`). However, Splunk's REST handler architecture constrains splitting.

### TD-03: Monolithic Frontend File
**Severity:** Medium | **Location:** `appserver/static/whitelist_manager.js` (6,786 lines)
**Description:** Same pattern on frontend. All UI logic in one file. Uses jQuery DOM manipulation without a component framework.
**Impact:** Difficult to maintain, no component reuse, tangled state management.
**Remediation:** Accept as architectural constraint of Splunk SimpleXML environment.

### TD-04: Optimistic Locking Parse Failure
**Severity:** High | **Location:** `bin/wl_handler.py` — `expected_mtime` handling
**Description:** Previously, parsing `expected_mtime` with a broad `(ValueError, TypeError)` catch and `pass` meant sending `"NaN"` could silently disable optimistic locking. This was patched but pattern may exist elsewhere.
**Impact:** Security bypass — concurrent edit protection disabled.
**Remediation:** Audit all parse operations for security-relevant values; ensure parse failures return errors, never silent fallthrough.

## Known Bugs / Edge Cases

### BUG-01: Duplicate Row Detection in Diffs
**Severity:** Medium | **Location:** `bin/wl_handler.py` — `_compute_diff()`
**Description:** When CSV contains identical rows, `_visible_key()` produces identical keys. The fix uses Python `id()` for object identity, but edge cases may remain with certain add/remove/edit combinations on duplicate rows.
**Impact:** Incorrect audit trail entries for duplicate-row operations.

### BUG-02: Approval Replay Precondition Gaps
**Severity:** Medium | **Location:** `bin/wl_handler.py` — approval replay paths
**Description:** Queued operations may not re-validate all preconditions at execution time. If state changes between request submission and admin approval (e.g., rule deleted then re-created), replay may operate on stale assumptions.
**Impact:** Stale state operations — creating resources that were intentionally deleted, or editing resources that no longer exist.

### BUG-03: Diff Position Shift with Simultaneous Add/Remove
**Severity:** Low | **Location:** `bin/wl_handler.py` — `_compute_diff()`
**Description:** Row numbers in audit events reference positions in `old_rows`. When many rows are added and removed simultaneously, reported row numbers may not match what the analyst sees in the UI.
**Impact:** Confusing audit trail — row numbers in events don't match visual positions.

## Security Concerns

### SEC-01: XSS in Error Messages
**Severity:** High | **Location:** `bin/wl_handler.py` — error response construction
**Description:** Some error messages may echo user-supplied values (filenames, rule names) without HTML encoding. If these render in the browser, XSS is possible.
**Impact:** Stored or reflected XSS via crafted filenames or rule names.
**Remediation:** Sanitize all user-supplied values in error responses. Frontend should also escape all server-provided strings before DOM insertion.

### SEC-02: SPL Injection Risk
**Severity:** Medium | **Location:** `bin/wl_handler.py` — Splunk REST API calls
**Description:** If user-supplied values (comments, reasons) are interpolated into SPL queries without escaping, SPL injection is possible. Audit event construction may be vulnerable.
**Impact:** An analyst could inject SPL commands via crafted comments.
**Remediation:** Use parameterized queries or strict input validation for all values that enter SPL context.

### SEC-03: CSRF Protection
**Severity:** Medium | **Location:** REST endpoint `/custom/wl_manager`
**Description:** Splunk's built-in `splunkd` session management provides some CSRF protection, but custom REST handlers may not fully validate CSRF tokens on all POST operations.
**Impact:** Cross-site request forgery could trigger CSV modifications.
**Remediation:** Verify Splunk's CSRF token is validated on every POST action.

### SEC-04: Client-Side Limit Bypass (Patched)
**Severity:** Info | **Location:** `bin/wl_handler.py`
**Description:** Previously, `_bulk_edit_count` was trusted from the frontend, allowing clients to omit it and bypass approval gates. Server now computes security-relevant values from actual data.
**Impact:** Resolved — documented for awareness.

### SEC-05: Reserved Prefix Column Injection
**Severity:** Medium | **Location:** `bin/wl_handler.py` — column validation
**Description:** `_` prefix columns are used for internal metadata (`_added_by`, `_added_at`, `_review_status`). Users could potentially create columns with `_` prefix via API to hide data from auditors or overwrite metadata.
**Impact:** Audit trail bypass, data hiding.
**Remediation:** Whitelist known internal columns; reject all other `_` prefixes at both frontend and backend.

### SEC-06: Role Inference from Notification Type
**Severity:** Info | **Location:** `appserver/static/notifications.js`
**Description:** Previously, `notifType === "cancelled"` was used to infer admin role. Fixed to use server-side role checks.
**Impact:** Resolved — documented for awareness.

## Performance Concerns

### PERF-01: O(n²) Diff Matching
**Severity:** Medium | **Location:** `bin/wl_handler.py` — `_compute_diff()`
**Description:** Similarity-based matching compares each added row against all removed rows to find the best match. For large CSVs (1000+ rows with many changes), this is O(n²).
**Impact:** Slow saves on large CSVs with many simultaneous changes.
**Remediation:** Acceptable for typical whitelist sizes (<500 rows). Monitor if CSVs grow larger.

### PERF-02: Full CSV Read on Every Operation
**Severity:** Low | **Location:** `bin/wl_handler.py` — `get_csv` action
**Description:** Every GET loads the entire CSV into memory. No pagination for large files.
**Impact:** Memory pressure and slow load times for very large CSVs (tested with 2000x100).
**Remediation:** Consider pagination for CSVs exceeding a threshold.

### PERF-03: Presence Tracker Accumulation
**Severity:** Low | **Location:** `bin/wl_handler.py` — presence tracking
**Description:** Presence tracking data accumulates without bounded cleanup. Over time, stale presence entries may grow.
**Impact:** Minor memory overhead, misleading "who's editing" indicators.

### PERF-04: Version Manifest Rewrite
**Severity:** Low | **Location:** `bin/wl_handler.py` — version control
**Description:** Version manifest JSON is fully rewritten on every save. No append-only optimization.
**Impact:** Negligible for MAX_VERSIONS=6. Only relevant if versioning is extended.

## Fragile Areas

### FRAG-01: Revert Manifest Consistency
**Location:** `bin/wl_handler.py` — revert flow
**Description:** Revert removes source version from manifest, creates new snapshot, writes updated manifest. If the process fails mid-way, manifest and actual files may diverge.
**Risk:** Orphaned version files or manifest entries pointing to missing files.

### FRAG-02: Approval Queue State Machine
**Location:** `bin/wl_handler.py` — approval workflow
**Description:** Approval queue entries transition through states (pending → approved/rejected/cancelled). Concurrent admin actions or process failures could leave entries in inconsistent states.
**Risk:** Stuck pending items, duplicate approvals.

### FRAG-03: Daily Limit Reset Timing
**Location:** `bin/wl_handler.py` — daily limit tracking
**Description:** Daily limits reset based on date comparison. Edge cases around midnight, timezone differences, and "zero means disabled vs unlimited" semantics have been problematic.
**Risk:** Limits not resetting or incorrectly resetting.

### FRAG-04: Frontend-Backend State Sync
**Location:** `appserver/static/whitelist_manager.js` — `originalRows` vs `currentRows`
**Description:** Frontend maintains `originalRows` snapshot and `currentRows` working copy. If `syncInputs()` is not called before `refreshTable()`, DOM input values are lost. Multiple code paths must remember to sync.
**Risk:** Data loss during UI interactions (typing → clicking action without sync).

## Test Coverage Gaps

| Area | Status | Risk |
|------|--------|------|
| Concurrent CSV writes | No tests | High — data corruption |
| Concurrent approval processing | No tests | Medium — state machine races |
| CSV with control characters | No tests | Medium — parsing errors |
| Windows file locking | No tests | Low — dev environment only |
| Approval replay preconditions | Partial | Medium — stale state |
| Midnight daily limit reset | No tests | Low — edge case |
| XSS in all input fields | No tests | High — security |
| CSRF token validation | No tests | Medium — security |
| Large CSV pagination | Stress test exists | Low — functional |
| Browser-based E2E | `test_ui_browser.py` exists | Medium — coverage unknown |

## Scaling Limits

| Component | Current Limit | Bottleneck |
|-----------|--------------|------------|
| CSV row count | Tested 2000 rows | Memory + O(n²) diff |
| CSV column count | Tested 100 columns | Horizontal scroll UI |
| Approval queue | No explicit limit | File I/O throughput |
| Version history | MAX_VERSIONS = 6 | Disk space |
| Detection rules | No explicit limit | `_detection_rules.json` size |
| Concurrent users | Presence-tracked | File lock contention |

## Dependencies at Risk

| Dependency | Risk | Notes |
|------------|------|-------|
| Splunk Python SDK (`splunklib`) | Low | Optional — fallback to `urllib` |
| jQuery (Splunk-bundled) | Low | Tied to Splunk version |
| Splunk REST API (port 8089) | Medium | Internal API — version changes may break |
| Python 3 only | Low | Splunk 9.x ships Python 3 |
| `csv` stdlib module | Low | Stable |

---
*Generated: 2026-03-31 by gsd:map-codebase*
*Sources: Agent analysis + CLAUDE.md + MEMORY.md lessons learned*
