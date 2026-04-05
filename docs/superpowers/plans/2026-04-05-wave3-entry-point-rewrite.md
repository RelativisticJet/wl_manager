# Wave 3: Entry Point Rewrite — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract 5 new AMD modules and extend 2 existing modules to reduce `whitelist_manager.js` from 3390 to ~1530 lines.

**Architecture:** Sequential module extraction from a monolithic Splunk AMD entry point. Each module uses `define()`, receives shared state via ES5 getter/setter proxy, communicates with other modules through late-binding callback trampolines wired by the entry point.

**Tech Stack:** JavaScript (ES5), Splunk AMD/RequireJS, jQuery, underscore, Docker (Splunk 9.3.1 container)

**Spec:** `docs/superpowers/specs/2026-04-05-wave3-entry-point-rewrite-design.md`

---

## Key References

- **Entry point:** `appserver/static/whitelist_manager.js` (3390 lines, build 528)
- **Modules dir:** `appserver/static/modules/`
- **App config:** `default/app.conf` (bump `build` on every deploy)
- **Container:** `wl_manager_test` (Splunk 9.3.1, admin/Chang3d!)
- **Splunk AMD rules:** Entry points use `require()`, modules use `define()`. Module paths must be `"app/wl_manager/modules/wl_xxx"`. `simplexml/ready!` goes LAST in deps array with no callback param.

## Deploy Protocol (run after every task that changes JS/CSS)

Every task references "Run deploy protocol" — this is what it means:

```bash
# 1. Bump build number in app.conf (increment by 1)
# 2. Copy all changed files (copy INDIVIDUAL .js files, not the modules/ directory):
MSYS_NO_PATHCONV=1 docker cp "C:/Users/PC/wl_manager/appserver/static/whitelist_manager.js" wl_manager_test:/opt/splunk/etc/apps/wl_manager/appserver/static/whitelist_manager.js
# For each new/changed module, copy individually:
# MSYS_NO_PATHCONV=1 docker cp "C:/Users/PC/wl_manager/appserver/static/modules/wl_diff.js" wl_manager_test:/opt/splunk/etc/apps/wl_manager/appserver/static/modules/wl_diff.js
MSYS_NO_PATHCONV=1 docker cp "C:/Users/PC/wl_manager/default/app.conf" wl_manager_test:/opt/splunk/etc/apps/wl_manager/default/app.conf
# 3. Clear ALL Splunk caches:
MSYS_NO_PATHCONV=1 docker exec -u 0 wl_manager_test bash -c 'rm -rf /opt/splunk/var/run/splunk/appserver/i18n/*.js-* /opt/splunk/var/run/splunk/appserver/static/app/wl_manager/ /opt/splunk/var/run/splunk/appserver/static/build/'
# 4. Fix permissions:
MSYS_NO_PATHCONV=1 docker exec -u 0 wl_manager_test chown -R splunk:splunk /opt/splunk/etc/apps/wl_manager/appserver/static/
# 5. Restart Splunk:
MSYS_NO_PATHCONV=1 docker exec -u splunk wl_manager_test /opt/splunk/bin/splunk stop
MSYS_NO_PATHCONV=1 docker exec -u splunk wl_manager_test /opt/splunk/bin/splunk start --answer-yes
```

---

## Task 0: Delete Phase 5-6 Leftovers

**Files:**
- Delete: `appserver/static/modules/wl_state.js`
- Delete: `appserver/static/modules/wl_orchestrator.js`
- Delete: `appserver/static/modules/wl_approval_ui.js`
- Delete: `appserver/static/modules/wl_presence.js`
- Delete: `appserver/static/modules/wl_cp_admin_limits.js`
- Delete: `appserver/static/modules/wl_cp_limits.js`
- Delete: `appserver/static/modules/wl_cp_modals.js`
- Delete: `appserver/static/modules/wl_cp_queue.js`
- Delete: `appserver/static/modules/wl_cp_trash.js`
- Delete: `appserver/static/modules/wl_cp_usage.js`

- [ ] **Step 1: Verify none of these files are imported**

Run: `grep -r "wl_state\|wl_orchestrator\|wl_approval_ui\|wl_presence\|wl_cp_admin_limits\|wl_cp_limits\|wl_cp_modals\|wl_cp_queue\|wl_cp_trash\|wl_cp_usage" appserver/static/whitelist_manager.js appserver/static/control_panel.js appserver/static/modules/*.js`
Expected: No matches in ANY entry point or active module (these Phase 5 modules are dead code)

- [ ] **Step 2: Delete all 10 files**

```bash
cd c:/Users/PC/wl_manager
git rm appserver/static/modules/wl_state.js
git rm appserver/static/modules/wl_orchestrator.js
git rm appserver/static/modules/wl_approval_ui.js
git rm appserver/static/modules/wl_presence.js
git rm appserver/static/modules/wl_cp_admin_limits.js
git rm appserver/static/modules/wl_cp_limits.js
git rm appserver/static/modules/wl_cp_modals.js
git rm appserver/static/modules/wl_cp_queue.js
git rm appserver/static/modules/wl_cp_trash.js
git rm appserver/static/modules/wl_cp_usage.js
```

- [ ] **Step 3: Run deploy protocol**

Deploy and verify the app still loads without console errors (no functional change).

- [ ] **Step 4: Commit**

```bash
git add -A appserver/static/modules/
git commit -m "chore: delete Phase 5-6 leftover module files (2944 lines dead code)"
```

---

**Important:** Source line numbers reference `whitelist_manager.js` at build 528 (3390 lines). After Task 0 deletes Phase 5 files, line numbers in the entry point are unchanged (only module files are deleted). However, after each extraction task, line numbers shift. Always verify the function name at the expected line before extracting.

---

