# Architecture Patterns: Modular Splunk App

**Project:** Whitelist Manager v3.0 (Full Rewrite)  
**Researched:** 2026-03-31  
**Focus:** Splitting monolithic REST handler and frontend into modules  

## Recommended Architecture

### Backend Modularity Pattern (Python)

**Structure:** Single REST handler entry point routes to focused domain modules. No shared state between modules except via explicit function parameters or file I/O.

```
bin/
  wl_handler.py           → REST entry point (200 lines) — routes actions to modules
  wl_constants.py         → Shared constants (magic numbers, config defaults)
  wl_validation.py        → Input sanitization (control char stripping, filename checks, cell limits)
  wl_rbac.py              → Role checking, permission enforcement
  wl_csv.py               → CSV read/write, diff computation, cell operations
  wl_versions.py          → Version snapshots, revert logic, manifest management
  wl_approval.py          → Approval queue CRUD, request processing, auto-cancellation
  wl_limits.py            → Daily limit tracking, per-user usage, resets
  wl_audit.py             → Structured event building, index posting, fallback logging
  wl_rules.py             → Detection rules registry (add/remove/list)
  wl_trash.py             → Soft-delete, restore, auto-purge with retention
  wl_presence.py          → In-memory user presence tracking, heartbeat logic
  wl_notifications.py     → Admin notification queue, toast delivery
```

**Import Pattern for Splunk `bin/` modules:**

```python
# wl_handler.py (main REST handler)
import sys
import os

# Add parent directory to path so sibling modules can be imported
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import domain modules
import wl_constants as const
import wl_validation as val
import wl_rbac
import wl_csv
import wl_versions
import wl_approval
import wl_limits
import wl_audit
import wl_rules
import wl_trash
import wl_presence
import wl_notifications

from splunk.persistconn.application import PersistentServerConnectionApplication

class WhitelistHandler(PersistentServerConnectionApplication):
    def _handle_post(self, request):
        action = self._get_param(request, "action")
        user = self._get_user(request)
        
        if action == "save_csv":
            return self._save_csv_action(request, user)
        elif action == "submit_approval":
            return self._submit_approval_action(request, user)
        # ... route to other domain modules
```

**Why this pattern:**

1. **No circular dependencies** — modules import constants + utilities, not each other
2. **Testable in isolation** — each module can be unit-tested independently (no monolith)
3. **Clear responsibility boundaries** — validation lives in `wl_validation.py`, RBAC in `wl_rbac.py`, etc.
4. **Splunk-compatible** — Splunk's `bin/` loader expects modules in the same directory, doesn't support packages (no `__init__.py`)
5. **Thread-safe** — locks remain in their domain modules (`wl_approval._approval_queue_lock()`, `wl_rules._detection_rules_lock()`)

### Frontend Modularity Pattern (AMD/RequireJS)

**Structure:** Entry point requires shared REST helper, table state manager, and feature modules. Modules communicate via event delegation (jQuery) or explicit callback passing.

```
appserver/static/
  whitelist_manager.js     → AMD entry point (100 lines) — defines main app, requires core modules
  modules/
    wl_rest.js             → Shared REST helpers (restGet, restPost with error handling)
    wl_constants.js        → Selectors, config values, regex patterns
    wl_state.js            → State manager (currentRows, originalRows, version tracking) — singleton
    wl_table.js            → Table rendering, cell editing, change tracking
    wl_search.js           → Filter/search functionality with highlighting
    wl_modals.js           → Modal dialogs (add row, remove, revert, reason prompt)
    wl_versions.js         → Version dropdown, revert submission
    wl_approval_ui.js      → Approval gate checks, status display, submission flow
    wl_presence.js         → Presence banner, heartbeat logic
    wl_csv_io.js           → CSV import/export, file validation, preview
    wl_events.js           → Event binding, delegation, lifecycle hooks
    wl_theme.js            → Dark/light theme detection and application
  control_panel.js         → Admin panel entry point
  modules/
    wl_cp_queue.js         → Approval queue UI, approve/reject handlers
    wl_cp_limits.js        → Daily limits table, config editor
    wl_cp_trash.js         → Trash management UI, restore/purge handlers
    wl_cp_settings.js      → Settings (permissions, retention, etc.)
  notifications.js         → Toast notification system, polling, bell UI
```

**AMD Module Boilerplate:**

