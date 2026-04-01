"""
Integration tests for CSV Import/Replace feature.

CSV import replace always requires approval. Tests verify the submission,
approval replay, and audit trail for import operations.

Run:  cd tests && python -m unittest test_csv_import -v
"""

import time
import unittest
from test_integration_base import (
    WLIntegrationTestCase, ADMIN, WLADMIN1, ANALYST1, ANALYST2,
    TEST_CSV, TEST_RULE, TEST_APP_CONTEXT,
    api_post, save_csv, get_csv_content,
    submit_approval, process_approval, cancel_request,
    get_approval_queue, search_audit, wait_for_indexing,
    make_rows,
)


class Test01_ImportApprovalGate(WLIntegrationTestCase):
    """CSV import replace always requires approval."""

    def test_import_replace_always_requires_approval(self):
        """check_approval_gate returns requires_approval=True for csv_import_replace."""
        payload = {
            "action": "check_approval_gate",
            "gate_action": "csv_import_replace",
            "csv_file": TEST_CSV,
            "app_context": TEST_APP_CONTEXT,
        }
        s, d = api_post(payload, creds=ANALYST1)
        self.assertEqual(s, 200)
        self.assertTrue(d.get("requires_approval"),
                        "csv_import_replace should always require approval")

    def test_submit_import_replace_request(self):
        """Can submit a csv_import_replace approval request."""
        headers, rows, _ = self._load_csv()
        visible = [h for h in headers if not h.startswith("_")]

        # Build replacement payload — just 3 rows
        replacement_rows = make_rows(visible, "import_r", 3)

        s, d = submit_approval(
            "csv_import_replace", creds=ANALYST1,
            description="Import replace test",
            original_payload={
                "action": "save_csv",
                "csv_file": TEST_CSV,
                "app_context": TEST_APP_CONTEXT,
                "detection_rule": TEST_RULE,
                "headers": visible,
                "rows": replacement_rows,
                "comment": "Imported CSV (replace mode)",
            },
            pending_highlight={
                "type": "import_replace",
                "row_count": 3,
                "col_count": len(visible),
            },
        )
        self.assertEqual(s, 200, f"Submit failed: {d}")

        # Cleanup — cancel the request
        cancel_request(d["request_id"], "Test cleanup", creds=ANALYST1)

    def test_import_replace_no_daily_limit(self):
        """csv_import_replace has no daily limit enforcement."""
        # This is implicitly tested: the submit succeeded without hitting
        # daily limits. csv_import_replace is exempt from _approval_limit_map.
        # Just verify it can be submitted.
        s, d = submit_approval(
            "csv_import_replace", creds=ANALYST2,
            description="No daily limit test")
        self.assertEqual(s, 200)
        cancel_request(d["request_id"], "Cleanup", creds=ANALYST2)


class Test02_ImportApproveReplay(WLIntegrationTestCase):
    """Test that approving an import replace request replaces the CSV."""

    def test_approve_import_replaces_csv(self):
        """Approving import replace overwrites CSV with submitted data."""
        # Get current state to restore later
        headers, rows, _ = self._load_csv()
        visible = [h for h in headers if not h.startswith("_")]
        original_count = len(rows)

        # Build small replacement CSV
        replacement_rows = make_rows(visible, "replaced", 3)

        # Submit import replace request
        s, d = submit_approval(
            "csv_import_replace", creds=ANALYST1,
            description="Approve replay test",
            original_payload={
                "action": "save_csv",
                "csv_file": TEST_CSV,
                "app_context": TEST_APP_CONTEXT,
                "detection_rule": TEST_RULE,
                "headers": visible,
                "rows": replacement_rows,
                "comment": "Import replace approval test",
            },
            pending_highlight={
                "type": "import_replace",
                "row_count": 3,
                "col_count": len(visible),
            },
        )
        self.assertEqual(s, 200)
        rid = d["request_id"]

        # Approve
        s2, d2 = process_approval(rid, "approve", creds=WLADMIN1)
        self.assertEqual(s2, 200, f"Approve failed: {d2}")

        # Verify CSV was replaced
        _, rows_after, _ = self._load_csv()
        self.assertEqual(len(rows_after), 3,
                         f"CSV should have 3 rows after import, got {len(rows_after)}")
        self.assertEqual(rows_after[0].get(visible[0]),
                         f"replaced_0_{visible[0]}")

        # Restore original CSV
        save_csv(headers, rows, comment="Restore after import test")


if __name__ == "__main__":
    unittest.main()
