---
phase: 05-frontend-architecture
plan: 03
subsystem: Frontend Architecture — Wave 2.5 Coupled Feature Modules
tags: [extraction, modularization, feature-modules, table, forms, versioning, approvals]
requirements: [FMOD-05]
key_files:
  created:
    - appserver/static/modules/wl_table.js
    - appserver/static/modules/wl_modals.js
    - appserver/static/modules/wl_versions.js
    - appserver/static/modules/wl_approval_ui.js
  modified:
    - appserver/static/whitelist_manager.js
    - default/app.conf
decisions:
  - "Module-local state for table (pagination, column widths, edit history) — not in State manager"
  - "Modals use simple form validation (required reason for removal)"
  - "Version dropdown shows 'Current' non-selectable + last 5 previous versions"
  - "Approval UI provides modal and status update functions — orchestration deferred to Wave 4"
dependency_graph:
  - wl_table requires: wl_constants, wl_state, wl_rest, wl_ui
  - wl_modals requires: wl_constants, wl_state, wl_rest, wl_ui
  - wl_versions requires: wl_constants, wl_state, wl_rest, wl_ui
  - wl_approval_ui requires: wl_constants, wl_state, wl_rest, wl_ui
  - whitelist_manager requires all above + Search, Presence, CsvIO
duration: 45 minutes
completed_date: 2026-04-02
---

# Phase 5 Plan 03: Coupled Feature Modules — Summary

**Wave 2.5 (Plan 05-03): Extract four tightly-coupled feature modules from the monolith that work together and depend on foundation modules.**

One-liner: Extracted table rendering, modal dialogs, version history, and approval UI into four clean AMD modules with clear public APIs.

---

## What Was Built

### wl_table.js (652 lines)
- **Purpose**: Core table rendering and editing experience
- **Public API**: `init()`, `refreshTable()`, `syncInputs()`, `getSelectedRows()`, `undoLastEdit()`
- **Features**:
  - Table rendering from `State.currentRows` with pagination (10/20/50 rows per page)
  - Inline cell editing with change tracking and undo support (last 50 edits)
  - Row selection with checkboxes (select-all + individual)
  - Column resize with drag handles (persisted to server)
  - Drag-drop row and column reordering
  - Auto-expanding textareas with character limits (1000 chars per cell)
  - Expiration date highlighting (yellow for expired rows)
  - Synchronized input capture (`syncInputs()`) before table refresh (prevents data loss)
  - **Critical invariant**: `refreshTable()` calls `syncInputs()` first (structural enforcement)

- **State Dependencies**:
  - Reads: `currentRows`, `currentHeaders`, `originalRows`, `expireColumn`, `csvLocked`
  - Writes: `currentRows` on row addition
  - Listens to: `state:currentRows`, `state:currentHeaders`, `state:csvLocked`, `state:csvFileSelected`
  - Fires: `wl:rowsEdited`, `wl:tableRefreshed`

- **Module-local state** (not in State manager):
  - `currentPage`, `ROWS_PER_PAGE`, `selectedIdxSet`, `resizeState`, `dragState`
  - `editHistory`, `colWidths`, `allColWidths` (column widths persisted per CSV)
  - Rationale: Table UI state is module-specific; no need to synchronize globally

### wl_modals.js (305 lines)
- **Purpose**: Modal dialogs for row operations
- **Public API**: `init()`, `showAddRowModal(callback)`, `showRemoveModal(rowIndices, callback)`, `showEditModal(rowIndex, callback)`, `showConfirmModal(title, message, options)`
- **Features**:
  - Add row modal: form with fields for each column, optional validation
  - Remove row modal: confirmation + required reason field (5+ chars, enforced)
  - Edit row modal: in-place field editing for single row
  - Generic confirm modal: reusable for approval flows, deletions, etc.
  - Form validation: reason required for removals, character limits on reasons
  - Modal styling: overlay with wl-modal classes, no `<button>` elements (use `<span>` for Splunk compatibility)

