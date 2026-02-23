# Whitelist Manager — User Guide

**Version 1.0.0** | Security Engineering Team

---

## Table of Contents

1. [Introduction](#1-introduction)
2. [Getting Started](#2-getting-started)
3. [Main Dashboard — Managing Whitelists](#3-main-dashboard--managing-whitelists)
   - [Selecting a Detection Rule](#31-selecting-a-detection-rule)
   - [Viewing CSV Contents](#32-viewing-csv-contents)
   - [Adding Rows](#33-adding-rows)
   - [Editing Rows](#34-editing-rows)
   - [Removing Rows](#35-removing-rows)
   - [Bulk Removal](#36-bulk-removal)
   - [Undo Functionality](#37-undo-functionality)
   - [Setting Expiration Dates](#38-setting-expiration-dates)
   - [Import and Export CSV](#39-import-and-export-csv)
4. [Audit Trail Dashboard](#4-audit-trail-dashboard)
   - [Filters](#41-filters)
   - [Summary Statistics](#42-summary-statistics)
   - [Action Log](#43-action-log)
   - [Expiring Soon Panel](#44-expiring-soon-panel)
5. [Understanding the Diff View](#5-understanding-the-diff-view)
6. [Role-Based Access](#6-role-based-access)
7. [FAQ and Troubleshooting](#7-faq-and-troubleshooting)

---

## 1. Introduction

Whitelist Manager is a Splunk application that provides a web-based interface for managing detection-rule CSV whitelists. Instead of manually editing CSV lookup files on the filesystem, security analysts can use the dashboard to view, add, edit, and remove whitelist entries — with every change automatically tracked in a full audit trail.

### Key Capabilities

- **Searchable dropdown** for 300+ detection rules
- **Editable CSV table** with pagination (10 rows per page)
- **Full audit trail** — every change records who, what, when, and why
- **Expiration management** — set expiration dates with presets; expired rows are automatically cleaned up
- **Git-style diff** — after saving, see exactly what changed
- **Cell-level edit tracking** — before/after values for every modified field
- **CSV import/export** — bulk upload and download
- **Role-based access control** — editors vs. viewers

---

## 2. Getting Started

### Quick Demo (Docker)

Want to try the app before installing on a production Splunk instance? Run the demo script to launch a containerized Splunk with sample data:

```bash
bash demo/demo.sh          # starts Splunk on http://localhost:9000
bash demo/demo.sh --stop   # tear down when done
```

Login: `admin` / `Chang3d!`. See `demo/Demo_Guide.pdf` for a full walkthrough.

### Accessing the App

1. Log in to Splunk Web
2. Navigate to **Apps > Whitelist Manager** (or click "Whitelist Manager" in the app bar)
3. The main dashboard loads automatically

### Required Role

- To **view** whitelists and audit trail: you need the `wl_viewer`, `wl_editor`, `admin`, or `sc_admin` role
- To **edit** whitelists (add, remove, modify rows): you need the `wl_editor`, `admin`, or `sc_admin` role

If you see a "Permission denied" error when trying to save, contact your Splunk administrator to assign you the `wl_editor` role.

### First-Time Workflow

1. Select a **Detection Rule** from the dropdown
2. Select a **CSV File** from the second dropdown
3. The CSV contents load in an editable table
4. Make your changes (add, edit, or remove rows)
5. Click **Save Changes**
6. Provide a comment explaining the change (required for audit)
7. Review the diff summary

---

## 3. Main Dashboard — Managing Whitelists

### 3.1 Selecting a Detection Rule

The **Detection Rule** dropdown supports type-ahead search. Start typing the rule name (e.g., a partial name or keyword) and matching rules appear instantly. Click a rule to select it.

Once a rule is selected, the **CSV File** dropdown populates with all CSV files mapped to that rule. If a rule has only one CSV, it is selected automatically.

> **Note:** If you see "No whitelisting exists for this detection rule," the rule has not been mapped to any CSV files yet. Contact your Splunk administrator.

### 3.2 Viewing CSV Contents

After selecting a rule and CSV file, the table displays:
- **Row numbers** (#) — visual 1-based row numbers
- **Checkboxes** — for selecting rows
- **Data columns** — all visible columns from the CSV (internal `_` columns are hidden)
- **Actions column** — a "Remove" button for each row

The table paginates at **10 rows per page**. Use the navigation buttons at the bottom:
- **First / Prev / Next / Last** — page navigation
- **Page X of Y (Z rows)** — current position

### 3.3 Adding Rows

1. Click the **+ Add Row** button
2. A new empty row appears at the bottom of the table (you'll be navigated to the last page)
3. Fill in all required fields
4. Click **Save Changes** when done

Multiple rows can be added before saving.

### 3.4 Editing Rows

All cells are directly editable — just click a cell and type. Changes are tracked at the cell level:

- The diff will show exactly which field changed, with before and after values
- The audit event records `edited` action with per-field details
- Internal metadata columns (`_added_by`, `_added_at`) are not shown but are preserved

> **Tip:** Expiration date cells open a date picker instead of free-text input (see Section 3.8).

### 3.5 Removing Rows

To remove a single row:

1. Click the **Remove** button on the row's Actions column
2. A prompt asks: "Why is this row being removed?" — **a reason is required**
3. Enter your reason and click OK
4. The row is removed and saved immediately
5. A 10-second **Undo** bar appears (see Section 3.7)

### 3.6 Bulk Removal

To remove multiple rows at once:

1. Check the boxes next to rows you want to remove
   - Use the **header checkbox** to select/deselect all rows across ALL pages
   - Individual checkboxes persist across page navigation
2. Click **Remove Selected (N)** where N is the count of selected rows
3. A prompt asks for a removal reason (applies to all selected rows)
4. All selected rows are removed and saved in one operation

### 3.7 Undo Functionality

After removing a single row, a 10-second undo bar appears:

```
Row removed: [first 3 field values...]  [Undo]  8s
```

- Click **Undo** to restore the row and save immediately
- The countdown shows seconds remaining
- After 10 seconds, the undo option expires

> **Note:** Undo is available for single-row removals only. Bulk removals do not have an undo option.

### 3.8 Setting Expiration Dates

If the CSV has an expiration column (e.g., `Expires`, `expiration_date`, `termination`), clicking the cell opens a **date/time picker**:

**Presets:**
- **7 Days** — sets expiration 7 days from now
- **30 Days** — sets expiration 30 days from now
- **6 Months** — sets expiration ~6 months from now
- **1 Year** — sets expiration 1 year from now

**Manual entry:**
- Pick a **Date** using the date picker
- Pick a **Time** using the time picker (defaults to 00:00)
- Click **Apply** to set the value

**Other options:**
- **Clear (Permanent)** — removes the expiration date (row never expires)
- **Cancel** — closes the picker without changes

Date format: `YYYY-MM-DD HH:MM`

**Automatic expiration:** When a CSV is loaded, any rows past their expiration date are automatically removed. This also runs hourly via a scheduled background task.

### 3.9 Import and Export CSV

**Export (Download):**
1. Click the **Export CSV** button
2. The current CSV content downloads as a `.csv` file
3. Internal metadata columns are excluded from the export

**Import (Upload):**
1. Click **Import CSV** and select a `.csv` file
2. The app compares imported rows against existing rows
3. Only **new rows** (not already in the CSV) are added
4. A message shows how many rows were imported
5. Review the merged result and click **Save Changes** to persist

> **Important:** The imported CSV must have the same column headers as the existing CSV. Missing columns will trigger an error.

### 3.10 Discarding Changes

Click **Discard Changes** to revert all unsaved modifications. This restores the table to the last saved state.

---

## 4. Audit Trail Dashboard

Navigate to the **Audit Trail** tab in the app navigation bar.

### 4.1 Filters

The dashboard provides four filters at the top:

| Filter | Description | Default |
|---|---|---|
| **Time Range** | Standard Splunk time picker | Last 7 days |
| **Analyst** | Filter by the user who made changes | All Analysts |
| **Detection Rule** | Filter by detection rule name | All Rules |
| **Action** | Filter by action type (Added, Removed, Edited, Auto Removed) | All Actions |

All filters apply to every panel on the dashboard. Changes take effect immediately.

### 4.2 Summary Statistics

Four single-value panels at the top show:

- **Total Changes** — sum of all row-level changes (added + removed + edited + auto-removed)
- **Rows Added** — total rows added across all events
- **Rows Removed** — total rows removed (manual + auto-expiration)
- **Rows Edited** — total rows with cell-level edits

### 4.3 Action Log

The main table shows detailed audit events:

| Column | Description |
|---|---|
| **timestamp** | When the change occurred (formatted as DD-MM-YYYY HH:MM:SS GMT+offset) |
| **action** | Type of change: added, removed, edited, auto_removed |
| **analyst** | Username who made the change ("system" for automatic cleanup) |
| **csv_file** | Which CSV file was modified |
| **detection_rule** | Which detection rule the CSV belongs to |
| **remove_reason** | Why rows were removed (required for manual removals) |
| **row_change_count** | Number of rows affected |
| **value** | Detailed per-row field values |
| **summary** | Human-readable one-line summary of the change |

The table shows 5 events per page. Events are sorted newest-first.

### 4.4 Expiring Soon Panel

The **Expiring Soon** table shows rows approaching their expiration date across all CSV files:

| Column | Description |
|---|---|
| **detection_rule** | Which rule the row belongs to |
| **csv_file** | Which CSV file contains the row |
| **Expires** | The expiration date with time remaining, e.g., "2026-03-15 00:00 (20 days 8 hours left)" |
| **value** | Row field values |

**Filtering:** The Expiring Soon panel respects the **Detection Rule** dropdown filter. Select a specific rule to see only its expiring entries.

**Time format:** Shows time remaining with proper pluralization:
- "15 days 8 hours left"
- "1 day 0 hours left" → "1 day left"
- "0 days 5 hours left" → "5 hours left"

---

## 5. Understanding the Diff View

After saving changes, a **Change Summary** appears below the table showing:

### Added Rows
Green section listing each new row as a JSON object.

### Removed Rows
Red section listing each deleted row as a JSON object.

### Unified Diff
A Git-style unified diff showing the exact changes:
- Lines starting with `+` (green) = added
- Lines starting with `-` (red) = removed
- Lines starting with `@@` (cyan) = section markers

The diff compares visible columns only (internal `_` metadata columns are excluded).

---

## 6. Role-Based Access

| Role | View Whitelists | Edit Whitelists | View Audit Trail |
|---|---|---|---|
| `wl_editor` | Yes | Yes | Yes |
| `wl_viewer` | Yes | No | Yes |
| `admin` | Yes | Yes | Yes |
| `sc_admin` | Yes | Yes | Yes |
| (no role) | No | No | No |

- **RBAC is enforced server-side** — even if you bypass the UI, the REST endpoint will reject unauthorized writes
- Role checks are performed via the Splunk REST API on every POST request

---

## 7. FAQ and Troubleshooting

### Q: I don't see any detection rules in the dropdown
**A:** The `rule_csv_map.csv` lookup file needs to be populated with your detection rules. Contact your Splunk administrator.

### Q: I get "Permission denied" when trying to save
**A:** You need the `wl_editor` role. Contact your Splunk administrator to assign it via Settings > Access Controls > Users.

### Q: The CSV file shows "not found"
**A:** The CSV file referenced in `rule_csv_map.csv` may not exist in the expected location. Check that:
- The `csv_file` value matches the actual filename
- The `app_context` points to the correct Splunk app containing the CSV
- The CSV file exists in that app's `lookups/` directory

### Q: My expiration dates aren't being recognized
**A:** The app supports these column names (case-insensitive): `Expires`, `expire`, `expiration`, `expiration_date`, `expiry`, `termination`, `termination_date`. The date must be in format `YYYY-MM-DD HH:MM` or `YYYY-MM-DD`.

### Q: Rows disappeared when I loaded the CSV
**A:** If the CSV has an expiration column, rows past their expiration date are automatically removed on load. A yellow warning banner shows how many rows were removed. This is by design.

### Q: How do I make a row permanent (never expires)?
**A:** Leave the expiration column empty, or click the cell and choose **Clear (Permanent)** in the date picker.

### Q: Can I edit the same CSV from multiple browser tabs?
**A:** This is not recommended. The app does not have multi-user locking. The last save wins. Coordinate with your team to avoid simultaneous edits.

### Q: Where is the audit data stored?
**A:** Audit events are stored in the `wl_audit` index with sourcetype `wl_audit`. A rotating log file backup is also maintained at `$SPLUNK_HOME/var/log/splunk/wl_manager_audit.log`.

### Q: How do I search audit events in SPL?
**A:**
```spl
index=wl_audit sourcetype=wl_audit
| table timestamp analyst action detection_rule csv_file comment
```

### Q: The "Expiring Soon" panel shows all rules even when I select a specific one
**A:** Ensure the Audit Trail dashboard view is up to date. If using a custom/local override, remove `local/data/ui/views/audit.xml` and restart Splunk.
