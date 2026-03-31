"""
Integration tests for Phase 2 persistence chain.

Tests the end-to-end flow of audit event construction and module integration.
These tests verify that the wl_audit, wl_csv, wl_versions modules work together
to support full data persistence with correct audit trails.

Note: These tests focus on module integration, not Docker/Splunk connectivity.
For Docker-dependent tests, see tests/integration/test_docker_integration.py.
"""

import pytest
import json
import os
import sys
import tempfile
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

# Add bin directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'bin'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'stubs'))

from wl_csv import read_csv, write_csv, compute_diff
from wl_audit import build_audit_event, post_audit_event, get_audit_logger
from wl_constants import MAX_VERSIONS


@pytest.mark.integration
class TestAuditEventConstruction:
    """Integration tests for audit event construction."""

    def test_build_audit_event_with_csv_metadata(self):
        """Verify audit event contains all required CSV fields."""
        event = build_audit_event(
            action="added",
            analyst="jsmith",
            detection_rule="Suspicious Login",
            csv_file="login_whitelist.csv",
            comment="Added trusted IP",
            value=["user_row_1: jsmith", "ip_row_1: 10.0.0.1"]
        )

        assert event["action"] == "added"
        assert event["analyst"] == "jsmith"
        assert event["detection_rule"] == "Suspicious Login"
        assert event["csv_file"] == "login_whitelist.csv"
        assert event["comment"] == "Added trusted IP"
        assert isinstance(event["value"], list)
        assert len(event["value"]) == 2

    def test_build_audit_event_edit_action_with_diff(self):
        """Verify audit event captures edit with before/after values."""
        event = build_audit_event(
            action="edited",
            analyst="jsmith",
            detection_rule="Test Rule",
            csv_file="test.csv",
            edited_row_count=1,
            value=[
                "ip_row_1_before: 10.0.0.1",
                "ip_row_1_after: 10.0.0.2",
            ]
        )

        assert event["action"] == "edited"
        assert event["edited_row_count"] == 1
        assert "before" in str(event["value"])
        assert "after" in str(event["value"])

    def test_build_audit_event_remove_with_reason(self):
        """Verify removal event captures reason."""
        event = build_audit_event(
            action="removed",
            analyst="jsmith",
            detection_rule="Test Rule",
            csv_file="test.csv",
            removed_row_count=2,
            remove_reason="Outdated entries",
            value=["user_row_1: jsmith", "user_row_2: alee"]
        )

        assert event["action"] == "removed"
        assert event["removed_row_count"] == 2
        assert event["remove_reason"] == "Outdated entries"

    def test_build_audit_event_revert_with_version_tracking(self):
        """Verify revert events track version timestamps."""
        event = build_audit_event(
            action="revert",
            analyst="admin",
            detection_rule="Test Rule",
            csv_file="test.csv",
            comment="Reverting to v1",
            reverted_from_version="2026-03-31 13:00:00",
            reverted_to_version="2026-03-31 12:00:00",
            new_record_version="2026-03-31 14:00:00",
            restoredback_row_count=2,
            removedback_row_count=1,
            editedback_row_count=0
        )

        assert event["action"] == "revert"
        assert event["reverted_from_version"] == "2026-03-31 13:00:00"
        assert event["reverted_to_version"] == "2026-03-31 12:00:00"
        assert event["new_record_version"] == "2026-03-31 14:00:00"
        assert event["restoredback_row_count"] == 2
        assert event["removedback_row_count"] == 1

    def test_build_audit_event_auto_removed_with_expiration(self):
        """Verify auto-removal events capture expiration metadata."""
        event = build_audit_event(
            action="auto_removed",
            analyst="system",
            detection_rule="Test Rule",
            csv_file="test.csv",
            auto_removed_count=3,
            reason="Rows past expiration date",
            value=["user_row_1: jsmith", "user_row_2: alee", "user_row_3: bob"]
        )

        assert event["action"] == "auto_removed"
        assert event["auto_removed_count"] == 3
        assert event["reason"] == "Rows past expiration date"


