# Phase 5: Frontend Architecture — Research

**Researched:** 2026-04-02
**Domain:** Frontend modularization with AMD modules, centralized state management, and shared REST helpers
**Confidence:** HIGH

## Summary

Phase 5 extracts the monolithic whitelist_manager.js (6,786 lines) into ~10-11 AMD modules with a centralized state manager (`wl_state.js`), shared REST helpers (`wl_rest.js`), and UI utilities module (`wl_ui.js`). This is a structural refactor with zero functional change — all features remain identical. The phase replicates the wave-based extraction pattern proven successful in Phase 4's backend modularization.

Key research findings:
- Splunk 9.3.1 ships with RequireJS (AMD) and jQuery 1.11 built-in, no external build tools needed
- AMD `define()` and `require()` are the standard patterns in Splunk apps; jQuery custom events are the preferred cross-module communication mechanism
- State manager should use getter/setter with event-driven subscriptions (already captured in CONTEXT.md decisions)
- QUnit is lightweight and suitable for frontend testing in the Splunk ecosystem; no special setup required beyond vendoring the library

**Primary recommendation:** Follow the wave-based extraction pattern from Phase 4. Build foundation modules first (state, REST, constants), test them thoroughly, then extract feature modules in dependency order. Use jQuery event delegation for inter-module communication and state events for reactive updates.

## User Constraints (from CONTEXT.md)

### Locked Decisions

#### State Management (wl_state.js)
- Getter/setter + events: `State.get(key)`, `State.set(key, val)` — setters fire jQuery custom events (`state:keyName`) so listeners react automatically
- Central registry: All shared state keys registered in `wl_state.js` with defaults and validators. Single source of truth for what shared state exists
- Throw on unknown key: `State.get('typo')` throws `TypeError`. All valid keys must be registered via internal `_register()`. Fail-fast, consistent with backend convention
- Full validation: `State.set()` enforces type/invariant validators per key. Validation failure throws `TypeError` — fail-fast, never silently accept bad state
- Cross-module state only: Only state accessed by 2+ modules goes in `wl_state.js`. Module-internal state (dragState, resizeState, msgTimer, currentPage, searchQuery) stays local to its module
- `State.reset()` method: Single call clears all shared state to registered defaults. Fires `'state:reset'` event so modules clear local state too. Called on CSV switch
- `State.batch()` method: Applies multiple key updates atomically, fires events only after all keys are set. Prevents intermediate renders when loading CSV data
- `State.isDirty()` computed property: Compares `currentRows` vs `originalRows`. Auto-fires `'state:dirty'` event when dirty status changes (on any currentRows/originalRows mutation). Save button subscribes once
- No event namespacing: Flat events only — `State.on('currentRows', fn)`, `State.on('reset', fn)`. No wildcard or group subscriptions
- Undo stays module-local: `undoState` and `undoTimer` stay in `wl_table.js`. Table handles snapshot/restore internally, only calls `State.set('currentRows', restoredRows)` on undo
- Debug API: Expose `window.__wlState` (behind `window.__wlDebug` flag) with `get()` and `dump()` for console debugging during development

#### Module Boundaries
- Strict layer dependency: Foundation (wl_constants, wl_state, wl_rest, wl_ui) can't depend on feature modules. Feature modules depend on foundation but NEVER on each other. Cross-feature communication goes through State events or `wl:*` custom events
- Return object API: Each module returns `{init, publicFn1, publicFn2}` via AMD `define()`. Clean contracts, no global namespace pollution
- Each module binds own DOM events: No centralized `wl_events.js`. Table binds table events, search binds search events, etc. Events co-located with handlers
- Flexible module count: Don't force 12 modules. Extract what makes sense. `wl_events.js` eliminated (absorbed). `wl_theme.js` absorbed into `wl_ui.js`. Actual count ~10-11
- Straddling functions → orchestrator: Cross-module workflows (save, load CSV, revert) stay in entry point as thin orchestrators that call module APIs in sequence. No business logic in orchestrator
- wl_csv_io.js is single module: Both import (parser, validator, preview) and export in one module (~300 lines). Not worth splitting
- wl_table.js accepts large size: ~1500-2000 lines is acceptable. Table rendering, cell editing, pagination, column resize, drag-drop, date picker, undo bar, row selection, textarea char counter — all tightly coupled to table DOM. Well-structured with clear internal sections
- Pagination in wl_table.js: `currentPage`, `ROWS_PER_PAGE`, page navigation are module-local state. Only used by table
- Column resize + drag-drop in wl_table.js: `resizeState`, `dragState`, `colWidths` are table-specific DOM interactions
- Date picker in wl_table.js: Activated by clicking Expires column cell. Table-specific UI flow
- formatDailyLimitMsg in wl_approval_ui.js: Daily limit message formatting is part of approval gate flow domain
- Theme toggle in wl_ui.js: Dark/light theme detection and toggle (~30 lines) grouped with other UI utilities
- Textarea maxlength counter in wl_table.js: Cell editing DOM interaction, co-located with other cell editing logic

#### Module Communication
- State events + entry point wiring: Modules emit intent via `wl:*` custom events on `$(document)`. Entry point listens and orchestrates cross-module flows. Example: `wl_table` fires `'wl:removeRequested'`, entry point catches it and calls `WlModals.showRemoveDialog()`
- `wl:` prefix for custom events: All custom inter-module events use `'wl:actionName'` format. State events use `'state:keyName'`. Clear separation from jQuery/Splunk/native DOM events
- Centralized error handler in wl_rest.js: Default `.fail()` handler fires `'wl:restError'` event. Entry point listens and shows error via `WlUI.showMsg()`. Modules can override per-call `.fail()` for special cases (e.g., 409 conflict handling)
- notifications.js → AMD module: Rewritten with `define()`, imports `wl_rest.js`. Replaces `window.__wlNotifCallbacks` with `'wl:notificationsUpdated'` event on document
- Ordered init, fail-fast: Entry point calls `module.init()` in dependency order (state → rest → ui → features). Any init throw catches to `showFatalError()`. No partial initialization
- showMsg/messages → wl_ui.js: Dedicated utility module for UI feedback: `showMsg`, `showFatalError`. Listens to `'wl:showMsg'` events. Any module can trigger messages without importing wl_ui

