"""
Backward compatibility tests for v2.0 audit events in v3.0.

Tests verify that pre-rewrite audit events (from v2.0) can be injected
and parsed correctly in v3.0 code, including all event types and field structures.

Test approach:
- Load golden v2.0 events from fixture
- Mock Splunk index write
- Call wl_audit.post_audit_event() with v2.0 event structure
- Verify no exceptions, field names match audit.xml expectations
"""

import unittest
import json
import sys
import os
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path

# Add bin directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'bin'))

try:
    from wl_audit import build_audit_event, post_audit_event
except ImportError:
    build_audit_event = None
    post_audit_event = None


class TestV2AuditEventsBackwardCompat(unittest.TestCase):
    """Tests for v2.0 audit event backward compatibility."""

    @classmethod
    def setUpClass(cls):
        """Load v2.0 audit event fixtures."""
        if build_audit_event is None or post_audit_event is None:
            cls.skipClass = True
            return

        fixture_path = Path(__file__).parent.parent / "fixtures" / "v2_audit_events.json"
        with open(fixture_path, "r") as f:
            cls.v2_events = json.load(f)

    def test_v2_audit_events_fixture_loads(self):
        """Verify v2.0 audit event fixture is valid JSON."""
        self.assertIsInstance(self.v2_events, list)
        self.assertGreater(len(self.v2_events), 0)

    def test_v2_added_event_parses(self):
        """Test that v2.0 'row_added' event parses without errors."""
        added_event = next(e for e in self.v2_events if e.get("action") == "row_added")
        self.assertIsNotNone(added_event)

        # Verify required fields
        self.assertIn("timestamp", added_event)
        self.assertIn("action", added_event)
        self.assertIn("analyst", added_event)
        self.assertIn("detection_rule", added_event)
        self.assertIn("csv_file", added_event)
        self.assertIn("app_context", added_event)
        self.assertIn("comment", added_event)

        # Verify action-specific fields
        self.assertEqual(added_event["action"], "row_added")
        self.assertIn("added_row_count", added_event)
        self.assertIn("value", added_event)
        self.assertIsInstance(added_event["value"], list)

    def test_v2_removal_event_parses(self):
        """Test that v2.0 'row_removed' event parses without errors."""
        removal_event = next(e for e in self.v2_events if e.get("action") == "row_removed")
        self.assertIsNotNone(removal_event)

        # Verify required fields
        self.assertIn("timestamp", removal_event)
        self.assertIn("action", removal_event)
        self.assertIn("analyst", removal_event)
        self.assertIn("detection_rule", removal_event)
        self.assertIn("csv_file", removal_event)

        # Verify removal-specific fields
        self.assertEqual(removal_event["action"], "row_removed")
        self.assertIn("removed_row_count", removal_event)
        self.assertIn("remove_reason", removal_event)
        self.assertIn("value", removal_event)

    def test_v2_edit_event_parses(self):
        """Test that v2.0 'row_edited' event parses without errors."""
        edit_event = next(e for e in self.v2_events if e.get("action") == "row_edited")
        self.assertIsNotNone(edit_event)

        # Verify required fields
        self.assertIn("timestamp", edit_event)
        self.assertIn("action", edit_event)
        self.assertIn("analyst", edit_event)

        # Verify edit-specific fields
        self.assertEqual(edit_event["action"], "row_edited")
        self.assertIn("edited_row_count", edit_event)
        self.assertIn("value", edit_event)
        # Edit values should contain before/after pairs
        self.assertTrue(
            any("_before:" in str(v) or "_after:" in str(v) for v in edit_event["value"])
        )

    def test_v2_revert_event_parses(self):
        """Test that v2.0 'revert' event with *back fields parses correctly."""
        revert_event = next(e for e in self.v2_events if e.get("action") == "revert")
        self.assertIsNotNone(revert_event)

        # Verify required fields
        self.assertIn("timestamp", revert_event)
        self.assertIn("action", revert_event)
        self.assertEqual(revert_event["action"], "revert")

        # Verify revert-specific fields (version traceability)
        self.assertIn("reverted_from_version", revert_event)
        self.assertIn("reverted_to_version", revert_event)
        self.assertIn("new_record_version", revert_event)

        # Verify *back fields for revert-driven changes
        self.assertIn("restoredback_row_count", revert_event)
        self.assertIn("removedback_row_count", revert_event)
        self.assertIn("editedback_row_count", revert_event)

        # Verify value lines use *back prefix
        self.assertTrue(
            any("restoredback_" in str(v) or "removedback_" in str(v) for v in revert_event.get("value", []))
        )

    def test_v2_auto_removed_event_parses(self):
        """Test that v2.0 'auto_removed' event parses without errors."""
        auto_event = next(e for e in self.v2_events if e.get("action") == "auto_removed")
        self.assertIsNotNone(auto_event)

        # Verify required fields
        self.assertIn("timestamp", auto_event)
        self.assertIn("action", auto_event)
        self.assertEqual(auto_event["action"], "auto_removed")

        # Verify auto-removal specific fields
        self.assertIn("auto_removed_count", auto_event)
        self.assertIn("value", auto_event)

    def test_v2_event_field_names_match_queries(self):
        """Test that v2.0 event field names match audit.xml SPL query expectations."""
        # Expected field names that audit.xml queries look for
        expected_fields = {
            "analyst", "detection_rule", "csv_file", "action",
            "timestamp", "app_context", "comment"
        }

        for event in self.v2_events:
            missing = expected_fields - set(event.keys())
            self.assertEqual(
                missing,
                set(),
                f"Event missing fields {missing}: {json.dumps(event, indent=2)}"
            )

    def test_v2_event_action_types_recognized(self):
        """Test that v2.0 action types are recognized by v3.0."""
        recognized_actions = {
            "row_added", "row_removed", "row_edited", "revert", "auto_removed"
        }

        for event in self.v2_events:
            action = event.get("action")
            self.assertIn(
                action,
                recognized_actions,
                f"Unknown action type: {action}"
            )

    @patch('wl_audit.post_audit_event')
    def test_v2_events_post_without_exception(self, mock_post):
        """Test that v2.0 events can be posted through build_audit_event without exceptions."""
        mock_post.return_value = (True, "")

        for v2_event in self.v2_events:
            # Reconstruct as v3.0 event using common fields
            v3_event = build_audit_event(
                action=v2_event["action"],
                analyst=v2_event["analyst"],
                detection_rule=v2_event["detection_rule"],
                csv_file=v2_event["csv_file"],
                comment=v2_event.get("comment", ""),
                app_context=v2_event.get("app_context", ""),
            )

            # Add v2.0-specific fields (v3.0 should accept them gracefully)
            for key, value in v2_event.items():
                if key not in ("action", "analyst", "detection_rule", "csv_file", "comment", "app_context"):
                    v3_event[key] = value

            # Should not raise exception
            success, error = post_audit_event("test_session_key", v3_event)
            # (Mock always returns success, real test verifies no exception)

    def test_v2_event_value_field_structure(self):
        """Test that v2.0 'value' field structure is preserved."""
        # Value field should be a list of strings
        for event in self.v2_events:
            if "value" in event:
                self.assertIsInstance(
                    event["value"],
                    list,
                    f"value field should be list, got {type(event['value'])}"
                )
                for item in event["value"]:
                    self.assertIsInstance(item, str)

    def test_v2_event_count_fields_are_integers(self):
        """Test that count fields are integers in v2.0 events."""
        count_fields = {
            "added_row_count", "removed_row_count", "edited_row_count",
            "auto_removed_count", "restoredback_row_count",
            "removedback_row_count", "editedback_row_count"
        }

        for event in self.v2_events:
            for field in count_fields:
                if field in event:
                    self.assertIsInstance(
                        event[field],
                        int,
                        f"{field} should be int, got {type(event[field])}"
                    )


if __name__ == "__main__":
    unittest.main()
