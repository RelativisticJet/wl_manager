"""
Integration tests for combined / non-standard actions and their audit trails.

Tests the tricky scenarios where multiple operations happen simultaneously
(edit+remove, add+edit+save, column ops, etc.) and verifies the audit log
captures everything correctly.

Run:  python -m pytest tests/test_combined_actions.py -v
"""

import copy
import time
import unittest
from test_integration_base import (
    WLIntegrationTestCase, ADMIN, WLADMIN1, ANALYST1, ANALYST2,
    TEST_CSV, TEST_RULE, TEST_APP_CONTEXT,
    api_get, api_post, get_csv_content, save_csv, search_audit,
    wait_for_indexing, clear_approval_queue, reset_daily_limits,
    make_row, make_rows,
)


class TestEditAndSave(WLIntegrationTestCase):
    """Tests for basic edit + save and the resulting audit events."""

    def test_single_cell_edit_audit(self):
        """Edit one cell → save → audit shows row_edited with count=1."""
        headers, rows, mtime = self._load_csv()
        if not rows:
            self.skipTest("Test CSV has no rows")

        # Modify a cell
        original_val = rows[0].get(headers[0], "")
        new_val = f"test_edit_{int(time.time())}"
        rows[0][headers[0]] = new_val

        status, result = save_csv(headers, rows, comment="Single cell edit",
                                  expected_mtime=mtime)
        self.assertEqual(status, 200)

        events = self._get_latest_audit("row_edited")
        self.assertTrue(events, "No row_edited audit event found")
        latest = events[0]
        self.assertEqual(str(latest.get("edited_row_count")), "1")
        self.assertEqual(latest.get("csv_file"), TEST_CSV)

        # Restore
        rows[0][headers[0]] = original_val
        save_csv(headers, rows, comment="Restore after edit test")

    def test_add_rows_audit(self):
        """Add 2 rows → save → audit shows row_added with count=2."""
        headers, rows, mtime = self._load_csv()
        original_count = len(rows)

        # Add 2 new rows
        visible = [h for h in headers if not h.startswith("_")]
        new_row1 = make_row(visible, "new1")
        new_row2 = make_row(visible, "new2")
        rows.append(new_row1)
        rows.append(new_row2)

        status, result = save_csv(headers, rows, comment="Add 2 test rows",
                                  expected_mtime=mtime)
        self.assertEqual(status, 200)
        self.assertIn("diff", result)

        events = self._get_latest_audit("row_added")
        self.assertTrue(events, "No row_added audit event")
        latest = events[0]
        self.assertEqual(str(latest.get("added_row_count")), "2")

        # Restore — remove the added rows
        _, rows_now, new_mtime = self._load_csv()
        rows_now = rows_now[:original_count]
        save_csv(headers, rows_now, comment="Cleanup added rows")

    def test_no_change_detection(self):
        """Save without changes → 'No changes detected'."""
        headers, rows, mtime = self._load_csv()

        status, result = save_csv(headers, rows, comment="No changes",
                                  expected_mtime=mtime)
        self.assertEqual(status, 200)
        self.assertIn("No changes", result.get("message", ""))