#### Migration Strategy
- Wave-based extraction: 4 waves matching Phase 4 backend pattern:
  - Wave 1: Foundation — `wl_constants.js`, `wl_state.js`, `wl_rest.js`, `wl_ui.js`
  - Wave 2: Independent features — `wl_search.js`, `wl_presence.js`, `wl_csv_io.js`
  - Wave 3: Coupled features — `wl_table.js`, `wl_modals.js`, `wl_versions.js`, `wl_approval_ui.js`
  - Wave 4: Orchestrator cleanup — slim entry point to ~100 lines, wire all events
- Keep inline until extracted: After each wave, entry point still contains unextracted code. Each wave moves code out and shrinks it. Always have working code
- One commit per wave: 4 commits for 4 waves. Each commit is a working app. Git revert is the rollback strategy
- Manual smoke + QUnit tests: After each wave: (1) deploy to Docker, (2) manual smoke test of critical paths, (3) QUnit tests for state manager and module APIs
- QUnit in tests/qunit/ + test dashboard: QUnit test files in `tests/qunit/test_*.js`. Hidden Splunk dashboard (`test_runner.xml`) loads QUnit + tests. Phase 5 scope: ~4 test files, ~50 assertions. Full E2E deferred to Phase 7
- QUnit bundled in app: Include QUnit library in app (vendored). Excluded from production package
- Flat modules/ directory: All modules in `appserver/static/modules/`. No subfolders needed for ~10 files
- No XML dashboard changes: AMD modules loaded via `require()`/`define()` inside entry point. Splunk's RequireJS handles discovery
- RequireJS paths → Claude's discretion (relative vs require.config)
- Deploy modules/ via wildcard: Copy entire `modules/` directory to container. Prevents version mismatch
- Build number bump only for caching: Continue existing pattern — bump app.conf build + clear i18n cache + restart. No per-file versioning
- Git revert + redeploy as rollback: Same as Phase 4. No feature flags or dual-mode fallback

#### Safety Enforcement
- `refreshTable()` auto-calls `syncInputs()`: Structural enforcement of the MEMORY.md lesson. syncInputs() is always the first line of refreshTable(). No caller can forget. Double-sync is idempotent

### Claude's Discretion
- AMD path configuration (relative imports vs require.config)
- Event bus implementation (`$(document)` vs dedicated `$({})` emitter)
- Detection rule dropdown module placement (entry point vs dedicated module)
- Admin role detection placement (entry point init vs REST module startup)
- Conflict handling placement (orchestrator vs wl_rest status hooks)
- QUnit library sourcing (vendored location)
- Deploy tool updates (MCP server file list vs wildcard-only)
- Internal section organization within large modules (wl_table.js)
- Exact module count if extraction reveals better boundaries

### Deferred Ideas (OUT OF SCOPE)
- control_panel.js modularization — Phase 6
- Browser E2E tests — Phase 7
- Performance profiling of AMD module loading — Phase 7/8 if needed
- Read/write lock semantics for state (concurrent tab scenarios) — not needed for current use case
- State persistence across page navigations (localStorage) — not needed, each page load is a fresh session
- `wl_events.js` as centralized event registry — eliminated, each module binds own events
- `wl_theme.js` as standalone — absorbed into `wl_ui.js`
- Pagination as standalone `wl_pagination.js` — absorbed into `wl_table.js`

---

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| FMOD-01 | whitelist_manager.js rewritten as thin AMD entry point (~100 lines) loading feature modules | AMD module pattern docs, entry point orchestration pattern, thin orchestrator principle |
| FMOD-02 | wl_constants.js extracts all selectors, config values, and regex patterns | Splunk convention for centralized constants, ease of testing and reuse across modules |
| FMOD-03 | wl_rest.js provides shared REST helpers (restGet, restPost) used by all JS files | REST helper pattern from Phase 4 backend, Splunk's Splunk.util.make_url() usage, HTTP status code handling |
| FMOD-04 | wl_state.js implements singleton state manager for all shared application state | AMD singleton pattern, jQuery custom events, event-driven state mutations |
| FMOD-05 | Feature modules extracted: wl_table.js, wl_search.js, wl_modals.js, wl_versions.js, wl_approval_ui.js, wl_csv_io.js, wl_presence.js | Module boundary decisions, separation of concerns, clear public APIs |
| FMOD-08 | notifications.js refactored to use shared wl_rest.js instead of duplicated helpers | REST helper consolidation, notifications module conversion to AMD, event-based communication |
| TEST-05 | Browser E2E tests for key workflows (load CSV, save, approve, revert) | QUnit framework, Splunk dashboard test runners, state manager testing, module initialization testing |

---

## Standard Stack

### Core Frontend Stack (Confirmed via Splunk 9.3.1)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| jQuery | 1.11 (bundled) | DOM manipulation, event delegation, AJAX | Bundled with Splunk; all Splunk JS apps use it. No npm install needed. |
| Underscore.js | 1.8+ (bundled) | Utility functions (escape, template) | Bundled with Splunk; used for HTML escaping to prevent XSS. |
| RequireJS (AMD) | 2.3+ (bundled) | Module loader, dependency management | Bundled with Splunk's MVC framework; all custom JS files use `require()` and `define()` |
| Splunk MVC | 9.3.1 (bundled) | UI components, utilities | `splunkjs/mvc/utils` for `Splunk.util.make_url()` and REST integration |

### Additional Framework Libraries (Phase 5 Scope)

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| QUnit | 2.19+ (vendor) | Unit testing framework | Phase 5: Test state manager and module APIs in tests/qunit/. Can be bundled without affecting production (excluded from app package) |

### Why No npm / Build Tools

