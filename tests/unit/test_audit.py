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


@pytest.mark.unit
class TestAuditMutationCoverageGaps:
    """Pin specific behaviors mutmut (Ring 3 Day 2) found could be
    silently mutated. See docs/RING_FINDINGS.md "R3-D2-F3 Mutation
    coverage (wl_audit.py)" for the full survivor analysis.
    """

    @patch('wl_audit.urllib.request.urlopen')
    def test_truncation_count_message_reports_exact_dropped_count(
        self, mock_urlopen
    ):
        """Kill mutmut #36: ``len(event['value']) - MAX`` mutated to
        ``+ MAX``.

        Existing ``test_post_audit_event_truncates_large_value_list``
        only asserts that the truncation marker contains the word
        ``'truncated'``. It does not pin the COUNT in the message,
        so flipping the arithmetic from subtract to add survives:
        the message still contains 'truncated', just with a wildly
        wrong count (e.g. 150 instead of 10).
        """
        from wl_audit import build_audit_event, post_audit_event
        from wl_constants import MAX_AUDIT_VALUE_LINES

        mock_response = MagicMock()
        mock_response.status = 200
        mock_urlopen.return_value = mock_response

        # Send exactly MAX+10 items so the dropped count is
        # deterministically 10, regardless of MAX_AUDIT_VALUE_LINES'
        # value.
        excess = 10
        large_list = [f"row_{i}" for i in range(MAX_AUDIT_VALUE_LINES + excess)]
        event = build_audit_event(
            action="removed",
            analyst="jsmith",
            detection_rule="Rule 1",
            csv_file="file.csv",
            value=large_list,
        )

        success, _ = post_audit_event("test-session-key", event)
        assert success is True

        # Last entry must literally contain "truncated 10 more"
        # (not "truncated 1024 more" from len + MAX arithmetic).
        marker = str(event["value"][-1])
        assert "truncated {} more".format(excess) in marker, (
            "expected the truncation marker to report the exact "
            "number of dropped entries, got: {!r}".format(marker)
        )

    @patch('wl_audit.urllib.request.urlopen')
    def test_authorization_header_exact_splunk_prefix(self, mock_urlopen):
        """Kill mutmut #55 (item E, 2026-05-19): Authorization header
        template ``"Splunk %s"`` mutated to ``"XXSplunk %sXX"``.

        Existing ``test_post_audit_event_sets_headers`` uses a substring
        ``in`` assertion (``"Splunk test-session-key" in <header>``) which
        the mutation slips past — the malformed header
        ``"XXSplunk test-session-keyXX"`` still contains the substring.
        In production the malformed header would cause Splunk's REST API
        to reject the request with 401 (unauthorized) and audit events
        would silently fail to land. Pin the header value with exact
        equality so any character mutation is killed.
        """
        from wl_audit import build_audit_event, post_audit_event

        mock_response = MagicMock()
        mock_response.status = 200
        mock_urlopen.return_value = mock_response

        event = build_audit_event(
            action="added",
            analyst="jsmith",
            detection_rule="Rule 1",
            csv_file="file.csv",
        )
        post_audit_event("MY_SESSION_KEY_12345", event)

        req = mock_urlopen.call_args[0][0]
        auth_header = req.headers["Authorization"]

        # Exact format pin: "Splunk <session_key>" — any character
        # mutation in the literal prefix or its template structure
        # produces a different string and fails this assertion.
        assert auth_header == "Splunk MY_SESSION_KEY_12345", (
            "Authorization header must be exactly "
            "'Splunk MY_SESSION_KEY_12345' (no extra characters, "
            "no template drift). Got: {!r}".format(auth_header)
        )

    @patch('wl_audit.urllib.request.urlopen')
    def test_generic_exception_returns_non_empty_error_message(self, mock_urlopen):
        """Kill mutmut #88 (item E, 2026-05-19): generic ``except Exception``
        branch assigns ``error_msg = str(e)``, mutated to ``error_msg = None``.

        The HTTPError / URLError / socket.timeout branches are covered by
        other tests, but the catch-all ``except Exception`` branch has no
        coverage. Mutating ``error_msg = str(e)`` to ``error_msg = None``
        makes the caller receive ``(False, None)`` instead of
        ``(False, "real error text")``, masking diagnostic information.

        Trigger by raising a non-{HTTPError, URLError, timeout} exception
        (RuntimeError) from urlopen, then assert that the returned
        ``error_msg`` is a non-empty string containing the original
        exception's text.
        """
        from wl_audit import build_audit_event, post_audit_event

        # RuntimeError doesn't match any of the specific except clauses
        # (HTTPError, URLError, socket.timeout) — falls through to the
        # generic ``except Exception``.
        mock_urlopen.side_effect = RuntimeError("kaboom: unexpected runtime failure")

        event = build_audit_event(
            action="added",
            analyst="jsmith",
            detection_rule="Rule 1",
            csv_file="file.csv",
        )
        success, error_msg = post_audit_event("SESSION_KEY", event)

        assert success is False
        # Mutant 88 sets error_msg = None — explicitly assert it isn't None.
        assert error_msg is not None, (
            "error_msg must not be None — mutant 88 silently drops "
            "the diagnostic text from generic-exception failures."
        )
        assert isinstance(error_msg, str), (
            "error_msg must be a string for caller-side logging compat. "
            "Got type: {}".format(type(error_msg))
        )
        assert len(error_msg) > 0, "error_msg must contain diagnostic text"
        assert "kaboom" in error_msg, (
            "error_msg should preserve the original exception's text "
            "(str(e) behavior). Got: {!r}".format(error_msg)
        )
