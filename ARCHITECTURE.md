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

### The Handler (`bin/wl_handler.py`)

This is the REST endpoint and the largest file in the backend. It uses a dispatch-table pattern:

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

> **Known limitation:** `wl_handler.py` is large. The action wrappers have been partially extracted into domain modules (see below), but the wrappers themselves remain. This is the top candidate for future refactoring. Run `make metrics` (or `pytest --cov=bin` + `radon cc bin/`) for current complexity and coverage numbers — we do not check in a metrics file because it drifts the moment anyone refactors.

### Domain Modules

Backend modules live under `bin/`. Run `ls bin/*.py` for the complete
current inventory — this table describes what each module owns, not how
large it is (line counts drift on every refactor and we do not keep them
synced by hand).

| Module | What it does |
|--------|--------------|
| `wl_csv.py` | Read/write CSV files, compute diffs (similarity-based matching), column width tracking |
| `wl_trash.py` | Soft-delete with retention policy, restore, purge (dual-admin for permanent delete) |
| `wl_versions.py` | Snapshot last 6 versions per CSV, manifest tracking, revert support |
| `wl_approval.py` | Approval queue CRUD, expiration (30 days), conflict cancellation |
| `wl_rules.py` | Detection rule registry, create/delete pipelines, mapping file management |
| `wl_replay.py` | Replay approved requests (re-executes the action the admin approved) |
| `wl_limits.py` | Per-analyst daily limits, per-admin limits, configurable reset schedules |
| `wl_constants.py` | All paths, thresholds, role sets, regex patterns — single source of truth |
| `wl_notify.py` | Notification storage, delivery, auto-cleanup (90-day max, 500 per user) |
| `wl_validation.py` | Filename validation, ASCII enforcement, path traversal prevention |
| `wl_audit.py` | Build and POST audit events to `wl_audit` index via Splunk REST API |
| `wl_rbac.py` | Role extraction, `is_admin()`, `is_superadmin()`, `is_editor()` |
| `wl_presence.py` | Track which users are editing which CSV (5-minute timeout) |
| `wl_filelock.py` | Cross-platform file locking for concurrent write safety |
| `wl_ratelimit.py` | Per-user rate limiting (requests per second) |
| `wl_logging.py` | Structured logging setup |
| `wl_fim_common.py` | Shared FIM helpers: GUID resolution, hashing, KV helpers |
| `wl_hmac_key.py` | Runtime HMAC key derivation and caching |

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

Frontend entry points live directly under `appserver/static/`.

| File | Dashboard |
|------|-----------|
| `whitelist_manager.js` | Main CSV editor |
| `control_panel.js` | Admin settings |
| `notifications.js` | Bell icon + dropdown (injected into all views) |
| `application.js` | Nav visibility (hides Control Panel for non-admins) |
| `audit_trail.js` | Audit dashboard helpers |

Entry points use `require()` (Splunk AMD). Modules use `define()` and return a public API object.

### Modules

AMD modules live under `appserver/static/modules/`. Run
`ls appserver/static/modules/` for the current inventory — the grouping
below shows the dependency layers, not the file-by-file sizes:

```text
Foundation layer (no cross-module deps):
  wl_constants.js   ─┐
  wl_rest.js        ─┤
  wl_ui.js          ─┘

Core UI layer:
  wl_table.js      ── Table rendering, inline editing, pagination,
                       column resize, drag-reorder, row selection

Feature layer (depend on foundation + wl_table.js):
  wl_nav.js         ── Rule/CSV dropdowns, URL params
  wl_save.js        ── Save pipeline, undo, change detection,
                       loadCsv, optimistic locking
  wl_modals.js      ── All modal dialogs
  wl_csv_io.js      ── Import/export, merge/replace
  wl_approval_ui.js ── Approval highlighting, submit, admin actions
  wl_versions.js    ── Version dropdown, revert flow
  wl_diff.js        ── Git-style diff display
  wl_datepicker.js  ── Date/time picker for Expires column
  wl_presence.js    ── User presence indicators
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

This is a directory-level overview. For the current file inventory, run
`ls bin/` or `ls appserver/static/modules/` — we do not enumerate every
file here because the list drifts on every new module.

```text
wl_manager/
  bin/                          # Backend (Python) — REST handler, domain
                                #   modules, scheduled scripts, FIM tooling.
                                #   Domain-module table above covers the
                                #   main responsibilities.
  appserver/static/             # Frontend (JavaScript + CSS)
    whitelist_manager.js        #   Main dashboard entry point
    control_panel.js            #   Admin panel entry point
    notifications.js            #   Notification bell (all views)
    application.js              #   Nav visibility control
    audit_trail.js              #   Audit dashboard helpers
    whitelist_manager.css       #   Styles (dark/light theme)
    modules/                    #   AMD modules — dependency layers above
  default/                      # Splunk configuration
    app.conf                    #   App metadata + build number
    restmap.conf                #   REST endpoint mapping
    indexes.conf                #   wl_audit index definition
    authorize.conf              #   RBAC roles
    savedsearches.conf          #   Scheduled searches
    collections.conf            #   KV store collections
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