- **AppInspect Requirement**: Splunk's official app compliance tool (AppInspect) rejects bundled/minified output. All JS must be source-readable.
- **Splunk's AMD Native**: RequireJS is built-in; no Webpack, Vite, or esbuild needed.
- **jQuery already loaded**: Bundled with Splunk Web; importing it again would be redundant.
- **Direct file delivery**: Copy JS files to `appserver/static/modules/` and Splunk's RequireJS handles discovery and loading.

### Installation Verification

RequireJS, jQuery, Underscore are all pre-loaded by Splunk when a dashboard loads. No `npm install` step.

For QUnit (testing only, excluded from production package):
- Source: [QUnit CDN](https://qunitjs.com/) or local copy (vendor into repo)
- Installation: Copy `qunit.js` and `qunit.css` to `tests/qunit/` directory
- No npm dependency tracking needed; files are committed directly

---

## Architecture Patterns

### Recommended Project Structure

```
appserver/static/
├── whitelist_manager.js        # Entry point (~100 lines) — thin orchestrator
├── notifications.js            # AMD module rewrite (325 lines → ~300)
├── whitelist_manager.css       # Unchanged
└── modules/
    ├── wl_constants.js         # Constants/selectors/regex/config
    ├── wl_state.js             # Singleton state manager
    ├── wl_rest.js              # Shared REST helpers
    ├── wl_ui.js                # UI utilities (showMsg, theme toggle)
    ├── wl_table.js             # Table rendering, cell editing, pagination, undo (~1500-2000 lines)
    ├── wl_search.js            # Search bar, filtering, highlighting
    ├── wl_modals.js            # Remove/add/edit dialogs, conflict dialogs
    ├── wl_versions.js          # Version dropdown, revert modal
    ├── wl_csv_io.js            # CSV import/export, parser, validator, preview
    ├── wl_approval_ui.js       # Approval pending display, daily limit messages
    └── wl_presence.js          # User presence tracking (typing indicators, conflicts)

tests/
├── qunit/
│   ├── test_state_manager.js   # ~20 assertions: state registration, get/set, events, validators, dirty check
│   ├── test_module_loading.js  # ~15 assertions: AMD require order, init sequences, module APIs
│   ├── test_rest_helpers.js    # ~10 assertions: URL building, AJAX wrapping, error handling
│   └── test_integration.js     # ~5 assertions: cross-module workflows, event firing
├── qunit.js                    # QUnit library (vendored)
├── qunit.css                   # QUnit stylesheet
└── qunit_runner.html           # Standalone test runner (for local development)

default/
└── data/ui/views/
    ├── whitelist_manager.xml   # Unchanged (loads entry point JS)
    ├── audit.xml               # Unchanged
    ├── default.xml             # Unchanged (nav)
    └── test_runner.xml         # NEW: QUnit dashboard for Docker testing
```

### Pattern 1: AMD Module Definition

**What:** Each feature module is defined with `define()`, declares dependencies, returns public API object with `init()` and feature functions.

**When to use:** Every module in `modules/` directory. Entry point uses `require()` to load them in dependency order.

**Example:**

```javascript
// appserver/static/modules/wl_table.js
// Source: AMD pattern standard in Splunk apps (splunkjs/mvc modules use this)

define([
    "jquery",
    "underscore",
    "modules/wl_constants",
    "modules/wl_state",
    "modules/wl_rest",
    "modules/wl_ui"
], function ($, _, Constants, State, Rest, UI) {
    "use strict";

    // ── Module-local state (private) ──
    var currentPage = 0;
    var ROWS_PER_PAGE = 10;
    var resizeState = null;   // { $th, header, startX, startWidth } during column resize
    var dragState = null;     // { type: "row"|"column", ... } during drag

    // ── Public API ──
    var publicAPI = {
        init: function () {
            // Initialize DOM, bind events
            renderTable(State.get('currentRows'), State.get('currentHeaders'));
            bindTableEvents();

            // Subscribe to state changes
            State.on('currentRows', function () {
                refreshTable();
            });

            State.on('reset', function () {
                // Clear local state on CSV switch
                currentPage = 0;
                resizeState = null;
                dragState = null;
            });

            return true;  // init success
        },

        renderTable: renderTable,
        refreshTable: refreshTable,
        syncInputs: syncInputs,
        getSelectedRows: getSelectedRows
    };

    // ── Internal functions ──
    function renderTable(rows, headers) {
        var $table = $("#wl-csv-table");
        // ... rendering logic
    }

    function refreshTable() {
        syncInputs();  // ALWAYS first (enforce lesson from MEMORY.md)
        var filtered = getFilteredRows();
        renderTable(filtered, State.get('currentHeaders'));
    }

    function syncInputs() {
        // Capture user-typed data from DOM inputs into currentRows
        var rows = State.get('currentRows');
        $(".wl-cell-edit").each(function (idx) {
            rows[idx].data = $(this).val();
        });
        State.set('currentRows', rows);
    }

    function bindTableEvents() {
        $(document).on("click", ".wl-row-remove", function (e) {
            var idx = $(this).data("row-idx");
            $(document).trigger("wl:removeRequested", [idx]);
        });
        // ... more events
    }

    // ... more internal functions

    return publicAPI;
});
```

### Pattern 2: Centralized State Manager with Events

**What:** Single `wl_state.js` module provides `State.get()`, `State.set()`, `State.on()`, and fires jQuery custom events when keys change. All modules subscribe to state changes.

**When to use:** For any state accessed by 2+ modules (currentRows, originalRows, selectedRule, selectedCsv, isAdmin, versionsList, pendingApprovals, csvLocked, etc.).

**Example:**

```javascript
// appserver/static/modules/wl_state.js
// Source: Singleton pattern + jQuery custom events (standard in jQuery-based apps)

define([
    "jquery",
    "underscore"
], function ($, _) {
    "use strict";

    var _state = {};
    var _defaults = {};
    var _validators = {};
    var _eventBus = $({});

    var State = {
        register: function (key, defaultValue, validatorFn) {
            // Called during State setup to register all valid keys
            _defaults[key] = defaultValue;
            _validators[key] = validatorFn || function () { return true; };
            _state[key] = defaultValue;
        },

        get: function (key) {
            if (!(key in _defaults)) {
                throw new TypeError("Unknown state key: " + key);
            }
            return _state[key];
        },

        set: function (key, val) {
            if (!(key in _defaults)) {
                throw new TypeError("Unknown state key: " + key);
            }
            if (!_validators[key](val)) {
                throw new TypeError("Validation failed for state key: " + key);
            }
            _state[key] = val;

            // Fire event: both "state:keyName" and "state:changed"
            _eventBus.trigger("state:" + key, [val]);
            _eventBus.trigger("state:changed", [key, val]);

            // Auto-fire "state:dirty" when currentRows or originalRows change
            if ((key === "currentRows" || key === "originalRows") &&
                !_.isEqual(_state.currentRows, _state.originalRows)) {
                _eventBus.trigger("state:dirty", [true]);
            }
        },

        batch: function (updates) {
            // Apply multiple updates atomically, fire events only after
            var keys = Object.keys(updates);
            keys.forEach(function (key) {
                if (!(key in _defaults)) {
                    throw new TypeError("Unknown state key: " + key);
                }
                if (!_validators[key](updates[key])) {
                    throw new TypeError("Validation failed for state key: " + key);
                }
                _state[key] = updates[key];
            });
            // Fire events for each key
            keys.forEach(function (key) {
                _eventBus.trigger("state:" + key, [_state[key]]);
            });
        },

        on: function (event, callback) {
            // Subscribe to "state:keyName" or "state:dirty", etc.
            _eventBus.on("state:" + event, callback);
        },

        isDirty: function () {
            return !_.isEqual(_state.currentRows, _state.originalRows);
        },

        reset: function () {
            // Clear all state to defaults
            _.keys(_defaults).forEach(function (key) {
                _state[key] = _defaults[key];
            });
            _eventBus.trigger("state:reset");
        },

        _debug: {
            get: function () { return _.clone(_state); },
            dump: function () { console.table(_state); }
        }
    };

    // Register all shared state keys with validators
    State.register('currentRows', [], function (val) { return _.isArray(val); });
    State.register('originalRows', [], function (val) { return _.isArray(val); });
    State.register('currentHeaders', [], function (val) { return _.isArray(val); });
    State.register('originalHeaders', [], function (val) { return _.isArray(val); });
    State.register('selectedRule', '', function (val) { return _.isString(val); });
    State.register('selectedCsv', '', function (val) { return _.isString(val); });
    State.register('selectedApp', '', function (val) { return _.isString(val); });
    State.register('isAdmin', false, function (val) { return _.isBoolean(val); });
    State.register('versionsList', [], function (val) { return _.isArray(val); });
    State.register('pendingApprovals', [], function (val) { return _.isArray(val); });
    State.register('csvLocked', false, function (val) { return _.isBoolean(val); });
    State.register('loadedMtime', null, function (val) { return val === null || _.isNumber(val); });

    // Debug API
    if (window.__wlDebug) {
        window.__wlState = State._debug;
    }

    return State;
});
```

### Pattern 3: Shared REST Helpers with Centralized Error Handling

**What:** Single `wl_rest.js` module exports `restGet()` and `restPost()` that all modules use. Default error handler fires `'wl:restError'` event so entry point can show a unified error message. Modules can override `.fail()` for special cases (409 conflict handling).

**When to use:** All REST calls. Never duplicate `$.ajax()` or `restGet/restPost` logic.

**Example:**

```javascript
// appserver/static/modules/wl_rest.js
// Source: REST helper pattern from Phase 4 backend (restGet/restPost wrapper pattern)

define([
    "jquery",
    "underscore",
    "splunkjs/mvc/utils"
], function ($, _, utils) {
    "use strict";

    var BASE_URL = Splunk.util.make_url(
        "/splunkd/__raw/services/custom/wl_manager");

    var Rest = {
        get: function (params, options) {
            params = params || {};
            params.output_mode = "json";
            options = options || {};

            var promise = $.ajax({
                url: BASE_URL,
                type: "GET",
                data: params,
                dataType: "json"
            });

            // Default error handler fires event; module can override
            if (!options.suppressDefaultErrorHandler) {
                promise.fail(function (xhr) {
                    var msg = "REST error: " + (xhr.status || "unknown");
                    $(document).trigger("wl:restError", [msg, xhr]);
                });
            }

            return promise;
        },

        post: function (payload, options) {
            options = options || {};

            var promise = $.ajax({
                url: BASE_URL + "?output_mode=json",
                type: "POST",
                contentType: "application/json",
                data: JSON.stringify(payload),
                dataType: "json"
            });

            if (!options.suppressDefaultErrorHandler) {
                promise.fail(function (xhr) {
                    // Special case: 409 Conflict (external change detected)
                    if (xhr.status === 409) {
                        $(document).trigger("wl:externalChange", [xhr.responseJSON]);
                        return;
                    }
                    var msg = "REST error: " + (xhr.status || "unknown");
                    $(document).trigger("wl:restError", [msg, xhr]);
                });
            }

            return promise;
        }
    };

    return Rest;
});
```

### Pattern 4: Entry Point Thin Orchestrator

**What:** The entry point (whitelist_manager.js) initializes modules in dependency order, wires up cross-module event handlers, and coordinates workflows (save, load CSV, revert). No business logic — just function calls in sequence.

**When to use:** The main entry point only. Never put business logic here; always delegate to modules.

**Example:**

```javascript
// appserver/static/whitelist_manager.js
// Source: Thin orchestrator pattern (replaces 6,786-line monolith)

require([
    "jquery",
    "underscore",
    "splunkjs/mvc",
    "splunkjs/mvc/utils",
    "splunkjs/mvc/simplexml/ready!",
    "modules/wl_constants",
    "modules/wl_state",
    "modules/wl_rest",
    "modules/wl_ui",
    "modules/wl_table",
    "modules/wl_search",
    "modules/wl_modals",
    "modules/wl_versions",
    "modules/wl_csv_io",
    "modules/wl_approval_ui",
    "modules/wl_presence"
], function ($, _, mvc, utils, ready,
    Constants, State, Rest, UI,
    Table, Search, Modals, Versions, CsvIO, ApprovalUI, Presence) {
    "use strict";

    // ── Init all modules in dependency order ──
    try {
        State.init && State.init();     // State must be first
        Rest.init && Rest.init();       // REST second
        UI.init && UI.init();           // UI third
        Table.init();                   // Features fourth
        Search.init();
        Modals.init();
        Versions.init();
        CsvIO.init();
        ApprovalUI.init();
        Presence.init();
    } catch (err) {
        UI.showFatalError("Initialization failed: " + err.message);
        return;
    }

    // ── URL parameter handling (orchestrator responsibility) ──
    var urlRule = getUrlParam('rule');
    var urlCsv = getUrlParam('csv');
    if (urlRule) {
        selectRule(urlRule, urlCsv);
    }

    // ── Cross-module event wiring ──

    // Table wants to remove a row → show modal
    $(document).on("wl:removeRequested", function (e, rowIdx) {
        Modals.showRemoveDialog(rowIdx);
    });

    // Modal confirmed → save CSV
    $(document).on("wl:saveRequested", function (e, rowData, reason) {
        doSave(rowData, reason);
    });

    // REST error → show message (already handled by wl_rest default, but entry point can extend)
    $(document).on("wl:restError", function (e, msg) {
        UI.showMsg(msg, "error");
    });

    // External change detected → show modal
    $(document).on("wl:externalChange", function () {
        Modals.showExternalChangeModal();
    });

    // ── Workflow orchestrators (no logic, just delegation) ──

    function doSave(rowData, reason) {
        Rest.post({
            action: "save_csv",
            csv_file: State.get('selectedCsv'),
            rows: rowData,
            comment: reason
        })
        .done(function (response) {
            State.set('originalRows', response.rows);  // Update original after save
            Table.refreshTable();
            UI.showMsg("Saved successfully", "success");
        });
    }

    function selectRule(rule, preferCsv) {
        Rest.get({ action: "get_rules_mapping" })
        .done(function (response) {
            State.set('allRules', response.rules);
            // Delegate rest to Search module
            Search.filterRules(rule);
            Search.selectRule(rule, preferCsv);
        });
    }

    // ── Polling for external changes ──
    var changeCheckTimer = setInterval(function () {
        checkForExternalChanges();
    }, 10000);

    function checkForExternalChanges() {
        // Orchestrator calls module function
        Rest.get({
            action: "get_csv",
            csv_file: State.get('selectedCsv'),
            _mtime: State.get('loadedMtime')
        }, { suppressDefaultErrorHandler: true })
        .done(function (response) {
            if (response.mtime !== State.get('loadedMtime')) {
                $(document).trigger("wl:externalChange");
            }
        });
    }
});

function getUrlParam(name) {
    var params = new URLSearchParams(window.location.search);
    return params.get(name) || "";
}
```

### Anti-Patterns to Avoid

- **Global state mutations outside State.set()**: Never do `currentRows = [...]` directly. Always call `State.set('currentRows', [...])` so subscribers are notified.
- **Direct cross-module function calls**: Never call `Table.renderTable()` from Search module. Always emit event (`$(document).trigger('wl:tableNeedsUpdate')`) and let orchestrator coordinate.
- **Forgetting to call syncInputs() before refreshTable()**: This is a structural requirement enforced by making syncInputs() the first line of refreshTable(). Double-sync is idempotent.
- **Module initialization without error handling**: Entry point must wrap all init calls in try-catch and call UI.showFatalError() on any throw.
- **Mixing module-private state with shared state**: `currentPage` (table-specific), `resizeState` (table-specific), `searchQuery` (search-specific) stay in their modules. Only truly shared state (currentRows, selectedRule, isAdmin, etc.) goes in State.
- **Event namespacing confusion**: Don't use `'state:*'` or `'wl:*'` carelessly. Stick to pattern: state events are `'state:keyName'` (e.g., `'state:currentRows'`), inter-module events are `'wl:actionName'` (e.g., `'wl:removeRequested'`).

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| State management across modules | Custom state object with getters/setters | wl_state.js singleton with validators and event emissions | Inconsistent updates lead to stale UI, cache invalidation bugs, and hard-to-debug state drift |
| REST request boilerplate | Inline $.ajax() calls repeated 6 times | wl_rest.js helpers (restGet, restPost) with centralized error handling | Duplicated $.ajax boilerplate causes bugs when base URL changes; centralized error handling enables uniform error UI |
| Module communication | Direct function calls between modules or shared global callbacks | jQuery custom events (`wl:` prefix) + state events (`state:` prefix) | Direct calls create tight coupling; changes in one module break others. Events are loosely coupled and testable. |
| CSV import validation | Re-implement RFC 4180 CSV parser | wl_csv_io.js with tested parseCSV, validateImportedCSV, renderImportPreview | CSV parsing has edge cases (quoted fields, embedded commas, BOM, line ending variations). Rewriting risks missing these. |
| Approval workflow orchestration | Inline approval checks in multiple handlers | Centralized wl_approval_ui.js with formatDailyLimitMsg, showApprovalReason | Duplicate approval checks → inconsistent behavior and hard-to-test conditional logic. Centralization enables consistent approval flow. |
| Date picker interaction | Custom date input handling | Built-in into wl_table.js module (co-located with Expires column cell editing) | Date input has UX complexity (timezone handling, presets, validation). Module-local state is simpler than cross-module coordination. |
| Theme detection | DOM-based guesses (brightness calc on load) | wl_ui.js ensureDarkTheme() with cached `wl-dark` class | Theme detection needs to run early before page renders. Centralizing in UI module ensures consistent theme application. |

**Key insight:** The biggest refactor win is eliminating duplicate code (REST helpers, state mutations, approval checks). Centralizing these in foundation modules prevents bugs and makes the system testable.

---

## Common Pitfalls

### Pitfall 1: Module Initialization Order Bugs

**What goes wrong:** Modules load in random order if dependencies aren't declared in AMD `require()` statement. Table tries to call `State.set()` before State is initialized → `Cannot read property 'set' of undefined`.

**Why it happens:** AMD loader parallelizes module loading unless dependency order is explicitly declared. If entry point says `require([..., wl_table, wl_state])` instead of `require([..., wl_state, wl_table])`, State might not be loaded yet.

**How to avoid:** 
1. Always declare dependencies in AMD `define()` and `require()` statements.
2. Entry point must initialize modules in dependency order: state → rest → ui → features.
3. Wrap all init calls in try-catch with UI.showFatalError() fallback.
4. Write one unit test that verifies module init order (call modules out of order, expect errors).

**Warning signs:** "Cannot read property 'set' of undefined" or "wl_state is not defined" in console.

### Pitfall 2: State Updates Not Triggering Subscribers

**What goes wrong:** UI doesn't update after `State.set('currentRows', newRows)`. Search bar filtering applies but table doesn't re-render. Reason: Subscriber never fires because event was spelled wrong or subscriber wasn't registered.

**Why it happens:** jQuery custom events require exact spelling. `State.on('currentRows')` vs `state:currentRows` mismatch → no event fires. Or subscriber registered too late (after state changed).

**How to avoid:**
1. Use constants for event names: `var EVENTS = { STATE_ROWS_CHANGED: 'state:currentRows' };`
2. Register all state subscribers in module.init() immediately, not in event handlers.
3. Write unit test: `State.set('currentRows', [...]); expect(subscriberCalled).toBe(true);`

**Warning signs:** UI doesn't update after state change; table shows stale data; "stale closure" or "state changed but no re-render".

### Pitfall 3: syncInputs() Forgotten Before refreshTable()

**What goes wrong:** User types data into a cell, clicks "Add Row", then their typed data disappears. Reason: refreshTable() called without syncInputs() first.

**Why it happens:** These are two separate functions in monolithic code. When extracted to modules, easy to forget the order.

**How to avoid:** 
1. Enforce structurally: Make syncInputs() the first line of refreshTable(). Always. No exceptions.
2. Code comment: `// NOTE: syncInputs() MUST be first line. See MEMORY.md lesson on data loss.`
3. Write unit test: Mock DOM with typed data, call refreshTable(), assert typed data captured into state.

**Warning signs:** Data disappears after row operations; user's typed text is lost; "I typed something and clicked Add Row, now it's gone".

### Pitfall 4: REST Error Handler Suppression Confusion

**What goes wrong:** Module calls `Rest.post()` with `suppressDefaultErrorHandler: true`, handles the error, but then entry point shows a SECOND error message. Two error messages displayed.

**Why it happens:** Default error handler is always active unless explicitly suppressed. Module forgets to pass the suppress flag.

**How to avoid:**
1. Document the option clearly: "Pass `{ suppressDefaultErrorHandler: true }` only if module has its own `.fail()` handler."
2. Code example in wl_rest.js:
   ```javascript
   // Special case: 409 Conflict — module handles it
   Rest.post(data, { suppressDefaultErrorHandler: true })
   .fail(function (xhr) {
       if (xhr.status === 409) { /* handle */ }
   });
   ```
3. Default behavior is to show error; only suppress if you handle it.

**Warning signs:** Duplicate error messages; errors shown twice; user confusion.

### Pitfall 5: Module-Local State Leaks Into Shared State

**What goes wrong:** `dragState` (only used by table column resizing) is accidentally put into wl_state.js. Now every module has a reference to it. Table modifies it → all modules see the change. If Search or Modals module reads `dragState` expecting it to be clean, they get stale drag state from a previous drag operation.

**Why it happens:** Easy to "just add it to State" to avoid thread-local or closure state. Unclear boundary between shared and private state.

**How to avoid:**
1. Decision rule: Only put state in wl_state.js if 2+ modules access it.
2. Code comment: `// dragState is TABLE-ONLY. Not shared. Stays in wl_table.js.`
3. Code review: Check that module.init() sets up its own local state variables, not State.register() calls for private state.
4. Test: Each module should have ≥1 unit test verifying its local state is isolated (e.g., page navigation doesn't leak into Search module).

**Warning signs:** Modules behaving unexpectedly after unrelated operations; "state pollution" or "stale state from other modules".

### Pitfall 6: Event Bus Choice Regret

**What goes wrong:** Entry point uses `$(document)` for event bus, but later discovery: different windows/iframes can't communicate because they don't share the same document object.

**Why it happens:** `$(document)` is convenient but DOM-dependent. Future iframe-based features would fail.

**How to avoid:**
1. Decision: $(document) is the standard in jQuery-based Splunk apps (no iframes in current scope).
2. If future iframe support is needed, switch to `var eventBus = $({})` singleton and pass it to all modules.
3. Code comment: `// Event bus is $(document). If iframe support needed, switch to shared $({}) emitter.`

**Warning signs:** Events don't fire in iframes; need to refactor event bus across all modules.

---

## Code Examples

### Example 1: State Manager Registration and Dirty Checking

Verified from CONTEXT.md decisions and jQuery custom event patterns.

```javascript
// appserver/static/modules/wl_state.js

// Setup (during module definition)
State.register('currentRows', [], function (val) { return _.isArray(val); });
State.register('originalRows', [], function (val) { return _.isArray(val); });

// Usage in table module
State.set('currentRows', newRows);  // Fires 'state:currentRows' and 'state:dirty'

// Subscription in entry point
State.on('dirty', function () {
    $(".wl-save-btn").prop('disabled', !State.isDirty());
});

// isDirty() implementation (computed property)
State.isDirty = function () {
    return !_.isEqual(State.get('currentRows'), State.get('originalRows'));
};
```

### Example 2: Shared REST Helpers with Error Handling

Verified from Phase 4 backend pattern and Splunk.util.make_url() usage.

```javascript
// appserver/static/modules/wl_rest.js

Rest.post({ action: "save_csv", rows: [...] })
.done(function (response) {
    UI.showMsg("Saved", "success");
})
.fail(function (xhr) {
    if (xhr.status === 409) {
        $(document).trigger("wl:externalChange");
    } else {
        UI.showMsg("Error: " + xhr.status, "error");
    }
});

// Or, module can suppress default error and handle specially:
Rest.post(data, { suppressDefaultErrorHandler: true })
.done(function (response) { /* ... */ })
.fail(function (xhr) {
    if (xhr.status === 409) {
        // Custom 409 handling
    } else {
        // Fall back to default handler
        $(document).trigger("wl:restError");
    }
});
```

### Example 3: Module Communication via Events

Verified from jQuery event delegation patterns in current codebase.

```javascript
// In wl_table.js: Table emits intent
$(document).on("click", ".wl-row-remove", function () {
    var idx = $(this).data("row-idx");
    $(document).trigger("wl:removeRequested", [idx]);
});

// In whitelist_manager.js (entry point): Orchestrator listens and coordinates
$(document).on("wl:removeRequested", function (e, idx) {
    Modals.showRemoveDialog(idx);
});

// In wl_modals.js: Modal confirms and triggers save
$(document).on("click", ".wl-remove-confirm", function () {
    $(document).trigger("wl:saveRequested", [rowData, reason]);
});
```

### Example 4: QUnit Test for State Manager

Verified from QUnit patterns and state manager design.

```javascript
// tests/qunit/test_state_manager.js

QUnit.test("State registration and validation", function (assert) {
    var State = require("modules/wl_state");
    State.register('testKey', 'default', function (val) { return typeof val === 'string'; });
    
    State.set('testKey', 'newValue');
    assert.equal(State.get('testKey'), 'newValue', 'Value set and retrieved');
});

QUnit.test("State change fires event", function (assert) {
    var State = require("modules/wl_state");
    var eventFired = false;
    
    State.on('testKey', function () {
        eventFired = true;
    });
    
    State.set('testKey', 'changed');
    assert.equal(eventFired, true, 'Event fired on set');
});

QUnit.test("isDirty compares rows", function (assert) {
    var State = require("modules/wl_state");
    State.set('currentRows', [{id: 1}]);
    State.set('originalRows', [{id: 1}]);
    assert.equal(State.isDirty(), false, 'Equal rows → not dirty');
    
    State.set('currentRows', [{id: 1}, {id: 2}]);
    assert.equal(State.isDirty(), true, 'Different rows → dirty');
});

QUnit.test("Unknown key throws error", function (assert) {
    var State = require("modules/wl_state");
    assert.throws(
        function () { State.get('unknownKey'); },
        /Unknown state key/,
        'Getting unknown key throws'
    );
});
```

---

## State of the Art

| Aspect | Current (v2.0) | Phase 5 Target (v3.0) | Impact |
|--------|-----------------|----------------------|--------|
| Frontend file organization | Monolithic (6,786 lines) | Modular (10-11 modules, each ~300-2000 lines) | Easier to understand, test, and maintain each feature independently |
| State management | ~40 closure variables at top of IIFE | Centralized wl_state.js singleton with registered keys and validators | Prevents state corruption, enables debugging via window.__wlState, clear contracts |
| REST code | Duplicated restGet/restPost in whitelist_manager.js and notifications.js (2x code) | Shared wl_rest.js used by all modules (1x code) | Fixes bugs once, not 6 times; centralized error handling |
| Module communication | Global callbacks (window.__wlNotifCallbacks), direct function calls, silent failures | jQuery custom events (wl:*, state:*), event-driven subscriptions, explicit error propagation | Loose coupling enables independent testing; events are self-documenting |
| Testing capability | No frontend unit tests | ~50 QUnit assertions covering state manager, module APIs, initialization order | Confidence that refactoring doesn't break workflows; safe to refactor further |
| Build/deploy complexity | Bump build number, clear i18n cache, restart | Same (no build tools added) | Maintains AppInspect compliance; Splunk's AMD handles everything |

**Deprecated/changed:**
- Inline state closures → wl_state.js singleton (improves debuggability)
- window.__wlNotifCallbacks → wl:notificationsUpdated event (improves coupling)
- Duplicated REST helpers → wl_rest.js imports (improves maintenance)

---

## Open Questions

### 1. **AMD Path Configuration: Relative vs require.config()**

**What we know:** 
- Current code uses `require(["jquery", "splunkjs/mvc", ...])` pattern
- Splunk's RequireJS uses `splunkjs/` namespace for built-in modules
- Phase 5 modules are in `appserver/static/modules/`

**What's unclear:** Should new modules be required as:
- Relative paths: `require(["modules/wl_state", "modules/wl_rest", ...])`
- Absolute paths with require.config: `require(["wl_state", "wl_rest", ...])` (requires config)

**Recommendation:** Use relative paths (`modules/wl_state`) to match existing Splunk pattern. Explicit is better than implicit; paths are clear and don't need external config.

### 2. **QUnit Test Runner: Standalone vs Splunk Dashboard**

**What we know:**
- QUnit can run standalone in `tests/qunit_runner.html` in browser
- Can also embed in Splunk dashboard (`test_runner.xml`) for Docker testing
- Phase 5 scope is ~50 assertions, small enough for either approach

**What's unclear:** Which is primary test runner during Phase 5? Or both?

**Recommendation:** Provide both:
- **Development**: `tests/qunit_runner.html` for fast feedback (no Docker restart)
- **CI/verification**: `test_runner.xml` dashboard for automated Docker testing (via `/gsd:verify-work`)

### 3. **Admin Role Detection: Entry Point vs REST Module**

**What we know:**
- Current code detects admin in whitelist_manager.js and notifications.js separately
- Both use `Rest.post({action: "get_approval_queue"})` to test access

**What's unclear:** Where should admin detection happen?
- In entry point at startup, then store in State?
- In REST module, triggered on first approval-requiring action?

**Recommendation:** Entry point at startup:
```javascript
Rest.post({ action: "get_approval_queue" })
.done(function () { State.set('isAdmin', true); })
.fail(function () { State.set('isAdmin', false); });
```
Admin role is foundational state needed by multiple modules early.

### 4. **Event Bus: $(document) vs $({}) Singleton**

**What we know:**
- Current code uses `$(document)` for event delegation in CONTEXT.md
- `$(document)` is DOM-tied; works across modules in same window
- `$({})` is a dedicated event emitter, not tied to DOM

**What's unclear:** Which is standard in Splunk apps? Does Phase 5 need iframe support?

**Recommendation:** Use `$(document)` (matches current codebase and Splunk convention). If Phase 6/7 needs iframe support, switch to shared `$({})` singleton (small refactor, all events in one place).

---

## Validation Architecture

> Validation enabled via `.planning/config.json` → workflow.nyquist_validation = true (present, not false)

### Test Framework

| Property | Value |
|----------|-------|
| Framework | QUnit 2.19+ (vendor) |
| Config file | None (QUnit runs standalone or via Splunk dashboard) |
| Quick run command | `open tests/qunit_runner.html` (in browser) or manually reload `test_runner.xml` in Docker |
| Full suite command | Deploy to Docker, navigate to test_runner.xml dashboard, verify all assertions pass |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| FMOD-01 | Entry point loads 10+ modules, orchestrates workflows | integration | Manual: load whitelist_manager.xml, verify no console errors | ✅ whitelist_manager.xml |
| FMOD-02 | Constants module exports selectors, regex, config | unit | `tests/qunit/test_constants.js`: verify exports exist | ❌ Wave 0 |
| FMOD-03 | REST helpers build correct URLs, fire error events | unit | `tests/qunit/test_rest_helpers.js`: mock AJAX, verify calls, events | ❌ Wave 0 |
| FMOD-04 | State manager registers keys, enforces validators, fires events | unit | `tests/qunit/test_state_manager.js`: ~20 assertions on get/set/on/isDirty/batch | ❌ Wave 0 |
| FMOD-05 | Feature modules init correctly, expose public APIs | integration | `tests/qunit/test_module_loading.js`: require each module, call init, verify return object | ❌ Wave 0 |
| FMOD-08 | notifications.js refactored as AMD module, uses wl_rest.js | integration | Manual: open notifications.js, verify it uses `define()`, imports Rest module, triggers `wl:notificationsUpdated` event | ❌ Wave 0 |
| TEST-05 | QUnit tests verify state transitions, module interactions | unit/integration | Deploy tests/qunit/ to Docker, open test_runner.xml, verify 50+ assertions PASS | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** Manual smoke test (load whitelist_manager.xml in Docker, verify core workflows: load CSV, edit row, save)
- **Per wave merge:** Run QUnit test suite (50+ assertions), manual smoke test all critical paths
- **Phase gate:** Full QUnit suite PASS + manual smoke test before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `tests/qunit/test_state_manager.js` — ~20 assertions, covers State registration, get/set, validators, events, isDirty, batch, reset
- [ ] `tests/qunit/test_rest_helpers.js` — ~10 assertions, covers URL building, AJAX wrapping, error event firing
- [ ] `tests/qunit/test_module_loading.js` — ~15 assertions, covers AMD module loading order, init sequences, API contracts
- [ ] `tests/qunit/test_integration.js` — ~5 assertions, covers cross-module event workflows (remove requested → modal → save)
- [ ] `tests/qunit_runner.html` — Standalone QUnit test runner for local development
- [ ] `default/data/ui/views/test_runner.xml` — Splunk dashboard for automated Docker testing
- [ ] `appserver/static/modules/` directory — Will be populated during Phase 5 implementation

---

## Sources

### Primary (HIGH confidence)

- **Splunk 9.3.1 AMD/RequireJS**: Confirmed in docker-compose.yml (image: splunk/splunk:9.3.1). RequireJS is bundled; jQuery 1.11+ bundled with Splunk MVC.
- **Current codebase patterns**: whitelist_manager.js uses `require()` and `$(document).on()` event delegation; notifications.js demonstrates REST helper duplication. Patterns verified from actual code.
- **CONTEXT.md Phase 5 decisions**: User confirmed all architectural decisions (state manager, module boundaries, event prefixes, wave-based extraction, QUnit testing).
- **CLAUDE.md project MEMORY**: Documented lesson "Always syncInputs() before refreshTable()" and "Apply same fix to ALL parallel code paths" — enforced structurally in this research.

### Secondary (MEDIUM confidence)

- **Phase 4 wave-based backend extraction**: STATE.md documents successful 4-plan extraction pattern (constants → validation → RBAC/presence → core modules). Same pattern reused for Phase 5 frontend.
- **jQuery custom events + state management pattern**: Standard in jQuery-based Splunk apps (no official Splunk docs, but confirmed in working Splunk app code).

### Tertiary (LOW confidence)

- **QUnit testing in Splunk apps**: Light research on QUnit; common in web development but not specifically tested in Splunk ecosystem yet. User discretion on test framework confirmation (could substitute with other frameworks if needed).

---

## Metadata

**Confidence breakdown:**
- **Standard stack:** HIGH — Splunk 9.3.1 bundle confirmed, jQuery/AMD usage confirmed in codebase
- **Architecture patterns:** HIGH — AMD and event delegation patterns confirmed in current code; state manager pattern standard in jQuery apps
- **Module boundaries:** HIGH — CONTEXT.md user decisions locked; extraction plan mirrors Phase 4 backend success
- **Testing strategy:** MEDIUM — QUnit selected based on Phase 5 scope (50 assertions); full E2E deferred to Phase 7

**Research date:** 2026-04-02
**Valid until:** 2026-04-09 (7 days — JavaScript ecosystem moves fast, QUnit updates quarterly)

**Key assumptions:**
- Splunk 9.3.1 remains the target version (no major version jump during Phase 5)
- No additional npm packages will be added (AppInspect compliance constraint)
- jQuery event delegation remains viable for cross-module communication (no major architectural shifts)
