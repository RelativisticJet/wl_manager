# Architecture

**Analysis Date:** 2026-03-31

## Pattern Overview

**Overall:** Client-server REST API with multi-layered validation, approval queuing, and audit logging.

**Key Characteristics:**
- **Stateless REST handlers**: All state persisted to JSON files in `lookups/` directory
- **Multi-gate validation**: Daily limits, approval queues, RBAC enforced server-side
- **Audit-first design**: Every CSV change generates structured audit events to Splunk index + local log file
- **Version control**: Up to 6 CSV snapshots maintained per file with JSON manifests
- **Diff engine**: Similarity-based matching detects edits even with concurrent row removals
- **Lock-free with optimistic locking**: File mtime tracking prevents race conditions without blocking reads

## Layers

**Presentation (Frontend):**
- Purpose: Interactive CSV editor with rule selection, inline cell editing, approval tracking
- Location: `appserver/static/` (whitelist_manager.js, control_panel.js, notifications.js, audit_trail.js)
- Contains: jQuery-based UI controllers, form validation, approval workflow UI, CSV import/export
- Depends on: REST API via `$.ajax()`, Splunk SDK for user/role detection
- Used by: Analysts (read/edit), Admins (view approval queue, manage limits), SuperAdmins (manage trash)

**API Layer (REST Handler):**
- Purpose: Single entry point for all client requests, routing to action handlers
- Location: `bin/wl_handler.py` — `WhitelistHandler` class extending `PersistentServerConnectionApplication`
- Contains: Request routing, RBAC enforcement, rate limiting, response serialization
- Depends on: Splunk SDK, custom audit/approval/version control modules
- Used by: Frontend via POST/GET to `/custom/wl_manager` endpoint (registered in `default/restmap.conf`)

**Business Logic (Action Handlers):**
- Purpose: Implement domain logic for each action (save_csv, create_csv, process_approval, etc.)
- Location: `bin/wl_handler.py` — Methods like `_save_csv()`, `_submit_approval()`, `_process_approval()`
- Contains: CSV reading/writing, diff computation, approval gate checks, daily limit enforcement, trash operations
- Depends on: Lookup file I/O, JSON manifest management, audit event generation
- Used by: API router in `_handle_post()` and `_handle_get()`

**Data Persistence:**
- Purpose: Read/write CSV files, JSON manifests, approval queues, limit configs
- Location: `lookups/` directory tree (`*.csv`, `_versions/`, `_trash/`, `_approval_queue.json`, `_daily_limits.json`)
- Contains: CSV data, version snapshots, trash metadata, approval request payloads
- Depends on: Filesystem with file locking (fcntl on Unix, optimistic mtime on Windows)
- Used by: Action handlers for all state I/O

**Audit & Observability:**
- Purpose: Log every change to Splunk index + rotating file for offline access
- Location: `bin/wl_handler.py` — `_index_audit()` method; backup to `var/log/splunk/wl_manager_audit.log`
- Contains: Structured audit events (added/removed/edited rows, approvals, deletions, reversions)
- Depends on: Splunk REST API (port 8089) for event posting, file logging
- Used by: All action handlers that modify state

**Dashboard/UI Views:**
- Purpose: SimpleXML dashboard scaffolding (actual UI built by JavaScript)
- Location: `default/data/ui/views/` (whitelist_manager.xml, control_panel.xml, audit.xml)
- Contains: HTML panels, empty divs (JavaScript populates), CSS hooks for theme detection
- Depends on: JavaScript controllers for all interactivity
- Used by: Splunk web UI for rendering the app

## Data Flow

**CSV Load Flow:**
1. Frontend calls `GET /custom/wl_manager?action=get_csv_content&csv_file=DR102_whitelist.csv`
2. Handler validates filename (no traversal), resolves path to `lookups/DR102_whitelist.csv`
3. Reads CSV via `_read_csv()` → DictReader converts to list of dicts
4. Returns headers + rows to frontend; also includes `loadedMtime` (file modification time)
5. Frontend snapshot: `originalRows`, `currentRows` initialized to returned rows

**CSV Save Flow (Happy Path):**
1. Frontend calls `POST /custom/wl_manager` with action `save_csv`, old/new rows, reason
2. Handler:
   - Validates user has EDIT_ROLES
   - Checks daily limits (`_check_daily_limit()`) — counts actions across all CSVs per analyst
   - Checks mtime hasn't changed since load (optimistic locking)
   - Calls `_compute_diff()` to detect added/removed/edited rows
   - If edits cross threshold (bulk + 3 rows), enqueues approval request instead of saving
   - Writes new CSV to disk
   - Creates version snapshot in `_versions/`
   - Generates audit event with diff details
   - Posts audit event to `wl_audit` index + `wl_manager_audit.log`
