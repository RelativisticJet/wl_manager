#!/usr/bin/env python3
"""Generate comprehensive test plan PDF for Whitelist Manager."""

from fpdf import FPDF
import os

OUTPUT = os.path.expanduser("~/Desktop/WL_Manager_Test_Plan.pdf")


class TestPlanPDF(FPDF):
    """Custom PDF with headers, footers, and helper methods."""

    def __init__(self):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.set_auto_page_break(auto=True, margin=20)
        self._section_num = 0
        self._test_num = 0
        self._total_tests = 0

    def header(self):
        if self.page_no() > 1:
            self.set_font("Helvetica", "I", 8)
            self.set_text_color(120, 120, 120)
            self.cell(0, 8, "Whitelist Manager - Comprehensive Test Plan", align="L")
            self.cell(0, 8, f"Page {self.page_no()}", align="R", new_x="LMARGIN", new_y="NEXT")
            self.line(10, 14, 200, 14)
            self.ln(4)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 7)
        self.set_text_color(150, 150, 150)
        self.cell(0, 10, "Generated for build 315 | March 2026", align="C")

    def title_page(self):
        self.add_page()
        self.ln(60)
        self.set_font("Helvetica", "B", 28)
        self.set_text_color(30, 30, 30)
        self.cell(0, 15, "Whitelist Manager", align="C", new_x="LMARGIN", new_y="NEXT")
        self.set_font("Helvetica", "", 18)
        self.set_text_color(80, 80, 80)
        self.cell(0, 12, "Comprehensive Test Plan", align="C", new_x="LMARGIN", new_y="NEXT")
        self.ln(10)
        self.set_font("Helvetica", "", 11)
        self.set_text_color(100, 100, 100)
        self.cell(0, 8, "Build 315  |  March 2026", align="C", new_x="LMARGIN", new_y="NEXT")
        self.cell(0, 8, "Splunk Enterprise Security App", align="C", new_x="LMARGIN", new_y="NEXT")
        self.ln(30)
        self.set_font("Helvetica", "", 10)
        self.set_text_color(60, 60, 60)
        lines = [
            "This document provides a complete test plan covering every feature,",
            "button, audit log entry, and edge case in the Whitelist Manager app.",
            "",
            "Tests are organized into sections by functional area.",
            "Each test includes steps, expected results, and automation notes.",
            "",
            "Test accounts:",
            "  admin / Chang3d!  -  Built-in Splunk admin",
            "  wladmin1 / WlAdmin123  -  wl_admin + user roles",
            "  wladmin2 / WlAdmin123  -  wl_admin + user roles",
            "  analyst1 / Analyst123  -  wl_analyst_editor + user roles",
            "  analyst2 / Analyst2  -  wl_analyst_editor + user roles",
        ]
        for line in lines:
            self.cell(0, 6, line, align="C", new_x="LMARGIN", new_y="NEXT")

    def section(self, title):
        self._section_num += 1
        self._test_num = 0
        if self.get_y() > 240:
            self.add_page()
        else:
            self.ln(6)
        self.set_font("Helvetica", "B", 14)
        self.set_text_color(20, 60, 120)
        self.cell(0, 10, f"Section {self._section_num}: {title}",
                  new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(20, 60, 120)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(4)

    def subsection(self, title):
        if self.get_y() > 255:
            self.add_page()
        self.set_font("Helvetica", "B", 11)
        self.set_text_color(40, 40, 40)
        self.ln(3)
        self.cell(0, 7, title, new_x="LMARGIN", new_y="NEXT")
        self.ln(1)

    def test(self, title, steps, expected, auto="Manual", priority="Medium"):
        self._test_num += 1
        self._total_tests += 1
        tid = f"T{self._section_num}.{self._test_num}"

        needed = 10 + len(steps) * 5 + len(expected) * 5 + 12
        if self.get_y() + needed > 275:
            self.add_page()

        # Test header with priority color
        colors = {"Critical": (180, 30, 30), "High": (200, 100, 0),
                  "Medium": (40, 40, 40), "Low": (100, 100, 100)}
        pc = colors.get(priority, (40, 40, 40))

        self.set_font("Helvetica", "B", 9)
        self.set_text_color(255, 255, 255)
        self.set_fill_color(*pc)
        self.cell(14, 6, f" {tid}", fill=True)
        self.set_fill_color(240, 240, 240)
        self.set_text_color(30, 30, 30)
        self.cell(0, 6, f"  {title}   [{priority}]  [{auto}]", fill=True,
                  new_x="LMARGIN", new_y="NEXT")

        self.set_font("Helvetica", "", 8)
        self.set_text_color(50, 50, 50)

        # Steps
        self.set_font("Helvetica", "B", 8)
        self.cell(0, 5, "  Steps:", new_x="LMARGIN", new_y="NEXT")
        self.set_font("Helvetica", "", 8)
        for i, step in enumerate(steps, 1):
            self.cell(8)
            self.multi_cell(0, 4.5, f"{i}. {step}", new_x="LMARGIN", new_y="NEXT")

        # Expected
        self.set_font("Helvetica", "B", 8)
        self.cell(0, 5, "  Expected:", new_x="LMARGIN", new_y="NEXT")
        self.set_font("Helvetica", "", 8)
        for exp in expected:
            self.cell(8)
            self.multi_cell(0, 4.5, f"- {exp}", new_x="LMARGIN", new_y="NEXT")

        self.ln(2)

    def note_box(self, text):
        """Info box for notes/tips."""
        if self.get_y() > 260:
            self.add_page()
        self.set_fill_color(230, 242, 255)
        self.set_draw_color(100, 160, 220)
        y = self.get_y()
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(30, 60, 100)
        self.cell(4)
        self.multi_cell(182, 5, f"NOTE: {text}", new_x="LMARGIN", new_y="NEXT",
                        fill=True, border=1)
        self.ln(2)


def build_pdf():
    pdf = TestPlanPDF()

    # ── Title page ──
    pdf.title_page()

    # ══════════════════════════════════════════════════════════════
    # SECTION 1: Navigation & CSV Loading
    # ══════════════════════════════════════════════════════════════
    pdf.add_page()
    pdf.section("Navigation & CSV Loading")

    pdf.test("Detection Rule search and selection",
             ["Open Whitelist Manager page",
              "Click the Detection Rule search box",
              "Type a partial rule name (e.g., 'DR1')",
              "Verify dropdown filters to matching rules",
              "Click a rule from the dropdown"],
             ["Dropdown filters dynamically as you type",
              "CSV File dropdown populates with mapped CSVs",
              "First CSV auto-loads into the table"],
             priority="Critical")

    pdf.test("Detection Rule clear button",
             ["Select a rule and load a CSV",
              "Click the X clear button on the rule dropdown"],
             ["Rule and CSV selections cleared",
              "Table returns to placeholder text",
              "Search bar, Revert dropdown, and action buttons hidden"],
             priority="High")

    pdf.test("CSV File switching",
             ["Select a rule with multiple CSV mappings",
              "Load the first CSV, make some edits (don't save)",
              "Switch to a different CSV from the dropdown"],
             ["New CSV loads, previous unsaved edits discarded",
              "Column widths restored for the new CSV",
              "Pending approvals update for new CSV"],
             priority="High")

    pdf.test("Rule with no CSV mappings",
             ["Select a detection rule that has no CSV mappings in rule_csv_map.csv"],
             ["Warning message: 'No whitelisting exists for this detection rule'"],
             priority="Medium")

    pdf.test("Click outside dropdown closes it",
             ["Open the Detection Rule dropdown by focusing the search",
              "Click somewhere else on the page"],
             ["Dropdown closes without selecting anything"],
             priority="Low")

    # ══════════════════════════════════════════════════════════════
    # SECTION 2: Table Display & Pagination
    # ══════════════════════════════════════════════════════════════
    pdf.section("Table Display & Pagination")

    pdf.test("Basic table rendering",
             ["Load a CSV with data",
              "Verify all column headers are visible",
              "Verify row numbers start at 1",
              "Verify metadata columns (_added_by, _added_at) are hidden"],
             ["All visible columns displayed with headers",
              "Row numbers sequential",
              "No _prefixed columns shown"],
             priority="Critical")

    pdf.test("Pagination controls",
             ["Load a CSV with >20 rows",
              "Click Next, Previous, First, Last page buttons",
              "Verify page info shows correct counts"],
             ["Navigation works correctly",
              "Page info shows 'Page X of Y (N rows - M columns)'"],
             priority="High")

    pdf.test("Rows-per-page selection",
             ["Load a CSV with >50 rows",
              "Change rows-per-page from 10 to 20 to 50",
              "Verify the current view position is preserved"],
             ["Table shows correct number of rows per page",
              "First visible row stays approximately the same"],
             priority="Medium")

    pdf.test("Select-all checkbox spans all pages",
             ["Load a CSV with multiple pages",
              "Click the select-all checkbox on page 1",
              "Navigate to page 2"],
             ["All rows on page 2 are also checked",
              "Remove Selected button shows total count across all pages"],
             priority="High")

    pdf.test("Row tooltip shows metadata",
             ["Load a CSV where some rows have _added_by metadata",
              "Hover over a row"],
             ["Tooltip shows 'Added by: username | Added at: timestamp'"],
             priority="Low")

    pdf.test("Expired row highlighting",
             ["Load a CSV with an Expires column",
              "Ensure some rows have past dates"],
             ["Expired rows highlighted in yellow with wl-row-expired class",
              "Auto-removal message appears if expired rows were cleaned"],
             auto="Can verify via API", priority="Medium")

    # ══════════════════════════════════════════════════════════════
    # SECTION 3: Inline Cell Editing
    # ══════════════════════════════════════════════════════════════
    pdf.section("Inline Cell Editing")

    pdf.test("Basic cell edit",
             ["Load a CSV, click into a cell",
              "Type a new value",
              "Click into a different cell"],
             ["Cell shows yellow highlight (wl-cell-edited)",
              "Value is tracked in memory"],
             priority="Critical")

    pdf.test("Enter key blocked in cells",
             ["Click into a cell",
              "Press Enter"],
             ["No newline inserted",
              "Cursor stays in same cell (Enter is blocked for CSV safety)"],
             priority="High")

    pdf.test("Paste sanitization",
             ["Copy text containing tabs and newlines from another app",
              "Paste into a cell"],
             ["Tabs and newlines replaced with spaces",
              "If pasted text >1000 chars, truncated with warning message"],
             priority="High")

    pdf.test("Ctrl+Z undo (cell edit history)",
             ["Edit cell A, then edit cell B",
              "Click outside all inputs (blur)",
              "Press Ctrl+Z twice"],
             ["First Ctrl+Z reverts cell B to original",
              "Second Ctrl+Z reverts cell A to original",
              "Only works when focus is NOT in an input field"],
             priority="Medium")

    pdf.test("Discard changes restores original",
             ["Edit several cells",
              "Click Discard Changes"],
             ["All cells revert to original loaded values",
              "Yellow highlights cleared",
              "'Changes discarded' message shown"],
             priority="High")

    # ══════════════════════════════════════════════════════════════
    # SECTION 4: Row Operations
    # ══════════════════════════════════════════════════════════════
    pdf.section("Row Operations")

    pdf.test("Add single row",
             ["Load a CSV",
              "Click Add Row"],
             ["Empty row appended at the end",
              "Page navigates to last page",
              "First cell of new row is focused",
              "Row is unsaved (local only)"],
             priority="Critical")

    pdf.test("Add row while searching - Clear Search modal",
             ["Load a CSV, type a search query",
              "Click Add Row"],
             ["'Clear Search?' modal appears",
              "On confirm: search cleared, row added",
              "On cancel: nothing happens"],
             priority="High")

    pdf.test("Remove unsaved row (no reason required)",
             ["Add a new row (don't save)",
              "Click the row's remove button (or select + Remove Selected)"],
             ["Row removed immediately, no reason modal",
              "No audit event created (row was never saved)"],
             priority="High")

    pdf.test("Remove saved row (reason required)",
             ["Load a CSV with existing rows",
              "Click the remove button on a saved row"],
             ["Remove modal appears with row preview (first 3 fields)",
              "Reason textarea is required",
              "On confirm: row removed, auto-saved, undo bar appears"],
             priority="Critical")

    pdf.test("Remove Selected (bulk) - mix of saved and unsaved",
             ["Add 2 new rows (don't save)",
              "Select the 2 new rows + 2 saved rows",
              "Click Remove Selected"],
             ["Unsaved rows removed immediately with message",
              "Saved rows trigger the reason/approval flow",
              "Correct count shown in confirmation"],
             priority="High")

    pdf.test("Undo bar after single row removal",
             ["Remove a saved row",
              "Watch the 10-second undo countdown",
              "Click Undo before timer expires"],
             ["Undo bar shows removed row info and countdown",
              "Undo restores the row and auto-saves",
              "'Undo row removal' comment in audit log"],
             auto="Partially automatable", priority="High")

    pdf.test("Undo bar expires after 10 seconds",
             ["Remove a saved row",
              "Wait 10 seconds without clicking Undo"],
             ["Undo bar disappears after countdown reaches 0",
              "Row removal is permanent"],
             priority="Medium")

    pdf.test("Row limit enforcement (5000)",
             ["Load a CSV near the 5000-row limit",
              "Try to Add Row beyond the limit"],
             ["Error message: row limit reached",
              "No row added"],
             auto="Automatable", priority="Medium")

    pdf.test("Row drag reorder",
             ["Load a CSV (not searching, not locked)",
              "Drag a row's grip handle to a different position"],
             ["Row visually moves during drag",
              "Other rows shift to show insertion point",
              "On drop: auto-saves immediately",
              "Audit log: row_reordered with from/to positions",
              "Any pending cell edits are DISCARDED before reorder"],
             priority="High")

    # ══════════════════════════════════════════════════════════════
    # SECTION 5: Column Operations
    # ══════════════════════════════════════════════════════════════
    pdf.section("Column Operations")

    pdf.test("Add column",
             ["Click Add Column",
              "Enter a valid column name",
              "Click OK"],
             ["New column appears in header",
              "All rows get empty value for new column",
              "Auto-saves immediately",
              "Audit log: column_added"],
             priority="Critical")

    pdf.test("Add column - validation",
             ["Try adding column starting with '_'",
              "Try adding column with commas or quotes",
              "Try adding column that duplicates existing name"],
             ["Each attempt shows appropriate error message",
              "No column added"],
             priority="High")

    pdf.test("Remove column",
             ["Click the X button on a column header"],
             ["Remove Column modal appears with reason textarea",
              "On confirm: column removed, auto-saved, undo bar shows",
              "Audit log: column_removed"],
             priority="Critical")

    pdf.test("Cannot remove last column",
             ["Load or create a CSV with only 1 column",
              "Try to remove that column"],
             ["Error: cannot remove the last column"],
             priority="Medium")

    pdf.test("Column rename (inline)",
             ["Click a column header text",
              "Edit the name in the inline input",
              "Press Enter (or blur)"],
             ["Column renames in header and all row data",
              "Auto-saves immediately",
              "Audit log: column_renamed with old_name/new_name",
              "Column width preserved under new name"],
             priority="High")

    pdf.test("Column rename - Escape cancels",
             ["Click column header text to enter rename mode",
              "Type a new name",
              "Press Escape"],
             ["Rename cancelled, original name restored"],
             priority="Medium")

    pdf.test("Column drag reorder",
             ["Drag a column's grip handle to a different position"],
             ["Column (header + all cells) visually moves",
              "On drop: auto-saves, audit log: column_reordered",
              "Pending cell edits are DISCARDED before reorder"],
             priority="High")

    pdf.test("Column resize",
             ["Drag the right edge of a column header",
              "Resize to a different width"],
             ["Column width changes (clamped 50-300px)",
              "Width persists after page reload (saved to server)"],
             priority="Medium")

    pdf.test("Column limit enforcement (100)",
             ["Load a CSV near the 100-column limit",
              "Try to Add Column beyond the limit"],
             ["Error message: column limit reached"],
             auto="Automatable", priority="Low")

    # ══════════════════════════════════════════════════════════════
    # SECTION 6: Bulk Edit
    # ══════════════════════════════════════════════════════════════
    pdf.section("Bulk Edit")

    pdf.test("Basic bulk edit",
             ["Select 3+ rows with checkboxes",
              "Click Bulk Edit",
              "Select a column from dropdown, enter a value",
              "Click Apply"],
             ["All selected rows update in that column",
              "Cells show yellow edit highlight",
              "Message: 'Click Save Changes to persist'",
              "Changes not saved until Save button clicked"],
             priority="Critical")

    pdf.test("Bulk edit with Expires column",
             ["Select rows, click Bulk Edit",
              "Choose the Expires column from dropdown"],
             ["Text input hidden, date picker shown instead",
              "Preset buttons (7 Days, 30 Days, 6 Months, 1 Year) available",
              "Clear (Permanent) button sets empty value",
              "Value stored in UTC format"],
             priority="High")

    pdf.test("Bulk edit - no actual changes",
             ["Select rows, click Bulk Edit",
              "Select a column, enter the SAME value already in those cells",
              "Click Apply"],
             ["'No changes' message shown",
              "Modal closes, no edits tracked"],
             priority="Medium")

    pdf.test("Bulk edit disabled without selection",
             ["Ensure no rows are checked",
              "Look at the Bulk Edit button"],
             ["Button is disabled/grayed out"],
             priority="Low")

    # ══════════════════════════════════════════════════════════════
    # SECTION 7: Save Changes Flow
    # ══════════════════════════════════════════════════════════════
    pdf.section("Save Changes Flow")

    pdf.test("Save with Comment column",
             ["Load a CSV that HAS a 'Comment' column",
              "Edit a cell, click Save Changes"],
             ["No browser prompt appears",
              "If any Comment cell is empty: save blocked with red highlights",
              "If all Comments filled: save proceeds using per-row comments"],
             priority="Critical")

    pdf.test("Save without Comment column",
             ["Load a CSV without a 'Comment' column",
              "Edit a cell, click Save Changes"],
             ["Browser prompt() asks for a comment (required, max 500 chars)",
              "Empty comment blocked with re-prompt",
              "On valid comment: save proceeds"],
             priority="Critical")

    pdf.test("Save adds + edits in one operation",
             ["Add 2 new rows with data",
              "Edit 1 existing cell",
              "Click Save Changes"],
             ["Single save_csv call to backend",
              "Separate audit events: row_added (count=2) and row_edited (count=1)",
              "Diff display shows both additions (green) and edits"],
             priority="High")

    pdf.test("Save empty rows are filtered out",
             ["Add a new row but leave ALL fields empty",
              "Click Save Changes"],
             ["Empty row is silently removed before save",
              "Not counted as an addition in audit"],
             priority="Medium")

    pdf.test("Ctrl+S keyboard shortcut",
             ["Make an edit",
              "Press Ctrl+S (or Cmd+S on Mac)"],
             ["Save triggers same as clicking Save Changes button"],
             priority="Medium")

    pdf.test("Double-save prevention",
             ["Make an edit",
              "Rapidly click Save Changes twice"],
             ["Only one save request sent (saving flag prevents double-fire)",
              "Button shows 'Saving...' text while in progress"],
             priority="High")

    pdf.test("Optimistic lock conflict (409)",
             ["Open the same CSV in two browser tabs",
              "Save in tab A",
              "Then save in tab B (stale mtime)"],
             ["Tab B gets 409 error: 'modified by another user'",
              "Error includes 'Click to reload' link"],
             priority="Critical", auto="Partially automatable")

    # ══════════════════════════════════════════════════════════════
    # SECTION 8: Search & Filter
    # ══════════════════════════════════════════════════════════════
    pdf.section("Search & Filter")

    pdf.test("Basic search filters rows",
             ["Load a CSV",
              "Type a search term in the search bar"],
             ["Only rows containing the term (in any visible column) are shown",
              "Matching cells highlighted with wl-cell-match class",
              "Banner: 'X of Y row(s) match'",
              "Page resets to 1"],
             priority="High")

    pdf.test("Search clear button",
             ["Enter a search term",
              "Click the X clear button"],
             ["Search cleared, all rows shown",
              "Cell highlights removed"],
             priority="Medium")

    pdf.test("Search blocks drag operations",
             ["Enter a search term",
              "Try to drag a row or column"],
             ["Drag does not initiate",
              "Row/column stays in place"],
             priority="Medium")

    pdf.test("Search blocks column rename",
             ["Enter a search term",
              "Try to click a column header to rename"],
             ["Warning: 'Clear search before renaming columns'"],
             priority="Medium")

    # ══════════════════════════════════════════════════════════════
    # SECTION 9: Version Control & Revert
    # ══════════════════════════════════════════════════════════════
    pdf.section("Version Control & Revert")

    pdf.test("Version dropdown shows last 5 versions",
             ["Load a CSV with version history",
              "Check the Revert dropdown"],
             ["'Current' shown at top (non-selectable)",
              "Up to 5 previous versions listed newest-first",
              "Format: 'DD-MM-YYYY HH:MM:SS (N rows, by analyst)'"],
             priority="High")

    pdf.test("Revert to previous version",
             ["Select a previous version from dropdown",
              "Enter a reason in the revert modal",
              "Click OK"],
             ["CSV content replaced with version data",
              "Diff display shows changes",
              "Audit log: revert with restoredback/removedback/changedback fields",
              "Version dropdown updates (reverted version removed, new snapshot created)"],
             priority="Critical")

    pdf.test("Revert disabled when locked",
             ["Trigger an approval request to lock the CSV",
              "Check the Revert dropdown"],
             ["Dropdown is disabled",
              "Cannot select a version"],
             priority="Medium")

    pdf.test("Version snapshots capped at 6",
             ["Make 8+ saves to a CSV",
              "Check lookups/_versions/ directory"],
             ["At most 6 version files (1 current + 5 previous)",
              "Oldest versions pruned"],
             auto="Automatable", priority="Medium")

    # ══════════════════════════════════════════════════════════════
    # SECTION 10: Date/Time Picker (Expires Column)
    # ══════════════════════════════════════════════════════════════
    pdf.section("Date/Time Picker (Expires Column)")

    pdf.test("Open picker by clicking Expires cell",
             ["Load a CSV with an Expires column",
              "Click on an Expires cell"],
             ["Floating date picker appears below the cell",
              "Cell is read-only (cannot type directly)"],
             priority="High")

    pdf.test("Preset buttons set correct dates",
             ["Open the picker",
              "Click '7 Days', '30 Days', '6 Months', '1 Year' buttons"],
             ["Date/time fields populate with now + N days/months",
              "Time field defaults to current time"],
             priority="High")

    pdf.test("Apply stores UTC, displays local",
             ["Set a date/time in the picker",
              "Click Apply"],
             ["Cell shows local time",
              "Underlying value stored as 'YYYY-MM-DD HH:MM UTC'",
              "Cell shows yellow edit highlight"],
             priority="High")

    pdf.test("Clear (Permanent) removes expiration",
             ["Open picker on a cell with an existing date",
              "Click 'Clear (Permanent)'"],
             ["Cell becomes empty (no expiration)",
              "Row will never auto-expire"],
             priority="Medium")

    pdf.test("Escape closes picker without change",
             ["Open the picker",
              "Press Escape"],
             ["Picker closes, cell value unchanged"],
             priority="Low")

    pdf.test("Only first matching expire column gets picker",
             ["Load a CSV with columns 'Expires', 'expire', 'termination_date'",
              "Click on cells in each column"],
             ["Only 'Expires' (first match) gets the date picker",
              "'expire' and 'termination_date' are plain text inputs"],
             priority="Medium")

    # ══════════════════════════════════════════════════════════════
    # SECTION 11: Export & Import
    # ══════════════════════════════════════════════════════════════
    pdf.section("Export & Import")

    pdf.test("Export CSV downloads current state",
             ["Load a CSV, make some unsaved edits",
              "Click Export CSV"],
             ["CSV file downloaded with CURRENT in-memory data (including unsaved edits)",
              "Metadata columns (_added_by etc.) excluded from export",
              "Audit log: csv_exported event"],
             priority="High")

    pdf.test("Export Audit Trail",
             ["Load a CSV",
              "Click Export Audit Trail"],
             ["Searches wl_audit index for this CSV/rule",
              "Downloads up to 10,000 events as CSV",
              "Audit log: audit_exported event"],
             priority="Medium")

    pdf.test("Import CSV - Replace mode (always requires approval)",
             ["Click Import CSV, select a .csv file",
              "Choose 'Replace' mode"],
             ["Approval request submitted automatically",
              "CSV becomes locked pending approval",
              "No immediate changes to the data"],
             priority="Critical")

    pdf.test("Import CSV - Merge mode",
             ["Click Import CSV, select a .csv file with some new rows",
              "Choose 'Merge' mode"],
             ["Only new unique rows added (duplicate keys skipped)",
              "Import headers must be superset of current headers",
              "If row limit exceeded: error",
              "If approval gate triggers: approval request created",
              "Otherwise: rows added locally, 'Click Save Changes' message"],
             priority="Critical")

    pdf.test("Import CSV - file size limit (5 MB)",
             ["Try importing a file larger than 5 MB"],
             ["Error message about file size limit"],
             priority="Medium")

    # ══════════════════════════════════════════════════════════════
    # SECTION 12: Approval Workflow - Analyst Side
    # ══════════════════════════════════════════════════════════════
    pdf.section("Approval Workflow - Analyst Side")

    pdf.note_box(
        "These tests require approval thresholds to be configured low enough to trigger. "
        "Use the Control Panel Daily Limits tab to set thresholds (e.g., "
        "bulk_row_removal_threshold=2, bulk_row_addition_threshold=2)."
    )

    pdf.test("Bulk removal triggers approval gate",
             ["As analyst1: select rows >= removal threshold",
              "Click Remove Selected"],
             ["Reason modal appears with 'Submit for Approval' button",
              "On submit: approval request created, CSV locked",
              "Audit log: request_submitted with action_type=bulk_row_removal"],
             priority="Critical")

    pdf.test("Bulk addition triggers approval gate",
             ["As analyst1: add rows >= addition threshold",
              "Click Save Changes"],
             ["Approval modal appears",
              "On submit: request created, CSV locked",
              "Unsaved additions stored in request payload"],
             priority="Critical")

    pdf.test("Bulk edit triggers approval gate",
             ["As analyst1: select rows >= edit threshold",
              "Bulk Edit with a value change",
              "Click Apply"],
             ["Approval request created for bulk_row_edit",
              "CSV locked pending approval"],
             priority="Critical")

    pdf.test("Column removal triggers approval gate",
             ["As analyst1: try to remove a column with >= threshold non-empty cells"],
             ["Approval request for column_removal",
              "CSV locked"],
             priority="High")

    pdf.test("Large revert triggers approval gate",
             ["As analyst1: revert to a version with >= threshold row/column changes"],
             ["Backend returns requires_approval",
              "Frontend auto-submits approval request",
              "CSV locked"],
             priority="High")

    pdf.test("CSV locked state - all write operations disabled",
             ["Trigger an approval to lock a CSV",
              "Try: Add Row, Add Column, Remove, Bulk Edit, Save, Import, Revert"],
             ["All buttons disabled or show 'CSV is locked' error",
              "All cells read-only",
              "Amber banner shows pending approval details"],
             priority="Critical")

    pdf.test("Cancel own request",
             ["As analyst1: submit an approval request",
              "See the approval bar with 'Cancel Request' button",
              "Click Cancel Request, enter a reason"],
             ["Cancellation modal with required reason textarea",
              "On confirm: request cancelled, CSV unlocked",
              "Audit log: request_cancelled"],
             priority="Critical")

    pdf.test("Non-admin analyst sees only Cancel (no Approve/Reject)",
             ["As analyst1 (non-admin): submit an approval request",
              "Check the approval bar"],
             ["Only 'Cancel Request' button shown",
              "No Approve or Reject buttons visible"],
             priority="High")

    pdf.test("Show Requested Rows filter",
             ["Trigger an approval for bulk row removal",
              "Click 'Show Requested Rows' in the approval bar"],
             ["Table filters to show only the affected rows",
              "Button toggles to 'Show All Rows'",
              "Click again to show all rows"],
             priority="Medium")

    pdf.test("Addition preview table for bulk_row_addition",
             ["Trigger an approval for bulk row addition",
              "Click 'Show Requested Rows'"],
             ["Read-only preview table appears below the approval bar",
              "Shows the rows that would be added (paginated)",
              "Prev/Next pagination if >10 rows"],
             priority="Medium")

    pdf.test("Daily limit exceeded blocks action",
             ["Set a daily limit to 1 for row_addition",
              "As analyst: add 1 row and save (succeeds)",
              "Try to add another row and save"],
             ["Second attempt blocked with daily limit error message",
              "Shows current count and maximum"],
             priority="High")

    # ══════════════════════════════════════════════════════════════
    # SECTION 13: Approval Workflow - Admin Side
    # ══════════════════════════════════════════════════════════════
    pdf.section("Approval Workflow - Admin Side")

    pdf.test("Approve request from Whitelist Manager page",
             ["As analyst1: submit approval request",
              "As wladmin1: open same CSV in Whitelist Manager",
              "Click Approve in the approval bar"],
             ["Confirm modal appears",
              "On confirm: changes applied, CSV unlocked",
              "Diff display shows what changed",
              "Audit log: request_approved"],
             priority="Critical")

    pdf.test("Reject request from Whitelist Manager page",
             ["As analyst1: submit approval request",
              "As wladmin1: open same CSV",
              "Click Reject, enter rejection reason"],
             ["Reason modal appears (required)",
              "On confirm: request rejected, CSV unlocked",
              "No changes applied to CSV",
              "Audit log: request_rejected with rejection_reason"],
             priority="Critical")

    pdf.test("Approve from Control Panel",
             ["As analyst1: submit approval request",
              "As wladmin1: open Control Panel > Approval Queue",
              "Click Approve on the pending request"],
             ["Confirm dialog appears",
              "On confirm: changes replayed from stored payload",
              "Queue refreshes, request moves to history"],
             priority="Critical")

    pdf.test("Reject from Control Panel",
             ["As analyst1: submit approval request",
              "As wladmin1: open Control Panel > Approval Queue",
              "Click Reject, enter reason"],
             ["Request rejected, moves to history with red status",
              "Rejection reason shown in history"],
             priority="Critical")

    pdf.test("Cancel own request from Control Panel",
             ["As wladmin1: submit an approval request",
              "Open Control Panel, find your request",
              "Click Cancel, enter reason"],
             ["Cancel button shown instead of Approve/Reject for own requests",
              "Request cancelled, moves to history with amber status"],
             priority="High")

    pdf.test("Download CSV from approval queue",
             ["Open Control Panel > Approval Queue",
              "Click 'Download CSV' on a pending request"],
             ["Current CSV file downloaded for review",
              "Download contains the CURRENT state (not the proposed changes)"],
             priority="Medium")

    pdf.test("Admin cannot approve own request",
             ["As wladmin1: trigger an action that requires approval",
              "As wladmin1: try to approve it from the approval bar or CP"],
             ["Self-approval is blocked",
              "Only Cancel button shown for own requests",
              "Another admin must approve"],
             priority="Critical")

    pdf.test("Approval queue auto-polling",
             ["Open Control Panel on one browser",
              "Submit/approve a request from another browser",
              "Watch the Control Panel"],
             ["Queue auto-refreshes within ~5 seconds",
              "New/changed items appear without manual refresh"],
             priority="Medium")

    # ══════════════════════════════════════════════════════════════
    # SECTION 14: Control Panel - Daily Limits
    # ══════════════════════════════════════════════════════════════
    pdf.section("Control Panel - Daily Limits")

    pdf.test("View and modify daily limits",
             ["As wladmin1: open Control Panel > Daily Limits",
              "Change a limit value",
              "Click Save Limits"],
             ["Limits saved successfully",
              "Change history table shows before/after diff",
              "Inline 'Limits changed' message appears"],
             priority="High")

    pdf.test("Reset frequency configuration",
             ["Set Reset Frequency to 'Daily'",
              "Set Reset Hour to 8",
              "Save Limits"],
             ["Counters reset daily at 08:00 UTC",
              "Reset Hour input visible when frequency is not 'Never'"],
             priority="High")

    pdf.test("Save as Default",
             ["Configure custom limits",
              "Click Save as Default"],
             ["Confirm dialog appears",
              "Custom defaults saved",
              "'Reset to Custom Defaults' button appears"],
             priority="Medium")

    pdf.test("Reset to Factory Defaults",
             ["After saving custom defaults",
              "Click 'Reset to Factory Defaults'"],
             ["Confirm dialog appears",
              "Limits restored to hard-coded factory values",
              "Custom defaults file deleted",
              "'Reset to Custom Defaults' button disappears"],
             priority="Medium")

    pdf.test("No-change detection on Save",
             ["Open Daily Limits without changing anything",
              "Click Save Limits"],
             ["'No changes to save' message (client detects no diff)"],
             priority="Low")

    pdf.test("0 means unlimited",
             ["Set a limit to 0",
              "Save Limits"],
             ["That action type has no daily cap",
              "Analyst Usage shows no 'LIMIT' badge for 0-limit actions"],
             priority="Medium")

    # ══════════════════════════════════════════════════════════════
    # SECTION 15: Control Panel - Analyst Usage
    # ══════════════════════════════════════════════════════════════
    pdf.section("Control Panel - Analyst Usage")

    pdf.test("Usage table shows per-analyst counts",
             ["As analyst1: perform several actions (add rows, edit, remove)",
              "As wladmin1: open Control Panel > Analyst Usage"],
             ["Table shows analyst1's action counts for current period",
              "Counts at/above limits shown in red with 'LIMIT' badge"],
             priority="High")

    pdf.test("Reset single analyst usage",
             ["Click Reset button next to an analyst's row"],
             ["Confirm dialog, then analyst's counters reset to 0",
              "Table refreshes"],
             priority="Medium")

    pdf.test("Reset All usage",
             ["Click Reset All button"],
             ["Confirm dialog, then all analysts' counters reset",
              "Table refreshes"],
             priority="Medium")

    pdf.test("Auto-refresh every 10 seconds",
             ["Leave Analyst Usage tab open",
              "Perform actions in another tab"],
             ["Usage table updates within ~10 seconds"],
             priority="Low")

    # ══════════════════════════════════════════════════════════════
    # SECTION 16: Audit Trail Dashboard
    # ══════════════════════════════════════════════════════════════
    pdf.section("Audit Trail Dashboard")

    pdf.test("Filter by Time Range",
             ["Change Time Range dropdown to different values"],
             ["All panels and tables update to reflect the selected time range"],
             priority="High")

    pdf.test("Filter by Analyst",
             ["Select a specific analyst from the dropdown"],
             ["All stats and tables show only that analyst's actions"],
             priority="High")

    pdf.test("Filter by Detection Rule",
             ["Select a specific detection rule"],
             ["All stats filter to that rule only"],
             priority="Medium")

    pdf.test("Filter by Action type",
             ["Select specific action types from the dropdown"],
             ["Stats and tables filter appropriately"],
             priority="Medium")

    pdf.test("Total Changes matches sum of panels",
             ["Select 'All Actions' with data present",
              "Sum up: Rows Added + Removed + Edited + Reordered + Cols Added + "
              "Removed + Renamed + Reordered + Reverted"],
             ["Total Changes = sum of all individual panels",
              "Revert counts as 1 event (not row-level)"],
             priority="High")

    pdf.test("Data Changes table shows correct summaries",
             ["Perform various actions: add, remove, edit, revert",
              "Check the Data Changes table"],
             ["Each action has a human-readable summary",
              "Reason column populated correctly",
              "Row/column change counts accurate"],
             priority="High")

    pdf.test("Activity Log shows request events",
             ["Submit, approve, reject, and cancel requests",
              "Check the Activity Log table"],
             ["All request lifecycle events shown",
              "Status and reason columns populated",
              "Export/import events also in this table"],
             priority="High")

    pdf.test("All 19 action types appear in filter",
             ["Open the Action filter dropdown"],
             ["All action types listed: row_added, row_removed, row_edited, "
              "auto_removed, revert, column_removed, column_added, row_reordered, "
              "column_reordered, column_renamed, audit_exported, csv_exported, "
              "csv_imported, request_submitted, request_approved, request_rejected, "
              "request_failed, request_cancelled"],
             priority="Medium")

    # ══════════════════════════════════════════════════════════════
    # SECTION 17: RBAC & Permissions
    # ══════════════════════════════════════════════════════════════
    pdf.section("RBAC & Permissions")

    pdf.test("wl_admin can edit AND approve",
             ["As wladmin1: add rows, edit cells, remove rows, bulk edit",
              "As wladmin1: approve another user's request"],
             ["All edit operations succeed (wl_admin is in EDIT_ROLES)",
              "Approval operations succeed (wl_admin is in ADMIN_ROLES)"],
             priority="Critical")

    pdf.test("wl_analyst_editor can edit but NOT approve",
             ["As analyst1: perform edit operations",
              "As analyst1: try to open Control Panel"],
             ["Edit operations succeed",
              "Control Panel shows 'Access Denied'",
              "No Approve/Reject buttons in approval bar"],
             priority="Critical")

    pdf.test("wl_admin cannot approve own request",
             ["As wladmin1: trigger an approval request",
              "As wladmin1: check the approval bar"],
             ["Only 'Cancel Request' shown, not Approve/Reject",
              "Self-approval guard intact"],
             priority="Critical")

    pdf.test("Read-only access for unauthenticated roles",
             ["Create a user with only 'user' role (no wl_* roles)",
              "Open Whitelist Manager"],
             ["Can view CSVs (GET actions allowed)",
              "All write buttons disabled or return 403",
              "Control Panel shows 'Access Denied'"],
             priority="High")

    # ══════════════════════════════════════════════════════════════
    # SECTION 18: Presence & Concurrency
    # ══════════════════════════════════════════════════════════════
    pdf.section("Presence & Concurrency")

    pdf.test("Presence bar shows other active users",
             ["As analyst1: open a CSV",
              "As analyst2: open the same CSV"],
             ["Both users see presence bar: 'Also viewing: otherUser'",
              "Presence updates within ~15 seconds"],
             priority="Medium")

    pdf.test("Max 10 concurrent users per CSV",
             ["Simulate 10+ users on the same CSV (or lower the limit)"],
             ["11th user gets 'CSV Busy' modal",
              "Redirected to rule selection"],
             priority="Low", auto="Difficult to test manually")

    pdf.test("Idle kick after 30 minutes",
             ["Open a CSV and leave idle for 30+ minutes"],
             ["Presence monitoring stops",
              "'CSV Busy' modal with idle message"],
             priority="Low", auto="Difficult to test manually")

    pdf.test("External change detection",
             ["Open CSV in browser tab A",
              "Save changes from browser tab B",
              "Watch tab A"],
             ["'CSV File Changed Externally' modal appears in tab A",
              "Options: Reload CSV or Keep editing",
              "Warns about unsaved changes if any"],
             priority="High")

    # ══════════════════════════════════════════════════════════════
    # SECTION 19: Dark Theme
    # ══════════════════════════════════════════════════════════════
    pdf.section("Dark Theme")

    pdf.test("Dark theme auto-detection",
             ["Open Splunk with dark theme enabled"],
             ["wl-dark class added to body",
              "All components use dark color scheme",
              "Approval bar, modals, buttons all properly themed"],
             priority="Medium")

    pdf.test("Light theme rendering",
             ["Open Splunk with light/default theme"],
             ["No wl-dark class on body",
              "Standard light color scheme applied"],
             priority="Low")

    # ══════════════════════════════════════════════════════════════
    # SECTION 20: NON-STANDARD / COMBINED ACTIONS (Edge Cases)
    # ══════════════════════════════════════════════════════════════
    pdf.section("NON-STANDARD / COMBINED ACTIONS (Edge Cases)")

    pdf.note_box(
        "These tests cover non-obvious interactions when multiple operations "
        "are performed simultaneously before saving. These are the most likely "
        "to surface bugs due to state management complexity."
    )

    pdf.subsection("20A: Edit + Remove Combinations")

    pdf.test("Edit cells THEN remove a different row, then Save",
             ["Edit cell in row 3",
              "Remove row 5 (single, with reason)",
              "Row 5 auto-saves with removal"],
             ["Row 5 removal triggers auto-save",
              "Edit to row 3 is INCLUDED in the removal save (syncInputs runs first)",
              "Audit: row_removed for row 5 + row_edited for row 3",
              "Edit comment becomes 'Edited alongside removal'"],
             priority="Critical")

    pdf.test("Edit cells THEN Remove Selected (bulk) with unsaved rows",
             ["Add 2 new rows, type data in them",
              "Edit 1 existing cell",
              "Select the 2 new rows + 1 saved row",
              "Click Remove Selected"],
             ["New rows removed immediately (no reason)",
              "Saved row triggers approval/reason flow",
              "Existing cell edit is preserved for the save"],
             priority="High")

    pdf.test("Edit a row THEN remove that same row",
             ["Edit cell in row 3",
              "Click remove on row 3"],
             ["Remove modal appears",
              "On confirm: row is removed",
              "The edit is irrelevant (row deleted)",
              "Audit: row_removed only, no row_edited for that row"],
             priority="High")

    pdf.subsection("20B: Edit + Column Operations")

    pdf.test("Edit cells THEN add a column",
             ["Edit a cell value",
              "Click Add Column, enter name, confirm"],
             ["Column addition auto-saves immediately",
              "Cell edit from step 1 is INCLUDED in the save (syncInputs)",
              "Audit: column_added + row_edited (if cell was different from original)"],
             priority="High")

    pdf.test("Edit cells THEN remove a column",
             ["Edit a cell in column A",
              "Remove column B"],
             ["Column removal auto-saves",
              "Cell edit in column A included in save",
              "Audit: column_removed + row_edited"],
             priority="High")

    pdf.test("Edit cells THEN rename a column",
             ["Edit a cell value",
              "Click column header, rename it, press Enter"],
             ["Rename auto-saves",
              "Cell edit included in same save",
              "Audit: column_renamed + possibly row_edited"],
             priority="Medium")

    pdf.subsection("20C: Edit + Reorder Combinations")

    pdf.test("Edit cells THEN drag-reorder a row",
             ["Edit 2 cells in different rows",
              "Drag a row to a new position"],
             ["WARNING: Row reorder DISCARDS all pending cell edits",
              "Rows restored from originalRows before reorder",
              "Only row_reordered event in audit",
              "Edited cell values are LOST"],
             priority="Critical")

    pdf.test("Edit cells THEN drag-reorder a column",
             ["Edit a cell value",
              "Drag a column to a new position"],
             ["WARNING: Column reorder DISCARDS all pending cell edits",
              "Only column_reordered in audit",
              "Edited value is LOST"],
             priority="Critical")

    pdf.subsection("20D: Add Row + Other Operations")

    pdf.test("Add rows THEN bulk edit those new rows",
             ["Add 3 new rows",
              "Type values in them",
              "Select the 3 new rows",
              "Bulk Edit a column with a value"],
             ["Bulk edit applies to unsaved rows",
              "When saved: all 3 rows counted as additions (not edits)"],
             priority="High")

    pdf.test("Add rows THEN reorder",
             ["Add 2 new rows, type data",
              "Drag an existing row to reorder"],
             ["Reorder discards ALL pending changes including new row data",
              "New rows are LOST (restored from originalRows)",
              "Only row_reordered in audit"],
             priority="Critical")

    pdf.test("Add empty rows THEN bulk edit them THEN save",
             ["Add 5 empty rows",
              "Select all 5",
              "Bulk Edit column 'user' with value 'testuser'",
              "Click Save Changes"],
             ["5 rows saved with 'user' = 'testuser' and other fields empty",
              "Audit: row_added with count=5",
              "Empty rows with ALL fields still empty are filtered out (but these have 'user' set)"],
             priority="High")

    pdf.subsection("20E: Multiple Column Operations")

    pdf.test("Add column THEN remove a different column (sequential auto-saves)",
             ["Add column 'NewCol' (auto-saves)",
              "Remove column 'OldCol' (auto-saves)"],
             ["Two separate save operations",
              "Two separate audit events: column_added + column_removed",
              "Version history shows 2 snapshots"],
             priority="Medium")

    pdf.test("Add column THEN rename it immediately",
             ["Add column 'TempName' (auto-saves, page refreshes)",
              "Click the new column header to rename to 'FinalName'"],
             ["Two saves: column_added(TempName) + column_renamed(TempName->FinalName)",
              "Final state has 'FinalName' column"],
             priority="Medium")

    pdf.subsection("20F: Approval + Concurrent Operations")

    pdf.test("Two users submit approval requests for same CSV",
             ["As analyst1: trigger bulk removal (creates request)",
              "As analyst2: try to trigger bulk addition on same CSV"],
             ["analyst2's action is blocked - CSV already locked by analyst1's request",
              "409 error: 'CSV has a pending approval'"],
             priority="High")

    pdf.test("Approve while analyst is viewing locked CSV",
             ["As analyst1: submit approval, CSV locked",
              "As analyst1: keep the locked CSV open in browser",
              "As wladmin1: approve the request"],
             ["analyst1's browser detects change via polling (within ~5 sec)",
              "CSV auto-reloads showing the applied changes",
              "Lock removed, editing re-enabled"],
             priority="High")

    pdf.test("Duplicate approval request prevention",
             ["As analyst1: submit bulk_row_removal request",
              "As analyst1: try to submit another bulk_row_removal on same CSV"],
             ["409: duplicate pending request detected",
              "Only one pending request per user/CSV/action_type allowed"],
             priority="Medium")

    pdf.subsection("20G: Search + Operations")

    pdf.test("Search active THEN Save (edits to hidden rows preserved)",
             ["Edit a cell in row 3",
              "Search for something that hides row 3 but shows row 7",
              "Edit a cell in row 7",
              "Click Save Changes"],
             ["Both edits (row 3 and row 7) are saved",
              "syncInputs captures visible inputs; row 3's edit was already in memory"],
             priority="High")

    pdf.test("Search THEN pagination THEN Save",
             ["Search to filter rows",
              "Navigate to page 2 of search results",
              "Edit a cell on page 2",
              "Click Save"],
             ["Edit is preserved across pagination + search",
              "syncInputs called before page change captures data"],
             priority="Medium")

    pdf.subsection("20H: Import + Existing State")

    pdf.test("Import Merge with unsaved local edits",
             ["Edit some cells (don't save)",
              "Import a CSV with Merge mode"],
             ["Merged rows added to currentRows",
              "Previous unsaved edits still present",
              "Both edits and merged rows saved together on Save"],
             priority="High")

    pdf.test("Import file with headers not matching current CSV",
             ["Load a CSV with columns [A, B, C]",
              "Import a file with columns [A, B, D] in Merge mode"],
             ["Error: import headers must be a superset of current headers",
              "No rows merged"],
             priority="Medium")

    pdf.subsection("20I: Edge Cases with Expires")

    pdf.test("Bulk edit Expires THEN single-cell edit Expires",
             ["Select 3 rows, Bulk Edit Expires to '7 Days'",
              "Then click on one of those cells and set a different date"],
             ["Single-cell edit overwrites the bulk edit for that cell",
              "Other 2 cells retain bulk edit value",
              "All 3 show as edited on Save"],
             priority="Medium")

    pdf.test("Auto-expiration removes rows on CSV load",
             ["Manually set some rows to past expiration dates (via API or direct file edit)",
              "Reload the CSV"],
             ["Expired rows automatically removed",
              "Warning banner: 'N expired row(s) were automatically removed'",
              "Audit: auto_removed event with row details"],
             auto="Automatable", priority="High")

    pdf.subsection("20J: Rapid/Stress Interactions")

    pdf.test("Rapid Add Row clicks",
             ["Click Add Row 10 times quickly"],
             ["10 empty rows added (no duplicates, no crashes)",
              "Each Add Row calls syncInputs first to preserve previous row data"],
             priority="Medium")

    pdf.test("Rapid Save clicks (double-save prevention)",
             ["Make a change",
              "Click Save 5 times in <1 second"],
             ["Only 1 save request sent",
              "No duplicate audit events"],
             priority="High")

    pdf.test("Type in cell, immediately click Add Row",
             ["Start typing in a cell",
              "Immediately click Add Row (before blur)"],
             ["Typed data is preserved (syncInputs called before add)",
              "New empty row appears at end"],
             priority="High")

    # ══════════════════════════════════════════════════════════════
    # SECTION 21: Security Validations
    # ══════════════════════════════════════════════════════════════
    pdf.section("Security Validations")

    pdf.test("Path traversal prevention",
             ["Try API call with csv_file='../../etc/passwd'",
              "Try csv_file='../secret.csv'"],
             ["400 error: invalid filename",
              "No file read outside app directory"],
             auto="Automatable", priority="Critical")

    pdf.test("XSS prevention in cell values",
             ["Enter '<script>alert(1)</script>' as a cell value",
              "Save and reload"],
             ["Script tags escaped, not executed",
              "Value shown as literal text in the cell"],
             auto="Partially automatable", priority="Critical")

    pdf.test("Rate limiting",
             ["Send 31+ POST requests within 60 seconds"],
             ["429 Too Many Requests after 30 writes",
              "Read limit: 120 per 60 seconds"],
             auto="Automatable", priority="Medium")

    pdf.test("Payload size limit (10 MB)",
             ["Try to POST a >10 MB payload"],
             ["413 error: payload too large"],
             auto="Automatable", priority="Medium")

    pdf.test("Cell value length limit (1000 chars)",
             ["Paste 1001+ characters into a cell",
              "Try to save"],
             ["Frontend truncates at 1000 with warning on paste",
              "Backend validates: 400 if >1000 chars"],
             auto="Partially automatable", priority="Medium")

    # ══════════════════════════════════════════════════════════════
    # SECTION 22: CSS & UI Polish
    # ══════════════════════════════════════════════════════════════
    pdf.section("CSS & UI Polish")

    pdf.test("Approval bar reason truncation",
             ["Trigger an approval with a very long reason (400+ chars)",
              "Check the approval bar"],
             ["Reason text truncated with ellipsis",
              "Hover expands to full text (white-space: normal)",
              "Title tooltip also shows full text"],
             priority="Medium")

    pdf.test("Addition preview cell truncation",
             ["Trigger addition approval with long cell values",
              "Click 'Show Requested Rows'"],
             ["Preview cells truncated at 260px with ellipsis",
              "Hover tooltip shows full value"],
             priority="Low")

    pdf.test("Control Panel reason column truncation",
             ["Check CP > Approval Queue with long reasons"],
             ["Reason cells use wl-cp-reason-cell with 260px max-width",
              "Hover shows full text via title attribute"],
             priority="Low")

    pdf.test("Modal overflow handling",
             ["Open any modal (Remove Row, Bulk Edit, etc.)",
              "Check behavior on narrow browser window"],
             ["Modal is scrollable within viewport",
              "No content clips or overflows"],
             priority="Low")

    # ── Summary page ──
    pdf.add_page()
    pdf.ln(10)
    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(30, 30, 30)
    pdf.cell(0, 12, "Test Plan Summary", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(8)

    pdf.set_font("Helvetica", "", 12)
    pdf.set_text_color(50, 50, 50)
    pdf.cell(0, 8, f"Total tests: {pdf._total_tests}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 8, f"Sections: {pdf._section_num}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(8)

    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 8, "Tests I (Claude) can help automate:", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    automatable = [
        "Backend API validation tests (path traversal, rate limiting, payload limits)",
        "Audit log verification (search wl_audit after each action)",
        "Daily limit counter verification",
        "Approval workflow state machine (submit/approve/reject/cancel/expire)",
        "Diff algorithm correctness (add+edit+remove combinations)",
        "Version snapshot count verification",
        "RBAC permission checks (all endpoint/role combinations)",
        "Optimistic locking conflict scenarios",
        "CSV import validation (headers, row limits, merge logic)",
        "Auto-expiration row removal verification",
    ]
    for item in automatable:
        pdf.cell(6)
        pdf.multi_cell(0, 6, f"- {item}", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(6)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 8, "Tests that require manual browser interaction:", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    manual = [
        "Drag-and-drop (row reorder, column reorder, column resize)",
        "Date/time picker interactions (preset buttons, calendar, apply/clear)",
        "Visual CSS verification (dark theme, truncation, highlights, colors)",
        "Keyboard shortcuts (Ctrl+S, Ctrl+Z, Escape, Alt+Arrow)",
        "Browser prompt() for comments (when no Comment column)",
        "Clipboard paste sanitization",
        "Presence bar updates between concurrent users",
        "Modal focus trapping and overlay click-to-close",
        "Undo bar countdown timer visual",
        "Concurrent multi-tab conflict detection modals",
    ]
    for item in manual:
        pdf.cell(6)
        pdf.multi_cell(0, 6, f"- {item}", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(8)
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(20, 60, 120)
    pdf.cell(0, 8, "Recommended testing order:", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(50, 50, 50)
    order = [
        "1.  Sections 1-3: Navigation, table display, basic editing (foundation)",
        "2.  Sections 4-6: Row/column/bulk operations (core CRUD)",
        "3.  Section 7: Save flow (the main integration point)",
        "4.  Section 20: Combined actions / edge cases (where bugs hide)",
        "5.  Sections 12-13: Approval workflow (complex state machine)",
        "6.  Sections 14-15: Control Panel admin features",
        "7.  Section 16: Audit trail verification (confirms all above logged correctly)",
        "8.  Sections 17-18: RBAC and concurrency (security)",
        "9.  Sections 21-22: Security and polish (final checks)",
    ]
    for item in order:
        pdf.cell(6)
        pdf.multi_cell(0, 6, item, new_x="LMARGIN", new_y="NEXT")

    # Output
    pdf.output(OUTPUT)
    print(f"PDF saved to: {OUTPUT}")
    print(f"Total tests: {pdf._total_tests}")
    print(f"Total sections: {pdf._section_num}")


if __name__ == "__main__":
    build_pdf()