class TestAddAndEditCombined(WLIntegrationTestCase):
    """Tests for adding rows + editing existing rows in one save."""

    def test_add_and_edit_separate_audit_events(self):
        """Add 1 row + edit 1 existing cell → save → 2 audit events."""
        headers, rows, mtime = self._load_csv()
        if not rows:
            self.skipTest("Test CSV has no rows")

        original_count = len(rows)
        visible = [h for h in headers if not h.startswith("_")]
        original_val = rows[0].get(visible[0], "")

        # Edit existing row
        ts = int(time.time())
        rows[0][visible[0]] = f"edited_{ts}"

        # Add new row
        new_row = make_row(visible, f"added_{ts}")
        rows.append(new_row)

        status, result = save_csv(headers, rows, comment="Add + edit combo",
                                  expected_mtime=mtime)
        self.assertEqual(status, 200)

        # Verify both audit event types exist
        wait_for_indexing()
        added_events = search_audit(
            f'csv_file="{TEST_CSV}" action="row_added"',
            earliest="-1m")
        edited_events = search_audit(
            f'csv_file="{TEST_CSV}" action="row_edited"',
            earliest="-1m")

        self.assertTrue(added_events, "Missing row_added event")
        self.assertTrue(edited_events, "Missing row_edited event")
        self.assertEqual(str(added_events[0].get("added_row_count")), "1")
        self.assertEqual(str(edited_events[0].get("edited_row_count")), "1")

        # Restore
        rows[0][visible[0]] = original_val
        _, r2, m2 = self._load_csv()
        r2 = r2[:original_count]
        r2[0][visible[0]] = original_val
        save_csv(headers, r2, comment="Cleanup add+edit test")


class TestRemoveAndAudit(WLIntegrationTestCase):
    """Tests for row removal with various scenarios."""

    def _ensure_test_rows(self, count=3):
        """Ensure the test CSV has at least `count` rows. Returns (headers, rows, mtime)."""
        headers, rows, mtime = self._load_csv()
        visible = [h for h in headers if not h.startswith("_")]
        while len(rows) < count:
            rows.append(make_row(visible, "filler", len(rows)))
        if len(rows) > len(self._load_csv()[1]):
            status, _ = save_csv(headers, rows, comment="Ensure test rows")
            self.assertEqual(status, 200)
            headers, rows, mtime = self._load_csv()
        return headers, rows, mtime

    def test_remove_single_row(self):
        """Remove 1 row → audit shows row_removed with reason."""
        headers, rows, mtime = self._ensure_test_rows(3)
        removed_row = rows.pop(1)  # Remove middle row

        status, result = save_csv(
            headers, rows, comment="Remove one row",
            expected_mtime=mtime,
            extra_payload={
                "removal_reasons": [{"reason": "Test removal reason"}],
            })
        self.assertEqual(status, 200)

        events = self._get_latest_audit("row_removed")
        if not events:
            # Could also be row_removed_multiple with count 1
            events = self._get_latest_audit("row_removed_multiple")
        self.assertTrue(events, "No removal audit event found")

    def test_remove_multiple_rows(self):
        """Remove 2 rows → audit shows row_removed_multiple or multiple row_removed."""
        headers, rows, mtime = self._ensure_test_rows(4)
        original_count = len(rows)

        # Remove first 2 rows
        rows = rows[2:]

        status, result = save_csv(
            headers, rows, comment="Remove two rows",
            expected_mtime=mtime,
            extra_payload={
                "removal_reasons": [
                    {"reason": "Bulk remove test A"},
                    {"reason": "Bulk remove test B"},
                ],
            })
        self.assertEqual(status, 200)

        # Verify audit
        wait_for_indexing()
        events = search_audit(
            f'csv_file="{TEST_CSV}" (action="row_removed" OR action="row_removed_multiple")',
            earliest="-1m")
        self.assertTrue(events, "No removal audit events")

    def test_edit_alongside_removal(self):
        """Edit row A + remove row B → edit gets 'Edited alongside removal' comment."""
        headers, rows, mtime = self._ensure_test_rows(4)
        visible = [h for h in headers if not h.startswith("_")]

        # Edit row 0
        ts = int(time.time())
        old_val = rows[0].get(visible[0], "")
        rows[0][visible[0]] = f"edited_alongside_{ts}"

        # Remove row 2
        removed = rows.pop(2)

        status, result = save_csv(
            headers, rows, comment="Edit + remove combo",
            expected_mtime=mtime,
            extra_payload={
                "removal_reasons": [{"reason": "Remove alongside edit"}],
            })
        self.assertEqual(status, 200)

        # Verify both events exist
        wait_for_indexing()
        edited_events = search_audit(
            f'csv_file="{TEST_CSV}" action="row_edited"',
            earliest="-1m")
        removal_events = search_audit(
            f'csv_file="{TEST_CSV}" (action="row_removed" OR action="row_removed_multiple")',
            earliest="-1m")

        self.assertTrue(edited_events, "Missing row_edited event for edit alongside removal")
        self.assertTrue(removal_events, "Missing removal event")

        # Check the edit event's comment mentions "alongside removal"
        edit_comment = edited_events[0].get("comment", "")
        self.assertIn("alongside removal", edit_comment.lower(),
                      f"Expected 'alongside removal' in comment, got: {edit_comment}")

        # Restore
        rows[0][visible[0]] = old_val
        _, cur_rows, cur_m = self._load_csv()
        cur_rows[0][visible[0]] = old_val
        visible_fill = {h: removed.get(h, "") for h in visible}
        cur_rows.insert(2, visible_fill)
        save_csv(headers, cur_rows, comment="Cleanup edit+remove test")


