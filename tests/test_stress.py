"""
Integration tests for stress / edge case scenarios.

Tests large CSVs near row/column limits and concurrent-like access patterns.

Run:  cd tests && python -m unittest test_stress -v
"""

import time
import unittest
from test_integration_base import (
    WLIntegrationTestCase, ADMIN, WLADMIN1, ANALYST1, ANALYST2,
    TEST_CSV, TEST_APP_CONTEXT,
    api_post, save_csv, get_csv_content, reset_daily_limits,
    make_row, make_rows,
)


def _set_max_limits(creds=WLADMIN1):
    """Set all daily limits and approval thresholds to max (1000)."""
    BIG = 1000
    api_post({"action": "set_daily_limits", "limits": {
        "row_addition": BIG, "row_removal": BIG, "row_edit": BIG,
        "bulk_row_removal": BIG, "bulk_row_addition": BIG, "bulk_row_edit": BIG,
        "column_addition": BIG, "column_removal": BIG, "column_rename": BIG,
        "column_reorder": BIG, "row_reorder": BIG, "revert": BIG,
        "bulk_row_removal_threshold": BIG, "bulk_row_edit_threshold": BIG,
        "bulk_row_addition_threshold": BIG, "column_nonempty_threshold": BIG,
        "revert_row_threshold": BIG, "revert_column_threshold": BIG,
    }}, creds=creds)
    api_post({"action": "reset_daily_usage"}, creds=creds)


