# Technology Stack

**Analysis Date:** 2026-03-31

## Languages

**Primary:**
- Python 3 - Backend REST handler (`bin/wl_handler.py`), scheduled cleanup scripts, custom search commands
- JavaScript (ES5) - Frontend UI controllers, browser-based CSV editing and validation
- Bash - Build, packaging, and deployment scripts (`scripts/`)

**Secondary:**
- SimpleXML - Splunk dashboard and view definitions (`default/data/ui/views/`)
- CSV/Lookup files - Data storage and rule-to-CSV mappings

## Runtime

**Environment:**
- Splunk Enterprise 9.3.1 - Core application platform (containerized via Docker)
- Python 3.x - Splunk bundled Python runtime for all server-side code

**Package Manager:**
- No external package manager - All Python dependencies are either Splunk-bundled or lazily imported

## Frameworks

**Core:**
- Splunk Enterprise Security (ES) - Detection rule framework and whitelist integration
- Splunk SDK (splunklib) - Optional, lazily imported for audit event indexing

**Frontend:**
- Splunk Web MVC Framework - JavaScript module loader (require/AMD), utils library, components
- jQuery - DOM manipulation (bundled with Splunk)
- Underscore.js - Utility functions (bundled with Splunk)

**Backend:**
- `splunk.persistconn.application.PersistentServerConnectionApplication` - REST handler base class

**Build/Dev:**
- Docker/Docker Compose - Containerized test environment (Splunk 9.3.1)

## Key Dependencies

**Critical:**
- `splunk.persistconn.application` - Splunk REST handler framework (bundled with Splunk)
- Python standard library only:
  - `urllib.request`, `urllib.parse` - HTTPS requests to Splunk API (audit event submission)
  - `json`, `csv` - Data serialization and CSV parsing
  - `logging`, `logging.handlers` - Rotating file logging for audit trail backup
  - `difflib` - Git-style diff computation for change detection
  - `collections.Counter` - Multiset operations for deduplication analysis
  - `datetime`, `timezone` - Timestamp handling and expiration date parsing
  - `fcntl` - File locking on Unix (skipped gracefully on Windows)

**Infrastructure:**
- Splunk Lookup Tables - CSV-based rule-to-CSV mappings and whitelist data (`lookups/rule_csv_map.csv`, `lookups/DR*.csv`)
- Splunk Index (`wl_audit`) - Dedicated index for audit events and change trail
- File System - Local lookup directory (`$SPLUNK_HOME/etc/apps/wl_manager/lookups/`) for CSV storage and version snapshots

## Configuration

**Environment:**
- `SPLUNK_HOME` - Path to Splunk installation (defaults to `/opt/splunk`)
  - Derived: App directory = `$SPLUNK_HOME/etc/apps/wl_manager`
  - Derived: Audit log = `$SPLUNK_HOME/var/log/splunk/wl_manager_audit.log`

**Build:**
- `default/app.conf` - App metadata, version (2.0.0), build number (480), UI settings
- `default/restmap.conf` - REST endpoint registration (`/custom/wl_manager` → `wl_handler.py`)
- `default/web.conf` - Expose REST handler over HTTP(S)
- `docker-compose.yml` - Development container definition (Splunk 9.3.1, port 8000 Web, port 8089 Management API)

**Authentication & Authorization:**
- `default/authorize.conf` - Custom RBAC roles:
  - `wl_superadmin` - System owner, controls limits and trash
  - `wl_admin` - Can approve/reject requests
  - `wl_analyst_editor` - View and edit whitelists
  - `wl_analyst_viewer` - Read-only access
  - Legacy roles: `wl_editor` (→ wl_analyst_editor), `wl_viewer` (→ wl_analyst_viewer)

**Indexing:**
- `default/indexes.conf` - `wl_audit` index definition (cold retention: 3 years = 94608000 seconds)
- `default/props.conf` - `wl_audit` sourcetype with `TRUNCATE = 0` for large audit events

## Platform Requirements

**Development:**
- Docker/Docker Compose (for containerized Splunk test environment)
- Python 3.x (for local script testing outside container)
- Bash shell (for build/package/validate scripts)
- Git (for version control)

**Production:**
- Splunk Enterprise 9.3.1 or compatible
- Management Port 8089 accessible (internal HTTPS for audit event submission)
- File system write permission to lookups directory (for CSV storage and version snapshots)
- File locking support (Unix fcntl, optional on Windows with graceful degradation)

---

*Stack analysis: 2026-03-31*
