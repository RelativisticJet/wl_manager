# Manual Test Plan — Whitelist Manager

Step-by-step test plan for UI-specific interactions that require real human input.
Execute in order. Each step has expected results.

**Accounts:**
- `analyst2` / `Chang3d!` — analyst role
- `wladmin2` / `Chang3d!` — admin role
- `superadmin1` / `Chang3d!` — superadmin role

---

## Pre-test Setup
- [ ] Clear audit index (restart Splunk with clean)
- [ ] Reset test data (CSVs, queue, notifications)

---

## Phase 1: analyst2 — Daily Whitelist Operations

Login as `analyst2`.

### 1.1 Navigation & Page Load
- [ ] Page loads with "Detection Rule" and "CSV File" dropdowns
- [ ] "Control Panel" nav link is NOT visible
- [ ] "Whitelist Manager" and "Audit Trail" nav links visible

### 1.2 Detection Rule Dropdown
- [ ] Click Detection Rule search box — dropdown opens
- [ ] Type "DR102" — list filters to matching rules
- [ ] Click "DR102_priv_escalation" — CSV auto-loads
- [ ] CSV File dropdown shows "DR102_whitelist.csv"
- [ ] "Revert to Version" dropdown shows current version

### 1.3 Table Rendering
- [ ] Table shows rows with host column
- [ ] Row numbers (1, 2, 3...) shown on left
- [ ] Checkboxes on each row + select-all in header
- [ ] Column drag handle (hamburger icon) visible
- [ ] Column remove button (x) visible

### 1.4 Inline Cell Editing
- [ ] Click a cell value — it becomes editable (textarea)
- [ ] Type new value — cell highlights as changed
- [ ] "Save Changes" button becomes enabled (not grayed out)
- [ ] Press Escape or click away — edit is preserved in memory

### 1.5 Add Row
- [ ] Click "+ Add Row" — new empty row appears at bottom
- [ ] Fill in data in the new row cells
- [ ] Click "+ Add Row" again — previous row data is NOT lost
- [ ] Row numbers update correctly

### 1.6 Save Changes
- [ ] Click "Save Changes" with edited + added rows
- [ ] Side-by-side diff panel appears showing changes
- [ ] Added rows shown in green, edited rows shown in yellow
- [ ] Comment was auto-filled or prompted

### 1.7 Remove Row (with reason)
- [ ] Click "Remove" button on a row
- [ ] Reason prompt appears — fill in reason
- [ ] Row is removed from table (but not saved yet)
- [ ] Click "Save Changes" — removal is saved
- [ ] Diff shows removed rows in red

### 1.8 Remove Selected (bulk)
- [ ] Select 2+ rows via checkboxes
- [ ] Click "Remove Selected" — reason prompt appears
- [ ] Fill reason — selected rows are removed
- [ ] "Save Changes" — bulk removal saved

### 1.9 Search / Filter
- [ ] Type text in "Filter rows..." search box
- [ ] Table filters to matching rows only
- [ ] Clear button (x) appears next to search
- [ ] Click clear — all rows shown again
- [ ] Search works with partial matches

### 1.10 Export CSV
- [ ] Click "Export CSV"
- [ ] CSV file downloads with correct data
- [ ] Open in Excel/text editor — data matches table

### 1.11 Export Audit
- [ ] Click "Export Audit"
- [ ] Audit CSV downloads

### 1.12 Discard Changes
- [ ] Make edits (add row, edit cell)
- [ ] Click "Discard Changes"
- [ ] Confirmation modal appears
- [ ] Click "Discard" — table reverts to saved state
- [ ] All unsaved changes are gone

### 1.13 Switch Detection Rules
- [ ] Select a different rule from dropdown
- [ ] Previous CSV unloads, new CSV loads
- [ ] Presence bar updates

---

## Phase 2: wladmin2 — Admin Operations

Login as `wladmin2`.

