"""
Integration tests for row expiration / auto-removal.

Verifies that rows with past dates in expiration columns are automatically
removed when the CSV is loaded, and the correct audit events are created.

Run:  cd tests && python -m unittest test_expiration -v
"""

import time
import unittest
from datetime import datetime, timezone, timedelta
from test_integration_base import (
    WLIntegrationTestCase, ADMIN, ANALYST1,
    TEST_CSV, TEST_APP_CONTEXT,
    api_get, save_csv, get_csv_content, search_audit, wait_for_indexing,
)


class Test01_ExpirationBasics(WLIntegrationTestCase):
    """Tests for auto-removal of expired rows on CSV load."""

    def _find_expire_col(self, headers):
        """Find the expiration column in headers."""
        expire_names = {
            "expires", "expire", "expiration", "expiration_date",
            "expiry", "termination", "termination_date",
        }
        for h in headers:
            if h.lower() in expire_names:
                return h
        return None

    def test_expired_utc_row_removed_on_load(self):
        """Row with past UTC date is auto-removed when CSV is loaded."""
        headers, rows, mtime = self._load_csv()
        expire_col = self._find_expire_col(headers)
        if not expire_col:
            self.skipTest("No expiration column in test CSV")

        visible = [h for h in headers if not h.startswith("_")]
        original_count = len(rows)

        # Add a row with expired UTC date (yesterday)
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1))
        expired_date = yesterday.strftime("%Y-%m-%d %H:%M") + " UTC"
        new_row = {h: f"expire_test_{h}" for h in visible}
        new_row[expire_col] = expired_date
        rows.append(new_row)

        status, result = save_csv(headers, rows, comment="Add expired row",
                                  expected_mtime=mtime)
        self.assertEqual(status, 200)

        # Reload — the expired row should be auto-removed
        time.sleep(1)
        s2, data2 = get_csv_content()
        self.assertEqual(s2, 200)

        # Check auto-removal happened
        auto_count = data2.get("auto_removed_count", 0)
        self.assertGreaterEqual(auto_count, 1,
                                "Expected at least 1 auto-removed row")

        # The row count should be back to original (expired row removed)
        self.assertEqual(len(data2["rows"]), original_count,
                         "Expired row should have been auto-removed")

    def test_future_date_row_not_removed(self):
        """Row with future date is NOT auto-removed."""
        headers, rows, mtime = self._load_csv()
        expire_col = self._find_expire_col(headers)
        if not expire_col:
            self.skipTest("No expiration column in test CSV")

        visible = [h for h in headers if not h.startswith("_")]
        original_count = len(rows)

        # Add a row with future UTC date (tomorrow)
        tomorrow = (datetime.now(timezone.utc) + timedelta(days=1))
        future_date = tomorrow.strftime("%Y-%m-%d %H:%M") + " UTC"
        new_row = {h: f"future_test_{h}" for h in visible}
        new_row[expire_col] = future_date
        rows.append(new_row)

        status, result = save_csv(headers, rows, comment="Add future row",
                                  expected_mtime=mtime)
        self.assertEqual(status, 200)

        # Reload — the future row should still be there
        time.sleep(1)
        s2, data2 = get_csv_content()
        self.assertEqual(len(data2["rows"]), original_count + 1,
                         "Future-dated row should NOT be removed")

        # Cleanup — remove the test row
        _, r3, m3 = self._load_csv()
        r3 = [r for r in r3 if r.get(visible[0]) != f"future_test_{visible[0]}"]
        save_csv(headers, r3, comment="Cleanup future row")

    def test_empty_expire_cell_treated_as_permanent(self):
        """Row with empty expiration cell is never auto-removed."""
        headers, rows, mtime = self._load_csv()
        expire_col = self._find_expire_col(headers)
        if not expire_col:
            self.skipTest("No expiration column in test CSV")

        visible = [h for h in headers if not h.startswith("_")]
        original_count = len(rows)

        # Add a row with empty expiration
        new_row = {h: f"perm_test_{h}" for h in visible}
        new_row[expire_col] = ""
        rows.append(new_row)

        status, result = save_csv(headers, rows, comment="Add permanent row",
                                  expected_mtime=mtime)
        self.assertEqual(status, 200)

        # Reload — should still be there
        time.sleep(1)
        s2, data2 = get_csv_content()
        self.assertEqual(len(data2["rows"]), original_count + 1,
                         "Row with empty expiration should be permanent")

        # Cleanup
        _, r3, m3 = self._load_csv()
        r3 = [r for r in r3 if r.get(visible[0]) != f"perm_test_{visible[0]}"]
        save_csv(headers, r3, comment="Cleanup permanent row")


class Test02_ExpirationAudit(WLIntegrationTestCase):
    """Tests for auto-removal audit events."""

    def _find_expire_col(self, headers):
        expire_names = {
            "expires", "expire", "expiration", "expiration_date",
            "expiry", "termination", "termination_date",
        }
        for h in headers:
            if h.lower() in expire_names:
                return h
        return None

    def test_auto_removed_audit_event(self):
        """Auto-removal creates an audit event with action='auto_removed'."""
        headers, rows, mtime = self._load_csv()
        expire_col = self._find_expire_col(headers)
        if not expire_col:
            self.skipTest("No expiration column in test CSV")

        visible = [h for h in headers if not h.startswith("_")]

        # Add 2 expired rows
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1))
        expired_date = yesterday.strftime("%Y-%m-%d %H:%M") + " UTC"
        for i in range(2):
            new_row = {h: f"audit_expire_{i}_{h}" for h in visible}
            new_row[expire_col] = expired_date
            rows.append(new_row)

        save_csv(headers, rows, comment="Add 2 expired rows for audit test",
                 expected_mtime=mtime)

        # Trigger auto-removal by loading
        time.sleep(1)
        get_csv_content()

        # Check audit
        events = self._get_latest_audit("auto_removed")
        self.assertTrue(events, "No auto_removed audit event found")
        latest = events[0]
        self.assertEqual(latest.get("analyst"), "system")
        self.assertGreaterEqual(int(latest.get("removed_row_count", 0)), 2)

    def test_malformed_date_rejected_on_save(self):
        """Row with malformed date in expiration column is rejected (400)."""
        headers, rows, mtime = self._load_csv()
        expire_col = self._find_expire_col(headers)
        if not expire_col:
            self.skipTest("No expiration column in test CSV")

        visible = [h for h in headers if not h.startswith("_")]

        # Add row with garbage date
        new_row = {h: f"malform_test_{h}" for h in visible}
        new_row[expire_col] = "not-a-date"
        rows.append(new_row)

        status, result = save_csv(headers, rows, comment="Add malformed date row",
                                  expected_mtime=mtime)
        self.assertEqual(status, 400,
                         f"Malformed date should be rejected: {result}")
        self.assertIn("Invalid date format", result.get("error", ""))


if __name__ == "__main__":
    unittest.main()
