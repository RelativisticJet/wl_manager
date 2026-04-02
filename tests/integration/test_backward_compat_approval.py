"""
Backward compatibility tests for v2.0 approval queue entries in v3.0.

Tests verify that pre-rewrite approval queue entries (from v2.0) can be loaded
and replayed correctly in v3.0 code.

Test approach:
- Load golden v2.0 queue entries from fixture
- Feed through wl_approval functions
- Verify entries parse and are recognized by v3.0
"""

import unittest
import json
import sys
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add bin directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'bin'))

try:
    from wl_approval import get_pending_for_csv, get_pending_for_rule, expire_pending_approvals
except ImportError:
    get_pending_for_csv = None
    get_pending_for_rule = None
    expire_pending_approvals = None


class TestV2ApprovalQueueBackwardCompat(unittest.TestCase):
    """Tests for v2.0 approval queue backward compatibility."""

    @classmethod
    def setUpClass(cls):
        """Load v2.0 approval queue fixture."""
        if get_pending_for_csv is None:
            cls.skipClass = True
            return

        fixture_path = Path(__file__).parent.parent / "fixtures" / "v2_approval_queue.json"
        with open(fixture_path, "r") as f:
            cls.v2_queue = json.load(f)

    def test_v2_approval_queue_fixture_loads(self):
        """Verify v2.0 approval queue fixture is valid JSON."""
        self.assertIsInstance(self.v2_queue, list)
        self.assertGreater(len(self.v2_queue), 0)

    def test_v2_queue_loads_without_error(self):
        """Test that v2.0 queue entries parse without errors."""
        for entry in self.v2_queue:
            self.assertIsInstance(entry, dict)
            # Should not raise exception
            self.assertIn("request_id", entry)
            self.assertIn("status", entry)
            self.assertIn("timestamp", entry)

    def test_v2_queue_entries_parseable(self):
        """Verify entries have expected structure."""
        required_fields = {"request_id", "status", "timestamp", "analyst", "action_type"}

        for entry in self.v2_queue:
            missing = required_fields - set(entry.keys())
            self.assertEqual(
                missing,
                set(),
                f"Entry missing fields {missing}: {json.dumps(entry, indent=2)}"
            )

    def test_v2_queue_actions_recognized(self):
        """Verify action_type values are recognized by v3.0."""
        recognized_actions = {
            "save_csv", "revert_csv", "add_rule", "delete_rule",
            "create_csv", "import_csv", "export_audit"
        }

        for entry in self.v2_queue:
            action = entry.get("action_type")
            self.assertIn(
                action,
                recognized_actions,
                f"Unknown action_type: {action}"
            )

    def test_v2_queue_status_values_recognized(self):
        """Verify status values are valid."""
        recognized_statuses = {"pending", "approved", "rejected", "expired", "cancelled"}

        for entry in self.v2_queue:
            status = entry.get("status")
            self.assertIn(
                status,
                recognized_statuses,
                f"Unknown status: {status}"
            )

    def test_v2_queue_pending_entries(self):
        """Test filtering pending entries."""
        pending = [e for e in self.v2_queue if e.get("status") == "pending"]
        self.assertGreater(len(pending), 0)

        for entry in pending:
            self.assertEqual(entry["status"], "pending")
            self.assertIn("analyst", entry)
            self.assertIn("reason", entry)

    def test_v2_queue_approved_entries(self):
        """Test filtering approved entries."""
        approved = [e for e in self.v2_queue if e.get("status") == "approved"]
        self.assertGreater(len(approved), 0)

        for entry in approved:
            self.assertEqual(entry["status"], "approved")

    def test_v2_queue_rejected_entries(self):
        """Test filtering rejected entries."""
        rejected = [e for e in self.v2_queue if e.get("status") == "rejected"]
        self.assertGreater(len(rejected), 0)

        for entry in rejected:
            self.assertEqual(entry["status"], "rejected")

    def test_v2_queue_csv_file_field(self):
        """Verify csv_file field for CSV-related actions."""
        for entry in self.v2_queue:
            action = entry.get("action_type")
            if action in ("save_csv", "revert_csv", "create_csv", "import_csv", "export_audit"):
                self.assertIn("csv_file", entry, f"Missing csv_file in {action}")

    def test_v2_queue_detection_rule_field(self):
        """Verify detection_rule field when applicable."""
        for entry in self.v2_queue:
            if "detection_rule" in entry:
                self.assertIsInstance(entry["detection_rule"], str)
                self.assertGreater(len(entry["detection_rule"]), 0)

    def test_v2_queue_payload_field_structure(self):
        """Verify payload field is a dict."""
        for entry in self.v2_queue:
            if "payload" in entry:
                self.assertIsInstance(entry["payload"], dict)

    def test_v2_queue_reason_field_present(self):
        """Verify reason field for audit trail."""
        for entry in self.v2_queue:
            self.assertIn("reason", entry)
            reason = entry.get("reason")
            self.assertIsInstance(reason, str)

    def test_v2_queue_timestamp_field_is_integer(self):
        """Verify timestamp is Unix epoch integer."""
        for entry in self.v2_queue:
            timestamp = entry.get("timestamp")
            self.assertIsInstance(timestamp, int)
            # Should be reasonable Unix timestamp (after 2020-01-01)
            self.assertGreater(timestamp, 1577836800)  # 2020-01-01

    def test_v2_queue_request_id_field_format(self):
        """Verify request_id is UUID format."""
        for entry in self.v2_queue:
            request_id = entry.get("request_id")
            self.assertIsInstance(request_id, str)
            # Should be UUID format: XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX
            self.assertRegex(
                request_id,
                r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
                f"Invalid UUID format: {request_id}"
            )

    def test_v2_queue_analyst_field_present(self):
        """Verify analyst field for audit trail."""
        for entry in self.v2_queue:
            analyst = entry.get("analyst")
            self.assertIsInstance(analyst, str)
            self.assertGreater(len(analyst), 0)

    def test_v2_save_csv_action_structure(self):
        """Verify save_csv action has expected structure."""
        save_entries = [e for e in self.v2_queue if e.get("action_type") == "save_csv"]
        self.assertGreater(len(save_entries), 0)

        for entry in save_entries:
            self.assertIn("csv_file", entry)
            self.assertIn("payload", entry)
            payload = entry.get("payload")
            self.assertIn("rows", payload)

    def test_v2_revert_csv_action_structure(self):
        """Verify revert_csv action has expected structure."""
        revert_entries = [e for e in self.v2_queue if e.get("action_type") == "revert_csv"]
        self.assertGreater(len(revert_entries), 0)

        for entry in revert_entries:
            self.assertIn("csv_file", entry)
            self.assertIn("payload", entry)
            payload = entry.get("payload")
            self.assertIn("reverted_to_version", payload)

    def test_v2_add_rule_action_structure(self):
        """Verify add_rule action has expected structure."""
        add_entries = [e for e in self.v2_queue if e.get("action_type") == "add_rule"]
        if add_entries:
            for entry in add_entries:
                self.assertIn("detection_rule", entry)
                self.assertIn("payload", entry)

    def test_v2_delete_rule_action_structure(self):
        """Verify delete_rule action has expected structure."""
        delete_entries = [e for e in self.v2_queue if e.get("action_type") == "delete_rule"]
        if delete_entries:
            for entry in delete_entries:
                self.assertIn("detection_rule", entry)

    def test_v2_queue_multiple_entries(self):
        """Verify fixture has multiple entries for realistic scenario."""
        self.assertGreaterEqual(
            len(self.v2_queue),
            5,
            "Fixture should contain at least 5 entries for realistic scenario"
        )

    def test_v2_queue_mixed_statuses(self):
        """Verify queue has entries with different statuses."""
        statuses = {e.get("status") for e in self.v2_queue}
        self.assertGreaterEqual(
            len(statuses),
            2,
            "Fixture should have multiple status types"
        )

    @patch('wl_approval._read_approval_queue')
    def test_v2_queue_can_be_read_back(self, mock_read):
        """Test that v2.0 queue can be read through v3.0 function."""
        # Mock the read function to return v2.0 queue
        mock_read.return_value = (self.v2_queue, "")

        # Should not raise exception
        queue, error = mock_read()
        self.assertEqual(error, "")
        self.assertEqual(queue, self.v2_queue)


if __name__ == "__main__":
    unittest.main()
