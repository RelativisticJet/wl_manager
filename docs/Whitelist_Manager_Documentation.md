# Whitelist Manager — User Guide

**Version 1.0.0** | Oleh Bezsonov

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
   - [Adding and Removing Columns](#310-adding-and-removing-columns)
   - [Version Control and Revert](#311-version-control-and-revert)
4. [Approval Workflows](#4-approval-workflows)
   - [When Approval Is Required](#41-when-approval-is-required)
   - [Submitting a Request](#42-submitting-a-request)
   - [Approval Notifications](#43-approval-notifications)
   - [Daily Usage Limits](#44-daily-usage-limits)
5. [Control Panel (Admin Only)](#5-control-panel-admin-only)
   - [Approval Queue](#51-approval-queue)
   - [Analyst Usage](#52-analyst-usage)
   - [Limits and Permissions](#53-limits-and-permissions)
6. [Audit Trail Dashboard](#6-audit-trail-dashboard)
   - [Filters](#61-filters)
   - [Summary Statistics](#62-summary-statistics)
   - [Action Log](#63-action-log)
   - [Expiring Soon Panel](#64-expiring-soon-panel)
7. [Role-Based Access](#7-role-based-access)
8. [Splunk Admin Installation Guide](#8-splunk-admin-installation-guide)
   - [Installation](#81-installation)
   - [Index Configuration](#82-index-configuration)
   - [Role Setup](#83-role-setup)
   - [Detection Rule Mapping](#84-detection-rule-mapping)
   - [Scheduled Searches](#85-scheduled-searches)
9. [FAQ and Troubleshooting](#9-faq-and-troubleshooting)

---

## 1. Introduction

Whitelist Manager is a Splunk application that provides a web-based interface for managing detection-rule CSV whitelists. Instead of manually editing CSV lookup files on the filesystem, security analysts can use the dashboard to view, add, edit, and remove whitelist entries — with every change automatically tracked in a full audit trail.

### Key Capabilities

- **Searchable dropdown** for detection rules with type-ahead filtering
- **Inline editable CSV table** with pagination and cell-level change tracking
- **Approval workflows** — bulk operations require admin approval above configurable thresholds
- **Daily usage limits** — per-analyst caps on removals, edits, additions, and reverts
- **Version control** — every save creates a snapshot; revert to any of the last 5 versions
- **Full audit trail** — every change records who, what, when, why, and the exact diff
- **Expiration management** — set expiration dates with presets; expired rows are auto-cleaned
- **CSV import/export** — bulk upload and download with merge logic
- **Role-based access control** — admins, editors, and viewers with server-side enforcement
- **Dark and light theme** support

---

## 2. Getting Started

### Quick Demo (Docker)

Want to try the app before installing on a production Splunk instance? Use the Docker demo:

```bash
git clone https://github.com/RelativisticJet/wl_manager.git
cd wl_manager
docker compose up -d
```

Wait ~90 seconds, then open `http://localhost:8000`. Login: `admin` / `Chang3d!`.

See `demo/Demo_Guide.pdf` for a full walkthrough with sample data.

### Accessing the App

1. Log in to Splunk Web
2. Navigate to **Apps > Whitelist Manager** (or click "Whitelist Manager" in the app bar)
3. The main dashboard loads automatically

### Navigation Bar

Depending on your role, you will see:

- **Whitelist Manager** — main dashboard (all roles)
- **Audit Trail** — audit log dashboard (all roles)
- **Control Panel** — admin dashboard (wl_admin, admin, sc_admin only)

### Required Roles

- To **view** whitelists and audit trail: `wl_analyst_viewer`, `wl_analyst_editor`, `wl_admin`, `admin`, or `sc_admin`
- To **edit** whitelists: `wl_analyst_editor`, `wl_admin`, `admin`, or `sc_admin`
- To **manage approvals and limits**: `wl_admin`, `admin`, or `sc_admin`

Legacy roles `wl_editor` and `wl_viewer` are supported for backward compatibility.

### First-Time Workflow

1. Select a **Detection Rule** from the dropdown
2. Select a **CSV File** from the second dropdown (auto-selected if only one)
3. The CSV contents load in an editable table
4. Make your changes (add, edit, or remove rows)
5. Click **Save Changes**
6. Provide a comment explaining the change (required for audit)
7. Review the diff summary showing exactly what changed

---

## 3. Main Dashboard — Managing Whitelists

### 3.1 Selecting a Detection Rule

The **Detection Rule** dropdown supports type-ahead search. Start typing a rule name and matching rules appear instantly. Click a rule to select it.

Once a rule is selected, the **CSV File** dropdown populates with all CSV files mapped to that rule. If a rule has only one CSV, it is selected automatically.

The dropdown also shows a **"+ Create new detection rule..."** option for adding new rules (requires appropriate permissions).

### 3.2 Viewing CSV Contents

After selecting a rule and CSV file, the table displays:

- **Checkboxes** — for selecting rows (bulk operations)
- **Row numbers** with drag handle — for reordering rows
- **Data columns** — all visible columns from the CSV (internal `_` columns are hidden)
- **Remove button** — per-row removal with required reason

The table paginates at **10 rows per page**. Use the navigation buttons at the bottom: First / Prev / Next / Last. A page indicator shows "Page X of Y (Z rows)".

A **search bar** at the top right filters rows across all columns. The search works across all pages, not just the current page.

### 3.3 Adding Rows

1. Click the **+ Add Row** button
2. A new empty row appears at the bottom of the table (highlighted in green)
3. Fill in the fields — click any cell to start typing
4. Click **Save Changes** when done

Multiple rows can be added before saving. New rows are tracked with `_added_by` (your username) and `_added_at` (timestamp) metadata.

### 3.4 Editing Rows

Click any cell to edit it inline. A textarea appears with the current value:

- Modified cells are highlighted to show pending changes
- The diff after saving shows exactly which fields changed, with before/after values
- The audit event records `edited` action with per-field details

**Bulk Edit**: Click the **Bulk Edit** button to enter bulk editing mode. This lets you modify multiple rows and save them as a single operation. Bulk edits above the configured threshold require admin approval.

### 3.5 Removing Rows

To remove a single row:

1. Click the **Remove** button on the row
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

If the number of rows exceeds the bulk removal threshold (default: 3), the operation requires admin approval instead of executing immediately.

### 3.7 Undo Functionality

After removing a single row, a 10-second undo bar appears:

```text
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
3. Internal metadata columns (`_added_by`, `_added_at`) are excluded from the export

**Import (Upload):**

1. Click **Import CSV** from the Export dropdown menu and select a `.csv` file
2. The app compares imported rows against existing rows
3. Only **new rows** (not already in the CSV) are added
4. A message shows how many rows were imported
5. Review the merged result and click **Save Changes** to persist

> **Important:** The imported CSV must have compatible column headers. The app will map columns by name.

### 3.10 Adding and Removing Columns

**Add Column:**

1. Click **+ Add Column**
2. Enter the column name in the prompt
3. The new column appears with empty values for all rows
4. Click **Save Changes** to persist

**Remove Column:**

- Right-click a column header or use the column menu to remove it
- A reason is required for columns with non-empty data
- Removing columns with many non-empty cells may require admin approval

### 3.11 Version Control and Revert

Every save creates a timestamped version snapshot. The **Revert to Version** dropdown shows:

- **Current** (non-selectable) — the active version
- Up to **5 previous versions** sorted newest-first
- Format: `DD-MM-YYYY HH:MM:SS (N rows, by username)`

To revert:

1. Select a version from the dropdown
2. A confirmation modal shows the changes that will be made (rows restored, removed, and changed)
3. Enter a reason for the revert
4. Click **Revert** to apply

Reverting creates a new snapshot (not a destructive operation). The reverted version is removed from the dropdown to prevent confusion.

If the revert affects many rows (above the threshold), it requires admin approval.

---

## 4. Approval Workflows

### 4.1 When Approval Is Required

The app enforces approval gates for bulk operations that exceed configurable thresholds:

| Operation | Default Threshold | What Happens |
| --- | --- | --- |
| Bulk row removal | 3+ rows | Requires admin approval |
| Bulk row edit | 3+ rows | Requires admin approval |
| Bulk row addition | 3+ rows | Requires admin approval |
| Column removal (non-empty) | 5+ non-empty cells | Requires admin approval |
| Revert | 5+ affected rows | Requires admin approval |

Thresholds are configurable by admins in the Control Panel.

### 4.2 Submitting a Request

When your operation triggers an approval gate:

1. The app shows a message explaining why approval is needed
2. You can add a reason/justification for the request
3. Click **Submit for Approval**
4. The request enters the approval queue
5. The CSV is **locked** until the request is resolved (no other edits allowed)

### 4.3 Approval Notifications

- You receive a notification when your request is approved, rejected, or cancelled
- Notifications appear as a bell icon badge in the top navigation
- Admins receive notifications when new requests are submitted

### 4.4 Daily Usage Limits

Each analyst has daily limits on operations (configurable by admins):

| Action | Default Limit |
| --- | --- |
| Row additions | 10/day |
| Row removals | 10/day |
| Bulk row removals | 10/day |
| Row edits | 10/day |
| Bulk row edits | 10/day |
| Column additions | 2/day |
| Column removals | 2/day |
| Reverts | 3/day |

You can check your remaining limits via the status indicator in the dashboard. Limits reset daily at midnight UTC (configurable).

---

## 5. Control Panel (Admin Only)

The Control Panel is accessible only to users with `wl_admin`, `admin`, or `sc_admin` roles.

### 5.1 Approval Queue

**Pending Requests** — shows all requests awaiting admin action:

- Request ID, timestamp, analyst, detection rule, CSV file, action type
- Analyst's reason for the request
- **Approve** and **Reject** buttons
- Self-approval is prevented — you cannot approve your own request

**Recent History** — shows resolved requests (approved, rejected, cancelled) with:

- Status badges (green = approved, red = rejected, orange = cancelled)
- Admin response/reason
- Which admin resolved it

Approved requests are executed automatically — the original save operation replays with admin authorization.

### 5.2 Analyst Usage

Shows daily usage counters for all active analysts:

- Current usage vs. configured limits for each operation type
- Refresh button with auto-refresh every 10 seconds
- Reset individual analyst usage if needed

### 5.3 Limits and Permissions

Configure global daily limits and approval thresholds:

- **Daily Limits** — per-analyst caps for each operation type
- **Approval Thresholds** — how many rows trigger the approval gate
- **Counter Reset Frequency** — daily, weekly, monthly, or permanent
- **Analyst Permissions** — enable/disable rule creation, CSV creation, rule deletion, CSV deletion (with optional approval requirement)

Changes take effect immediately for all analysts.

---

## 6. Audit Trail Dashboard

Navigate to the **Audit Trail** tab in the app navigation bar.

### 6.1 Filters

The dashboard provides four filters at the top:

| Filter | Description | Default |
| --- | --- | --- |
| **Time Range** | Standard Splunk time picker | Last 7 days |
| **Analyst** | Filter by the user who made changes | All Analysts |
| **Detection Rule** | Filter by detection rule name | All Rules |
| **Action** | Filter by action type | All Actions |

Available action types: Added, Removed, Edited, Revert, Auto-Removed, CSV Exported, CSV Imported, Request Submitted, Request Approved, Request Rejected, Request Cancelled.

### 6.2 Summary Statistics

Summary panels show counts for the selected time range:

- **Row-level**: Total Changes, Rows Added, Rows Removed, Rows Edited, Rows Reordered
- **Column-level**: Columns Added, Removed, Renamed, Reordered, Reverted
- **Export/Import**: Audit Exported, CSV Exported, CSV Imported, CSV Created, Detection Rule Created
- **Approval**: Requests Submitted, Approved, Rejected, Failed, Cancelled

### 6.3 Action Log

The main table shows detailed audit events with:

| Column | Description |
| --- | --- |
| **timestamp** | When the change occurred |
| **action** | Type of change |
| **analyst** | Username who made the change ("system" for auto-cleanup) |
| **csv_file** | Which CSV file was modified |
| **detection_rule** | Which detection rule the CSV belongs to |
| **comment** | User-provided reason for the change |
| **summary** | Human-readable description of the change |
| **value** | Per-row field details |

### 6.4 Expiring Soon Panel

Shows rows approaching their expiration date across all CSV files, with time remaining displayed in human-readable format (e.g., "15 days 8 hours left").

---

## 7. Role-Based Access

| Role | View Whitelists | Edit Whitelists | Control Panel | Inherits |
| --- | --- | --- | --- | --- |
| `wl_admin` | Yes | Yes | Yes | `power` |
| `wl_analyst_editor` | Yes | Yes | No | `power` |
| `wl_analyst_viewer` | Yes | No | No | `user` |
| `admin` | Yes | Yes | Yes | (Splunk built-in) |
| `sc_admin` | Yes | Yes | Yes | (Splunk built-in) |
| (no role) | No | No | No | — |

- **RBAC is enforced server-side** — even if you bypass the UI, the REST endpoint rejects unauthorized requests
- Role checks are performed via the Splunk REST API on every POST request
- The `_from_approval` flag is a Python function parameter, not controllable from the client

---

## 8. Splunk Admin Installation Guide

### 8.1 Installation

**Requirements:**

- Splunk Enterprise 8.x or 9.x (tested on 9.3.1)
- Python 3 (bundled with Splunk 8+)
- ~10 MB disk space for the app + audit data

**Install the `.spl` package:**

1. Download `wl_manager-2.0.0.spl` from the [Releases](https://github.com/RelativisticJet/wl_manager/releases) page
2. In Splunk Web: **Apps > Manage Apps > Install app from file**
3. Upload the `.spl` file and restart Splunk

Or via CLI:

```bash
$SPLUNK_HOME/bin/splunk install app wl_manager-2.0.0.spl
$SPLUNK_HOME/bin/splunk restart
```

### 8.2 Index Configuration

The app creates a `wl_audit` index via `indexes.conf`. Verify after installation:

```spl
| eventcount index=wl_audit
```

If your organization requires index creation through a deployment server or index cluster master, create the index manually:

```ini
[wl_audit]
homePath   = $SPLUNK_DB/wl_audit/db
coldPath   = $SPLUNK_DB/wl_audit/colddb
thawedPath = $SPLUNK_DB/wl_audit/thaweddb
```

### 8.3 Role Setup

The app ships with three roles in `default/authorize.conf`:

```ini
[role_wl_admin]
importRoles = power
srchIndexesAllowed = wl_audit
srchIndexesDefault = wl_audit

[role_wl_analyst_editor]
importRoles = power
srchIndexesAllowed = wl_audit
srchIndexesDefault = wl_audit

[role_wl_analyst_viewer]
importRoles = user
srchIndexesAllowed = wl_audit
srchIndexesDefault = wl_audit
```

Assign roles via **Settings > Access Controls > Users** or through your identity provider (LDAP/SAML).

**Recommended role assignments:**

- SOC analysts who manage whitelists: `wl_analyst_editor`
- SOC managers who approve changes: `wl_admin`
- Auditors who review changes: `wl_analyst_viewer`

### 8.4 Detection Rule Mapping

Edit `lookups/rule_csv_map.csv` to map your detection rules to CSV lookup files:

```csv
rule_name,csv_file,app_context
DR55_brute_force_login,DR55_brute_force_users.csv,wl_manager
MY_CUSTOM_RULE,my_custom_whitelist.csv,search
```

**Fields:**

- `rule_name` — display name shown in the Detection Rule dropdown
- `csv_file` — filename of the CSV in the app's (or target app's) `lookups/` directory
- `app_context` — the Splunk app containing the CSV. Use `wl_manager` for CSVs stored in this app, or another app name (e.g., `search`, `SA-AccessProtection`) to manage CSVs in other apps

The app ships with 18 sample detection rules. Replace or extend these with your own.

**To create the CSV lookup file:**

1. Create a CSV file with headers in the appropriate `lookups/` directory
2. At minimum, include the fields your detection rule uses for matching
3. Optionally include `Comment` and `Expires` columns for comments and auto-expiration

### 8.5 Scheduled Searches

The app includes one scheduled search:

- **wl_expiring_soon** — runs hourly, removes rows past their expiration date from all CSVs that have an expiration column. Removed rows are logged as `auto_removed` in the audit trail.

Verify it is enabled: **Settings > Searches, reports, and alerts > wl_expiring_soon**.

---

## 9. FAQ and Troubleshooting

### Q: I don't see any detection rules in the dropdown

**A:** The `rule_csv_map.csv` lookup file needs to be populated with your detection rules. See Section 8.4.

### Q: I get "Permission denied" when trying to save

**A:** You need the `wl_analyst_editor` or `wl_admin` role. Contact your Splunk administrator to assign it via Settings > Access Controls > Users.

### Q: My save was blocked — "requires admin approval"

**A:** Your operation exceeded the bulk threshold (e.g., removing 3+ rows). The request has been submitted to the approval queue. An admin will review it in the Control Panel.

### Q: The CSV shows "locked" and I can't edit

**A:** Another user (or you) has a pending approval request for this CSV. The CSV is locked until the request is approved, rejected, or cancelled. Check the pending approval banner for details.

### Q: The CSV file shows "not found"

**A:** Check that:

- The `csv_file` value in `rule_csv_map.csv` matches the actual filename
- The `app_context` points to the correct Splunk app containing the CSV
- The CSV file exists in that app's `lookups/` directory

### Q: My expiration dates aren't being recognized

**A:** The app supports these column names (case-insensitive): `Expires`, `expire`, `expiration`, `expiration_date`, `expiry`, `termination`, `termination_date`. The date must be in format `YYYY-MM-DD HH:MM` or `YYYY-MM-DD`.

### Q: Rows disappeared when I loaded the CSV

**A:** If the CSV has an expiration column, rows past their expiration date are automatically removed on load. A yellow warning banner shows how many rows were removed. This is by design.

### Q: Can two analysts edit the same CSV simultaneously?

**A:** The app has optimistic locking. If two analysts load the same CSV and one saves first, the second analyst's save will be rejected with a "Conflict: the CSV file was modified" error. They must reload the CSV and reapply their changes.

### Q: Where is the audit data stored?

**A:** Audit events are stored in the `wl_audit` index with sourcetype `wl_audit`. Query them with:

```spl
index=wl_audit sourcetype=wl_audit
| table timestamp analyst action detection_rule csv_file comment
```

### Q: How do I back up the whitelist data?

**A:** The CSV lookup files are in `$SPLUNK_HOME/etc/apps/wl_manager/lookups/`. Version snapshots are in `lookups/_versions/`. Back up both directories.

### Q: The "Control Panel" tab is not visible

**A:** The Control Panel is restricted to `wl_admin`, `admin`, and `sc_admin` roles. If you need access, contact your Splunk administrator.
