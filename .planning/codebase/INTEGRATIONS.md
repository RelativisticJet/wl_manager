# External Integrations

**Analysis Date:** 2026-03-31

## APIs & External Services

**Splunk Management API (Internal):**
- Splunk REST API (localhost, port 8089)
  - Endpoint: `https://127.0.0.1:8089/services/receivers/simple`
  - Purpose: Submit audit events to the `wl_audit` index
  - Authentication: Splunk session token (system authtoken from request)
  - Implementation: `bin/wl_handler.py` → `_index_audit()` method
  - Protocol: HTTPS (self-signed certificate, verification disabled)
  - Payload: JSON audit events with structured change data

**Splunk Web API:**
- Splunk Web on port 8000
- Used by: Frontend JavaScript via `/splunkd/__raw/` proxy
- Purpose: Admin detection, REST handler invocation
- Authentication: Browser session cookies, passed via `passHttpCookies` in `default/restmap.conf`

## Data Storage

**Databases:**
- None - Application is file-based

**File Storage:**
- Local File System (Lookups Directory):
  - Location: `$SPLUNK_HOME/etc/apps/wl_manager/lookups/`
  - Files:
    - `rule_csv_map.csv` - Master mapping of detection rules to CSV files
    - `DR*.csv` - Individual whitelist CSV files (e.g., `DR102_whitelist.csv`, `DR310_impossible_travel.csv`)
    - `_versions/` - Version snapshots (6 kept: 1 current + 5 previous)
    - `_versions/{csv_name}_versions.json` - Manifest of version metadata
    - `_detection_rules.json` - Registry of detection rules without CSV mappings
    - `_approval_queue.json` - Pending approval requests
    - `_daily_limits.json` - Per-analyst daily usage counts
    - `_limit_config.json` - Configurable daily limits per action type
    - `_trash_config.json` - Trash retention settings
    - `_notifications.json` - User notification queue
  - Access: Direct file I/O via Python `csv`, `json`, `open()` with file locking (fcntl on Unix)
  - Persistence: Splunk index volumes persist across container restarts

**Caching:**
- In-Memory Presence Tracker:
  - Structure: `_presence = { "csv_file": { "user": {"seen": timestamp, "activity": timestamp} } }`
  - Purpose: Track which users are viewing which CSVs (for "User is editing" warnings)
  - Lifetime: Session memory, lost on application restart
  - Cleanup: Automatic on idle timeout (IDLE_TIMEOUT = 1800 seconds = 30 minutes)

- In-Memory Rate Limiting:
  - Structure: `_rate_limits = { (user, action): [timestamp, ...] }`
  - Purpose: Sliding-window rate limiting per user per action type
  - Limits:
    - Write (POST) actions: 30 per user per 60-second window
    - Read (GET) actions: 120 per user per 60-second window
  - Cleanup: Automatic pruning of stale entries when window slides

## Authentication & Identity

**Auth Provider:**
- Splunk Enterprise built-in authentication
- Implementation: LDAP, SAML, or local users (configured at Splunk instance level)

**Session Handling:**
- Splunk session tokens via `passSystemAuth` in `default/restmap.conf`
- Token sources:
  - `request.get("system_authtoken", "")` - Preferred (system token for audit writes)
  - `request.get("session", {}).get("authtoken", "")` - Fallback (user token)
- Frontend: Browser cookies + Splunk Web session (transparent to application)

**Authorization:**
- Role-Based Access Control (RBAC) via `default/authorize.conf`:
  - Read (GET) actions: All authenticated users
  - Write (POST) actions: `wl_editor`, `wl_analyst_editor`, `wl_admin`, `wl_superadmin`, `admin`, `sc_admin`
  - Admin actions (approval, control panel): `admin`, `sc_admin`, `wl_admin`, `wl_superadmin`
  - Super-admin actions (limits, trash): `wl_superadmin` only

## Monitoring & Observability