## Task 1: Extract `wl_diff.js`

**Files:**
- Create: `appserver/static/modules/wl_diff.js`
- Modify: `appserver/static/whitelist_manager.js` (remove lines 2201-2443, add require dep + init)
- Modify: `default/app.conf` (bump build)

- [ ] **Step 1: Create `wl_diff.js` module**

Create `appserver/static/modules/wl_diff.js`. Extract the `renderDiff` function (entry point lines 2204-2443) into a `define()` module.

Module structure:
```javascript
define(["jquery", "underscore"], function ($, _) {
    "use strict";

    var DIFF_MAX_ROWS = 10;
    var DIFF_MAX_COLS = 8;
    var $diff = null;

    function renderDiff(diff) {
        // ... paste lines 2205-2442 verbatim (the function body) ...
    }

    return {
        init: function (opts) { $diff = opts.$diff; },
        renderDiff: renderDiff
    };
});
```

Key changes from entry point version:
- `$diff` becomes module-private var, set via `init()`
- `DIFF_MAX_ROWS` and `DIFF_MAX_COLS` become module-level constants (were local to `renderDiff`)
- No other changes to the function body — it uses only `$`, `_`, and `$diff`

- [ ] **Step 2: Update entry point — add Diff to require array**

In `whitelist_manager.js`, add `"app/wl_manager/modules/wl_diff"` to the require array (after `wl_csv_io`, before `wl_debug`). Add `Diff` to the callback params.

Update require array (line 20-34):
```javascript
require([
    "jquery",
    "underscore",
    "splunkjs/mvc",
    "splunkjs/mvc/utils",
    "app/wl_manager/modules/wl_constants",
    "app/wl_manager/modules/wl_rest",
    "app/wl_manager/modules/wl_ui",
    "app/wl_manager/modules/wl_table",
    "app/wl_manager/modules/wl_versions",
    "app/wl_manager/modules/wl_modals",
    "app/wl_manager/modules/wl_csv_io",
    "app/wl_manager/modules/wl_diff",
    "app/wl_manager/modules/wl_debug",
    "splunkjs/mvc/simplexml/ready!"
], function ($, _, mvc, utils, C, REST, UI, Table, Versions, Modals, CsvIO, Diff, Debug) {
```

- [ ] **Step 3: Add Diff.init() call**

Add after the existing `CsvIO.init(...)` block:

```javascript
// ── Diff module init ──
Diff.init({ $diff: $diff });
```

- [ ] **Step 4: Update Versions.init() actions**

Change the `renderDiff` trampoline in Versions.init to use Diff module:

```javascript
renderDiff: function () { return Diff.renderDiff.apply(null, arguments); },
```

- [ ] **Step 5: Remove extracted code from entry point**

Delete lines 2201-2443 (the `// Diff rendering` section header through the end of `renderDiff` function and its expand click handler). Replace with:

```javascript
    // (renderDiff → extracted to modules/wl_diff.js)
```

- [ ] **Step 6: Update all `renderDiff` call sites in entry point**

