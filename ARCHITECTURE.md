# Architecture Guide

> Start here if you want to understand, debug, or extend Whitelist Manager.

## How It Works (30-second version)

SOC analysts open a Splunk dashboard, pick a detection rule, select a CSV whitelist, edit rows inline, and save. Every change is diff-logged to an audit index. Admins configure approval gates and daily limits via a Control Panel.

```
Browser (Splunk Web)
  |
  |  AJAX (JSON over Splunk REST proxy)
  v
wl_handler.py  ------>  wl_audit.py  ------>  index=wl_audit
  |                        (audit events)
  |---> wl_csv.py          (read/write/diff CSVs)
  |---> wl_rules.py        (create/delete detection rules)
  |---> wl_approval.py     (approval queue management)
  |---> wl_limits.py       (daily limit enforcement)
  |---> wl_versions.py     (version snapshots)
  |---> wl_trash.py        (soft-delete / recycle bin)
  |---> wl_replay.py       (replay approved requests)
  |---> wl_rbac.py         (role checks)
  |---> wl_validation.py   (input sanitization)
```

## Backend (Python)

All backend code lives in `bin/`. There are **no external Python dependencies** — only the standard library and Splunk's bundled SDK.

### The Handler (`wl_handler.py` — 5,223 lines)

This is the REST endpoint. It uses a dispatch-table pattern:

```python
GET_ACTIONS = {
    "get_csv_content": (None, "_action_get_csv_content"),     # public
    "get_approval_queue": (ADMIN_ROLES, "_action_get_queue"), # admin-only
    ...
}
POST_ACTIONS = {
    "save_csv": (EDIT_ROLES, "_action_save_csv"),
    "process_approval": (ADMIN_ROLES, "_action_process_approval"),
    ...
}
```

Each action maps to a `(required_roles, method_name)` tuple. The dispatcher checks RBAC, then calls `getattr(self, method_name)`. Action wrappers validate input and delegate to domain modules.

> **Known limitation:** `wl_handler.py` is large. The action wrappers have been partially extracted into domain modules (see below), but the wrappers themselves remain. This is the top candidate for future refactoring. See [CODE_METRICS.md](docs/CODE_METRICS.md) for complexity analysis.

### Domain Modules

| Module | Lines | What it does |
|--------|-------|-------------|
| `wl_csv.py` | 1,069 | Read/write CSV files, compute diffs (similarity-based matching), column width tracking |
| `wl_trash.py` | 765 | Soft-delete with retention policy, restore, purge (dual-admin for permanent delete) |
| `wl_versions.py` | 643 | Snapshot last 6 versions per CSV, manifest tracking, revert support |
| `wl_approval.py` | 620 | Approval queue CRUD, expiration (30 days), conflict cancellation |
| `wl_rules.py` | 538 | Detection rule registry, create/delete pipelines, mapping file management |
| `wl_replay.py` | 508 | Replay approved requests (re-executes the action the admin approved) |
| `wl_limits.py` | 474 | Per-analyst daily limits, per-admin limits, configurable reset schedules |
| `wl_constants.py` | 463 | All paths, thresholds, role sets, regex patterns — single source of truth |
| `wl_notify.py` | 238 | Notification storage, delivery, auto-cleanup (90-day max, 500 per user) |
| `wl_validation.py` | 202 | Filename validation, ASCII enforcement, path traversal prevention |
| `wl_audit.py` | 191 | Build and POST audit events to `wl_audit` index via Splunk REST API |
| `wl_rbac.py` | 169 | Role extraction, `is_admin()`, `is_superadmin()`, `is_editor()` |
| `wl_presence.py` | 160 | Track which users are editing which CSV (5-minute timeout) |
| `wl_filelock.py` | 104 | Cross-platform file locking for concurrent write safety |
| `wl_ratelimit.py` | 66 | Per-user rate limiting (requests per second) |
| `wl_logging.py` | 57 | Structured logging setup |

### Scheduled Scripts