class Test01_LargeCsvBoundaries(WLIntegrationTestCase):
    """Tests near the row and column limits."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        _set_max_limits()
        time.sleep(0.5)

    @classmethod
    def tearDownClass(cls):
        reset_daily_limits()
        super().tearDownClass()

    def test_save_exceeding_row_limit(self):
        """Saving 5001 rows fails with 400 (hard cap)."""
        headers, _, _ = self._load_csv()
        visible = [h for h in headers if not h.startswith("_")]

        rows_5001 = make_rows(visible, "r", 5001)
        status, result = save_csv(headers, rows_5001,
                                  comment="5001 row overflow test")
        self.assertEqual(status, 400)

    def test_add_many_rows_within_daily_limit(self):
        """Adding many rows within daily limit succeeds."""
        headers, orig_rows, mtime = self._load_csv()
        visible = [h for h in headers if not h.startswith("_")]
        orig_count = len(orig_rows)

        # Add 200 new rows (make_rows uses empty string for Expires column)
        for row in make_rows(visible, "stress", 200):
            orig_rows.append(row)

        status, result = save_csv(headers, orig_rows,
                                  comment="Add 200 rows stress test",
                                  expected_mtime=mtime)
        self.assertEqual(status, 200,
                         f"Adding 200 rows should succeed: {result}")

        # Verify
        _, rows_after, _ = self._load_csv()
        self.assertEqual(len(rows_after), orig_count + 200)

        # Restore — remove the added rows
        save_csv(headers, rows_after[:orig_count],
                 comment="Restore after add rows test")

    def test_save_at_column_limit_boundary(self):
        """Saving exactly 100 columns succeeds (at hard cap)."""
        import subprocess, tempfile, os

        csv_path = "/opt/splunk/etc/apps/wl_manager/lookups/DR999_stress_test.csv"
        env = {**os.environ, 'MSYS_NO_PATHCONV': '1'}

        # Backup original CSV from container
        orig_csv = subprocess.run(
            ["docker", "exec", "wl_manager_test", "cat", csv_path],
            capture_output=True, text=True, env=env
        ).stdout

        # Write a tiny CSV to a temp file and docker cp it in
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv',
                                         delete=False, newline='') as f:
            f.write("a,b\nx,y\n")
            tmp_path = f.name

        try:
            subprocess.run(["docker", "cp", tmp_path,
                           f"wl_manager_test:{csv_path}"], env=env)
            subprocess.run(["docker", "exec", "-u", "0", "wl_manager_test",
                           "chown", "splunk:splunk", csv_path], env=env)

            # Now save with 100 columns (replaces 2-col/1-row CSV)
            big_headers = [f"col_{i}" for i in range(100)]
            rows = [{h: "v" for h in big_headers}]

            status, result = save_csv(big_headers, rows,
                                      comment="100 column boundary test")
            self.assertEqual(status, 200,
                             f"100 columns should be within limit: {result}")
        finally:
            # Restore original CSV
            with open(tmp_path, 'w', newline='') as f:
                f.write(orig_csv)
            subprocess.run(["docker", "cp", tmp_path,
                           f"wl_manager_test:{csv_path}"], env=env)
            subprocess.run(["docker", "exec", "-u", "0", "wl_manager_test",
                           "chown", "splunk:splunk", csv_path], env=env)
            os.unlink(tmp_path)

    def test_save_exceeding_column_limit(self):
        """Saving 101 columns fails with 400 (hard cap)."""
        big_headers = [f"col_{i}" for i in range(101)]
        rows = [{h: "v" for h in big_headers}]

        status, result = save_csv(big_headers, rows,
                                  comment="101 column overflow test")
        self.assertEqual(status, 400)

    def test_cell_value_at_limit(self):
        """Cell value at exactly 1000 chars succeeds."""
        headers, rows, mtime = self._load_csv()
        visible = [h for h in headers if not h.startswith("_")]
        old_val = rows[0].get(visible[0], "")

        rows[0][visible[0]] = "A" * 1000
        status, result = save_csv(headers, rows, comment="1000 char cell",
                                  expected_mtime=mtime)
        self.assertEqual(status, 200,
                         f"1000 char cell should succeed: {result}")

        # Restore
        _, r2, m2 = self._load_csv()
        r2[0][visible[0]] = old_val
        save_csv(headers, r2, comment="Restore cell limit test")

    def test_cell_value_exceeding_limit(self):
        """Cell value at 1001 chars fails with 400."""
        headers, rows, mtime = self._load_csv()
        visible = [h for h in headers if not h.startswith("_")]

        rows[0][visible[0]] = "A" * 1001
        status, result = save_csv(headers, rows, comment="1001 char cell",
                                  expected_mtime=mtime)
        self.assertEqual(status, 400)


class Test02_ConcurrentAccess(WLIntegrationTestCase):
    """Tests for optimistic locking under concurrent-like access."""

    def test_stale_mtime_rejected(self):
        """Save with outdated mtime is rejected (409 conflict)."""
        headers, rows, mtime = self._load_csv()
        visible = [h for h in headers if not h.startswith("_")]

        # Save once to advance mtime
        rows[0][visible[0]] = f"advance_{int(time.time())}"
        s1, _ = save_csv(headers, rows, comment="Advance mtime",
                         expected_mtime=mtime)
        self.assertEqual(s1, 200)

        # Try saving with old mtime
        rows[0][visible[0]] = f"stale_{int(time.time())}"
        s2, d2 = save_csv(headers, rows, comment="Stale save",
                          expected_mtime=mtime)  # old mtime!
        self.assertEqual(s2, 409, f"Expected 409, got {s2}: {d2}")

    def test_two_users_sequential_saves(self):
        """Two users saving sequentially — second must use fresh mtime."""
        # User 1 loads and saves
        h1, r1, m1 = self._load_csv(creds=ANALYST1)
        visible = [h for h in h1 if not h.startswith("_")]
        r1[0][visible[0]] = f"user1_{int(time.time())}"
        s1, _ = save_csv(h1, r1, comment="User 1 edit",
                         expected_mtime=m1, creds=ANALYST1)
        self.assertEqual(s1, 200)

        # User 2 loads (gets fresh mtime) and saves
        h2, r2, m2 = self._load_csv(creds=ANALYST2)
        r2[0][visible[0]] = f"user2_{int(time.time())}"
        s2, d2 = save_csv(h2, r2, comment="User 2 edit",
                          expected_mtime=m2, creds=ANALYST2)
        self.assertEqual(s2, 200,
                         f"User 2 with fresh mtime should succeed: {d2}")


class Test03_EmptyAndEdgeCases(WLIntegrationTestCase):
    """Edge cases for empty CSVs, no-change saves, etc."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Restore default limits so approval thresholds are low (3)
        reset_daily_limits()
        time.sleep(0.5)

    def test_save_empty_rows_triggers_approval(self):
        """Saving CSV with 0 rows (removing all) triggers approval gate (403)."""
        headers, rows, mtime = self._load_csv()
        # Removing all rows exceeds bulk_row_removal_threshold (default 3) → approval required
        if len(rows) >= 3:
            status, result = save_csv(headers, [], comment="Empty rows test",
                                      expected_mtime=mtime)
            self.assertEqual(status, 403,
                             f"Removing all rows should require approval: {result}")
        else:
            self.skipTest("Need >= 3 rows to trigger approval gate")

    def test_no_change_save(self):
        """Saving without changes returns 'No changes detected'."""
        headers, rows, mtime = self._load_csv()
        status, result = save_csv(headers, rows, comment="No changes",
                                  expected_mtime=mtime)
        self.assertEqual(status, 200)
        self.assertIn("No changes", result.get("message", ""))


if __name__ == "__main__":
    unittest.main()