The remaining call sites in the entry point (in save functions that haven't been extracted yet) should now call `Diff.renderDiff(diffInfo)`. Search for `renderDiff(` in the entry point — these will move to `wl_save.js` in Task 7, but for now they must work. Since `renderDiff` was a closure function and is now `Diff.renderDiff`, add an alias:

```javascript
var renderDiff = Diff.renderDiff;
```

Add this after the `Diff.init()` call.

- [ ] **Step 7: Run deploy protocol**

Bump build to 529. Deploy. Verify:
- Select a rule + CSV, edit a cell, Save → diff panel appears below table
- Verify side-by-side comparison renders correctly
- Check browser console for errors

- [ ] **Step 8: Commit**

```bash
git add appserver/static/modules/wl_diff.js appserver/static/whitelist_manager.js default/app.conf
git commit -m "feat(modularize): extract wl_diff.js — git-style diff renderer (Wave 3 Step 1)"
```

---

## Task 2: Extract `wl_datepicker.js`

**Files:**
- Create: `appserver/static/modules/wl_datepicker.js`
- Modify: `appserver/static/whitelist_manager.js` (remove lines 2449-2596, add require dep + init)
- Modify: `default/app.conf` (bump build)

- [ ] **Step 1: Create `wl_datepicker.js` module**

Create `appserver/static/modules/wl_datepicker.js`. Extract lines 2449-2596 (from `var $datePicker = null` through `closeDatePicker` function).

Module structure:
```javascript
define(["jquery"], function ($) {
    "use strict";

    var $datePicker = null;
    var $activeExpiresInput = null;
    var _state = null;

    function padTwo(n) { /* line 2452-2453 */ }
    function formatDateForPicker(d) { /* line 2456-2457 */ }
    function formatLocalDateTime(d) { /* line 2460-2462 */ }
    function formatUTCDateTime(d) { /* line 2465-2467 */ }
    function createDatePicker() { /* lines 2470-2550 */ }
    function showDatePicker($input) { /* lines 2553-2589 */ }
    function closeDatePicker() { /* lines 2591-2596 */ }

    return {
        init: function (opts) { _state = opts.state; },
        showDatePicker: showDatePicker,
        closeDatePicker: closeDatePicker,
        formatLocalDateTime: formatLocalDateTime
    };
});
```

Key changes from entry point version:
- `currentRows` references inside `createDatePicker` (apply/clear handlers) and `showDatePicker` change to `_state.currentRows`
- Everything else stays verbatim

Specific lines to change inside the extracted code:
- Line 2529: `if (currentRows[idx])` → `if (_state.currentRows[idx])`
- Line 2529: `currentRows[idx][header] = utcStr` → `_state.currentRows[idx][header] = utcStr`
- Line 2540: `if (currentRows[idx])` → `if (_state.currentRows[idx])`
- Line 2540: `currentRows[idx][header] = ""` → `_state.currentRows[idx][header] = ""`
- Line 2560: `(currentRows[idx] && currentRows[idx][header])` → `(_state.currentRows[idx] && _state.currentRows[idx][header])`

- [ ] **Step 2: Update entry point — add DatePicker to require array**

Add `"app/wl_manager/modules/wl_datepicker"` after `wl_diff` in require array. Add `DatePicker` to callback params.

- [ ] **Step 3: Add DatePicker.init() call**

Add after `Diff.init()`:

```javascript
// ── DatePicker module init ──
DatePicker.init({ state: _tableState });
```

- [ ] **Step 4: Update Table.init() actions — formatLocalDateTime**

Change the `formatLocalDateTime` trampoline:

```javascript
formatLocalDateTime: function () { return DatePicker.formatLocalDateTime.apply(null, arguments); },
```

- [ ] **Step 5: Remove extracted code from entry point**

Delete lines 2445-2596 (section header through `closeDatePicker`). Replace with:

```javascript
    // (Date/Time Picker → extracted to modules/wl_datepicker.js)
```

- [ ] **Step 6: Update event bindings**

The two event bindings (lines 2598-2612) stay in entry point. Update them to use module:

```javascript
$table.on("click.wl", ".wl-expires-input", function (e) {
    e.stopPropagation();
    DatePicker.showDatePicker($(this));
});

$(document).on("click", function (e) {
    if (DatePicker.isOpen && DatePicker.isOpen()) {
        // ... close logic
    }
});
```

Actually, simpler: keep `closeDatePicker` accessible via alias or direct call:

```javascript
$(document).on("click", function (e) {
    // Close date picker if clicking outside
    var $dp = $("#wl-date-picker");
    if ($dp.length && $dp.css("display") !== "none") {
        if (!$(e.target).closest("#wl-date-picker").length &&
            !$(e.target).closest(".wl-expires-input").length) {
            DatePicker.closeDatePicker();
        }
    }
});
```

- [ ] **Step 7: Remove `formatLocalDateTime` alias if still present**

Search entry point for `var formatLocalDateTime`. If the Table.init actions trampoline now uses `DatePicker.formatLocalDateTime`, remove any stale local alias.

- [ ] **Step 8: Run deploy protocol**

Bump build to 530. Deploy. Verify:
- Select a rule + CSV with an Expires column
- Click an Expires cell → date picker popup appears
- Select a preset (7 Days) → date fills in
- Click Apply → value saved in cell
- Click outside → picker closes
- Check console for errors

- [ ] **Step 9: Commit**

```bash
git add appserver/static/modules/wl_datepicker.js appserver/static/whitelist_manager.js default/app.conf
git commit -m "feat(modularize): extract wl_datepicker.js — Expires column date picker (Wave 3 Step 2)"
```

---

## Task 3: Extract `wl_presence.js`

**Files:**
- Create: `appserver/static/modules/wl_presence.js`
- Modify: `appserver/static/whitelist_manager.js` (remove lines 3068-3279, add require dep + init)
- Modify: `default/app.conf` (bump build)

- [ ] **Step 1: Create `wl_presence.js` module**

Create `appserver/static/modules/wl_presence.js`. Extract lines 3068-3279 (from `var presenceTimer` through `renderPresenceBar`).

Module structure:
```javascript
define(["jquery", "underscore", "splunkjs/mvc",
        "app/wl_manager/modules/wl_rest"],
function ($, _, mvc, REST) {
    "use strict";

    var restGet = REST.restGet;
    var presenceTimer = null;
    var currentUser = "";
    var lastActivityTime = Date.now();
    var IDLE_TIMEOUT_MS = 30 * 60 * 1000;

    var _state = null;
    var _$table = null;
    var _actions = null;

    function getCurrentUser() { /* lines 3081-3097 */ }
    function startPresenceMonitoring() { /* lines 3099-3105 */ }
    function stopPresenceMonitoring() { /* lines 3107-3108 */ }
    function reportPresence() { /* lines 3111-3156 */ }
    function showPresenceFullModal(message) { /* lines 3159-3186 */ }
    function handleCsvRemoved(csvName) { /* lines 3189-3225 */ }
    function renderPresenceBar(users) { /* lines 3228-3278 */ }

    return {
        init: function (opts) {
            _$table = opts.$table;
            _state = opts.state;
            _actions = opts.actions;
        },
        startPresenceMonitoring: startPresenceMonitoring,
        stopPresenceMonitoring: stopPresenceMonitoring,
        handleCsvRemoved: handleCsvRemoved,
        getCurrentUser: getCurrentUser,
        updateActivity: function () { lastActivityTime = Date.now(); }
    };
});
```

Key changes from entry point version:
- `selectedCsv` → `_state.selectedCsv`
- `selectedApp` → `_state.selectedApp`
- `restGet(...)` stays as-is (imported from wl_rest)
- `showMsg(...)` references: reportPresence doesn't call showMsg, so no change needed
- `$table` → `_$table` (for `renderPresenceBar` which does `_$table.find(...)` and `_$table.prepend(...)`)
- `$ruleClear.trigger("click")` in dismiss handlers → `_actions.onDismiss()`
- `stopChangeMonitoring()` in `handleCsvRemoved` → `_actions.stopChangeMonitoring()`
- The activity tracker IIFE (lines 3074-3078) stays in entry point, calls `Presence.updateActivity()`

- [ ] **Step 2: Update entry point — add Presence to require array**

Add `"app/wl_manager/modules/wl_presence"` after `wl_datepicker`. Add `Presence` to callback params.

- [ ] **Step 3: Add Presence.init() call**

Add after `DatePicker.init()`:

```javascript
// ── Presence module init ──
Presence.init({
    $table: $table,
    state:  _tableState,
    actions: {
        onDismiss:            function () { $ruleClear.trigger("click"); },
        stopChangeMonitoring: function () { stopChangeMonitoring(); }
    }
});
```

Note: `stopChangeMonitoring` is still a local function at this point (moves to Save in Task 7). Use a trampoline.

- [ ] **Step 4: Remove extracted code from entry point**

Delete lines 3064-3279 (section header through `renderPresenceBar`). Replace with:

```javascript
    // (Presence monitoring → extracted to modules/wl_presence.js)
```

- [ ] **Step 5: Update activity tracker**

The activity tracker IIFE (lines 3074-3078) stays in entry point but now calls the module:

```javascript
(function trackActivity() {
    var events = "click.wlactivity keydown.wlactivity input.wlactivity mousedown.wlactivity";
    $(document).off(events).on(events, function () {
        Presence.updateActivity();
    });
})();
```

- [ ] **Step 6: Update all call sites in entry point**

Search for these function calls and update:
- `startPresenceMonitoring()` → `Presence.startPresenceMonitoring()`
- `stopPresenceMonitoring()` → `Presence.stopPresenceMonitoring()`
- `handleCsvRemoved(...)` → `Presence.handleCsvRemoved(...)`
- `getCurrentUser()` → `Presence.getCurrentUser()`

These appear in: `loadCsv` done handler, `beforeunload` handler, rule clear handler, `checkForExternalChanges` fail handler.

- [ ] **Step 7: Run deploy protocol**

Bump build to 531. Deploy. Verify:
- Select a rule + CSV → "Also viewing:" bar appears (if another session is open)
- Wait idle → presence modal appears after 30min (or test with shorter timeout)
- Check console for errors

- [ ] **Step 8: Commit**

```bash
git add appserver/static/modules/wl_presence.js appserver/static/whitelist_manager.js default/app.conf
git commit -m "feat(modularize): extract wl_presence.js — real-time collaboration indicators (Wave 3 Step 3)"
```

---

**>>> USER VISUAL CHECKPOINT 1: After Task 3 <<<**

Ask user to verify in browser:
1. Date picker works (click Expires cell, presets, apply, clear)
2. Presence bar renders ("Also viewing: ...")
3. Diff display works (edit + save → diff panel shows changes)
4. No console errors

---

## Task 4: Extend `wl_csv_io.js` with Audit Export

**Files:**
- Modify: `appserver/static/modules/wl_csv_io.js`
- Modify: `appserver/static/whitelist_manager.js` (remove lines 2918-3048)
- Modify: `default/app.conf` (bump build)

- [ ] **Step 1: Read current `wl_csv_io.js` to understand its structure**

Read the module's return statement to know where to add the new function and export.

- [ ] **Step 2: Add `exportAuditCsv` and `splEscape` to `wl_csv_io.js`**

Copy lines 2922-3048 from entry point (`exportAuditCsv` function including nested `splEscape`).

Key changes:
- `selectedCsv` → `_state.selectedCsv`
- `selectedRule` → `_state.selectedRule`
- `showMsg(...)` → `UI.showMsg(...)` (UI is already imported by wl_csv_io)
- `csvEscape(...)` → just `csvEscape(...)` (already a local function in the module)
- `restGet(...)` → `restGet(...)` (already aliased from REST in the module)
- `currentHeaders` → `_state.currentHeaders` (if used — check)

Add `exportAuditCsv: exportAuditCsv` to the module's return object.

- [ ] **Step 3: Remove extracted code from entry point**

Delete lines 2918-3064 (section header through end of `exportAuditCsv`). Replace with:

```javascript
    // (exportAuditCsv → extracted to modules/wl_csv_io.js)
```

- [ ] **Step 4: Update button binding in entry point**

Change:
```javascript
$table.on("click.wl", "#btn-audit-export", function () { exportAuditCsv(); });
```
To:
```javascript
$table.on("click.wl", "#btn-audit-export", function () { CsvIO.exportAuditCsv(); });
```

- [ ] **Step 5: Remove `csvEscape` alias if no longer needed**

Check if `var csvEscape = CsvIO.csvEscape` is still used anywhere in the entry point after this extraction. If not, remove the alias.

- [ ] **Step 6: Run deploy protocol**

Bump build to 532. Deploy. Verify:
- Select a rule + CSV → click "Export Audit" button
- CSV file downloads with audit trail data
- Check console for errors

- [ ] **Step 7: Commit**

```bash
git add appserver/static/modules/wl_csv_io.js appserver/static/whitelist_manager.js default/app.conf
git commit -m "feat(modularize): add exportAuditCsv to wl_csv_io.js (Wave 3 Step 4)"
```

---

## Task 5: Extend `wl_modals.js` with Bulk Edit Modal

**Files:**
- Modify: `appserver/static/modules/wl_modals.js`
- Modify: `appserver/static/whitelist_manager.js` (remove lines 2691-2908)
- Modify: `default/app.conf` (bump build)

- [ ] **Step 1: Read current `wl_modals.js` to understand its structure**

Read the module's init pattern, `_state` proxy usage, `_actions` object, and return statement.

- [ ] **Step 2: Add `showBulkEditModal` to `wl_modals.js`**

Copy lines 2695-2908 from entry point (the entire `showBulkEditModal` function including nested `updateBulkValueInput` and `applyBulkEditLocally`).

Key changes:
- `currentHeaders` → `_state.currentHeaders`
- `currentRows` → `_state.currentRows`
- `csvLocked` → `_state.csvLocked`
- `saving` → `_state.saving`
- `selectedCsv` → `_state.selectedCsv`
- `selectedApp` → `_state.selectedApp`
- `selectedRule` → `_state.selectedRule`
- `loadedMtime` → `_state.loadedMtime`
- `pendingBulkEditCount` → `_state.pendingBulkEditCount`
- `syncInputs()` → `_actions.syncInputs()`
- `refreshTable()` → `_actions.refreshTable()`
- `doSave()` → `_actions.doSave()`
- `showMsg(...)` → `UI.showMsg(...)` (already imported)
- `formatDailyLimitMsg(...)` → `UI.formatDailyLimitMsg(...)`
- `restPost(...)` → `restPost(...)` (already aliased)
- `submitBulkEditApproval(...)` → `_actions.submitBulkEditApproval(...)` (new callback)
- `showRemoveRowModal(...)` → keep using `_actions.showRemoveRowModal(...)` pattern — BUT this function name collision: `showRemoveRowModal` is already in `_actions`. Check if the bulk edit modal actually calls it. Looking at lines 2876: yes, it calls `showRemoveRowModal(...)` for the approval reason prompt. This is already `_actions.showRemoveRowModal`.

Add new callback to Modals.init `_actions`:
```javascript
submitBulkEditApproval: opts.actions.submitBulkEditApproval
```

Add `showBulkEditModal: showBulkEditModal` to the module's return object.

- [ ] **Step 3: Remove extracted code from entry point**

Delete lines 2691-2918 (section header through end of `showBulkEditModal`). Replace with:

```javascript
    // (showBulkEditModal → extracted to modules/wl_modals.js)
```

- [ ] **Step 4: Update button binding in entry point**

Change:
```javascript
$table.on("click.wl", "#btn-bulk-edit", function () { showBulkEditModal(); });
```
To:
```javascript
$table.on("click.wl", "#btn-bulk-edit", function () { Modals.showBulkEditModal(); });
```

- [ ] **Step 5: Update Modals.init in entry point — add submitBulkEditApproval callback**

In the Modals.init block, add to the actions object:

```javascript
submitBulkEditApproval: function () { return submitBulkEditApproval.apply(null, arguments); }
```

Note: `submitBulkEditApproval` is still a local function at this point (moves to ApprovalUI in Task 6). The late-binding trampoline handles this.

- [ ] **Step 6: Run deploy protocol**

Bump build to 533. Deploy. Verify:
- Select a rule + CSV, check some row checkboxes
- Click "Bulk Edit" button → modal appears
- Select a column, enter a value, click Apply
- Verify values are applied to selected rows
- If Expires column selected, verify date picker sub-UI appears in modal
- Check console for errors

- [ ] **Step 7: Commit**

```bash
git add appserver/static/modules/wl_modals.js appserver/static/whitelist_manager.js default/app.conf
git commit -m "feat(modularize): add showBulkEditModal to wl_modals.js — Group D (Wave 3 Step 5)"
```

---

## Task 6: Extract `wl_approval_ui.js`

**Files:**
- Create: `appserver/static/modules/wl_approval_ui.js`
- Modify: `appserver/static/whitelist_manager.js` (remove lines 824-1382, add require dep + init)
- Modify: `default/app.conf` (bump build)

This is the largest extraction — 433 lines across 3 source regions.

- [ ] **Step 1: Create `wl_approval_ui.js` module**

Create `appserver/static/modules/wl_approval_ui.js`. Extract these source ranges:
- Lines 824-1055: `submitApprovalRequest`, `submitBulkEditApproval`, `submitInlineMultiEditApproval`
- Lines 1057-1141: `buildLockedState`, `applyPendingCssHighlighting`, `extractApprovalReason`, `getPendingRowIndices`
- Lines 1143-1145: `pendingFilterActive`, `pendingFilterIndices` declarations
- Lines 1146-1382: `applyPendingHighlighting`, `bindApprovalActions`, `showAdditionPreview`, `renderAdditionPreview`

Module structure:
```javascript
define(["jquery", "underscore",
        "app/wl_manager/modules/wl_rest",
        "app/wl_manager/modules/wl_ui"],
function ($, _, REST, UI) {
    "use strict";

    var restGet  = REST.restGet;
    var restPost = REST.restPost;
    var showMsg  = UI.showMsg;
    var formatDailyLimitMsg = UI.formatDailyLimitMsg;

    var _state = null;
    var _$table = null;
    var _$revertSelect = null;
    var _actions = null;

    var additionPreviewPage = 0;
    var additionPreviewData = null;
    var PREVIEW_PAGE_SIZE = 10;

    // ... all 13 functions pasted here ...

    return {
        init: function (opts) {
            _$table = opts.$table;
            _$revertSelect = opts.$revertSelect;
            _state = opts.state;
            _actions = opts.actions;
        },
        submitApprovalRequest: submitApprovalRequest,
        submitBulkEditApproval: submitBulkEditApproval,
        submitInlineMultiEditApproval: submitInlineMultiEditApproval,
        applyPendingHighlighting: applyPendingHighlighting,
        applyPendingCssHighlighting: applyPendingCssHighlighting,
        buildLockedState: buildLockedState,
        getPendingRowIndices: getPendingRowIndices,
        clearPendingFilter: function () {
            _state.pendingFilterActive = false;
            _state.pendingFilterIndices = null;
            additionPreviewData = null;
        }
    };
});
```

Key changes (apply to ALL extracted functions):
- All state vars (`currentRows`, `currentHeaders`, `originalRows`, `selectedCsv`, `selectedApp`, `selectedRule`, `loadedMtime`, `csvLocked`, `saving`, `pendingBulkEditCount`, `pendingApprovals`, `isAdmin`, `pendingFilterActive`, `pendingFilterIndices`) → prefix with `_state.`
- `syncInputs()` → `_actions.syncInputs()`
- `refreshTable()` → `_actions.refreshTable()`
- `loadCsv(...)` → `_actions.loadCsv(...)`
- `showRemoveRowModal(...)` → `_actions.showRemoveRowModal(...)`
- `showApproveConfirmModal(...)` → `_actions.showApproveConfirmModal(...)`
- `showRejectReasonModal(...)` → `_actions.showRejectReasonModal(...)`
- `showCancelRequestModal(...)` → `_actions.showCancelRequestModal(...)`
- `getCurrentUser()` → `_actions.getCurrentUser()`
- `Table.resetPage()` → `_actions.resetPage()`
- `showMsg(...)` → `showMsg(...)` (aliased from UI at module top)
- `restPost(...)` → `restPost(...)` (aliased from REST at module top)
- `$table` → `_$table`
- `$revertSelect` → `_$revertSelect`

- [ ] **Step 2: Add 2 new state proxy properties in entry point**

In the `_tableState` proxy IIFE (around line 154-177), add:

```javascript
prop("pendingApprovals",  function () { return pendingApprovals; },  function (v) { pendingApprovals = v; });
prop("isAdmin",           function () { return isAdmin; },           function (v) { isAdmin = v; });
```

- [ ] **Step 3: Update entry point — add ApprovalUI to require array**

Add `"app/wl_manager/modules/wl_approval_ui"` after `wl_presence`. Add `ApprovalUI` to callback params.

- [ ] **Step 4: Add ApprovalUI.init() call**

Add after `Presence.init()`:

```javascript
// ── ApprovalUI module init ──
ApprovalUI.init({
    $table:        $table,
    $revertSelect: $revertSelect,
    state:         _tableState,
    actions: {
        syncInputs:              function () { return syncInputs(); },
        refreshTable:            function () { return refreshTable(); },
        loadCsv:                 function () { return loadCsv.apply(null, arguments); },
        showRemoveRowModal:      function () { return Modals.showRemoveRowModal.apply(null, arguments); },
        showApproveConfirmModal: function () { return Modals.showApproveConfirmModal.apply(null, arguments); },
        showRejectReasonModal:   function () { return Modals.showRejectReasonModal.apply(null, arguments); },
        showCancelRequestModal:  function () { return Modals.showCancelRequestModal.apply(null, arguments); },
        getCurrentUser:          function () { return Presence.getCurrentUser(); },
        resetPage:               function () { return Table.resetPage(); }
    }
});
```

- [ ] **Step 5: Remove extracted code from entry point**

Delete lines 824-1382 (from `submitApprovalRequest` through `renderAdditionPreview`). Also delete `pendingFilterActive` and `pendingFilterIndices` var declarations (they move to module as state proxy props). Replace with:

```javascript
    // (Approval UI — submission, pending state, highlighting →
    //  extracted to modules/wl_approval_ui.js)
```

- [ ] **Step 6: Update all call sites in entry point**

Search and replace:
- `submitApprovalRequest(...)` → `ApprovalUI.submitApprovalRequest(...)`
- `submitBulkEditApproval(...)` → `ApprovalUI.submitBulkEditApproval(...)`
- `submitInlineMultiEditApproval(...)` → `ApprovalUI.submitInlineMultiEditApproval(...)`
- `applyPendingHighlighting()` → `ApprovalUI.applyPendingHighlighting()`
- `applyPendingCssHighlighting()` → `ApprovalUI.applyPendingCssHighlighting()`
- `buildLockedState()` → `ApprovalUI.buildLockedState()`
- `getPendingRowIndices(...)` → `ApprovalUI.getPendingRowIndices(...)`

Also update the admin detection IIFE (line 91):
```javascript
ApprovalUI.applyPendingHighlighting();
```

And update Table.init actions:
```javascript
submitApprovalRequest:       function () { return ApprovalUI.submitApprovalRequest.apply(null, arguments); },
applyPendingCssHighlighting: function () { return ApprovalUI.applyPendingCssHighlighting(); },
```

And update Modals.init actions:
```javascript
submitBulkEditApproval: function () { return ApprovalUI.submitBulkEditApproval.apply(null, arguments); },
```

- [ ] **Step 7: Run deploy protocol**

Bump build to 534. Deploy. Verify:
- Load a CSV with pending approvals → orange highlighting appears, lock banner shows
- Approve/Reject/Cancel buttons work (admin view)
- Submit a new approval request (add 3+ rows, save) → request submitted
- "Show Requested Rows" filter works
- Addition preview renders for pending bulk additions
- Check console for errors

- [ ] **Step 8: Commit**

```bash
git add appserver/static/modules/wl_approval_ui.js appserver/static/whitelist_manager.js default/app.conf
git commit -m "feat(modularize): extract wl_approval_ui.js — approval submission + pending UI (Wave 3 Step 6)"
```

---

**>>> USER VISUAL CHECKPOINT 2: After Task 6 <<<**

Ask user to verify in browser:
1. Approval submission works (add rows → triggers gate → submits)
2. Pending highlighting (orange rows/columns)
3. Approve/reject/cancel inline actions
4. "Show Requested Rows" filter
5. No console errors

---

## Task 7: Extract `wl_save.js`

**Files:**
- Create: `appserver/static/modules/wl_save.js`
- Modify: `appserver/static/whitelist_manager.js` (remove ~530 lines across 9 source ranges, add require dep + init)
- Modify: `default/app.conf` (bump build)

This is the most complex extraction — 15 functions from 9 non-contiguous source ranges.

- [ ] **Step 1: Create `wl_save.js` module**

Create `appserver/static/modules/wl_save.js`. Extract these source ranges:

| Function | Entry point lines |
|----------|------------------|
| `handleSaveError` | 322-345 |
| `doSaveColumnAddition` | 720-787 |
| `doSaveColumnRemoval` | 1387-1462 |
| `showUndoBar` | 1468-1513 |
| `doUndo` | 1516-1553 |
| `clearUndo` | 1556-1564 |
| `startChangeMonitoring` | 1570-1573 |
| `stopChangeMonitoring` | 1576-1578 |
| `checkForExternalChanges` | 1580-1605 |
| `hasUnsavedChanges` | 1607-1620 |
| `showExternalChangeModal` | 1622-1667 |
| `getAuditComment` | 1673-1753 |
| `doSave` | 1865-2060 |
| `doSaveRemoval` | 2065-2127 |
| `doSaveBulkRemoval` | 2132-2199 |

Module structure:
```javascript
define(["jquery", "underscore",
        "app/wl_manager/modules/wl_rest",
        "app/wl_manager/modules/wl_ui",
        "app/wl_manager/modules/wl_constants"],
function ($, _, REST, UI, C) {
    "use strict";

    var restGet  = REST.restGet;
    var restPost = REST.restPost;
    var showMsg  = UI.showMsg;
    var clearMsg = UI.clearMsg;
    var formatDailyLimitMsg = UI.formatDailyLimitMsg;

    var _state = null;
    var _$table = null;
    var _$msg = null;
    var _actions = null;

    var undoTimer = null;
    var undoState = null;
    var changeCheckTimer = null;

    // ... all 15 functions pasted here ...

    return {
        init: function (opts) {
            _$table = opts.$table;
            _$msg = opts.$msg;
            _state = opts.state;
            _actions = opts.actions;
        },
        doSave: doSave,
        doSaveRemoval: doSaveRemoval,
        doSaveBulkRemoval: doSaveBulkRemoval,
        doSaveColumnAddition: doSaveColumnAddition,
        doSaveColumnRemoval: doSaveColumnRemoval,
        handleSaveError: handleSaveError,
        showUndoBar: showUndoBar,
        clearUndo: clearUndo,
        startChangeMonitoring: startChangeMonitoring,
        stopChangeMonitoring: stopChangeMonitoring,
        hasUnsavedChanges: hasUnsavedChanges
    };
});
```

Key changes (apply to ALL extracted functions):
- All state vars → `_state.` prefix (see spec Step 7 state proxy list for the 14 properties)
- `syncInputs()` → `_actions.syncInputs()`
- `refreshTable()` → `_actions.refreshTable()`
- `loadCsv(...)` → `_actions.loadCsv(...)`
- `reloadCsvQuiet(...)` → `_actions.reloadCsvQuiet(...)`
- `loadVersions(...)` → `_actions.loadVersions(...)`
- `renderDiff(...)` → `_actions.renderDiff(...)`
- `submitApprovalRequest(...)` → `_actions.submitApprovalRequest(...)`
- `submitInlineMultiEditApproval(...)` → `_actions.submitInlineMultiEditApproval(...)`
- `showRemoveRowModal(...)` → `_actions.showRemoveRowModal(...)`
- `handleCsvRemoved(...)` → `_actions.handleCsvRemoved(...)`
- `showMsg(...)` → `showMsg(...)` (aliased at module top)
- `$table` → `_$table`
- `$msg` → `_$msg` (used in handleSaveError for click binding)
- `C.NON_ASCII_RE` and `C.ASCII_ERROR_MSG` → same (C imported directly)

- [ ] **Step 2: Update entry point — add Save to require array**

Add `"app/wl_manager/modules/wl_save"` after `wl_approval_ui`. Add `Save` to callback params.

- [ ] **Step 3: Add Save.init() call**

Add after `ApprovalUI.init()`:

```javascript
// ── Save module init ──
Save.init({
    $table: $table,
    $msg:   $msg,
    state:  _tableState,
    actions: {
        syncInputs:                    function () { return syncInputs(); },
        refreshTable:                  function () { return refreshTable(); },
        loadCsv:                       function () { return loadCsv.apply(null, arguments); },
        reloadCsvQuiet:                function () { return reloadCsvQuiet.apply(null, arguments); },
        loadVersions:                  function () { return Versions.loadVersions.apply(null, arguments); },
        renderDiff:                    function () { return Diff.renderDiff.apply(null, arguments); },
        submitApprovalRequest:         function () { return ApprovalUI.submitApprovalRequest.apply(null, arguments); },
        submitInlineMultiEditApproval: function () { return ApprovalUI.submitInlineMultiEditApproval.apply(null, arguments); },
        showRemoveRowModal:            function () { return Modals.showRemoveRowModal.apply(null, arguments); },
        handleCsvRemoved:              function () { return Presence.handleCsvRemoved.apply(null, arguments); }
    }
});
```

- [ ] **Step 4: Remove extracted code from entry point**

Delete all 9 source ranges listed in Step 1. Replace each with a comment:

```javascript
    // (handleSaveError → extracted to modules/wl_save.js)
    // (doSaveColumnAddition, doSaveColumnRemoval → extracted to modules/wl_save.js)
    // (Undo system → extracted to modules/wl_save.js)
    // (External change detection → extracted to modules/wl_save.js)
    // (getAuditComment → extracted to modules/wl_save.js)
    // (doSave, doSaveRemoval, doSaveBulkRemoval → extracted to modules/wl_save.js)
```

- [ ] **Step 5: Update all call sites in entry point**

Update Table.init actions:
```javascript
doSave:               function () { return Save.doSave(); },
doSaveRemoval:        function () { return Save.doSaveRemoval.apply(null, arguments); },
doSaveBulkRemoval:    function () { return Save.doSaveBulkRemoval.apply(null, arguments); },
doSaveColumnAddition: function () { return Save.doSaveColumnAddition.apply(null, arguments); },
handleSaveError:      function () { return Save.handleSaveError.apply(null, arguments); },
clearUndo:            function () { return Save.clearUndo(); },
```

Update Versions.init actions:
```javascript
handleSaveError: function () { return Save.handleSaveError.apply(null, arguments); },
```

Update `doColumnRemoveWithGateCheck` (stays in entry point):
```javascript
doSaveColumnRemoval(colName, reason);  →  Save.doSaveColumnRemoval(colName, reason);
```

Update Presence.init actions:
```javascript
stopChangeMonitoring: function () { Save.stopChangeMonitoring(); }
```

Update remaining entry point call sites:
- `startChangeMonitoring()` → `Save.startChangeMonitoring()`
- `stopChangeMonitoring()` → `Save.stopChangeMonitoring()`
- `clearUndo()` → `Save.clearUndo()`
- `hasUnsavedChanges()` → `Save.hasUnsavedChanges()`
- `handleSaveError(...)` → `Save.handleSaveError(...)`

Also remove stale var declarations: `undoTimer`, `undoState`, `saving` debounce flag stays in state proxy, `changeCheckTimer`.

- [ ] **Step 6: Run deploy protocol**

Bump build to 535. Deploy. Verify:
- Edit a cell → Save → success message + diff display
- Remove a row → auto-save → undo bar appears (10s countdown)
- Click Undo → row restored
- Bulk remove (select + remove) → saves correctly
- Add a column → saves
- Remove a column → gate check → saves or submits approval
- External change detection: open CSV in two tabs, save in one → other shows "CSV changed externally" modal
- Optimistic lock conflict: verify handleSaveError shows reload link
- Comment validation: edit CSV without Comment column → audit comment modal appears
- Check console for errors

- [ ] **Step 7: Run circular chain test**

Test the full chain from spec risk assessment:
- Edit 2+ rows → Save → verify approval submission triggers → CSV reloads → pending highlighting appears → change monitoring restarts
- This exercises: `Save.doSave()` → `ApprovalUI.submitApprovalRequest()` → `loadCsv()` → `ApprovalUI.applyPendingHighlighting()` → `Save.startChangeMonitoring()`

- [ ] **Step 8: Commit**

```bash
git add appserver/static/modules/wl_save.js appserver/static/whitelist_manager.js default/app.conf
git commit -m "feat(modularize): extract wl_save.js — save pipeline, undo, change detection (Wave 3 Step 7)"
```

---

## Task 8: Entry Point Cleanup

**Files:**
- Modify: `appserver/static/whitelist_manager.js`
- Modify: `default/app.conf` (bump build)

- [ ] **Step 1: Remove all extracted placeholder comments**

Search for `// (... → extracted to modules/...)` comments and remove them. They served as navigation aids during extraction but are now clutter.

- [ ] **Step 2: Remove stale variable declarations**

Check for `var` declarations that no longer have any references:
- `undoTimer`, `undoState` — moved to Save module
- `changeCheckTimer` — moved to Save module
- `additionPreviewPage`, `additionPreviewData`, `PREVIEW_PAGE_SIZE` — moved to ApprovalUI
- Any stale aliases (`var renderDiff = ...`, etc.)

- [ ] **Step 3: Remove stale module aliases**

Check if any Wave 1-2 extraction aliases (the `var xxx = Module.xxx` pattern) are no longer used:
- `var renderDiff = Diff.renderDiff` — still needed? (used in Versions.init trampoline? No — trampoline uses `Diff.renderDiff` directly). Remove if unused.
- `var csvEscape = CsvIO.csvEscape` — still needed? Remove if unused.
- Check all `var xxx = Module.xxx` patterns.

- [ ] **Step 4: Clean up the admin detection IIFE**

Verify it uses `ApprovalUI.applyPendingHighlighting()` (not the old local function).

- [ ] **Step 5: Verify entry point line count**

Run `wc -l appserver/static/whitelist_manager.js`. Target: ~1530 lines (acceptable range: 1400-1650).

- [ ] **Step 6: Run deploy protocol**

Bump build to 536. Deploy.

- [ ] **Step 7: Commit**

```bash
git add appserver/static/whitelist_manager.js default/app.conf
git commit -m "chore(modularize): entry point cleanup — remove dead code and stale aliases (Wave 3 Step 8)"
```

---

**>>> USER VISUAL CHECKPOINT 3: Full Regression <<<**

Ask user to verify ALL features in browser:

1. **Navigation**: Select rule → CSV list populates → select CSV → table loads
2. **Editing**: Edit cells inline → Save → diff display shows changes
3. **Row operations**: Add row, remove row (single + bulk) → undo bar works
4. **Column operations**: Add column, remove column
5. **Search**: Type in search bar → rows filter → clear button works
6. **Import/Export**: Export CSV, import CSV (merge + replace)
7. **Versions**: Revert dropdown shows versions → revert works
8. **Approval workflow**: Submit request → orange highlighting → approve/reject/cancel
9. **Bulk edit**: Select rows → bulk edit modal → apply values
10. **Date picker**: Click Expires cell → picker appears → presets + manual entry
11. **Audit export**: Click Export Audit → CSV downloads
12. **Presence**: "Also viewing:" bar appears when multiple sessions open
13. **External changes**: Edit in another tab → "CSV changed externally" modal
14. **Keyboard shortcuts**: Ctrl+S (save), Ctrl+Z (undo cell edit), Escape (close)
15. **Theme**: Dark/light theme renders correctly
16. **No console errors** throughout all tests

---

## Post-Wave-3 Cleanup (separate session)

Not part of this plan, but noted for future:
- Remove `wl_debug.js` from both entry points (`whitelist_manager.js` and `control_panel.js`)
- Update `project_frontend_modularization.md` memory with Wave 3 completion status
- Update `MEMORY.md` with lessons learned
