# Whitelist Manager for Splunk ES

A Splunk application for managing detection-rule CSV whitelists with a full audit trail.

Built for **Splunk Enterprise Security (ES)** on-prem environments with 300+ detection rules.

## Features

- **Two codependent dropdowns** — select a detection rule, then its associated CSV files
- **Editable CSV table** — add, remove, and modify whitelist entries in-browser
- **Git-style audit trail** — every change records who, what, when, with unified diff
- **RBAC enforcement** — only `wl_editor` role can save changes
- **Dual audit storage** — events indexed in `wl_audit` + rotating log file
- **Master mapping CSV** — `rule_csv_map.csv` links rules to their CSV files across apps
- **CLI wrapper** — `wl_wrapper.py` for command-line bulk operations

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
| `rule_name` | Detection rule name | `DR45_suspicious_login` |
| `csv_file` | CSV filename | `DR45_whitelist_users.csv` |
| `app_context` | Splunk app containing the CSV | `SplunkEnterpriseSecuritySuite` |

A rule can map to multiple CSVs (one row per CSV).

## Architecture

```
wl_manager/
├── bin/
│   ├── wl_handler.py       # REST handler (PersistentServerConnectionApplication)
│   └── wl_wrapper.py       # CLI wrapper for terminal operations
├── default/
│   ├── app.conf            # App metadata
│   ├── restmap.conf        # REST endpoint registration
│   ├── web.conf            # Splunk Web exposure
│   ├── indexes.conf        # wl_audit index definition
│   ├── authorize.conf      # wl_editor / wl_viewer roles
│   ├── transforms.conf     # Lookup definitions
│   └── data/ui/
│       ├── nav/default.xml
│       └── views/
│           ├── whitelist_manager.xml  # Main dashboard
│           └── audit.xml              # Audit trail dashboard
├── appserver/static/
│   ├── whitelist_manager.js   # Frontend controller
│   └── whitelist_manager.css  # Styles
├── lookups/
│   └── rule_csv_map.csv    # Master rule-to-CSV mapping
└── metadata/
    └── default.meta        # RBAC permissions
```

## RBAC Roles

| Role | Permissions |
|---|---|
| `wl_editor` | Read + write whitelists, view audit trail |
| `wl_viewer` | Read-only access to whitelists and audit trail |
| `admin` / `sc_admin` | Full access (built-in) |

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

### Validation & Packaging

```bash
# Validate app structure, syntax, security
bash scripts/validate.sh

# Build .spl package
bash scripts/package.sh
# Output: dist/wl_manager-<version>.spl
```

## Releasing a New Version

1. Update `version` in `default/app.conf`
2. Commit and push
3. Create a GitHub release with a tag matching the version (e.g., `v1.1.0`)
4. The CI workflow automatically builds and attaches the `.spl` to the release

## Audit Trail

Every CSV save generates an audit event containing:

- **Analyst** — who made the change
- **Timestamp** — UTC ISO-8601
- **Detection rule** — which rule the whitelist belongs to
- **Comment** — mandatory analyst-provided reason
- **Diff** — added rows, removed rows, and unified text diff

View the audit trail at **Apps > Whitelist Manager > Audit Trail**.

Search in SPL:
```spl
index=wl_audit sourcetype=wl_audit
| spath
| table timestamp analyst detection_rule csv_file comment rows_added rows_removed
```