```javascript
// modules/wl_table.js — Feature module defining table rendering

define([
    "jquery",
    "underscore",
    "splunkjs/mvc/utils",
    "./wl_rest",       // Relative path to sibling module in same directory
    "./wl_constants",
    "./wl_state"       // State manager — accessed as singleton
], function ($, _, utils, restHelper, constants, stateManager) {
    "use strict";

    // Private module state (not shared with other modules)
    var isRendering = false;

    // Public API
    var tableModule = {
        renderTable: function (rows, headers) {
            isRendering = true;
            // ... render logic
            isRendering = false;
        },

        getSelectedRows: function () {
            // ... return selected rows
        },

        clearSelection: function () {
            // ... clear checkboxes
        }
    };

    return tableModule;
});

// whitelist_manager.js — Main app entry point

require([
    "jquery",
    "underscore",
    "splunkjs/mvc",
    "splunkjs/mvc/utils",
    "splunkjs/mvc/simplexml/ready!",
    "./modules/wl_rest",
    "./modules/wl_constants",
    "./modules/wl_state",
    "./modules/wl_table",
    "./modules/wl_search",
    "./modules/wl_modals",
    "./modules/wl_versions"
], function ($, _, mvc, utils, readyEvent,
            restHelper, constants, stateManager, 
            tableModule, searchModule, modalsModule, versionsModule) {
    "use strict";

    // Initialize the app
    var app = {
        init: function () {
            stateManager.loadFromServer();
            tableModule.renderTable(
                stateManager.getCurrentRows(),
                stateManager.getHeaders()
            );
            
            // Bind search input event
            $(constants.selectors.searchInput).on("keyup", function () {
                var query = $(this).val();
                searchModule.filter(query);
                tableModule.renderTable(
                    searchModule.getFilteredRows(),
                    stateManager.getHeaders()
                );
            });

            // Bind save button
            $(constants.selectors.saveBtn).on("click", function () {
                app.saveCsv();
            });
        },

        saveCsv: function () {
            var payload = {
                action: "save_csv",
                csv_file: stateManager.getSelectedCsv(),
                old_rows: stateManager.getOriginalRows(),
                new_rows: stateManager.getCurrentRows(),
                reason: $(constants.selectors.reasonInput).val()
            };

            restHelper.post(payload)
                .done(function (resp) {
                    stateManager.markSaved();
                    modalsModule.showDiffModal(resp.diff);
                })
                .fail(function (err) {
                    modalsModule.showErrorModal(err.message);
                });
        }
    };

    // Start the app when Splunk is ready
    readyEvent.on("ready", function () {
        app.init();
    });
});
```

**State Manager Pattern (wl_state.js):**

The state manager is a singleton — required by all feature modules that read/write shared application state. No direct data passing between modules; all state reads/writes go through the state manager.

```javascript
// modules/wl_state.js

define(["jquery", "./wl_rest"], function ($, restHelper) {
    "use strict";

    // Private internal state
    var state = {
        currentHeaders: [],
        originalHeaders: [],
        currentRows: [],
        originalRows: [],
        selectedRule: "",
        selectedCsv: "",
        loadedMtime: null,
        isSaving: false
    };

    // Public API — the only way other modules access state
    var stateManager = {
        // Getters
        getHeaders: function () {
            return state.currentHeaders;
        },

        getCurrentRows: function () {
            return state.currentRows;
        },

        getOriginalRows: function () {
            return state.originalRows;
        },

        getSelectedCsv: function () {
            return state.selectedCsv;
        },

        getLoadedMtime: function () {
            return state.loadedMtime;
        },

        // Setters
        setHeaders: function (headers) {
            state.currentHeaders = headers;
            state.originalHeaders = JSON.parse(JSON.stringify(headers));
        },

        setRows: function (rows) {
            state.currentRows = rows;
            state.originalRows = JSON.parse(JSON.stringify(rows));
            state.loadedMtime = Date.now();
        },

        setSelectedCsv: function (csv) {
            state.selectedCsv = csv;
        },

        // Modify current rows (for edits/adds/removes)
        updateRow: function (index, newValues) {
            Object.assign(state.currentRows[index], newValues);
            // Trigger change event
            $(document).trigger("wl:rowChanged", [index]);
        },

        addRow: function (row) {
            state.currentRows.push(row);
            $(document).trigger("wl:rowAdded");
        },

        removeRow: function (index) {
            state.currentRows.splice(index, 1);
            $(document).trigger("wl:rowRemoved", [index]);
        },

        markSaved: function () {
            state.originalRows = JSON.parse(JSON.stringify(state.currentRows));
            state.originalHeaders = JSON.parse(JSON.stringify(state.currentHeaders));
            state.isSaving = false;
        },

        // Load full CSV from server
        loadFromServer: function (rule, csv) {
            var self = this;
            return restHelper.get({
                action: "get_csv_content",
                detection_rule: rule,
                csv_file: csv
            }).done(function (resp) {
                self.setHeaders(resp.headers);
                self.setRows(resp.rows);
                state.selectedRule = rule;
                state.selectedCsv = csv;
                state.loadedMtime = resp.loadedMtime;
                $(document).trigger("wl:csvLoaded");
            });
        }
    };

    return stateManager;
});
```