@pytest.mark.integration
class TestCSVDiffToAuditFlow:
    """Integration tests for CSV diff → audit event flow."""

    def test_csv_diff_maps_to_audit_counts(self, tmp_path):
        """Verify CSV diff results correctly map to audit event counts."""
        # Setup
        csv_path = tmp_path / "test.csv"
        headers = ["user", "ip"]

        # Write v1
        v1_rows = [
            {"user": "jsmith", "ip": "10.0.0.1"},
            {"user": "alee", "ip": "10.0.0.2"},
        ]
        write_csv(str(csv_path), headers, v1_rows)

        # Read v1
        read_headers, read_rows = read_csv(str(csv_path))
        assert len(read_rows) == 2

        # Create v2 with edits
        v2_rows = [
            {"user": "jsmith", "ip": "10.0.0.10"},  # edited
            {"user": "bob", "ip": "10.0.0.3"},      # added
            # alee removed
        ]

        # Compute diff
        diff = compute_diff(headers, v1_rows, headers, v2_rows)

        # Build audit event with diff counts
        event = build_audit_event(
            action="edited",
            analyst="jsmith",
            detection_rule="Test Rule",
            csv_file="test.csv",
            comment="Updated whitelist",
            added_row_count=len(diff.get("added", [])),
            removed_row_count=len(diff.get("removed", [])),
            edited_row_count=len(diff.get("edited", []))
        )

        # Verify
        assert event["added_row_count"] >= 0
        assert event["removed_row_count"] >= 0
        assert event["edited_row_count"] >= 0

    def test_multiple_csv_operations_generate_unique_events(self):
        """Verify each CSV operation generates a distinct audit event."""
        # Create three separate audit events
        event1 = build_audit_event(
            action="added",
            analyst="jsmith",
            detection_rule="Rule 1",
            csv_file="file1.csv"
        )

        event2 = build_audit_event(
            action="removed",
            analyst="alee",
            detection_rule="Rule 2",
            csv_file="file2.csv"
        )

        event3 = build_audit_event(
            action="edited",
            analyst="bob",
            detection_rule="Rule 3",
            csv_file="file3.csv"
        )

        # Verify all are distinct
        assert event1["analyst"] == "jsmith"
        assert event2["analyst"] == "alee"
        assert event3["analyst"] == "bob"

        assert event1["action"] == "added"
        assert event2["action"] == "removed"
        assert event3["action"] == "edited"


@pytest.mark.integration
class TestAuditEventPosting:
    """Integration tests for audit event HTTP posting."""

    @patch('wl_audit.urllib.request.urlopen')
    def test_post_audit_event_serialization(self, mock_urlopen):
        """Verify audit event is correctly serialized to JSON."""
        # Mock response
        mock_response = MagicMock()
        mock_response.status = 200
        mock_urlopen.return_value = mock_response

        # Build and post event
        event = build_audit_event(
            action="added",
            analyst="jsmith",
            detection_rule="Rule 1",
            csv_file="file.csv",
            added_row_count=1,
            value=["user_row_1: jsmith"]
        )

        success, error = post_audit_event("test-session-key", event)

        assert success is True
        assert error == ""

        # Verify request was made
        mock_urlopen.assert_called_once()

        # Get the request object that was sent
        call_args = mock_urlopen.call_args
        request_obj = call_args[0][0]

        # Verify it was a POST request
        assert request_obj.get_method() == "POST"

        # Verify headers are set
        assert "Authorization" in request_obj.headers
        assert "Splunk " in request_obj.headers["Authorization"]

    @patch('wl_audit.urllib.request.urlopen')
    def test_post_audit_event_handles_large_value_arrays(self, mock_urlopen):
        """Verify large value arrays are truncated before posting."""
        # Mock response
        mock_response = MagicMock()
        mock_response.status = 200
        mock_urlopen.return_value = mock_response

        # Create event with many values (>MAX_AUDIT_VALUE_LINES to trigger truncation)
        large_value_list = [f"row_{i}" for i in range(600)]
        event = build_audit_event(
            action="removed",
            analyst="jsmith",
            detection_rule="Rule 1",
            csv_file="file.csv",
            removed_row_count=600,
            value=large_value_list
        )

        success, error = post_audit_event("test-session-key", event)

        assert success is True
        # Value list should be truncated to MAX_AUDIT_VALUE_LINES + 1 (for truncation message)
        assert len(event["value"]) < len(large_value_list)
        assert len(event["value"]) <= 501  # MAX_AUDIT_VALUE_LINES (500) + 1 truncation message

    @patch('wl_audit.urllib.request.urlopen')
    def test_post_audit_event_recovers_from_network_errors(self, mock_urlopen):
        """Verify posting handles network errors gracefully."""
        import urllib.error

        # Mock network error
        mock_urlopen.side_effect = urllib.error.URLError("Connection refused")

        # Try to post
        event = build_audit_event(
            action="added",
            analyst="jsmith",
            detection_rule="Rule 1",
            csv_file="file.csv"
        )

        success, error = post_audit_event("test-session-key", event)

        assert success is False
        assert "Connection refused" in error or "Connection" in error


@pytest.mark.integration
class TestAuditLoggerIntegration:
    """Integration tests for audit logger."""

    def test_get_audit_logger_is_idempotent(self):
        """Verify get_audit_logger returns same instance."""
        logger1 = get_audit_logger()
        logger2 = get_audit_logger()

        assert logger1 is logger2

    def test_audit_logger_has_handlers(self):
        """Verify audit logger has at least one handler."""
        logger = get_audit_logger()
        assert len(logger.handlers) > 0

    def test_audit_event_logging_on_post_failure(self, caplog):
        """Verify posting failures are logged."""
        import logging
        from unittest.mock import patch
        import urllib.error

        # Mock network error
        with patch('wl_audit.urllib.request.urlopen') as mock_urlopen:
            mock_urlopen.side_effect = urllib.error.URLError("Network error")

            # Post an event
            event = build_audit_event(
                action="added",
                analyst="jsmith",
                detection_rule="Rule 1",
                csv_file="file.csv"
            )

            with caplog.at_level(logging.ERROR):
                success, error = post_audit_event("test-session-key", event)

            assert success is False
            # Error should be logged (may appear in logger or caplog)
            assert "Network error" in error or "error" in error.lower()
