# Frontend Modularization Plan

## Source Files
- `whitelist_manager.js` — 6786 lines → entry point + 8 modules
- `control_panel.js` — 2025 lines → entry point + shared modules
- `notifications.js` — 325 lines → already standalone, keep as-is

## Splunk AMD Rules (non-negotiable)

1. Entry points (`script="..."`) use `require()`, NEVER `define()`
2. Modules use `define()` and return a public API object
3. Module paths: `"app/wl_manager/modules/wl_xxx"` (not bare `"modules/..."`)
4. `simplexml/ready!` goes LAST in dependency array (no callback param)
5. REST URL: `/splunkd/__raw/services/custom/wl_manager` (not `/custom/...`)
6. Include `X-Splunk-Form-Key` CSRF header from `splunkweb_csrf_token_8000` cookie
7. Include `X-Requested-With: XMLHttpRequest` header

## Module Extraction Order (dependency-first)

### Wave 1: Foundation (no cross-module deps)

**Module 1: `wl_constants.js`** (~80 lines)
- Source lines: 32-78 (state defaults, limits, patterns)
- Contains: MAX_ROWS, MAX_COLUMNS, MAX_CELL_CHARS, ROWS_PER_PAGE, PAGE_SIZE_OPTIONS, EXPIRE_COLUMN_NAMES_LIST, VALID_EXPIRE_RE, SAFE_COLNAME_RE, IMPORT_* constants
- Depends on: nothing
- Test: load page, no console errors

**Module 2: `wl_rest.js`** (~80 lines)
- Source lines: 503-555 (restUrl, restGet, restPost, handleSaveError)
- Contains: REST URL builder with splunkd proxy, CSRF headers, GET/POST helpers, conflict handler
- Depends on: jQuery (Splunk builtin)
- Test: detection rules load in dropdown

**Module 3: `wl_ui.js`** (~60 lines)
- Source lines: 559-611, 398-430 (showMsg, formatDailyLimitMsg, theme detection, char counter)
- Contains: message display, theme detection, textarea char counter
- Depends on: jQuery
- Test: messages still display

### Wave 2: Features (depend on Wave 1)

**Module 4: `wl_table.js`** (~1100 lines)
- Source lines: 1739-2830 (renderTable, refreshTable, syncInputs, buildRow, resize, drag, reorder, pagination)
- Contains: table rendering, inline editing, pagination, column resize, drag-drop, row/column reorder
- Depends on: wl_constants, wl_rest, wl_ui
- Test: select a rule+CSV, table renders with data

**Module 5: `wl_search.js`** (~50 lines)
- Source lines: 6000-6082 (search bar events, clearSearch, getFilteredRows)
- Contains: search/filter functionality
- Depends on: wl_table (calls refreshTable)
- Test: type in search bar, table filters

**Module 6: `wl_versions.js`** (~170 lines)
- Source lines: 4886-5130 (loadVersions, renderVersionsDropdown, showRevertModal, doRevert)
- Contains: version dropdown, revert flow
- Depends on: wl_rest, wl_ui
- Test: version dropdown shows versions, revert works

**Module 7: `wl_modals.js`** (~760 lines)
- Source lines: 980-1735 (showRemoveModal, showNewRuleModal, showCreateCsvModal, showApprovalReasonPopup)
- Contains: all modal dialogs (remove, create rule, create CSV, approval reason)
- Depends on: wl_rest, wl_ui, wl_constants
- Test: remove button opens modal, new rule modal works

**Module 8: `wl_csv_io.js`** (~450 lines)
- Source lines: 82-396, 4408-4800 (parseCSV, validateImportedCSV, exportCsv, importCsv, merge/replace)
- Contains: CSV parsing, validation, import, export
- Depends on: wl_constants, wl_ui
- Test: export CSV, import CSV

### Wave 3: Entry Point Rewrite

**`whitelist_manager.js` entry point** (~300 lines)
- Uses `require()` with `simplexml/ready!` LAST
- All state variables remain in entry point (shared via closure or passed to module.init())
- Wires modules together, handles initialization, URL params, keyboard shortcuts
- Delegates to modules for all heavy lifting

## Strategy: Shared State

Instead of a separate `wl_state.js` module (which caused key mismatch bugs last time), keep state variables in the entry point and pass them to modules via init functions:

```javascript
// In entry point:
var state = { currentRows: [], selectedRule: "", ... };

// Pass to modules:
Table.init(state, REST, UI, Constants);
Search.init(state, Table);
Versions.init(state, REST, UI);
```

This avoids the state-key-name mismatch problem entirely. Modules receive a reference to the same state object.

## Testing Protocol (per module)

1. Extract module, update entry point to use it
2. `docker cp` all changed files
3. Bump build in app.conf
4. Clear i18n cache: `rm -f /opt/splunk/var/run/splunk/appserver/i18n/*.js-*`
5. Restart Splunk
6. curl test: `curl -s -k -u admin:Chang3d! "https://localhost:8089/services/custom/wl_manager?action=get_mapping&output_mode=json" | head -50`
7. Check splunkd log for errors
8. Visual check at milestones (after Wave 1, after Wave 2)

## Control Panel

Same approach — extract shared modules (wl_rest, wl_ui, wl_constants) are reused. Control-panel-specific modules:
- `wl_cp_queue.js` — approval queue management
- `wl_cp_limits.js` — daily limits configuration
- `wl_cp_trash.js` — trash/recycle bin management

## Milestone Checkpoints (user visual verification)

1. After Wave 1 complete (constants + REST + UI extracted) — "can you load the page and search rules?"
2. After Wave 2 complete (all modules extracted) — "full test: load CSV, edit, save, revert"
3. After control_panel.js done — "check Control Panel tabs"