3. Frontend receives success response with diff for display

**CSV Save Flow (Approval Path):**
1. Frontend detects save would cross approval threshold, calls `check_approval_gate()` first
2. If gate applies, shows "This requires approval" → user clicks "Submit for Approval"
3. Frontend calls `submit_approval()` with full payload (headers, rows, reason, action type)
4. Handler stores request in `_approval_queue.json` with `status: "pending"`
5. Sends "approval required" notification to admin users
6. Frontend shows approval status: "Awaiting approval from admin"

**Approval Processing Flow (Admin):**
1. Admin views Control Panel (control_panel.xml + control_panel.js)
2. Calls `get_approval_queue()` — returns all pending requests grouped by action
3. Admin reviews request payload (original + new rows, reason, analyst name)
4. Clicks "Approve" → calls `process_approval()` with `request_id` and `decision: "approved"`
5. Handler:
   - Validates admin role, checks daily admin limit (separate from analyst limits)
   - Re-validates preconditions (rule/CSV still exists, not conflicting)
   - Calls `_save_csv(..., _from_approval=True)` to replay the approved change
   - Updates queue item: `status: "approved"`, `resolved_by: "admin_name"`, `resolved_at: timestamp`
   - Auto-cancels conflicting pending requests (e.g., if rule was deleted, cancel all pending edits for that rule)
   - Generates approval-specific audit event with `action: "approved"`
   - Notifies analyst of approval

**Version Revert Flow:**
1. Frontend shows revert dropdown with last 5 versions (plus "Current")
2. User selects old version → frontend calls `revert_csv()` with selected version timestamp
3. Handler:
   - Reads old version from `_versions/DR102_versions.json` manifest
   - Loads old CSV content from `_versions/DR102_v_<timestamp>.csv`
   - Computes diff between current and old (same `_compute_diff()`)
   - Writes current CSV with old content
   - Creates new version snapshot (preserves old content under new timestamp)
   - Removes old version from manifest (keeps only last 5 previous)
   - Generates revert audit event with `*back` suffixed fields (restoredback_*, removedback_*, changedback_*)
4. Frontend shows diff visualization for revert

**Expiration Auto-cleanup Flow:**
1. Scheduled search runs (defined in `savedsearches.conf`) — checks for rows with expired `Expires` column
2. Splunk job calls `wl_expiration_cleanup.py` script
3. Script reads CSV, identifies rows where Expires date <= today
4. Calls REST API to save CSV with those rows removed
5. Handler treats as normal removal, generates audit with `action: "auto_removed"` + analyst="system"

## Key Abstractions

**Version Manifest (`_versions/DR102_versions.json`):**
- Purpose: Track snapshots and enable revert dropdown
- Format: List of version objects with `timestamp`, `row_count`, `analyst`, `action_type`
- Pattern: JSON array, newest first (for dropdown); old versions are deleted when count exceeds 6

**Approval Queue (`_approval_queue.json`):**
- Purpose: Store pending requests awaiting admin approval
- Format: List of request objects with `request_id`, `status` (pending/approved/rejected/cancelled), `action_type`, `payload` (full CSV), `analyst`, `timestamp`
- Pattern: File-locked read-modify-write cycles prevent concurrent approval overwrites

**Daily Limits Tracking (`_daily_limits.json`):**
- Purpose: Count analyst actions per reset period (daily/weekly/monthly/yearly)
- Format: Nested dict `{analyst: {action_type: count}}`
- Pattern: Resets at configured UTC time; admin can manually reset or force unlimited (0)

**Limit Config (`_limit_config.json`):**
- Purpose: Configure per-action thresholds and approval gates
- Format: Dict with keys `row_removal`, `bulk_row_edit`, `revert`, etc. and values (int or dict)
- Pattern: Defaults loaded from `DEFAULT_LIMITS` constant; admins can customize via Control Panel

**Detection Rules Registry (`_detection_rules.json`):**
- Purpose: Track all detection rule names (including those without CSV mappings yet)
- Format: JSON list of rule names
- Pattern: Created when analyst "Create Detection Rule" action is approved

