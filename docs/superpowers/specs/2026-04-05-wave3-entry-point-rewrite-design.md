# Wave 3: Entry Point Rewrite — Design Spec

**Date**: 2026-04-05
**Author**: Oleh + Claude
**Status**: Approved
**Approach**: A (Aggressive extraction, phased)

## Overview

Reduce `whitelist_manager.js` from 3390 lines to ~1530 lines by extracting 5 new AMD modules and extending 2 existing modules. The entry point retains state declarations, DOM setup, module wiring, rule/CSV navigation, and core orchestration.

## Decisions Record

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Rule/CSV nav (~363 lines) | Keep in entry point | Core navigation glue; extracting adds module init overhead for modest savings |
| Admin action bar binding (~100 lines) | Keep in entry point | Thin event handlers calling already-extracted modals; consistent with nav decision |
| Approval UI scope | Submission + pending only | `bindApprovalActions` moves with `applyPendingHighlighting` (called only by it, not standalone wiring) |
| Save + renderDiff | Split into `wl_save.js` + `wl_diff.js` | renderDiff is a pure renderer; save is all side effects. Different concerns, different testability |
| Audit export | Add to `wl_csv_io.js` | "Anything that produces or consumes CSV" — `csvEscape` already there |
| Bulk edit modal | Add to `wl_modals.js` | "All modals in one place" — consistent with Groups A/B/C pattern |
| Phase 5 leftovers | Delete all upfront | Clean slate; avoids confusion about which files are "real" |

## Step 0: Delete Phase 5-6 Leftovers

Delete these dead module files (not imported by current entry point):

| File | Lines | Origin |
|------|-------|--------|
| `wl_state.js` | 295 | Phase 5 (`92f8643`) |
| `wl_orchestrator.js` | 406 | Phase 5 (`f2fd003`) |
| `wl_approval_ui.js` | 205 | Phase 5 (`fb99e5c`) |
| `wl_presence.js` | 208 | Phase 5 (`80f815b`) |
| `wl_cp_admin_limits.js` | 221 | Phase 5 CP |
| `wl_cp_limits.js` | 314 | Phase 5 CP |
| `wl_cp_modals.js` | 150 | Phase 5 CP |
| `wl_cp_queue.js` | 465 | Phase 5 CP |
| `wl_cp_trash.js` | 339 | Phase 5 CP |
| `wl_cp_usage.js` | 341 | Phase 5 CP |

**Total: 2,944 lines of dead code.** Single commit, no functional change.

## Step 1: `wl_diff.js` (~243 lines) — NEW MODULE

### Purpose
Git-style diff rendering after saves and reverts. Pure rendering function — takes a diff object, builds HTML.

### Source lines
2204-2443 (entry point)

### Functions
- `renderDiff(diff)` — builds complete diff HTML: stats bar, column change badges, side-by-side edited row comparison with smart column selection, added/removed row lists, expandable overflow

### Internal constants
- `DIFF_MAX_ROWS = 10`
- `DIFF_MAX_COLS = 8`

### Dependencies
- jQuery, underscore (Splunk builtins)
- No other modules

### Public API
```javascript
define(["jquery", "underscore"], function ($, _) {
    return {
        init: function (opts) { /* opts: { $diff } */ },
        renderDiff: renderDiff
    };
});
```

### Consumers
- `wl_save.js` — after every successful save (5 save functions)
- `wl_versions.js` — after revert
- Both receive `renderDiff` through `actions` callbacks

## Step 2: `wl_datepicker.js` (~168 lines) — NEW MODULE

### Purpose
Date/time picker UI for Expires column cells. Presets (7d/30d/6mo/1y), manual date+time input, UTC conversion for storage, local display.

### Source lines
2449-2612 (entry point)

### Functions
- `padTwo(n)` — zero-pad helper
- `formatDateForPicker(d)` — YYYY-MM-DD from Date
- `formatLocalDateTime(d)` — YYYY-MM-DD HH:MM local
- `formatUTCDateTime(d)` — YYYY-MM-DD HH:MM UTC
- `createDatePicker()` — lazy-creates picker DOM, binds preset/apply/clear/cancel
- `showDatePicker($input)` — positions picker below input, reads stored UTC value
- `closeDatePicker()` — hides picker, clears active input ref

### Internal state (module-private)
- `$datePicker` — cached jQuery ref
- `$activeExpiresInput` — currently active input

