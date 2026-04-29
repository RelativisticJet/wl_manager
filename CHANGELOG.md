# Changelog

All notable changes to this project will be documented in this file.

## Unreleased — 2026-04-29 (build 620)

### Security — ASCII validation tightening (rounds 1-4)

**Breaking change**: detection rule names, CSV filenames, approval reasons,
comments, and `app_context` values are now strictly ASCII. Submissions
containing CJK ideographs, Cyrillic, Greek, Arabic, emoji, zero-width
characters, bidi-override marks, fullwidth ASCII lookalikes, combining
diacritics, null bytes, or other control characters are rejected with
HTTP 400. Length caps also enforced at the submission gate (rule names
≤100 chars, CSV filenames ≤200 chars).

If you have external automation that submits requests via REST and was
relying on the historical Unicode-permissive behavior of `c.isalnum()`,
those calls now return 400 instead of being queued for approval.
Migrate to ASCII-only payloads.

### Added

- `bin/wl_validation.py`: `is_ascii_name()`, `is_valid_app_context()`,
  `validate_ascii_text()` (round 1)
- `bin/wl_trash.py`: `_safe_trash_item_dir()` containment helper used
  by `purge_trash_item` and `restore_from_trash` (round 3)
- `tests/unit/test_ascii_validation.py`: 69 unit tests covering
  adversarial Unicode edge cases (rounds 1-3)
- `tests/e2e/test_concurrent_save_race.cjs`: characterizes the
  optimistic-lock behavior under concurrent saves (round 4)
- `scripts/pre-commit`: section #8 blocks new `c.isalnum()` usage in
  `bin/` to prevent regression to the Unicode-permissive pattern
  (round 3)
- `cross_app_csv_read` audit event: emitted when a user reads a CSV
  from an `app_context` other than `wl_manager` — provides forensic
  visibility into cross-app lookups for insider-threat investigations
  (round 4)
- `fim_mapping_unreadable` audit event: emitted by FIM watcher when
  `rule_csv_map.csv` cannot be parsed (e.g. UTF-8 corruption); this
  prevents silent loss of CSV integrity monitoring (round 3)

### Fixed

- **HIGH** Trash item path traversal: `purge_trash_item` and
  `restore_from_trash` previously fed user-supplied `trash_id`
  directly into `os.path.join` and `shutil.rmtree` without
  containment checks. A malicious admin sending
  `trash_id="../../tmp"` would have silently deleted
  `/opt/splunk/.../tmp` (round 3)
- **MED** Dual-admin meta validation: `_submit_dual_approval`
  accepted CJK in `rule_name`, `csv_file`, and `trash_id` fields
  even though POST-action wrappers had been tightened. Pollution
  of the dual-approval queue and audit trail prevented (round 3)
- **MED** Submit-approval bypass: a direct
  `action=submit_approval` POST bypassed the ASCII validation that
  was wired into `_submit_create_delete_approval`. Inner choke
  point now validates too (round 2)
- **MED** GET handler `app_context` validation: 4 GET endpoints
  (`get_csv_content`, `get_versions`, `check_csv_status`,
  `get_col_widths`) now reject malformed `app_context` at the
  wrapper instead of relying on lower-layer `resolve_csv_path`
  (round 4)
- **MED** FIM watcher resilient to UnicodeDecodeError on
  `rule_csv_map.csv` — single rogue byte previously crashed the
  watcher and silently disabled CSV integrity monitoring (round 3)
- **LOW** `is_ascii_name` rejects whitespace-only strings; previously
  `"   "` would pass the regex
- **LOW** `is_safe_filename` rejects null bytes and other ASCII
  control characters (round 2)
- **LOW** `_execute_replay_create_csv` returns clear "Invalid CSV
  file name" error for legacy CJK queue entries instead of crashing
  with `NoneType` from `write_csv(None, ...)` (round 2)

### Changed

- Build numbers 618 → 620 over 4 hardening rounds in this release
- Pre-commit hook now runs additional drift guard for `c.isalnum()`
  pattern in `bin/`

## [2.0.0] - 2026-03-22

### Added