| Script | Trigger | What it does |
|--------|---------|-------------|
| `wl_expiration_cleanup.py` | Hourly (inputs.conf) | Removes expired rows from CSVs, writes audit events |
| `wl_expiring_soon.py` | Daily (inputs.conf) | Alerts on rows expiring within N days |

### RBAC Tiers

```
Viewer          — Read CSVs and audit trail
Editor          — Edit CSVs, submit approval requests
Admin           — Approve/reject, configure limits, manage trash
Superadmin      — Set admin limits, factory reset, assign roles
```

Admins are exempt from approval gates (they ARE the approvers). Self-reset of daily usage is blocked (defense in depth).

## Frontend (JavaScript)

The frontend runs inside Splunk's SimpleXML dashboard framework. All dynamic UI is built via JavaScript because Splunk strips `<button>`, empty `<div>`, and most HTML elements from dashboard panels.

### Entry Points

| File | Lines | Dashboard |
|------|-------|-----------|
| `whitelist_manager.js` | 517 | Main CSV editor |
| `control_panel.js` | 2,012 | Admin settings |
| `notifications.js` | 327 | Bell icon + dropdown (injected into all views) |
| `application.js` | 52 | Nav visibility (hides Control Panel for non-admins) |
| `audit_trail.js` | 51 | Audit dashboard helpers |

Entry points use `require()` (Splunk AMD). Modules use `define()` and return a public API object.

### Modules (13 total, in `appserver/static/modules/`)

```
wl_constants.js (40)  ─┐
wl_rest.js      (43)  ─┤  Foundation (no cross-module deps)
wl_ui.js       (129)  ─┘
       │
       v
wl_table.js    (1,537) ── Table rendering, inline editing, pagination,
       │                   column resize, drag-reorder, row selection
       │
       ├── wl_nav.js        (457) ── Rule/CSV dropdowns, URL params
       ├── wl_save.js     (1,023) ── Save pipeline, undo, change detection,
       │                              loadCsv, optimistic locking
       ├── wl_modals.js   (1,320) ── All modal dialogs
       ├── wl_csv_io.js   (1,177) ── Import/export, merge/replace
       ├── wl_approval_ui.js (631) ── Approval highlighting, submit, admin actions
       ├── wl_versions.js   (333) ── Version dropdown, revert flow
       ├── wl_diff.js       (277) ── Git-style diff display
       ├── wl_datepicker.js (178) ── Date/time picker for Expires column
       └── wl_presence.js   (241) ── User presence indicators
```

### Shared State Pattern

State lives in the entry point. Modules receive a proxy object with ES5 getter/setter properties:

```javascript
// Entry point creates the proxy
var _tableState = {};
Object.defineProperty(_tableState, "currentRows", {
    get: function () { return currentRows; },
    set: function (v) { currentRows = v; }
});

// Modules read/write through _state
Table.init({ state: _tableState, ... });
// Inside wl_table.js:  _state.currentRows = newRows;
```

This avoids the "state key mismatch" bug that occurred with a separate state module.

### Module Communication

Modules don't import each other directly (except `wl_csv_io` which imports parsing functions). Instead, the entry point wires them via callback objects:

```javascript
Save.init({
    state: _tableState,
    actions: {
        refreshTable: function () { return Table.refreshTable(); },
        loadVersions: function () { return Versions.loadVersions(...); },
        ...
    }
});
```

This keeps dependencies explicit and avoids circular imports in the AMD module system.

## Key Design Decisions

### Why similarity-based diff (not positional)?

When rows are removed and edited simultaneously, positional comparison produces false "edits" because row indices shift. The diff engine pairs removed and added rows by field similarity, classifying a pair as an "edit" only if >= 50% of visible fields match.

### Why deferred save with undo?

Row and column removal use a 10-second local undo window before saving. This prevents double audit events (remove + undo = 2 events for net zero change) and avoids charging daily limits for "changed my mind" actions.

### Why `_resp(200, {"error": ...})` instead of HTTP 4xx?