class TestColumnOperations(WLIntegrationTestCase):
    """Tests for column add, remove, rename, reorder and their audit trails."""

    def test_add_column(self):
        """Add a column → audit shows column_added."""
        headers, rows, mtime = self._load_csv()
        new_col = f"test_col_{int(time.time())}"

        # Add column before any metadata columns
        meta_idx = next((i for i, h in enumerate(headers) if h.startswith("_")),
                        len(headers))
        headers.insert(meta_idx, new_col)
        for row in rows:
            row[new_col] = ""

        status, result = save_csv(headers, rows, comment=f"Add column {new_col}",
                                  expected_mtime=mtime)
        self.assertEqual(status, 200)

        events = self._get_latest_audit("column_added")
        self.assertTrue(events, "No column_added audit event")

        # Cleanup — remove the column
        _, rows2, m2 = self._load_csv()
        h2 = [h for h in self._load_csv()[0] if h != new_col]
        for r in rows2:
            r.pop(new_col, None)
        save_csv(h2, rows2, comment=f"Remove test column {new_col}",
                 extra_payload={"column_removal_reasons": [{"column": new_col, "reason": "Cleanup"}]})

    def test_remove_column(self):
        """Remove a column → audit shows column_removed with reason."""
        headers, rows, mtime = self._load_csv()

        # First add a test column to remove
        test_col = f"removeme_{int(time.time())}"
        meta_idx = next((i for i, h in enumerate(headers) if h.startswith("_")),
                        len(headers))
        headers.insert(meta_idx, test_col)
        for row in rows:
            row[test_col] = ""  # Empty to avoid column_nonempty_threshold
        save_csv(headers, rows, comment=f"Add {test_col} for removal test")

        # Now remove it
        h2, rows2, m2 = self._load_csv()
        h2_clean = [h for h in h2 if h != test_col]
        for r in rows2:
            r.pop(test_col, None)

        status, result = save_csv(
            h2_clean, rows2, comment=f"Remove column {test_col}",
            expected_mtime=m2,
            extra_payload={"column_removal_reasons": [{"column": test_col, "reason": "Test removal"}]})
        self.assertEqual(status, 200)

        events = self._get_latest_audit("column_removed")
        self.assertTrue(events, "No column_removed audit event")

    def test_rename_column(self):
        """Rename a column → audit shows column_renamed with old/new names."""
        headers, rows, mtime = self._load_csv()

        # Add a column to rename
        old_name = f"rename_old_{int(time.time())}"
        new_name = f"rename_new_{int(time.time())}"
        meta_idx = next((i for i, h in enumerate(headers) if h.startswith("_")),
                        len(headers))
        headers.insert(meta_idx, old_name)
        for row in rows:
            row[old_name] = "rval"
        save_csv(headers, rows, comment=f"Add {old_name} for rename test")

        # Rename it
        h2, rows2, m2 = self._load_csv()
        h2 = [new_name if h == old_name else h for h in h2]
        for r in rows2:
            if old_name in r:
                r[new_name] = r.pop(old_name)

        status, result = save_csv(
            h2, rows2, comment=f"Rename {old_name} to {new_name}",
            expected_mtime=m2,
            extra_payload={
                "column_renames": [{"old_name": old_name, "new_name": new_name}]
            })
        self.assertEqual(status, 200)

        events = self._get_latest_audit("column_renamed")
        self.assertTrue(events, "No column_renamed audit event")
        self.assertEqual(events[0].get("column_renamed_before"), old_name)
        self.assertEqual(events[0].get("column_renamed_after"), new_name)

        # Cleanup
        h3, rows3, m3 = self._load_csv()
        h3_clean = [h for h in h3 if h != new_name]
        for r in rows3:
            r.pop(new_name, None)
        save_csv(h3_clean, rows3, comment="Cleanup rename test",
                 extra_payload={"column_removal_reasons": [{"column": new_name, "reason": "Cleanup"}]})

    def test_reorder_columns(self):
        """Reorder columns → audit shows column_reordered."""
        headers, rows, mtime = self._load_csv()
        visible = [h for h in headers if not h.startswith("_")]
        if len(visible) < 2:
            self.skipTest("Need at least 2 visible columns to reorder")

        # Swap first two visible columns
        meta = [h for h in headers if h.startswith("_")]
        new_visible = [visible[1], visible[0]] + visible[2:]
        new_headers = new_visible + meta

        status, result = save_csv(
            new_headers, rows, comment="Reorder columns",
            expected_mtime=mtime,
            extra_payload={
                "column_reorder": {
                    "column": visible[0],
                    "from_position": 0,
                    "to_position": 1,
                }
            })
        self.assertEqual(status, 200)

        events = self._get_latest_audit("column_reordered")
        self.assertTrue(events, "No column_reordered audit event")

        # Restore original order
        _, rows2, m2 = self._load_csv()
        save_csv(headers, rows2, comment="Restore column order",
                 extra_payload={
                     "column_reorder": {
                         "column": visible[0],
                         "from_position": 1,
                         "to_position": 0,
                     }
                 })


