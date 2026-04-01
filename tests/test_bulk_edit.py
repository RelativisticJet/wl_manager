"""
Integration tests for Bulk Edit feature.

Tests bulk editing a column value across multiple rows, including
the approval workflow trigger at threshold and audit events.

Run:  cd tests && python -m unittest test_bulk_edit -v
"""

import time
import unittest
from test_integration_base import (
    WLIntegrationTestCase, ADMIN, WLADMIN1, ANALYST1, ANALYST2,
    TEST_CSV, TEST_RULE, TEST_APP_CONTEXT,
    api_post, save_csv, get_csv_content, search_audit,
    submit_approval, process_approval, cancel_request,
    get_approval_queue, wait_for_indexing, reset_daily_limits,
)


def set_daily_limits(limits, creds=WLADMIN1):
    return api_post({"action": "set_daily_limits", "limits": limits},
                    creds=creds)


def reset_usage(analyst=None, creds=WLADMIN1):
    payload = {"action": "reset_daily_usage"}
    if analyst:
        payload["analyst"] = analyst
    return api_post(payload, creds=creds)


class Test01_BulkEditDirect(WLIntegrationTestCase):
    """Tests for bulk edit via direct save (below approval threshold)."""

    def test_bulk_edit_single_column(self):
        """Bulk edit changes a column value across multiple rows."""
        headers, rows, mtime = self._load_csv()
        visible = [h for h in headers if not h.startswith("_")]
        if len(rows) < 3:
            self.skipTest("Need at least 3 rows")

        target_col = visible[0]
        original_vals = [rows[i].get(target_col, "") for i in range(2)]

        # Edit first 2 rows
        ts = int(time.time())
        for i in range(2):
            rows[i][target_col] = f"bulk_edited_{ts}"

        status, result = save_csv(
            headers, rows, comment="Bulk edit test",
            expected_mtime=mtime,
            extra_payload={"_bulk_edit_count": 2})
        self.assertEqual(status, 200)

        # Verify the edit persisted
        _, rows_after, _ = self._load_csv()
        for i in range(2):
            self.assertEqual(rows_after[i].get(target_col),
                             f"bulk_edited_{ts}")

        # Check audit event
        events = self._get_latest_audit("row_edited")
        self.assertTrue(events, "No row_edited audit event")
        self.assertGreaterEqual(int(events[0].get("edited_row_count", 0)), 2)

        # Restore
        _, r2, m2 = self._load_csv()
        for i in range(2):
            r2[i][target_col] = original_vals[i]
        save_csv(headers, r2, comment="Restore bulk edit")


class Test02_BulkEditApproval(WLIntegrationTestCase):
    """Tests for bulk edit triggering the approval workflow."""

    def test_bulk_edit_at_threshold_requires_approval(self):
        """Bulk editing >= threshold rows triggers approval gate (403)."""
        # Set threshold to 2
        set_daily_limits({"bulk_row_edit_threshold": 2})
        time.sleep(0.3)

        headers, rows, mtime = self._load_csv()
        visible = [h for h in headers if not h.startswith("_")]
        if len(rows) < 2:
            self.skipTest("Need at least 2 rows")

        target_col = visible[0]
        for i in range(2):
            rows[i][target_col] = f"threshold_{int(time.time())}"

        status, result = save_csv(
            headers, rows, comment="Should trigger approval",
            expected_mtime=mtime, creds=ANALYST1,
            extra_payload={"_bulk_edit_count": 2})
        self.assertEqual(status, 403,
                         f"Expected 403 approval required, got {status}: {result}")
        self.assertTrue(result.get("requires_approval"),
                        "Response should include requires_approval flag")

        # Restore threshold
        reset_daily_limits(creds=ADMIN)

    def test_bulk_edit_below_threshold_succeeds(self):
        """Bulk editing below threshold rows succeeds directly."""
        # Set high threshold
        set_daily_limits({"bulk_row_edit_threshold": 100})
        reset_usage(analyst="analyst1", creds=WLADMIN1)
        time.sleep(0.3)

        headers, rows, mtime = self._load_csv()
        visible = [h for h in headers if not h.startswith("_")]
        if not rows:
            self.skipTest("Need rows")

        target_col = visible[0]
        old_val = rows[0].get(target_col, "")
        rows[0][target_col] = f"below_thresh_{int(time.time())}"

        status, result = save_csv(
            headers, rows, comment="Below threshold edit",
            expected_mtime=mtime, creds=ANALYST1,
            extra_payload={"_bulk_edit_count": 1})
        self.assertEqual(status, 200)

        # Restore
        _, r2, m2 = self._load_csv()
        r2[0][target_col] = old_val
        save_csv(headers, r2, comment="Restore below threshold")
        reset_daily_limits(creds=ADMIN)


if __name__ == "__main__":
    unittest.main()
