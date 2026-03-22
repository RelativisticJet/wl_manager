# Changelog

All notable changes to this project will be documented in this file.

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