- **State Dependencies**:
  - Reads: `currentRows`, `currentHeaders`, `csvLocked`
  - Listens to: `state:currentRows`, `state:currentHeaders`, `state:csvLocked`
  - Fires: `wl:rowAdded`, `wl:rowRemoved`, `wl:rowEdited`

### wl_versions.js (254 lines)
- **Purpose**: Version history management and revert functionality
- **Public API**: `init()`, `loadVersions()`, `showVersionDropdown()`, `revertToVersion(versionId, reason)`, `getVersionHistory()`
- **Features**:
  - Loads version history from server via `get_versions` action
  - Displays dropdown with "Current" label (non-selectable) at top
  - Lists last 5 previous versions with format: "24-02-2026 12:37:16 (42 rows, by admin)"
  - Revert with reason modal: required reason field (5+ chars)
  - Posts revert request via `revert_csv` action
  - Updates State with reverted CSV data
  - Automatic reload of versions after successful revert

- **State Dependencies**:
  - Reads: `selectedCsv`, `selectedApp`, `currentRows`
  - Writes: `currentHeaders`, `currentRows`, `originalRows` on revert
  - Listens to: `state:csvFileSelected`, `state:selectedCsv`
  - Fires: `wl:versionsLoaded`, `wl:csvReverted`

### wl_approval_ui.js (205 lines)
- **Purpose**: Approval request UI and queue status management
- **Public API**: `init()`, `showApprovalNeeded(actionType, reason, options)`, `updateApprovalStatus()`, `getQueueStatus()`, `formatDailyLimitMsg(limitData)`, `showDailyLimitWarning(limitData)`
- **Features**:
  - Shows modal when action requires approval (tells user it's queued)
  - Polls server every 30 seconds for queue status
  - Maintains `pendingApprovalCount` and `adminPendingCount` in State
  - Updates visual approval indicator in UI
  - Formats daily limit enforcement messages for display
  - Supports approval gates and limit checks (messages, not enforcement)

- **State Dependencies**:
  - Reads: `isAdmin`, `csvLocked`
  - Writes: `pendingApprovalCount`, `adminPendingCount` (on status update)
  - Listens to: `state:pendingApprovalCount`, `state:adminPendingCount`, `state:csvLocked`, `state:isAdmin`
  - Fires: `wl:approvalRequested`, `wl:approvalStatusUpdated`

---

## Integration Points

**Entry point (whitelist_manager.js) now:**
1. Requires all Wave 1 foundation modules + Wave 2 feature modules + Wave 2.5 modules
2. Initializes modules in dependency order:
   - Foundation (Constants, State, REST, UI) — injected via require()
   - Wave 2 (Search, Presence, CsvIO) — `init()` calls
   - Wave 2.5 (Table, Modals, Versions, ApprovalUI) — `init()` calls
3. Wires event handlers:
   - `wl:rowRemovalRequested` → `Modals.showRemoveModal()`
   - `wl:csvImported` → trigger `refreshTable()`
   - Placeholder comments for Wave 4 orchestration refinement

**Cross-module communication:**
- Via State manager (read/write) for shared data
- Via jQuery custom events (`wl:*`) for async notifications
- No direct cross-module function calls (clean dependency graph)

---

## Acceptance Criteria Met

All Wave 2.5 tasks executed and verified:

### Task 1: wl_table.js
- ✓ Module created with 652 lines
- ✓ Renders table from State.currentRows with pagination
- ✓ Inline cell editing with change tracking
- ✓ Row selection with checkboxes
- ✓ Column resize with drag handles
- ✓ Undo support (Ctrl+Z equivalent) with 50-edit history
- ✓ Fire `wl:rowsEdited` on changes
- ✓ Listen to State changes for external updates
- ✓ `refreshTable()` calls `syncInputs()` first (structural enforcement)

### Task 2: wl_modals.js
- ✓ Module created with 305 lines
- ✓ `showAddRowModal()` — form with all column fields
- ✓ `showRemoveModal()` — confirmation + required reason (5+ chars)
- ✓ `showEditModal()` — in-place field editing
- ✓ Form validation enforced
- ✓ Reason required for removal
- ✓ Fire custom events (`wl:rowAdded`, `wl:rowRemoved`, `wl:rowEdited`)
- ✓ UI messages on success/error via UI.showMsg()

### Task 3: wl_versions.js
- ✓ Module created with 254 lines
- ✓ `loadVersions()` — fetches via REST.restGet('get_versions')
- ✓ `showVersionDropdown()` — displays "Current" + last 5 versions
- ✓ Format: "24-02-2026 12:37:16 (42 rows, by admin)"
- ✓ `revertToVersion()` — prompts for reason, posts via REST.restPost('revert_csv')
- ✓ Updates State with reverted CSV data
- ✓ Fire `wl:csvReverted` event
- ✓ Listen to `state:csvFileSelected` to refresh versions

### Task 4: wl_approval_ui.js
- ✓ Module created with 205 lines
- ✓ `showApprovalNeeded()` — shows modal with action details
- ✓ `updateApprovalStatus()` — polls server, updates State counts
- ✓ `getQueueStatus()` — returns current queue status
- ✓ `formatDailyLimitMsg()` — formats limit enforcement messages
- ✓ Fire `wl:approvalRequested` and `wl:approvalStatusUpdated`
- ✓ Listen to State changes

### Task 5: Entry Point Updated
- ✓ `whitelist_manager.js` requires all four Wave 2.5 modules
- ✓ Modules initialized in correct order
- ✓ Event handlers wired for `wl:rowRemovalRequested`
- ✓ Placeholder comments mark Wave 4 orchestration work

### Task 6: Build Number Bumped
- ✓ Build number incremented: 485 → 486
- ✓ All files committed atomically (fb99e5c)

---

## Deviations from Plan

**None.** Plan executed exactly as written. All modules created with correct sizes, public APIs, and State dependencies. All acceptance criteria met.

---

## Next Steps: Wave 3 Finalization (Plan 05-04)

Plan 05-04 will:
1. Complete remaining monolith extraction: approval workflows, bulk edit flows
2. Add missing event wiring in entry point (table → modals, versions, approvals orchestration)
3. Ensure backward compatibility with existing features
4. Validate all features work together via integration testing
5. Prepare for Wave 4 (final entry point refactoring to <100 lines)

---

## Technical Notes

### Why Module-Local State?
Pagination index, column widths, edit history, and resize state are table-specific and don't need global synchronization. Keeping them local keeps State manager clean and table module self-contained.

### Why syncInputs() Called First?
Users type into cells while viewing a page, then click "Next Page". If we don't call `syncInputs()` before redrawing, the unsaved edits on the previous page are lost. This is a critical invariant: `refreshTable()` must always call `syncInputs()` first.

### AMD Module Pattern
All modules follow the same pattern established by Wave 1 foundation:
- `define(['modules/...'], function(deps) { ... return { init, publicFn1, ... } })`
- Single initialization via `init()` call in entry point
- Event-driven communication via jQuery events and State listeners
- No shared module-level state across modules

### Splunk Compatibility
- No `<button>` elements in modals (Splunk strips them from SimpleXML). Used `<span>` with CSS classes instead.
- AMD/RequireJS for module loading (standard Splunk pattern)
- jQuery for DOM manipulation and AJAX (bundled with Splunk)
- Underscore.js for `_.escape()` (bundled with Splunk)

---

## Files Modified/Created

```
appserver/static/modules/
  ├── wl_table.js          (NEW, 652 lines)
  ├── wl_modals.js         (NEW, 305 lines)
  ├── wl_versions.js       (NEW, 254 lines)
  └── wl_approval_ui.js    (NEW, 205 lines)

appserver/static/
  └── whitelist_manager.js (MODIFIED: require + init calls)

default/
  └── app.conf             (MODIFIED: build 485 → 486)
```

**Total new code:** 1,416 lines across four modules
**Total net change:** +1,461 lines (entry point updates + new modules)
**Commit:** fb99e5c

---

**Requirement FMOD-05: Coupled features extracted (Wave 2.5 complete)**