### 2.1 Create Detection Rule
- [ ] Click Detection Rule dropdown
- [ ] Click "+ Create new detection rule"
- [ ] Modal appears with rule name input
- [ ] Enter "DR_MANUAL_TEST" — click Create
- [ ] Rule created, page shows "No whitelisting exists"

### 2.2 Create CSV
- [ ] Click "Create CSV" button
- [ ] Enter CSV name and column headers (comma-separated): `src_ip,dest_ip,severity`
- [ ] Verify spaces in column names are rejected with clear error
- [ ] Enter valid names without spaces — click Create
- [ ] Empty table with headers appears

### 2.3 Add Column
- [ ] Click "+ Add Column"
- [ ] Modal appears — enter "notes"
- [ ] Try entering "bad name" (with space) — error shown
- [ ] Enter "notes" — column added to table
- [ ] Save

### 2.4 Add Rows & Save
- [ ] Add 3 rows with data in all columns
- [ ] Save — diff shows 3 added rows

### 2.5 Bulk Edit
- [ ] Click "Bulk Edit"
- [ ] Select column, enter new value
- [ ] Apply — all cells in that column updated
- [ ] Save — diff shows bulk edits

### 2.6 Column Rename
- [ ] Click on column header text
- [ ] Input appears — rename the column
- [ ] Press Enter — column renamed
- [ ] Save — audit records column rename

### 2.7 Column Reorder (drag)
- [ ] Drag column header (hamburger icon) to new position
- [ ] Drop — columns reorder
- [ ] Auto-saves

### 2.8 Row Reorder (drag)
- [ ] Drag row (grip icon) to new position
- [ ] Drop — rows reorder
- [ ] Auto-saves

### 2.9 Revert to Previous Version
- [ ] Open "Revert to Version" dropdown
- [ ] Shows "current" at top + previous versions with timestamps
- [ ] Select a previous version
- [ ] Reason prompt appears — fill in reason
- [ ] Click Revert — CSV reverts to selected version
- [ ] Diff shows the revert changes

### 2.10 Import CSV
- [ ] Click "Import CSV"
- [ ] Select a CSV file from disk
- [ ] Preview shows imported data
- [ ] Confirm import — data replaces current rows
- [ ] Save

### 2.11 Control Panel — Limits & Permissions
- [ ] Navigate to Control Panel
- [ ] Click "Limits & Permissions" tab
- [ ] All limit inputs visible (row_removal, revert, etc.)
- [ ] Change a limit value, click "Save Limits"
- [ ] Success message — value persists on page refresh

### 2.12 Control Panel — Analyst Usage
- [ ] Click "Analyst Usage" tab
- [ ] Table shows analyst daily usage stats
- [ ] "Reset" button available for individual analysts

### 2.13 Control Panel — Trash Management
- [ ] Click "Trash Management" tab
- [ ] Shows retention period
- [ ] Lists any trashed items

---

## Phase 3: analyst2 — Approval Workflows

Login as `analyst2`.

### 3.1 Create Rule Request (requires approval)
- [ ] Click "+ Create new detection rule"
- [ ] Enter name + reason
- [ ] Message: "Your request has been submitted for approval"
- [ ] Rule does NOT appear in dropdown yet

### 3.2 Notification Check
- [ ] No notification for own request submission

---

## Phase 4: superadmin1 — Approval Processing

Login as `superadmin1`.

### 4.1 Notification Click → Control Panel
- [ ] Click notification bell
- [ ] See analyst2's request notification
- [ ] Click notification — redirects to Control Panel Approval Queue

### 4.2 Approve Request
- [ ] Pending Requests shows analyst2's create rule request
- [ ] "Download CSV" button NOT shown (create_rule has no CSV)
- [ ] Click "Approve" — confirmation modal with "Approve" button
- [ ] Click Approve — "Request approved and executed"
- [ ] Request moves to Recent History with "approved" status

### 4.3 Reject Request (if another pending)
- [ ] Click "Reject" on a pending request
- [ ] Rejection reason modal appears
- [ ] Fill reason — click Reject
- [ ] Request moves to history with "rejected" status