**Shared REST Helper (wl_rest.js):**

Eliminates 6x duplication of restGet/restPost across files. Used by all modules that need to call the backend.

```javascript
// modules/wl_rest.js

define(["jquery", "splunkjs/mvc/utils"], function ($, utils) {
    "use strict";

    var baseUrl = Splunk.util.make_url(
        "/splunkd/__raw/services/custom/wl_manager"
    );

    return {
        get: function (params) {
            params = params || {};
            params.output_mode = "json";
            return $.ajax({
                url: baseUrl,
                type: "GET",
                data: params,
                dataType: "json"
            });
        },

        post: function (payload) {
            return $.ajax({
                url: baseUrl + "?output_mode=json",
                type: "POST",
                contentType: "application/json",
                data: JSON.stringify(payload),
                dataType: "json"
            });
        },

        // Error helper — standard error message extraction
        getErrorMessage: function (jqXhr) {
            try {
                if (jqXhr.responseJSON && jqXhr.responseJSON.error) {
                    return jqXhr.responseJSON.error;
                }
            } catch (e) { /* ignore */ }
            return jqXhr.statusText || "Request failed";
        }
    };
});
```

**Event-Based Module Communication:**

Modules don't call each other directly. Instead, they emit/listen to jQuery events on `$(document)`.

```javascript
// modules/wl_table.js
$(document).on("wl:csvLoaded", function () {
    // CSV loaded by state manager via server fetch
    tableModule.renderTable(stateManager.getCurrentRows());
});

$(document).on("wl:rowChanged wl:rowAdded wl:rowRemoved", function () {
    // Some module modified state — re-render
    tableModule.renderTable(stateManager.getCurrentRows());
});

// modules/wl_search.js
$(document).on("wl:csvLoaded", function () {
    searchModule.clearFilter();
    searchModule.rebuildIndex(stateManager.getCurrentRows());
});
```

## Component Boundaries

### Backend Module Responsibilities

| Module | Responsibility | Communicates With | Owns |
|--------|---------------|--------------------|------|
| `wl_handler.py` | REST routing, request/response serialization | All domain modules | HTTP layer |
| `wl_constants.py` | Constants, defaults, limits, config | None (read-only) | Magic numbers |
| `wl_validation.py` | Input sanitization, filename checks, cell limits | — | Validation rules |
| `wl_rbac.py` | Role membership checks, permission enforcement | Splunk SDK | Permission logic |
| `wl_csv.py` | Read/write files, diff computation, cell operations | `wl_versions`, `wl_constants` | CSV I/O |
| `wl_versions.py` | Version snapshots, manifest management, revert | `wl_csv`, `wl_constants` | File versioning |
| `wl_approval.py` | Queue CRUD, status tracking, conflict resolution | `wl_rules`, `wl_constants` | Approval state |
| `wl_limits.py` | Daily usage tracking, reset scheduling, enforcement | `wl_constants` | Limit state |
| `wl_audit.py` | Event building, index posting, fallback logging | Splunk REST API | Audit trail |
| `wl_rules.py` | Detection rules registry, rule-to-CSV mapping | `wl_constants`, file I/O | Rules registry |
| `wl_trash.py` | Soft-delete, restore, purge with retention | `wl_csv`, `wl_rules`, `wl_constants` | Trash metadata |
| `wl_presence.py` | User presence tracking, timeouts | `wl_constants` | Presence state |
| `wl_notifications.py` | Admin notification queue, toast logic | `wl_constants`, file I/O | Notification state |

### Frontend Module Responsibilities

| Module | Responsibility | Depends On | Mutates |
|--------|----------------|-----------|---------|
| `wl_rest.js` | HTTP abstraction layer | jQuery | — |
| `wl_constants.js` | Selectors, config, regex | — | — |
| `wl_state.js` | Shared application state (singleton) | `wl_rest` | All state |
| `wl_table.js` | Table rendering, cell editing, change tracking | `wl_state` | DOM |
| `wl_search.js` | Search/filter logic, highlighting | `wl_state` | DOM (highlights) |
| `wl_modals.js` | Modal dialogs, form validation | `wl_rest`, `wl_constants` | DOM |
| `wl_versions.js` | Version dropdown, revert submission | `wl_state`, `wl_rest` | DOM |
| `wl_approval_ui.js` | Approval gate checks, submission | `wl_rest`, `wl_state` | — |
| `wl_presence.js` | Presence banner, heartbeat polling | `wl_rest` | DOM |
| `wl_csv_io.js` | CSV import/export, validation | `wl_state` | — |
| `wl_events.js` | Event binding, lifecycle | All feature modules | Event handlers |
| `wl_theme.js` | Theme detection, CSS class toggle | — | DOM |