- **Approval Workflows**: Bulk operations above configurable thresholds require admin approval. Admins approve/reject/cancel from the Control Panel. Self-approval prevention enforced.
- **Control Panel** (admin-only dashboard): Approval Queue with approve/reject buttons, Analyst Usage monitoring, Limits & Permissions configuration.
- **Daily Usage Limits**: Per-analyst caps on row removals, edits, additions, column changes, and reverts. Configurable reset frequency (daily/weekly/monthly/permanent).
- **Notification System**: Bell icon notifications for approval status updates (submitted, approved, rejected, cancelled).
- **Version Control**: Every save creates a timestamped CSV snapshot. Revert to any of the last 5 versions with full audit trail. Revert events use `*back` field naming for clarity.
- **Inline Cell Editing**: Click any cell to edit in place with textarea. Change tracking shows before/after diffs.
- **Bulk Edit Mode**: Edit multiple rows and save as a single operation.
- **Column Management**: Add and remove columns. Column removal with non-empty cells can require approval.
- **Row Drag-and-Drop Reordering**: Drag rows to reorder with `_row_reorder` audit events.
- **CSV Import**: Upload CSV files with merge logic (only new rows added).
- **Row Expiration**: Set expiration dates with presets (7d, 30d, 6mo, 1yr). Expired rows auto-removed on load and via hourly scheduled cleanup.
- **Dark/Light Theme**: Automatic theme detection with CSS custom properties.
- **Search Bar**: Filter rows across all columns with clear button.
- **Optimistic Locking**: Concurrent edit detection via file mtime. Second save with stale mtime is rejected with conflict error.
- **Rate Limiting**: Per-user sliding window rate limiter for read/write operations.
- **New Roles**: `wl_admin`, `wl_analyst_editor`, `wl_analyst_viewer` (legacy `wl_editor`/`wl_viewer` still supported).
- **Audit Dashboard**: Enhanced with approval stats, column change tracking, revert tracking, and expiring-soon panel.
- **Example SPL Queries**: Documentation with common audit queries for compliance and monitoring.

### Security

- Server-side RBAC enforcement on every POST request via Splunk REST API
- Path traversal protection with `_safe_filename()`, `_safe_realpath()`, and symlink detection
- Input sanitization via `_sanitize_text()` on all user-controlled audit log fields
- `_from_approval` flag is a Python function parameter (not injectable from client)
- `_bulk_edit_count` computed server-side from diff (not trusted from client)
- `_approval_request_id` only read when `_from_approval=True`
- `log_event` action requires `EDIT_ROLES` (prevents audit log injection by viewers)
- `wl_analyst_viewer` role inherits `user` instead of `power` (least privilege)
- Payload size limit (10 MB) to prevent DoS
- `props.conf` with `TRUNCATE=0` for large audit events

### Fixed

- RBAC cancel bug: compared username to role name strings instead of checking user's actual roles
- `_build_request_value_fields()` crash: removed call to non-existent method in cancel path
- `doSave` failure handler: now resets `currentHeaders` alongside `currentRows`
- `MAX_TRACKED_ANALYSTS` overflow: tracks under `__overflow__` bucket instead of silently allowing unlimited operations
- GET 400 response: added missing `get_notifications` and `get_request_csv` to valid actions list

### Changed

- Version bumped to 2.0.0
- Navigation: replaced Search tab with Control Panel (admin-only)
- `default.meta`: updated permissions for new roles
- `restmap.conf`: added `passSystemAuth = true` for audit event writing
- Package script: excludes dev artifacts (`.claude/`, `.pytest_cache/`, `CLAUDE.md`, etc.)
- Development credentials moved to environment variables with defaults

## [1.0.0] - 2026-02-15

### Added

- Initial release of Splunk Whitelist Manager
- Web-based interface for managing detection rule CSV whitelists
- Support for 18 sample detection rules
- Role-based access control (`wl_editor`, `wl_viewer`)
- Audit trail logging to `wl_audit` index
- Bulk add/remove operations
- REST API at `/custom/wl_manager`
- Configurable rule mapping via `rule_csv_map.csv`
