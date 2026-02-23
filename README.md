# Whitelist Manager for Splunk

A Splunk application for managing detection-rule CSV whitelists with a full audit trail.

Built for **Splunk Enterprise Security (ES)** on-prem environments with hundreds of detection rules.

## Features

- **Searchable detection rule dropdown** — type-ahead search across 300+ detection rules
- **Editable CSV table** — add, remove, and edit whitelist entries in-browser with pagination
- **Row selection** — select individual rows or all rows across pages for bulk operations
- **Git-style audit trail** — every change records who, what, when, with unified diff and cell-level edit tracking
- **Expiration management** — date/time picker with presets (7 days, 30 days, 6 months, 1 year); supports 7 column name variants
- **Auto-expiration cleanup** — expired rows removed automatically on load and via hourly scheduled task
- **Undo support** — 10-second undo window after row removal
- **CSV import/export** — bulk upload to merge rows, download current CSV
- **RBAC enforcement** — server-side role checks; only `wl_editor` / `admin` / `sc_admin` can save changes
- **Dual audit storage** — events indexed in `wl_audit` + rotating log file backup
- **Master mapping CSV** — `rule_csv_map.csv` links rules to their CSV files across apps
- **CLI wrapper** — `wl_wrapper.py` for command-line and automation operations
- **Dark/light theme** — automatically detects and adapts to Splunk's active theme
- **Expiring Soon dashboard** — shows rows approaching expiration with "X days Y hours left" display

## Quick Start

### Install from `.spl`

1. Download the latest `.spl` from [Releases](../../releases)
2. In Splunk Web: **Apps > Manage Apps > Install app from file**
3. Upload the `.spl` file and restart Splunk

### Post-Install Setup

1. **Populate the mapping** — Edit `lookups/rule_csv_map.csv` via **Settings > Lookups > Lookup table files** to map your detection rules to their CSV files
2. **Assign roles** — Give analysts the `wl_editor` role via **Settings > Access Controls > Users**
3. **Verify** — Navigate to **Apps > Whitelist Manager** and test the dropdowns

## Mapping CSV Format

The master mapping (`rule_csv_map.csv`) has three columns:

| Column | Description | Example |
|---|---|---|
| `rule_name` | Detection rule name | `My_Detection_Rule` |
| `csv_file` | CSV filename | `my_whitelist.csv` |
| `app_context` | Splunk app containing the CSV | `SplunkEnterpriseSecuritySuite` |

A rule can map to multiple CSVs (one row per CSV). Leave `app_context` empty if the CSV is in `wl_manager/lookups/`.

## Supported Expiration Column Names

The app recognizes these column names (case-insensitive) as expiration dates:

`Expires`, `expire`, `expiration`, `expiration_date`, `expiry`, `termination`, `termination_date`

Date formats supported: `YYYY-MM-DD HH:MM`, `YYYY-MM-DD`

## Architecture

```
wl_manager/
├── bin/
│   ├── wl_handler.py              # REST handler (PersistentServerConnectionApplication)
│   ├── wl_expiring_soon.py        # Custom search command: | wlexpiringsoon
│   ├── wl_expiration_cleanup.py   # Scheduled hourly cleanup
│   └── wl_wrapper.py              # CLI wrapper for terminal operations
├── default/
│   ├── app.conf                   # App metadata
│   ├── restmap.conf               # REST endpoint registration
│   ├── web.conf                   # Splunk Web exposure
│   ├── commands.conf              # Custom search command registration
│   ├── inputs.conf                # Scheduled cleanup (hourly)
│   ├── indexes.conf               # wl_audit index definition
│   ├── authorize.conf             # wl_editor / wl_viewer roles
│   ├── transforms.conf            # Lookup definitions
│   ├── savedsearches.conf         # Expiring soon saved search
│   └── data/ui/
│       ├── nav/default.xml
│       └── views/
│           ├── whitelist_manager.xml  # Main dashboard
│           └── audit.xml              # Audit trail dashboard
├── appserver/static/
│   ├── whitelist_manager.js       # Frontend controller
│   └── whitelist_manager.css      # Styles (dark/light theme)
├── lookups/
│   └── rule_csv_map.csv           # Master rule-to-CSV mapping
├── metadata/
│   └── default.meta               # RBAC permissions
└── docs/
    ├── Whitelist_Manager_Documentation.md    # User Guide
    ├── Whitelist_Manager_Documentation.html  # Full Documentation (PDF-ready)
    └── Splunk_Admin_Installation_Guide.md    # Admin Guide
```

## RBAC Roles

| Role | Permissions |
|---|---|
| `wl_editor` | Read + write whitelists, view audit trail |
| `wl_viewer` | Read-only access to whitelists and audit trail |
| `admin` / `sc_admin` | Full access (built-in Splunk roles) |

## Dashboards

### Whitelist Manager (Main)
- Searchable detection rule dropdown
- CSV file selector
- Editable table with Add Row, Remove, Save, Discard, Import, Export
- Date/time picker for expiration columns
- Git-style diff display after save

### Audit Trail
- Time range, analyst, detection rule, and action filters
- Summary stats: Total Changes, Rows Added, Rows Removed, Rows Edited
- Detailed action log with per-row values
- Expiring Soon panel filtered by selected detection rule

## Quick Demo (Docker)

Evaluate the app in a containerized Splunk instance with one command:

```bash
bash demo/demo.sh          # build .spl, start Splunk on http://localhost:9000
bash demo/demo.sh --stop   # stop and remove the demo container
bash demo/demo.sh --clean  # stop + remove container and data volume
```

Login: `admin` / `Chang3d!` at http://localhost:9000

The demo seeds three sample detection rules with whitelist data so you can immediately test all features. See `demo/Demo_Guide.pdf` for a step-by-step walkthrough.

## Development

### Prerequisites

- Docker Desktop
- Git Bash (Windows) or Bash (Linux/macOS)
- Python 3.9+

### Local Testing

```bash
# Start containerized Splunk
docker compose up -d

# Wait ~60 seconds for Splunk to start, then run tests
bash scripts/test_integration.sh

# Stop
docker compose down
```

### Packaging

```bash
# Build .spl package
bash scripts/package.sh
# Output: dist/wl_manager-<version>.spl
```

## Audit Trail

Every CSV change generates audit events containing:

- **Analyst** — who made the change
- **Timestamp** — Unix epoch (displayed as formatted datetime in dashboard)
- **Detection rule** — which rule the whitelist belongs to
- **Action** — added, removed, edited, or auto_removed
- **Comment** — analyst-provided reason for the change
- **Row details** — per-row field values with row numbers
- **Removal reason** — why rows were removed (required)

View the audit trail at **Apps > Whitelist Manager > Audit Trail**.

Search in SPL:
```spl
index=wl_audit sourcetype=wl_audit
| table timestamp analyst action detection_rule csv_file comment
```

## Security

- **Path traversal prevention** — filenames validated, `os.path.basename()` applied to app context
- **XSS prevention** — all user values escaped with `_.escape()` before DOM insertion
- **Server-side RBAC** — role checks performed server-side via Splunk REST API
- **No hardcoded credentials** — uses Splunk session tokens exclusively
- **No external dependencies** — Python stdlib only (no pip packages)
- **Authentication required** — REST endpoint requires valid Splunk session

## License

Proprietary — Security Engineering Team