## Build & Extract Order

**Rationale:** Extract dependencies before dependents. Test each module as standalone before integration.

### Phase 1: Foundation Modules (no dependencies on other domain modules)

1. **wl_constants.py** — All other modules depend on this. Extract first.
2. **wl_validation.py** — Pure validation logic, no domain logic dependencies
3. **wl_rbac.py** — Splunk SDK integration, used by handler
4. **wl_presence.py** — Presence tracking, independent from approval/rules
5. **wl_notifications.py** — Notification queue, independent logic

### Phase 2: Core Domain Modules (depend on Phase 1)

6. **wl_csv.py** — CSV I/O, the data heart; versioning depends on this
7. **wl_versions.py** — Version control (depends on wl_csv)
8. **wl_audit.py** — Audit event construction, widely used
9. **wl_rules.py** — Rules registry, needed for rule operations
10. **wl_trash.py** — Soft-delete (depends on wl_csv, wl_rules)

### Phase 3: Complex Orchestration Modules (depend on Phase 1–2)

11. **wl_limits.py** — Daily limit tracking and enforcement
12. **wl_approval.py** — Approval queue (depends on wl_rules for conflict resolution)

### Phase 4: REST Handler (ties all modules together)

13. **wl_handler.py** → Extract action methods one-by-one, replacing monolithic methods with calls to domain modules

**Test strategy per phase:**

- **Phase 1–2:** Unit tests for each module in isolation (mock Splunk SDK)
- **Phase 3:** Integration tests with mock file I/O
- **Phase 4:** E2E tests against live Docker container

### Frontend Build Order

**Principle:** Extract utilities first, then feature modules that share no state, then state manager, then integrations.