**Error Tracking:**
- None - Application logs errors locally

**Logs:**
- File-based rotating log:
  - Location: `$SPLUNK_HOME/var/log/splunk/wl_manager_audit.log`
  - Purpose: Persistent audit trail independent of Splunk indexing
  - Rotation: 10 MB per file, 5 backup files (RotatingFileHandler)
  - Fallback: stderr → splunkd.log if directory not writable (Docker compatibility)
- Splunk Index:
  - Index: `wl_audit` (dedicated, separate from main)
  - Events: Structured JSON with action, analyst, detection_rule, csv_file, timestamp, before/after diffs
  - Retention: 3 years (94608000 seconds)

## CI/CD & Deployment

**Hosting:**
- Docker/Docker Compose (development)
  - Container image: `splunk/splunk:9.3.1`
  - Container name: `wl_manager_test`
  - Ports: 8000 (Web UI), 8089 (Management API), 8088 (HEC)
  - Volumes: Bind-mounted app directories from host

- Splunk Enterprise (production)
  - Installation: Via `splunk install app wl_manager-<version>.spl`
  - Packaging: Bash script `scripts/package.sh` creates .tar.gz with .spl extension

**CI Pipeline:**
- None - No automated CI/CD detected
- Manual validation scripts available:
  - `scripts/validate.sh` - Syntax and configuration checks
  - `scripts/test_integration.sh` - Integration tests against container
  - `scripts/package.sh` - Build .spl deployment package

**MCP Server (Optional Tooling):**
- Splunk MCP Server (Claude integration, not production):
  - Path: `~/.claude/mcp/splunk_mcp_server.py`
  - Config: `~/.claude/.mcp.json`
  - Purpose: Provide Splunk CLI access to Claude for development/testing
  - Tools: `splunk_search`, `splunk_restart`, `splunk_deploy`, `splunk_read_lookup`, etc.

## Environment Configuration

**Required Environment Variables:**
- `SPLUNK_HOME` (default: `/opt/splunk`) - Splunk installation root
- `SPLUNK_PASSWORD` (for Docker, default: `Chang3d!`) - Container admin password

**Configuration Files (Read at Startup):**
- `default/app.conf` - App metadata and build version
- `default/restmap.conf` - REST endpoint registration
- `default/authorize.conf` - RBAC role definitions
- `default/indexes.conf` - Index definitions
- `default/props.conf` - Event field truncation settings
- `default/commands.conf` - Custom search command registration (`wlexpiringsoon`)
- `default/transforms.conf` - Lookup table definitions
- `default/savedsearches.conf` - Scheduled searches and alert rules
- `default/inputs.conf` - Scheduled script inputs (expiration cleanup)

**Secrets Location:**
- No secrets in codebase (by design)
- Splunk session tokens provided via request headers (Splunk-managed)
- No API keys, passwords, or credentials stored

## Webhooks & Callbacks

**Incoming:**
- None - Application does not accept external webhooks

**Outgoing:**
- Audit events to Splunk index (HTTPS POST):
  - Triggered on every save/delete/revert operation
  - Payload: JSON event with action metadata and structured diff
  - Recipient: `https://127.0.0.1:8089/services/receivers/simple` (local only)

**Scheduled Tasks:**
- Expiration Cleanup Job:
  - Frequency: Every hour (3600 seconds)
  - Script: `bin/wl_expiration_cleanup.py` (registered in `default/inputs.conf`)
  - Purpose: Auto-remove rows with Expires column past current date
  - Audit: Writes `auto_removed` events to `wl_audit` index

- Expiring Soon Alert (Saved Search):
  - Name: `wl_expiring_soon` (in `default/savedsearches.conf`)
  - Purpose: Dashboard report showing rows approaching expiration
  - Execution: On-demand or scheduled (configurable)
  - Query: Maps across all CSV lookups, computes time until expiration

---

*Integration audit: 2026-03-31*
