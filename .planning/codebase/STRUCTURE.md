# Codebase Structure

## Directory Layout

```
wl_manager/
├── appserver/static/           # Frontend assets (JS, CSS)
│   ├── whitelist_manager.js    # Main UI controller (6786 lines)
│   ├── whitelist_manager.css   # Styles with dark/light theme (1585 lines)
│   ├── control_panel.js        # Admin control panel UI (2025 lines)
│   ├── notifications.js        # Toast notification system (325 lines)
│   ├── audit_trail.js          # Audit dashboard helpers
│   ├── application.js          # Splunk app entry point
│   └── application.css         # Splunk app base styles
├── bin/                        # Backend Python handlers
│   ├── wl_handler.py           # Main REST handler (7078 lines)
│   ├── wl_expiration_cleanup.py # Scheduled: remove expired rows
│   ├── wl_expiring_soon.py     # Scheduled: alert on expiring rows
│   └── wl_wrapper.py           # Splunk search command wrapper
├── default/                    # Splunk configuration files
│   ├── app.conf                # App metadata, build number
│   ├── restmap.conf            # REST endpoint → handler mapping
│   ├── indexes.conf            # wl_audit index definition
│   ├── authorize.conf          # RBAC roles: wl_editor, wl_viewer
│   ├── savedsearches.conf      # Scheduled searches (expiration alerts)
│   ├── inputs.conf             # Scripted inputs for scheduled tasks
│   ├── commands.conf           # Custom search command definitions
│   ├── props.conf              # Event parsing (TRUNCATE=0 for large audit events)
│   ├── transforms.conf         # Lookup definitions
│   ├── web.conf                # Web UI settings
│   └── data/ui/
│       ├── nav/default.xml     # Navigation menu
│       └── views/
│           ├── whitelist_manager.xml  # Main dashboard
│           ├── audit.xml              # Audit trail dashboard
│           └── control_panel.xml      # Admin control panel
├── lookups/                    # CSV whitelist data files
│   ├── rule_csv_map.csv        # Maps detection rules → CSV files
│   ├── _detection_rules.json   # Detection rules registry
│   ├── DR*.csv                 # Whitelist CSV files (20+ files)
│   ├── _versions/              # Version snapshots (auto-managed)
│   └── _trash/                 # Soft-deleted CSVs with metadata
├── tests/                      # Test suite (24 files, 9007 lines)
│   ├── test_compute_diff.py    # Diff algorithm unit tests
│   ├── test_approval_*.py      # Approval workflow tests
│   ├── test_rbac.py            # Role-based access tests
│   ├── test_daily_limits.py    # Rate limiting tests
│   ├── test_e2e_*.py           # End-to-end API tests
│   ├── test_stress.py          # Load/stress tests
│   └── test_ui_browser.py      # Browser-based UI tests
├── scripts/                    # Build and deployment
│   ├── package.sh              # Create .spl package for distribution
│   ├── validate.sh             # AppInspect validation
│   └── test_integration.sh     # Integration test runner
├── docs/                       # Documentation
│   └── screenshots/            # UI screenshots
├── demo/                       # Demo scripts
│   ├── demo.sh                 # Automated demo script
│   └── generate_demo_guide.py  # Demo guide generator
├── .github/workflows/          # CI/CD
│   ├── ci.yml                  # Continuous integration
│   ├── release.yml             # Release automation
│   └── validate-and-package.yml # AppInspect + packaging
├── docker-compose.yml          # Dev container (Splunk 9.3.1)
├── metadata/                   # Splunk metadata (permissions)
└── dist/                       # Built packages (.spl)
```

## Key Locations

| What | Where |
|------|-------|
| All backend logic | `bin/wl_handler.py` (single monolithic file) |
| All frontend UI logic | `appserver/static/whitelist_manager.js` |
| Admin settings UI | `appserver/static/control_panel.js` |
| Notification toasts | `appserver/static/notifications.js` |
| Whitelist data | `lookups/DR*.csv` |
| Rule-to-CSV mapping | `lookups/rule_csv_map.csv` |
| Detection rules registry | `lookups/_detection_rules.json` |
| Version snapshots | `lookups/_versions/{csv_name}_*.csv` |
| Version manifests | `lookups/_versions/{csv_name}_versions.json` |
| Trash storage | `lookups/_trash/{csv_name}__csv_{timestamp}/` |
| Audit index config | `default/indexes.conf` |
| RBAC roles | `default/authorize.conf` |
| REST endpoint mapping | `default/restmap.conf` |

## Naming Conventions

| Type | Convention | Example |
|------|-----------|---------|
| CSV files | `DR{number}_{description}.csv` | `DR102_whitelist.csv` |
| Version snapshots | `{csv_name}_{timestamp}.csv` | `DR102_whitelist_20260331_143500.csv` |
| Version manifests | `{csv_name}_versions.json` | `DR102_whitelist_versions.json` |
| Trash directories | `{csv_name}__csv_{timestamp}/` | `DR_TEST__csv_20260329_000450/` |
| Python handlers | `wl_*.py` | `wl_handler.py` |
| CSS classes | `.wl-*` prefix | `.wl-modal`, `.wl-dark` |
| JS functions | `camelCase` | `refreshTable()`, `syncInputs()` |
| Python methods | `_snake_case` (private) | `_compute_diff()`, `_check_rbac()` |
| Config files | Splunk standard | `app.conf`, `restmap.conf` |

## File Size Distribution

| File | Lines | Role |
|------|-------|------|
| `bin/wl_handler.py` | 7,078 | Backend — all server logic |
| `appserver/static/whitelist_manager.js` | 6,786 | Frontend — main UI |
| `appserver/static/control_panel.js` | 2,025 | Frontend — admin panel |
| `appserver/static/whitelist_manager.css` | 1,585 | Styles |
| `appserver/static/notifications.js` | 325 | Frontend — notifications |
| `tests/` (24 files) | 9,007 | Test suite |
| **Total core code** | **~17,800** | |

---
*Generated: 2026-03-31 by gsd:map-codebase*