class TestRowReorder(WLIntegrationTestCase):
    """Tests for row reorder and audit trail."""

    def test_reorder_rows(self):
        """Reorder rows → audit shows row_reordered with from/to positions."""
        headers, rows, mtime = self._load_csv()
        if len(rows) < 2:
            self.skipTest("Need at least 2 rows to reorder")

        # Swap first two rows
        rows[0], rows[1] = rows[1], rows[0]

        status, result = save_csv(
            headers, rows, comment="Reorder rows",
            expected_mtime=mtime,
            extra_payload={
                "row_reorder": {"from_position": 0, "to_position": 1}
            })
        self.assertEqual(status, 200)

        events = self._get_latest_audit("row_reordered")
        self.assertTrue(events, "No row_reordered audit event")

        # Restore
        _, rows2, m2 = self._load_csv()
        rows2[0], rows2[1] = rows2[1], rows2[0]
        save_csv(headers, rows2, comment="Restore row order",
                 extra_payload={
                     "row_reorder": {"from_position": 1, "to_position": 0}
                 })


class TestOptimisticLocking(WLIntegrationTestCase):
    """Tests for conflict detection via mtime-based optimistic locking."""

    def test_stale_mtime_causes_409(self):
        """Save with old mtime → 409 conflict."""
        headers, rows, mtime = self._load_csv()

        # Save once to advance mtime
        visible = [h for h in headers if not h.startswith("_")]
        ts = int(time.time())
        rows[0][visible[0]] = f"advance_{ts}"
        save_csv(headers, rows, comment="Advance mtime")

        # Now try saving with the OLD mtime
        status, data = save_csv(headers, rows, comment="Stale save",
                                expected_mtime=mtime)
        self.assertEqual(status, 409, f"Expected 409 conflict, got {status}")

        # Restore
        headers2, rows2, m2 = self._load_csv()
        rows2[0][visible[0]] = rows[0].get(visible[0], "")
        save_csv(headers2, rows2, comment="Cleanup lock test")