Splunk's REST proxy on port 8000 swallows non-200 response bodies. The frontend `.done()` handler checks `if (data.error)` to detect errors. This is a Splunk platform constraint, not a design choice.

### Why no external JavaScript libraries?

Splunk bundles jQuery and underscore. Adding external libraries requires Splunk AppInspect approval and complicates packaging. The app uses only what Splunk provides.

## Where to Start

| I want to... | Start here |
|---|---|
| Fix a backend bug | Find the action in `wl_handler.py`'s dispatch table, trace to the domain module |
| Fix a frontend bug | Check the browser console for the module name, read that module's JSDoc header |
| Add a new REST action | Add to `GET_ACTIONS` or `POST_ACTIONS` in `wl_handler.py`, create the wrapper method |
| Add a new UI feature | Create a new `wl_*.js` module, wire it in the entry point's `require()` list |
| Understand the security model | Read [docs/SECURITY_ARCHITECTURE.md](docs/SECURITY_ARCHITECTURE.md) |
| Run tests | `make test` (requires Docker) or `pytest tests/` for unit tests |
| Package for distribution | `make package` creates `dist/wl_manager-VERSION.spl` |

## File Map

```
wl_manager/
  bin/                          # Backend (Python)
    wl_handler.py               #   REST endpoint + dispatch tables
    wl_csv.py                   #   CSV read/write/diff
    wl_rules.py                 #   Detection rule CRUD
    wl_approval.py              #   Approval queue
    wl_replay.py                #   Replay approved actions
    wl_limits.py                #   Daily limits
    wl_versions.py              #   Version snapshots
    wl_trash.py                 #   Soft-delete / recycle bin
    wl_audit.py                 #   Audit event posting
    wl_rbac.py                  #   Role-based access control
    wl_validation.py            #   Input sanitization
    wl_constants.py             #   All constants and paths
    wl_notify.py                #   Notifications
    wl_presence.py              #   User presence tracking
    wl_filelock.py              #   File locking
    wl_ratelimit.py             #   Rate limiting
    wl_logging.py               #   Logging setup
    wl_expiration_cleanup.py    #   Scheduled: remove expired rows
    wl_expiring_soon.py         #   Scheduled: expiration alerts
  appserver/static/             # Frontend (JavaScript)
    whitelist_manager.js        #   Main dashboard entry point
    control_panel.js            #   Admin panel entry point
    notifications.js            #   Notification bell (all views)
    application.js              #   Nav visibility control
    audit_trail.js              #   Audit dashboard helpers
    whitelist_manager.css       #   Styles (dark/light theme)
    modules/                    #   AMD modules (13 files)
      wl_table.js               #     Table rendering + editing
      wl_modals.js              #     All modal dialogs
      wl_csv_io.js              #     CSV import/export
      wl_save.js                #     Save pipeline + undo
      wl_approval_ui.js         #     Approval UI
      wl_nav.js                 #     Dropdown navigation
      wl_versions.js            #     Version/revert UI
      wl_diff.js                #     Diff display
      wl_presence.js            #     Presence indicators
      wl_datepicker.js          #     Date picker
      wl_ui.js                  #     Message banner, theme
      wl_rest.js                #     REST helpers, CSRF
      wl_constants.js           #     Frontend constants
  default/                      # Splunk configuration
    app.conf                    #   App metadata + build number
    restmap.conf                #   REST endpoint mapping
    indexes.conf                #   wl_audit index definition
    authorize.conf              #   RBAC roles
    savedsearches.conf          #   Scheduled searches
    data/ui/views/              #   Dashboard XML files
  lookups/                      # Data files
    rule_csv_map.csv            #   Detection rule -> CSV mapping
    DR*.csv                     #   Whitelist CSV files
    _versions/                  #   Version snapshots (auto-managed)
  docs/                         # Documentation
  scripts/                      # Build, validate, test scripts
  tests/                        # Test suites
  .github/                      # CI/CD workflows + issue templates
```