**Trash Metadata (`_trash/<trash_id>/metadata.json`):**
- Purpose: Track deleted CSVs/rules for recovery window
- Format: Dict with `item_type`, `name`, `rule_name`, `deleted_by`, `deleted_at`, `retention_days`
- Pattern: Files automatically purged after retention period; manual purge requires dual-admin approval

## Entry Points

**Frontend Entry Point (whitelist_manager.xml):**
- Location: `default/data/ui/views/whitelist_manager.xml`
- Triggers: User navigates to Whitelist Manager app in Splunk Web
- Responsibilities: 
  - Load whitelist_manager.js + control_panel.js + notifications.js
  - Render empty HTML scaffold (dropdowns, table container, message area)
  - Detect dark theme and apply CSS classes

**REST API Entry Point (/custom/wl_manager):**
- Location: Endpoint registered in `default/restmap.conf`, handler at `bin/wl_handler.py`
- Triggers: Frontend `$.ajax()` calls
- Responsibilities:
  - Parse GET/POST requests
  - Enforce RBAC and rate limiting
  - Route to action handler based on `action` parameter
  - Return JSON responses (or error codes)

**Approval Queue Polling (Control Panel):**
- Location: `appserver/static/control_panel.js`
- Triggers: Admin opens Control Panel view
- Responsibilities:
  - Poll for pending approvals every 5 seconds
  - Display queue with action type, analyst, timestamp, payload preview
  - Enable approve/reject buttons

**Auto-expiration Cleanup (Scheduled Search):**
- Location: `default/savedsearches.conf` (defines schedule); backend: `bin/wl_expiration_cleanup.py`
- Triggers: Splunk scheduler runs on configured cron (typically daily)
- Responsibilities:
  - Query each CSV for expired rows
  - Call REST API to remove them
  - Generate audit events with action="auto_removed"

## Error Handling

**Strategy:** Try-catch all handler methods, return structured error responses. No silent failures.

**Patterns:**
- Invalid input → 400 Bad Request with error message
- Permission denied → 403 Forbidden
- Resource not found → 404 Not Found
- Rate limit exceeded → 429 Too Many Requests
- Payload too large → 413 Payload Too Large
- Server error → 500 with generic message (detail logged to splunkd.log)
- File locking timeout → Retry indefinitely (long-lived connections can wait)

**Audit error events:**
- Approval rejection → `action: "rejected"`, includes rejection reason
- Diff computation failure → Stored as `action: "error"`, prevents save
- Import validation failure → Frontend shows validation errors (not audit event)

## Cross-Cutting Concerns

**Logging:** 
- Audit trail: Structured JSON events to Splunk `wl_audit` index via REST API (port 8089)
- Fallback: Rotating file logger at `var/log/splunk/wl_manager_audit.log` (10 MB, 5 backups)
- Python logging to stderr (captured in splunkd.log) for debugging

**Validation:** 
- Filename validation: `_safe_filename()` checks no traversal, valid CSV extension, alphanumeric content
- Cell validation: Max 1000 chars, no null bytes, control chars stripped
- Column validation: Max 100 columns, no spaces (must use underscores), reserved `_` prefix rejected
- Row validation: Max 5000 rows, consistent field count with headers
- Expiration date format: `YYYY-MM-DD` or `YYYY-MM-DD HH:MM`

**Authentication:** 
- Splunk session token (passed in HTTP headers by SDK)
- User identity extracted via `self._get_user(request)` from session
- All POST actions require authenticated user (reject "unknown" identity)

**Authorization (RBAC):**
- **Read access**: All authenticated users
- **Write access (POST)**: `wl_editor`, `wl_analyst_editor`, `wl_admin`, `wl_superadmin`, `admin`, `sc_admin`
- **Admin actions (approve/reject, manage limits)**: `admin`, `sc_admin`, `wl_admin`, `wl_superadmin`
- **Superadmin actions (trash purge, limit config)**: `wl_superadmin`
- Role checks: `roles.intersection(EDIT_ROLES)` enforced before action execution

**Rate Limiting:**
- Sliding-window per user per action type
- Write (POST): 30 requests per 60 seconds
- Read (GET): 120 requests per 60 seconds
- Returns 429 if exceeded

**Presence Tracking:**
- In-memory dict `_presence` tracks CSV files open by users
- Updated via `report_presence()` action (frontend sends heartbeat every 15 sec)
- Shows "user X is editing" banner after 5+ seconds of activity
- Times out after 60 seconds of no heartbeat

---

*Architecture analysis: 2026-03-31*