class TestDiffAlgorithmViaAPI(WLIntegrationTestCase):
    """Verify the diff algorithm produces correct results via the API."""

    def test_diff_shows_additions(self):
        """Diff result includes added rows."""
        headers, rows, mtime = self._load_csv()
        visible = [h for h in headers if not h.startswith("_")]

        new_row = make_row(visible, "diff_test")
        rows.append(new_row)

        status, result = save_csv(headers, rows, comment="Diff add test",
                                  expected_mtime=mtime)
        self.assertEqual(status, 200)

        diff = result.get("diff", {})
        if isinstance(diff, dict):
            self.assertGreater(diff.get("added_count", 0), 0,
                               "Diff should report added rows")
        else:
            self.assertIn("+", str(diff), "Diff should contain + lines")

        # Cleanup
        _, r2, m2 = self._load_csv()
        r2 = [r for r in r2 if r.get(visible[0]) != f"diff_test_{visible[0]}"]
        save_csv(headers, r2, comment="Cleanup diff test")

    def test_diff_shows_edits(self):
        """Diff result includes changed fields."""
        headers, rows, mtime = self._load_csv()
        if not rows:
            self.skipTest("No rows")
        visible = [h for h in headers if not h.startswith("_")]
        old_val = rows[0].get(visible[0], "")
        rows[0][visible[0]] = f"diff_edit_{int(time.time())}"

        status, result = save_csv(headers, rows, comment="Diff edit test",
                                  expected_mtime=mtime)
        self.assertEqual(status, 200)
        diff = result.get("diff", "")
        self.assertTrue(diff, "Expected non-empty diff for edit")

        # Restore
        _, r2, m2 = self._load_csv()
        r2[0][visible[0]] = old_val
        save_csv(headers, r2, comment="Restore diff edit test")


class TestSecurityValidations(WLIntegrationTestCase):
    """Backend security checks via API."""

    def test_path_traversal_get(self):
        """GET with path traversal CSV name → 400 or 404."""
        status, data = api_get("get_csv_content", {
            "csv_file": "../../etc/passwd",
            "app_context": TEST_APP_CONTEXT,
        })
        self.assertIn(status, (400, 404))

    def test_path_traversal_save(self):
        """POST save_csv with traversal name → 400."""
        status, data = save_csv(
            ["col"], [{"col": "val"}],
            csv_file="../../../etc/shadow.csv")
        self.assertIn(status, (400, 404))

    def test_cell_value_length_limit(self):
        """Cell value >1000 chars → 400."""
        headers, rows, mtime = self._load_csv()
        visible = [h for h in headers if not h.startswith("_")]
        rows[0][visible[0]] = "A" * 1001

        status, data = save_csv(headers, rows, comment="Oversized cell",
                                expected_mtime=mtime)
        self.assertEqual(status, 400)

    def test_row_limit_5000(self):
        """Exceeding 5000 rows → 400."""
        headers, rows, mtime = self._load_csv()
        visible = [h for h in headers if not h.startswith("_")]

        # Generate 5001 rows
        big_rows = make_rows(visible, "r", 5001)

        status, data = save_csv(headers, big_rows, comment="Too many rows")
        self.assertEqual(status, 400)

    def test_column_limit_100(self):
        """Exceeding 100 columns → 400."""
        big_headers = [f"col_{i}" for i in range(101)]
        rows = [{h: "v" for h in big_headers}]

        status, data = save_csv(big_headers, rows, comment="Too many columns")
        self.assertEqual(status, 400)


if __name__ == "__main__":
    unittest.main()
