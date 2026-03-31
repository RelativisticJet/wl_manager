"""
Unit tests for wl_audit module.

Tests audit event construction and posting to Splunk wl_audit index.
"""

import pytest
import logging
import os
import sys
import json
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock
from unittest import mock

# Add bin directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'bin'))


@pytest.mark.unit
class TestGetAuditLogger:
    """Test get_audit_logger function."""

    def test_get_audit_logger_returns_logger(self):
        """Verify get_audit_logger returns a logging.Logger instance."""
        from wl_audit import get_audit_logger

        logger = get_audit_logger()
        assert isinstance(logger, logging.Logger)


@pytest.mark.unit
class TestBuildAuditEvent:
    """Test build_audit_event function."""

    def test_build_audit_event_basic_fields(self):
        """Verify build_audit_event includes all required fields."""
        from wl_audit import build_audit_event

        event = build_audit_event(
            action="added",
            analyst="jsmith",
            detection_rule="Suspicious Login",
            csv_file="login_whitelist.csv"
        )

        assert event["action"] == "added"
        assert event["analyst"] == "jsmith"
        assert event["detection_rule"] == "Suspicious Login"
        assert event["csv_file"] == "login_whitelist.csv"
        assert "timestamp" in event
        assert event["app_context"] == ""
        assert event["comment"] == ""

    def test_build_audit_event_with_comment(self):
        """Verify comment is included in event."""
        from wl_audit import build_audit_event

        event = build_audit_event(
            action="removed",
            analyst="jsmith",
            detection_rule="Rule 1",
            csv_file="file.csv",
            comment="Removing old entries"
        )

        assert event["comment"] == "Removing old entries"

    def test_build_audit_event_with_extra_kwargs(self):
        """Verify extra kwargs are merged into event dict."""
        from wl_audit import build_audit_event

        event = build_audit_event(
            action="edited",
            analyst="jsmith",
            detection_rule="Rule 1",
            csv_file="file.csv",
            removed_row_count=5,
            edited_row_count=3,
            custom_field="custom_value"
        )

        assert event["removed_row_count"] == 5
        assert event["edited_row_count"] == 3
        assert event["custom_field"] == "custom_value"

    def test_build_audit_event_timestamp_format(self):
        """Verify timestamp is Unix timestamp (integer)."""
        from wl_audit import build_audit_event

        event = build_audit_event(
            action="added",
            analyst="jsmith",
            detection_rule="Rule 1",
            csv_file="file.csv"
        )

        # Timestamp should be integer (Unix epoch seconds)
        assert isinstance(event["timestamp"], int)
        # Should be a reasonable timestamp (after 2025-01-01 and before 2030)
        ts = event["timestamp"]
        assert ts > 1704067200  # 2025-01-01
        assert ts < 1893456000  # 2030-01-01

    def test_build_audit_event_with_app_context(self):
        """Verify app_context can be overridden."""
        from wl_audit import build_audit_event

        event = build_audit_event(
            action="added",
            analyst="jsmith",
            detection_rule="Rule 1",
            csv_file="file.csv",
            app_context="custom_app"
        )

        assert event["app_context"] == "custom_app"

    def test_build_audit_event_action_types(self):
        """Verify different action types work."""
        from wl_audit import build_audit_event

        for action in ["added", "removed", "edited", "revert", "auto_removed", "trash_restored"]:
            event = build_audit_event(
                action=action,
                analyst="jsmith",
                detection_rule="Rule 1",
                csv_file="file.csv"
            )
            assert event["action"] == action


