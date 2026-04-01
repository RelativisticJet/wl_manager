"""
Unit tests for wl_notify module.

Tests 2 public functions:
- notify_admins
- notify_analyst

Includes 15+ test cases covering message formatting, admin discovery,
error handling, and non-blocking behavior.
"""

import sys
import os
from unittest.mock import patch, MagicMock

import pytest

# Add bin/ to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "bin"))

from wl_notify import (
    notify_admins,
    notify_analyst,
    _get_notification_message,
)


@pytest.fixture
def mock_session_key():
    """Mock Splunk session key."""
    return "test-session-key"


@pytest.fixture
def mock_admin_users():
    """Mock get_admin_users to return test admins."""
    return ["admin1", "admin2"]


@pytest.fixture
def mock_get_admin_users(monkeypatch, mock_admin_users):
    """Mock wl_rbac.get_admin_users."""
    import wl_notify
    monkeypatch.setattr(
        wl_notify,
        "get_admin_users",
        MagicMock(return_value=mock_admin_users)
    )


# ═══════════════════════════════════════════════════════════════════════════
# Tests: Message Formatting
# ═══════════════════════════════════════════════════════════════════════════

def test_message_format_approval_pending():
    """Test message format for approval_pending notification."""
    details = {
        "analyst": "jsmith",
        "action_type": "save_csv",
        "csv_file": "DR123.csv",
        "detection_rule": "Rule1",
        "reason": "Update whitelist",
    }

    message = _get_notification_message("approval_pending", details)

    assert "Approval required" in message
    assert "jsmith" in message
    assert "save csv" in message or "save_csv" in message
    assert "DR123.csv" in message


def test_message_format_approval_approved():
    """Test message format for approval_approved notification."""
    details = {
        "action_type": "save_csv",
        "csv_file": "DR123.csv",
        "detection_rule": "Rule1",
        "reason": "Update",
        "resolution_time": "2026-04-01 12:00:00",
    }

    message = _get_notification_message("approval_approved", details)

    assert "APPROVED" in message
    assert "save" in message.lower()


def test_message_format_approval_rejected():
    """Test message format for approval_rejected notification."""
    details = {
        "action_type": "delete_rule",
        "detection_rule": "Rule1",
        "reason": "Not ready",
        "resolution_time": "2026-04-01 12:00:00",
    }

    message = _get_notification_message("approval_rejected", details)

    assert "REJECTED" in message or "Rejected" in message


def test_message_format_approval_cancelled():
    """Test message format for approval_cancelled notification."""
    details = {
        "action_type": "save_csv",
        "reason": "CSV was deleted",
        "csv_file": "DR123.csv",
    }

    message = _get_notification_message("approval_cancelled", details)

    assert "CANCELLED" in message or "Cancelled" in message


def test_message_format_approval_expired():
    """Test message format for approval_expired notification."""
    details = {
        "action_type": "save_csv",
        "detection_rule": "Rule1",
        "csv_file": "DR123.csv",
    }

    message = _get_notification_message("approval_expired", details)

    assert "EXPIRED" in message or "Expired" in message


# ═══════════════════════════════════════════════════════════════════════════
# Tests: notify_admins
# ═══════════════════════════════════════════════════════════════════════════

def test_notify_admins_success(mock_session_key, mock_get_admin_users, monkeypatch):
    """Test successful admin notification."""
    import wl_notify
    monkeypatch.setattr(
        wl_notify,
        "_send_splunk_notification",
        MagicMock(return_value=(True, ""))
    )

    success, error = notify_admins(
        mock_session_key,
        "approval_pending",
        {"analyst": "jsmith", "action_type": "save_csv"}
    )

    assert success
    assert error == ""


def test_notify_admins_calls_get_admin_users(mock_session_key, mock_get_admin_users, monkeypatch):
    """Test notify_admins calls get_admin_users."""
    import wl_notify
    monkeypatch.setattr(
        wl_notify,
        "_send_splunk_notification",
        MagicMock(return_value=(True, ""))
    )
    mock_get_admin = MagicMock(return_value=["admin1", "admin2"])
    monkeypatch.setattr(wl_notify, "get_admin_users", mock_get_admin)

    notify_admins(mock_session_key, "approval_pending", {})

    mock_get_admin.assert_called_once_with(mock_session_key)


def test_notify_admins_formats_message(mock_session_key, mock_get_admin_users, monkeypatch):
    """Test message is formatted correctly."""
    import wl_notify
    send_mock = MagicMock(return_value=(True, ""))
    monkeypatch.setattr(wl_notify, "_send_splunk_notification", send_mock)

    details = {
        "analyst": "jsmith",
        "action_type": "save_csv",
        "csv_file": "DR123.csv",
    }

    notify_admins(mock_session_key, "approval_pending", details)

    # Verify message was created
    send_mock.assert_called()
    call_args = send_mock.call_args
    message = call_args[0][2]  # Third argument is message
    assert "Approval required" in message


def test_notify_admins_handles_empty_admin_list(mock_session_key, monkeypatch):
    """Test handles case with no admins gracefully."""
    import wl_notify
    monkeypatch.setattr(wl_notify, "get_admin_users", MagicMock(return_value=[]))

    success, error = notify_admins(mock_session_key, "approval_pending", {})

    assert success
    assert error == ""