### Dependencies
- jQuery (Splunk builtin)
- State proxy: reads/writes `currentRows[idx][header]`

### Public API
```javascript
define(["jquery"], function ($) {
    return {
        init: function (opts) { /* opts: { state } */ },
        showDatePicker: showDatePicker,
        closeDatePicker: closeDatePicker,
        formatLocalDateTime: formatLocalDateTime
    };
});
```

### Event binding stays in entry point (2 delegated handlers)
```javascript
$table.on("click.wl", ".wl-expires-input", function (e) {
    e.stopPropagation();
    DatePicker.showDatePicker($(this));
});
$(document).on("click", function (e) { /* close-on-outside-click */ });
```

## Step 3: `wl_presence.js` (~216 lines) — NEW MODULE

### Purpose
Real-time collaboration indicators — polls server every 15s, reports which users are viewing the same CSV, handles idle timeout (30min), renders "Also viewing:" bar, shows modals for busy/deleted CSV.

### Source lines
3068-3279 (entry point)

### Functions
- `getCurrentUser()` — extracts username from Splunk JS SDK or DOM fallback
- `startPresenceMonitoring()` — starts 15s polling
- `stopPresenceMonitoring()` — clears interval
- `reportPresence()` — REST call, handles `presence_full`, `idle_kicked`, 404
- `showPresenceFullModal(message)` — "CSV Busy" modal
- `handleCsvRemoved(csvName)` — "CSV Removed" modal, stops monitoring, resets state
- `renderPresenceBar(users)` — "Also viewing: user1, user2" bar with overflow toggle
- `updateActivity()` — resets `lastActivityTime` (called by entry point's activity tracker)

### Internal state (module-private)
- `presenceTimer` — setInterval ID
- `currentUser` — cached username
- `lastActivityTime` — last interaction timestamp
- `IDLE_TIMEOUT_MS` — 30min constant

### Dependencies
- jQuery, underscore, `splunkjs/mvc` (Splunk builtins)
- `wl_rest` (for `restGet`)

### Callbacks via `actions`
- `onDismiss()` — triggers `$ruleClear.click()` to reset to initial state
- `stopChangeMonitoring()` — stops Save module's mtime polling

### Public API
```javascript
define(["jquery", "underscore", "splunkjs/mvc",
        "app/wl_manager/modules/wl_rest"],
function ($, _, mvc, REST) {
    return {
        init: function (opts) { /* opts: { $table, state, actions } */ },
        startPresenceMonitoring: startPresenceMonitoring,
        stopPresenceMonitoring: stopPresenceMonitoring,
        handleCsvRemoved: handleCsvRemoved,
        getCurrentUser: getCurrentUser,
        updateActivity: updateActivity
    };
});
```

## Step 4: Extend `wl_csv_io.js` (+145 lines)

### Added function
- `exportAuditCsv()` — runs Splunk search on `wl_audit` index, formats results as CSV, triggers download via blob URL

### Added internal helper
- `splEscape(val)` — escapes values for Splunk search query syntax

### Dependencies
- `restGet` (already imported)
- State proxy: reads `selectedCsv`, `selectedRule` (already available)

### No new callbacks needed
Self-contained function. Uses `UI.showMsg` (already a direct dependency).

### Updated public API
```javascript
// Add to existing return object:
exportAuditCsv: exportAuditCsv
```

## Step 5: Extend `wl_modals.js` (+226 lines)

### Added function
- `showBulkEditModal()` — Group D modal. Applies a single value to a column across selected rows. Includes inline date picker sub-UI for Expires columns, approval gate check, local apply logic.

### Note on internal date picker
The bulk edit modal has its own simplified date picker (presets + time input) embedded inline within the modal DOM. This is intentionally separate from `wl_datepicker.js` — different UX pattern (inline vs positioned popup), different lifecycle. Merging would create coupling for no benefit.

### New callback in `actions`
- `submitBulkEditApproval(col, val, rowIndices, changedCount, reason)` — from ApprovalUI

### State proxy
Already has `currentRows`, `currentHeaders`, `csvLocked`, `saving`. No new props needed.

### Updated public API
```javascript
// Add to existing return object:
showBulkEditModal: showBulkEditModal
```

## Step 6: `wl_approval_ui.js` (~433 lines) — NEW MODULE

### Purpose
Approval workflow submission (3 submit functions), pending state management (locked state, CSS highlighting, row filtering), and addition preview table for pending row-addition requests.

### Source lines
824-1055 (submission), 1057-1141 (pending state helpers), 1143-1382 (pending highlighting + addition preview)

### Functions

**Submission group:**
- `submitApprovalRequest(actionType, reason, rowIndices, colName)` — generic submission for bulk removal, bulk addition, column removal
- `submitBulkEditApproval(col, val, rowIndices, changedCount, reason)` — bulk edit submission
- `submitInlineMultiEditApproval(changedCount, reason)` — inline multi-row edit submission

**Pending state group:**
- `buildLockedState()` — sets `csvLocked` from `pendingApprovals.length`
- `applyPendingCssHighlighting()` — adds `.wl-pending-approval` classes to matching rows/columns/table
- `extractApprovalReason(pa)` — extracts analyst reason from different action types
- `getPendingRowIndices(pa)` — counter-based matching of pending row_keys to current rows

**Pending UI group:**
- `applyPendingHighlighting()` — master function: CSS highlighting + lock controls + build approval action bar + call `bindApprovalActions()`
- `bindApprovalActions()` — wires approve/reject/cancel/filter buttons
- `showAdditionPreview(pa)` — initiates read-only preview of rows pending addition
- `renderAdditionPreview()` — renders paginated preview table

### Internal state (module-private)
- `additionPreviewPage` — current preview page
- `additionPreviewData` — `{ headers, rowKeys }`
- `PREVIEW_PAGE_SIZE` — 10

### Dependencies
- jQuery, underscore (Splunk builtins)
- `wl_rest` (for `restGet`, `restPost`)
- `wl_ui` (for `showMsg`, `formatDailyLimitMsg`)

### State proxy access
Reads/writes (existing props): `currentRows`, `currentHeaders`, `originalRows`, `selectedCsv`, `selectedApp`, `selectedRule`, `loadedMtime`, `csvLocked`, `saving`, `pendingBulkEditCount`, `pendingFilterActive`, `pendingFilterIndices`
Reads/writes (new props added in Wave 3): `pendingApprovals`, `isAdmin`

### Callbacks via `actions`
- `syncInputs()` — from Table
- `refreshTable()` — from Table
- `loadCsv(csv, app)` — from entry point
- `showRemoveRowModal(...)` — from Modals
- `showApproveConfirmModal(id)` — from Modals
- `showRejectReasonModal(id)` — from Modals
- `showCancelRequestModal(id)` — from Modals
- `getCurrentUser()` — from Presence
- `resetPage()` — from Table

### Public API
```javascript
define(["jquery", "underscore",
        "app/wl_manager/modules/wl_rest",
        "app/wl_manager/modules/wl_ui"],
function ($, _, REST, UI) {
    return {
        init: function (opts) { /* opts: { $table, $revertSelect, state, actions } */ },
        submitApprovalRequest: submitApprovalRequest,
        submitBulkEditApproval: submitBulkEditApproval,
        submitInlineMultiEditApproval: submitInlineMultiEditApproval,
        applyPendingHighlighting: applyPendingHighlighting,
        applyPendingCssHighlighting: applyPendingCssHighlighting,
        buildLockedState: buildLockedState,
        getPendingRowIndices: getPendingRowIndices,
        clearPendingFilter: function () {
            pendingFilterActive = false;
            pendingFilterIndices = null;
            additionPreviewData = null;
        }
    };
});
```

### What stays in entry point
- `doColumnRemoveWithGateCheck()` (source lines 792-822, ~30 lines) — orchestration across ApprovalUI + Save + Modals

## Step 7: `wl_save.js` (~530 lines) — NEW MODULE

### Purpose
Full save pipeline — all 5 save functions, undo system, comment validation modal, conflict error handling, and external change detection.

### Source lines
322-345 (handleSaveError), 720-787 (doSaveColumnAddition), 1387-1462 (doSaveColumnRemoval), 1465-1564 (undo), 1567-1667 (external change detection), 1670-1753 (getAuditComment), 1865-2060 (doSave), 2065-2127 (doSaveRemoval), 2132-2199 (doSaveBulkRemoval)

### Functions

**Save functions:**
- `doSave()` — full save with pre-save gate checks, approval routing, empty row cleanup
- `doSaveRemoval(removedRow, reason, rowNumber, prevRows, prevOriginal)` — auto-save after single row removal
- `doSaveBulkRemoval(removedEntries, reason, prevRows, prevOriginal)` — auto-save after bulk removal
- `doSaveColumnAddition(colName)` — save after adding a column
- `doSaveColumnRemoval(colName, reason)` — save after removing a column

**Support functions:**
- `handleSaveError(xhr, fallbackMsg)` — optimistic lock conflict handling with reload link
- `getAuditComment(callback)` — comment validation + modal when CSV lacks Comment column

**Undo system:**
- `showUndoBar(removedRow, prevRows, prevOriginal, removedColName, prevHeaders, prevOrigHeaders)` — 10-second countdown
- `doUndo()` — restores previous state and saves to server
- `clearUndo()` — clears timer and state

**External change detection:**
- `startChangeMonitoring()` — starts 5s mtime polling
- `stopChangeMonitoring()` — clears interval
- `checkForExternalChanges()` — polls `check_csv_status`, triggers reload or conflict modal
- `hasUnsavedChanges()` — compares current vs original rows/headers
- `showExternalChangeModal()` — "CSV changed externally" modal

### Internal state (module-private)
- `undoTimer`, `undoState` — undo countdown
- `changeCheckTimer` — mtime polling

### Dependencies
- jQuery, underscore (Splunk builtins)
- `wl_rest` (for `restGet`, `restPost`)
- `wl_ui` (for `showMsg`, `clearMsg`, `formatDailyLimitMsg`)
- `wl_constants` (for `NON_ASCII_RE`, `ASCII_ERROR_MSG`)

### State proxy access
Reads/writes (existing props): `currentRows`, `currentHeaders`, `originalRows`, `originalHeaders`, `selectedCsv`, `selectedApp`, `selectedRule`, `loadedMtime`, `loadedPendingCount`, `saving`, `csvLocked`, `pendingBulkEditCount`, `expireColumn`, `searchQuery`

Note: Save and ApprovalUI access different subsets of the proxy. Neither module writes the other's props. No cross-module state conflicts.

### Callbacks via `actions`
- `syncInputs()` — from Table
- `refreshTable()` — from Table
- `loadCsv(csv, app)` — from entry point
- `reloadCsvQuiet(cb)` — from entry point
- `loadVersions(csv, app)` — from Versions
- `renderDiff(diffInfo)` — from Diff
- `submitApprovalRequest(...)` — from ApprovalUI
- `submitInlineMultiEditApproval(...)` — from ApprovalUI
- `showRemoveRowModal(...)` — from Modals
- `handleCsvRemoved(csvName)` — from Presence

### Public API
```javascript
define(["jquery", "underscore",
        "app/wl_manager/modules/wl_rest",
        "app/wl_manager/modules/wl_ui",
        "app/wl_manager/modules/wl_constants"],
function ($, _, REST, UI, C) {
    return {
        init: function (opts) { /* opts: { $table, $msg, state, actions } */ },
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

### Why undo and external change detection belong here
Both are tightly coupled to the save lifecycle:
- Undo calls `restPost` with `save_csv`, references `loadedMtime`, calls `reloadCsvQuiet` — it IS a save operation
- External change detection manages `loadedMtime` conflict state — it's the other side of optimistic locking
- Together they own the complete `loadedMtime` lifecycle: set on save response, checked by polling, conflict-handled on mismatch

## Step 8: Entry Point Cleanup

### What remains (~1530 lines)

| Area | Lines | Purpose |
|------|-------|---------|
| State + admin detection | ~35 | Shared state vars, IIFE admin role check |
| DOM refs + module init | ~230 | Element lookups, JS-built DOM, `_tableState` proxy, 12 module inits |
| Rule/CSV navigation | ~363 | `loadRules`, `renderRuleList`, `filterRules`, `selectRule`, `renderCsvList`, `selectCsvItem`, `updateUrlParams`, `onCsvSelected`, dropdown event bindings |
| Core orchestration | ~170 | `loadCsv`, `reloadCsvQuiet`, `doColumnRemoveWithGateCheck`, activity tracker, notification listener |
| Event bindings | ~80 | Expires click, search, keyboard shortcuts, button bindings |
| Hooks + init | ~35 | Presence hooks, `beforeunload`, URL param parsing |
| Comments/whitespace | ~120 | Section dividers, extracted placeholders |
| **Total** | **~1530** | |

### State proxy additions (2 new properties)

```javascript
prop("pendingApprovals", function () { return pendingApprovals; }, function (v) { pendingApprovals = v; });
prop("isAdmin",          function () { return isAdmin; },          function (v) { isAdmin = v; });
```

Note: The existing 18 properties (`currentHeaders`, `originalHeaders`, `currentRows`, `originalRows`, `selectedRule`, `selectedCsv`, `selectedApp`, `expireColumn`, `searchQuery`, `csvLocked`, `saving`, `loadedMtime`, `pendingBulkEditCount`, `pendingFilterActive`, `pendingFilterIndices`, `mappingData`, `reasonGates`, `allRules`) are carried forward unchanged from Wave 2.

### Admin detection timing fix

The admin role detection IIFE (line 84-94) calls `applyPendingHighlighting()` asynchronously. After Wave 3, this function lives in `ApprovalUI` module. The call must use a late-binding trampoline to ensure it resolves at call-time (after all inits complete):

```javascript
(function detectAdminRole() {
    restGet({ action: "get_approval_queue" })
    .done(function () {
        isAdmin = true;
        if (pendingApprovals.length) {
            ApprovalUI.applyPendingHighlighting();  // safe: async callback fires after all inits
        }
    });
})();
```

This is safe because: (1) the IIFE fires an async REST call, (2) the `.done()` callback executes on a future event loop tick, (3) all module inits run synchronously before the first event loop yield. The callback will always fire after `ApprovalUI.init()` completes.

### Require array (final)
```javascript
require([
    "jquery", "underscore", "splunkjs/mvc", "splunkjs/mvc/utils",
    "app/wl_manager/modules/wl_constants",
    "app/wl_manager/modules/wl_rest",
    "app/wl_manager/modules/wl_ui",
    "app/wl_manager/modules/wl_table",
    "app/wl_manager/modules/wl_versions",
    "app/wl_manager/modules/wl_modals",
    "app/wl_manager/modules/wl_csv_io",
    "app/wl_manager/modules/wl_diff",
    "app/wl_manager/modules/wl_datepicker",
    "app/wl_manager/modules/wl_presence",
    "app/wl_manager/modules/wl_approval_ui",
    "app/wl_manager/modules/wl_save",
    "app/wl_manager/modules/wl_debug",
    "splunkjs/mvc/simplexml/ready!"
], function ($, _, mvc, utils, C, REST, UI, Table, Versions, Modals,
             CsvIO, Diff, DatePicker, Presence, ApprovalUI, Save, Debug) {
```

### Module init wiring (new modules only)
```javascript
Diff.init({ $diff: $diff });

DatePicker.init({ state: _tableState });

Presence.init({
    $table: $table,
    state:  _tableState,
    actions: {
        onDismiss:            function () { $ruleClear.trigger("click"); },
        stopChangeMonitoring: function () { Save.stopChangeMonitoring(); }
    }
});

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

### Updated existing module inits

**Table.init `actions`** — replace local function refs:
- `handleSaveError` → `Save.handleSaveError`
- `doSave` → `Save.doSave`
- `doSaveRemoval` → `Save.doSaveRemoval`
- `doSaveBulkRemoval` → `Save.doSaveBulkRemoval`
- `doSaveColumnAddition` → `Save.doSaveColumnAddition`
- `submitApprovalRequest` → `ApprovalUI.submitApprovalRequest`
- `clearUndo` → `Save.clearUndo`
- `applyPendingCssHighlighting` → `ApprovalUI.applyPendingCssHighlighting`
- `formatLocalDateTime` → `DatePicker.formatLocalDateTime`

**Versions.init `actions`** — update:
- `renderDiff` → `Diff.renderDiff`
- `handleSaveError` → `Save.handleSaveError`

**Modals.init `actions`** — add:
- `submitBulkEditApproval` → `ApprovalUI.submitBulkEditApproval`

(All via late-binding trampolines: `function () { return Module.fn.apply(null, arguments); }`)

## Extraction Order and Dependencies

```
Step 0: Delete Phase 5 leftovers           (no deps, no functional change)
Step 1: wl_diff.js                          jQuery, underscore only
Step 2: wl_datepicker.js                    jQuery + state proxy
Step 3: wl_presence.js                      jQuery, underscore, mvc, wl_rest
Step 4: wl_csv_io.js (extend)              adds exportAuditCsv, no new deps
Step 5: wl_modals.js (extend)              adds showBulkEditModal
Step 6: wl_approval_ui.js                  wl_rest, wl_ui + callbacks
Step 7: wl_save.js                         wl_rest, wl_ui, wl_constants + callbacks
Step 8: Entry point cleanup                remove dead code, final wiring
```

### Why this order
- Steps 1-3 are independent (zero cross-dependencies), sequential for safe deploy+test
- Step 1 (Diff) first — consumed by both Save (Step 7) and Versions (already extracted)
- Step 2 (DatePicker) second — simplest extraction, no callbacks
- Step 3 (Presence) third — `handleCsvRemoved` needed by Save (Step 7)
- Steps 4-5 (extensions) before modules that consume them
- Step 6 (ApprovalUI) before Step 7 (Save) — `doSave` calls `submitApprovalRequest`
- Step 7 (Save) last — most connected module, depends on 6 other modules
- Step 8 (cleanup) — final dead code removal, extracted comment placeholders

## Testing Protocol (per step)

1. Extract module / extend existing module
2. Update entry point: add `require()` dep, init block, remove extracted code
3. `docker cp` all changed files
4. Bump `build` in `app.conf`
5. Clear Splunk caches (`rm -rf` i18n + static/app + static/build)
6. `chown -R splunk:splunk` static dir
7. Stop + start Splunk
8. Test in browser: verify feature works, check console for errors
9. Commit atomically

### User visual checkpoints
- **After Step 3** — date picker, presence bar, diff display
- **After Step 6** — approval workflow (submit, highlight, approve/reject/cancel)
- **After Step 8** — full regression: save, remove, undo, revert, import, export, bulk edit, keyboard shortcuts

## Risk Assessment

### High risk

**1. Circular callback chains**
`Save.doSave()` → `ApprovalUI.submitApprovalRequest()` → `loadCsv()` → `ApprovalUI.applyPendingHighlighting()` → indirectly `Save.startChangeMonitoring()`.
**Mitigation**: All cross-module calls go through late-binding trampolines. No Wave 3 module imports another directly. Circular references structurally impossible at AMD level.
**Runtime safety**: The chain is safe because each link is async (REST `.done()` callbacks). `doSave` returns immediately after posting; `submitApprovalRequest`'s `.done()` calls `loadCsv`; `loadCsv`'s `.done()` calls `applyPendingHighlighting` + `startChangeMonitoring`. No two steps execute in the same synchronous call stack, so no re-entrancy or state race is possible.
**Test case**: After Step 7, test: edit 2+ rows → Save → verify approval submission → verify CSV reloads → verify pending highlighting appears → verify change monitoring restarts. This exercises the full circular chain.

**2. State proxy property count (20 properties)**
**Mitigation**: ~40 lines of boilerplate. Acceptable vs separate state module (Phase 5 failure). No action unless >30 properties.

**3. `handleCsvRemoved` called from two modules**
Both Presence (404 on report_presence) and Save (404 on check_csv_status) need it.
**Mitigation**: Lives in Presence. Save receives it as `actions.handleCsvRemoved` callback.

**4. Dual date picker implementations**
Bulk edit modal has inline picker; `wl_datepicker.js` has positioned popup.
**Mitigation**: Intentionally separate — different UX, different lifecycle. Documented as design decision.

### Medium risk

**5. Module init order**
Save.init() must run after ApprovalUI, Presence, Diff.
**Mitigation**: Late-binding trampolines defer resolution to call-time. No module calls actions during init. Order follows dependency graph.

**6. `wl_debug.js` removal**
**Mitigation**: Keep through Wave 3, remove in post-Wave-3 cleanup commit.

### Low risk

**7. Deploy cache issues** — mitigated by 7-step deploy protocol.
**8. `wl_csv_io.js` at ~1170 lines** — independent functions, no shared internal state.

## Summary

| Component | Type | Lines | Step |
|-----------|------|-------|------|
| Phase 5 leftovers | Delete | -2,944 | 0 |
| `wl_diff.js` | New module | ~243 | 1 |
| `wl_datepicker.js` | New module | ~168 | 2 |
| `wl_presence.js` | New module | ~216 | 3 |
| `wl_csv_io.js` | Extend | +145 | 4 |
| `wl_modals.js` | Extend | +226 | 5 |
| `wl_approval_ui.js` | New module | ~433 | 6 |
| `wl_save.js` | New module | ~530 | 7 |
| Entry point cleanup | Rewrite | ~1530 remaining | 8 |

**Entry point reduction**: 3390 → ~1530 lines (55% reduction).
**Total modules after Wave 3**: 12 (7 existing + 5 new).
**Post-Wave-3 cleanup**: Remove `wl_debug.js` from both entry points.