### 4.4 Admin Limits Tab
- [ ] Click "Admin Limits" tab (superadmin only)
- [ ] Shows admin-specific limits (rule_deletion, csv_deletion, etc.)

### 4.5 Trash — Restore
- [ ] If trash has items, click "Restore"
- [ ] Modal shows "Restore" button (not function code!)
- [ ] Click Restore — item restored
- [ ] Success message

### 4.6 Trash — Reset Admin Limits
- [ ] Click "Reset Admin Limits" in Admin Limits tab
- [ ] Modal shows "Reset" button (not function code!)
- [ ] Click Reset — limits reset to defaults

---

## Phase 5: Cross-Account Interactions

### 5.1 Presence Detection
- [ ] Open browser Tab A as analyst2, select DR102
- [ ] Open browser Tab B as wladmin2, select DR102
- [ ] Tab A shows "Also viewing: wladmin2" in presence bar
- [ ] Tab B shows "Also viewing: analyst2" in presence bar

### 5.2 Concurrent Edit Conflict
- [ ] Tab A (analyst2): edit a cell, click Save
- [ ] Tab B (wladmin2): edit same CSV, click Save
- [ ] Tab B should show "file was modified" conflict modal
- [ ] Tab B can reload and retry

### 5.3 CSV Removed While Viewing
- [ ] Tab A: viewing a test CSV
- [ ] Tab B (admin): permanently remove that CSV
- [ ] Tab A: within 5 seconds, "CSV Removed" modal appears
- [ ] Click OK — page resets to initial state

### 5.4 Lock Banner (pending approval)
- [ ] analyst2 submits a bulk removal requiring approval
- [ ] CSV shows lock banner: "remove csv by analyst2"
- [ ] Editing is disabled while approval is pending
- [ ] Other users see the same lock banner

---

## Phase 6: Audit Trail Verification

Login as any admin.

### 6.1 Audit Trail Dashboard
- [ ] Navigate to "Audit Trail" page
- [ ] Dashboard panels load with data
- [ ] Action filter dropdown works (Added, Removed, Edited, Revert)
- [ ] CSV file filter works
- [ ] Time range picker works

### 6.2 Verify Events
After all phases, verify the audit trail contains:
- [ ] `row_added` events from Phase 1 (attributed to analyst2)
- [ ] `row_edited` events from Phase 1
- [ ] `row_removed` events from Phase 1
- [ ] `csv_created` event from Phase 2 (attributed to wladmin2)
- [ ] `dr_created` event from Phase 2
- [ ] `column_added` event from Phase 2
- [ ] `column_renamed` event from Phase 2
- [ ] `revert` event from Phase 2
- [ ] `request_submitted` events from Phase 3
- [ ] `request_approved` / `request_rejected` events from Phase 4
- [ ] Each event has: correct analyst, timestamp, csv_file, detection_rule

---

## Phase 7: Edge Cases

### 7.1 Empty CSV
- [ ] Create a rule with no CSV — shows "No whitelisting exists"
- [ ] Create CSV with headers only, no rows — saves correctly
- [ ] Add first row — saves correctly

### 7.2 Wide CSV (many columns)
- [ ] Select a CSV with 10+ columns
- [ ] Horizontal scrolling works
- [ ] All columns editable

### 7.3 Large CSV
- [ ] Select DR_STRESS_2000x100 (if available)
- [ ] Table renders without browser freeze
- [ ] Scrolling is smooth

### 7.4 Special Characters in Data
- [ ] Enter `O'Brien` in a cell — saves correctly
- [ ] Enter `10.0.0.1, 10.0.0.2` (comma) — saves correctly (CSV-quoted)
- [ ] Enter `<script>alert(1)</script>` — displayed as text, not executed

### 7.5 Browser Back/Forward
- [ ] Select Rule A, then Rule B
- [ ] Click browser Back — returns to Rule A
- [ ] Click Forward — returns to Rule B

---

**Total test cases: ~60+**
**Estimated manual execution time: 45-60 minutes**