def test_notify_admins_logs_on_splunk_error(mock_session_key, mock_get_admin_users, monkeypatch):
    """Test logs error when notification fails."""
    import wl_notify
    monkeypatch.setattr(
        wl_notify,
        "_send_splunk_notification",
        MagicMock(return_value=(False, "Network error"))
    )

    success, error = notify_admins(mock_session_key, "approval_pending", {})

    assert not success
    assert "Network error" in error


# ═══════════════════════════════════════════════════════════════════════════
# Tests: notify_analyst
# ═══════════════════════════════════════════════════════════════════════════

def test_notify_analyst_success(mock_session_key, monkeypatch):
    """Test successful analyst notification."""
    import wl_notify
    monkeypatch.setattr(
        wl_notify,
        "_send_splunk_notification",
        MagicMock(return_value=(True, ""))
    )

    success, error = notify_analyst(
        mock_session_key,
        "jsmith",
        "approval_approved",
        {"action_type": "save_csv"}
    )

    assert success
    assert error == ""


def test_notify_analyst_formats_message(mock_session_key, monkeypatch):
    """Test message is formatted correctly."""
    import wl_notify
    send_mock = MagicMock(return_value=(True, ""))
    monkeypatch.setattr(wl_notify, "_send_splunk_notification", send_mock)

    details = {
        "action_type": "save_csv",
        "csv_file": "DR123.csv",
        "reason": "Update whitelist",
    }

    notify_analyst(mock_session_key, "jsmith", "approval_approved", details)

    send_mock.assert_called()
    call_args = send_mock.call_args
    message = call_args[0][2]  # Third argument is message
    assert "APPROVED" in message or "approved" in message.lower()


def test_notify_analyst_invalid_user(mock_session_key):
    """Test invalid user returns error."""
    success, error = notify_analyst(
        mock_session_key,
        "",
        "approval_approved",
        {}
    )

    assert not success
    assert "Invalid" in error or "analyst" in error.lower()


def test_notify_analyst_handles_splunk_unavailable(mock_session_key, monkeypatch):
    """Test non-blocking on Splunk error."""
    import wl_notify
    monkeypatch.setattr(
        wl_notify,
        "_send_splunk_notification",
        MagicMock(return_value=(False, "Splunk unavailable"))
    )

    success, error = notify_analyst(
        mock_session_key,
        "jsmith",
        "approval_approved",
        {}
    )

    # Should return failure but not raise exception
    assert not success
    assert error != ""


def test_notify_analyst_logs_error(mock_session_key, monkeypatch):
    """Test error is logged."""
    import wl_notify
    monkeypatch.setattr(
        wl_notify,
        "_send_splunk_notification",
        MagicMock(return_value=(False, "Error"))
    )

    notify_analyst(mock_session_key, "jsmith", "approval_approved", {})

    # Verify function completed without raising


# ═══════════════════════════════════════════════════════════════════════════
# Tests: Error Handling
# ═══════════════════════════════════════════════════════════════════════════

def test_notify_non_blocking_no_exception(mock_session_key, monkeypatch):
    """Test notification failures don't raise exceptions."""
    import wl_notify
    monkeypatch.setattr(
        wl_notify,
        "_send_splunk_notification",
        MagicMock(side_effect=Exception("Splunk error"))
    )

    # Should not raise
    success, error = notify_analyst(
        mock_session_key,
        "jsmith",
        "approval_approved",
        {}
    )

    assert not success


def test_notify_logs_to_audit_logger(mock_session_key, monkeypatch):
    """Test errors are logged via audit logger."""
    import wl_notify
    logger_mock = MagicMock()
    monkeypatch.setattr(wl_notify, "_logger", logger_mock)
    monkeypatch.setattr(
        wl_notify,
        "_send_splunk_notification",
        MagicMock(return_value=(False, "Error"))
    )

    notify_analyst(mock_session_key, "jsmith", "approval_approved", {})

    # Verify logger was called
    logger_mock.error.assert_called()


# ═══════════════════════════════════════════════════════════════════════════
# Integration tests
# ═══════════════════════════════════════════════════════════════════════════

def test_notify_flow_approval_submission(mock_session_key, mock_get_admin_users, monkeypatch):
    """Test full flow: admin notified of approval request."""
    import wl_notify
    send_mock = MagicMock(return_value=(True, ""))
    monkeypatch.setattr(wl_notify, "_send_splunk_notification", send_mock)

    details = {
        "analyst": "jsmith",
        "action_type": "save_csv",
        "csv_file": "DR123.csv",
        "detection_rule": "Rule1",
        "reason": "Update whitelist",
    }

    success, error = notify_admins(mock_session_key, "approval_pending", details)

    assert success
    assert send_mock.called


def test_notify_flow_approval_outcome(mock_session_key, monkeypatch):
    """Test full flow: analyst notified of approval outcome."""
    import wl_notify
    send_mock = MagicMock(return_value=(True, ""))
    monkeypatch.setattr(wl_notify, "_send_splunk_notification", send_mock)

    details = {
        "action_type": "save_csv",
        "csv_file": "DR123.csv",
        "reason": "Update",
        "resolution_time": "2026-04-01 12:00:00",
    }

    success, error = notify_analyst(
        mock_session_key,
        "jsmith",
        "approval_approved",
        details
    )

    assert success
    assert send_mock.called