@pytest.mark.unit
class TestPostAuditEvent:
    """Test post_audit_event function."""

    @patch('wl_audit.urllib.request.urlopen')
    def test_post_audit_event_success(self, mock_urlopen):
        """Verify successful post returns (True, '')."""
        from wl_audit import build_audit_event, post_audit_event

        # Mock successful response
        mock_response = MagicMock()
        mock_response.status = 200
        mock_urlopen.return_value = mock_response

        event = build_audit_event(
            action="added",
            analyst="jsmith",
            detection_rule="Rule 1",
            csv_file="file.csv"
        )

        success, error = post_audit_event("test-session-key", event)

        assert success is True
        assert error == ""
        mock_urlopen.assert_called_once()

    @patch('wl_audit.urllib.request.urlopen')
    def test_post_audit_event_failure_4xx(self, mock_urlopen):
        """Verify 4xx response returns (False, error_msg)."""
        from wl_audit import build_audit_event, post_audit_event
        import urllib.error

        # Mock 400 error
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="test",
            code=400,
            msg="Bad Request",
            hdrs={},
            fp=None
        )

        event = build_audit_event(
            action="added",
            analyst="jsmith",
            detection_rule="Rule 1",
            csv_file="file.csv"
        )

        success, error = post_audit_event("test-session-key", event)

        assert success is False
        assert "400" in error or "Bad Request" in error

    @patch('wl_audit.urllib.request.urlopen')
    def test_post_audit_event_failure_5xx(self, mock_urlopen):
        """Verify 5xx response returns (False, error_msg)."""
        from wl_audit import build_audit_event, post_audit_event
        import urllib.error

        # Mock 500 error
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="test",
            code=500,
            msg="Internal Server Error",
            hdrs={},
            fp=None
        )

        event = build_audit_event(
            action="added",
            analyst="jsmith",
            detection_rule="Rule 1",
            csv_file="file.csv"
        )

        success, error = post_audit_event("test-session-key", event)

        assert success is False
        assert "500" in error or "Internal Server Error" in error

    @patch('wl_audit.urllib.request.urlopen')
    def test_post_audit_event_network_error(self, mock_urlopen):
        """Verify network error returns (False, error_msg)."""
        from wl_audit import build_audit_event, post_audit_event
        import urllib.error

        # Mock network error
        mock_urlopen.side_effect = urllib.error.URLError("Connection refused")

        event = build_audit_event(
            action="added",
            analyst="jsmith",
            detection_rule="Rule 1",
            csv_file="file.csv"
        )

        success, error = post_audit_event("test-session-key", event)

        assert success is False
        assert "Connection refused" in error

    @patch('wl_audit.urllib.request.urlopen')
    def test_post_audit_event_timeout(self, mock_urlopen):
        """Verify timeout error returns (False, error_msg)."""
        from wl_audit import build_audit_event, post_audit_event
        import socket

        # Mock timeout
        mock_urlopen.side_effect = socket.timeout("Request timeout")

        event = build_audit_event(
            action="added",
            analyst="jsmith",
            detection_rule="Rule 1",
            csv_file="file.csv"
        )

        success, error = post_audit_event("test-session-key", event)

        assert success is False
        assert "timeout" in error.lower() or "Request timeout" in error

    @patch('wl_audit.urllib.request.urlopen')
    def test_post_audit_event_sets_headers(self, mock_urlopen):
        """Verify HTTP headers are set correctly."""
        from wl_audit import build_audit_event, post_audit_event

        # Mock successful response
        mock_response = MagicMock()
        mock_response.status = 200
        mock_urlopen.return_value = mock_response

        event = build_audit_event(
            action="added",
            analyst="jsmith",
            detection_rule="Rule 1",
            csv_file="file.csv"
        )

        success, _ = post_audit_event("test-session-key", event)

        assert success is True
        # Verify that urlopen was called with a Request object
        mock_urlopen.assert_called_once()
        call_args = mock_urlopen.call_args
        request_obj = call_args[0][0]

        # Verify headers were set
        assert "Authorization" in request_obj.headers
        assert "Splunk test-session-key" in request_obj.headers["Authorization"]
        assert request_obj.headers["Content-type"] == "application/json"

    def test_post_audit_event_no_session_key(self):
        """Verify posting without session key returns (False, error_msg)."""
        from wl_audit import build_audit_event, post_audit_event

        event = build_audit_event(
            action="added",
            analyst="jsmith",
            detection_rule="Rule 1",
            csv_file="file.csv"
        )

        success, error = post_audit_event("", event)

        assert success is False
        assert "session key" in error.lower()

    @patch('wl_audit.urllib.request.urlopen')
    def test_post_audit_event_truncates_large_value_list(self, mock_urlopen):
        """Verify large value arrays are truncated."""
        from wl_audit import build_audit_event, post_audit_event
        from wl_constants import MAX_AUDIT_VALUE_LINES

        # Mock successful response
        mock_response = MagicMock()
        mock_response.status = 200
        mock_urlopen.return_value = mock_response

        # Create event with large value list
        large_list = [f"row_{i}" for i in range(MAX_AUDIT_VALUE_LINES + 10)]
        event = build_audit_event(
            action="removed",
            analyst="jsmith",
            detection_rule="Rule 1",
            csv_file="file.csv",
            value=large_list
        )

        success, _ = post_audit_event("test-session-key", event)

        assert success is True
        # Verify list was truncated
        assert len(event["value"]) <= MAX_AUDIT_VALUE_LINES + 1  # +1 for truncation message
        assert "truncated" in str(event["value"][-1]).lower()

    @patch('wl_audit.urllib.request.urlopen')
    def test_post_audit_event_with_revert_fields(self, mock_urlopen):
        """Verify revert-specific fields are preserved."""
        from wl_audit import build_audit_event, post_audit_event

        # Mock successful response
        mock_response = MagicMock()
        mock_response.status = 200
        mock_urlopen.return_value = mock_response

        event = build_audit_event(
            action="revert",
            analyst="jsmith",
            detection_rule="Rule 1",
            csv_file="file.csv",
            reverted_from_version="2026-03-31 12:00:00",
            reverted_to_version="2026-03-31 11:00:00",
            new_record_version="2026-03-31 13:00:00",
            restoredback_row_count=2,
            removedback_row_count=1,
            editedback_row_count=0
        )

        success, error = post_audit_event("test-session-key", event)

        assert success is True
        assert event["reverted_from_version"] == "2026-03-31 12:00:00"
        assert event["reverted_to_version"] == "2026-03-31 11:00:00"
        assert event["new_record_version"] == "2026-03-31 13:00:00"