1. **modules/wl_constants.js** — Used everywhere
2. **modules/wl_rest.js** — Shared HTTP layer (unblock all server calls)
3. **modules/wl_state.js** — Singleton state manager (core dependency)
4. **modules/wl_table.js** → Extract from whitelist_manager.js
5. **modules/wl_search.js** → Extract from whitelist_manager.js
6. **modules/wl_versions.js** → Extract from whitelist_manager.js
7. **modules/wl_modals.js** → Extract from whitelist_manager.js
8. **modules/wl_approval_ui.js** → Extract from whitelist_manager.js
9. **modules/wl_csv_io.js** → Extract from whitelist_manager.js
10. **modules/wl_presence.js** → Extract from whitelist_manager.js
11. **modules/wl_theme.js** → Extract from whitelist_manager.js
12. **modules/wl_events.js** → Extract lifecycle and event binding
13. **whitelist_manager.js** → Rewrite as thin entry point (100 lines)
14. **control_panel.js & modules/** → Repeat for admin panel

## Key Integration Points

### Backend-Frontend Contract

**Action Request Format (unchanged):**
```json
{
  "action": "save_csv",
  "detection_rule": "DR102 - Phishing",
  "csv_file": "DR102_whitelist.csv",
  "old_rows": [...],
  "new_rows": [...],
  "reason": "User feedback"
}
```

**Response Format (unchanged):**
```json
{
  "success": true,
  "diff": {
    "added": [...],
    "removed": [...],
    "edited": [...]
  },
  "message": "CSV saved"
}
```

**Backward compatibility:** API contract frozen. All modularization is internal.

### Shared Constants Pattern

**Backend:**
```python
# wl_constants.py
EDIT_ROLES = {"wl_editor", "wl_admin", ...}
MAX_ROWS = 5000
APPROVAL_BULK_THRESHOLD = 3
BULK_EDIT_THRESHOLD = 3
```

**Frontend:**
```javascript
// modules/wl_constants.js
var config = {
    maxRows: 5000,
    maxColumns: 100,
    maxCellChars: 1000,
    selectors: {
        saveBtn: "#btn-save",
        table: "#csv-table",
        searchInput: "#search-csv"
    }
};
```

**Synchronization:** Magic numbers defined in ONE place per layer. Backend/frontend values hardcoded to match during init.

## Locking & Concurrency

**Backend locking remains per-module:**

```python
# wl_approval.py
import threading

_approval_queue_lock = threading.RLock()

def _read_approval_queue():
    with _approval_queue_lock:
        # read and return
        pass

# wl_rules.py
_detection_rules_lock = threading.RLock()

@contextmanager
def _detection_rules_modify():
    with _detection_rules_lock:
        yield
```

**Frontend has no locks** (single-threaded JavaScript).

## Testing Strategy (Post-Modularization)

### Unit Tests

**Backend per-module:**
```bash
python -m pytest tests/unit/test_wl_csv.py         # CSV operations
python -m pytest tests/unit/test_wl_approval.py    # Approval queue
python -m pytest tests/unit/test_wl_limits.py      # Daily limits
python -m pytest tests/unit/test_wl_validation.py  # Input validation
```

**Frontend per-module (mock Splunk SDK):**
```javascript
QUnit.test("wl_state: setRows updates internal state", function(assert) {
    var stateManager = require("modules/wl_state");
    stateManager.setRows([{user: "alice"}, {user: "bob"}]);
    assert.equal(stateManager.getCurrentRows().length, 2);
});
```

### Integration Tests

**Backend modules together:**
```bash
python -m pytest tests/integration/test_save_csv.py  # CSV + versions + audit + limits
```

**Frontend modules together:**
```javascript
// Splunk web UI test: load whitelist_manager.js, verify all modules initialize
```

### E2E Tests

**Against live Docker container:**
```bash
python -m pytest tests/e2e/test_e2e_api.py
```

## Critical Pitfalls During Modularization

1. **Circular dependencies:** Use constants module to break cycles. Never `import wl_X` inside `wl_X`.

2. **Lost file locking:** Every write operation must be wrapped in the appropriate context manager (e.g., `_csv_file_lock(csv_path)` in `wl_csv.py`). Don't migrate locks to handler.

3. **Frontend state mutation bypasses:** All state reads/writes must go through `wl_state.js` singleton. Don't let modules cache their own copies of rows/headers.

4. **Approval replay branches:** Every approval action path must call `wl_approval._save_csv_inner(..., _from_approval=True)`. Test with `process_approval_inner()` to catch missing paths.

5. **Magic number desync:** If a constant changes (e.g., `MAX_ROWS`), update BOTH backend and frontend. No "config file" — they're hardcoded. Document sync points.

6. **Module import path issues:** Splunk `bin/` doesn't support packages. All modules must be in `bin/` directory. Use absolute imports: `import wl_csv`, not `from . import wl_csv`.

7. **Test isolation:** Don't let unit tests touch the real Splunk instance. Mock file I/O and Splunk SDK calls.

8. **AMD module caching:** Once a module is `require()`d, subsequent requires return the same instance (singleton pattern for `wl_state.js`). Intentional for state manager, beware for stateless modules.

## Recommended Migration Path

1. **Create new files** (`wl_constants.py`, etc.) alongside `wl_handler.py`
2. **Gradually extract** methods from `wl_handler.py` into domain modules
3. **Refactor handler** to route to extracted modules
4. **Test each extraction** with unit + integration tests
5. **Repeat for frontend:** Create `modules/` directory, extract one feature at a time
6. **Final integration:** Ensure audit.xml dashboard still works with unchanged API

**Zero-downtime deployment:** Each extraction is backward-compatible (same REST API contract).

---

## Sources

**Official Splunk Documentation (training knowledge):**
- Splunk REST API: Handler routing via `passPayload=true` and `request["payload"]` JSON parsing
- AMD in Splunk Web: RequireJS module system with `define()` and `require()`
- Python in Splunk: `bin/` modules imported via `sys.path` manipulation, no package structure

**Codebase Analysis (2026-03-31):**
- `wl_handler.py` (7,078 lines) — Functions grouped by domain, ready for extraction
- `whitelist_manager.js` (6,786 lines) — State scattered across global vars, feature modules tangled
- Test suite (24 files, 9,007 lines) — Integration tests establish contract; unit test structure clear

**Confidence Levels:**

| Area | Confidence | Notes |
|------|-----------|-------|
| Python module import pattern | HIGH | Verified in `wl_handler.py` init pattern; `sys.path.insert(0)` is Splunk standard |
| AMD boilerplate | HIGH | Matches Splunk Web framework (mvc, utils require patterns) |
| State manager pattern | HIGH | jQuery event delegation in current app, extended to state singleton |
| Backend modularization | MEDIUM | Splunk doesn't document "large app" patterns; inferred from `bin/` structure and function grouping |
| File locking migration | HIGH | Current code uses `fcntl` + context managers; pattern is clear |
| Testing strategy | MEDIUM | No Splunk docs on per-module unit tests; based on current test structure |

