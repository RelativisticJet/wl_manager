"""
Unit tests for wl_limits module (Layer 3).

Tests verify daily usage limits, enforcement, reset scheduling, and status API.
Tests mock file I/O and time to enable deterministic offline testing.

Coverage target: >= 80%
"""

import os
import sys
import json
import tempfile
import pytest
from unittest import mock
from unittest.mock import patch, MagicMock, mock_open
from datetime import datetime, timezone

# Add bin directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'bin'))

import wl_limits
from wl_constants import RESET_ALL_USERS


# ═══════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture
def mock_daily_limits():
    """Mock daily_limits.json content."""
    return {
        "2026-04-01": {
            "jsmith": {
                "row_removal": 3,
                "bulk_row_removal": 1,
                "row_edit": 5,
            },
            "admin": {
                "rule_deletion": 1,
                "approval_count": 5,
            }
        }
    }


@pytest.fixture
def mock_limit_config():
    """Mock limit_config.json content."""
    return {
        "row_removal": 10,
        "bulk_row_removal": 10,
        "column_removal": 2,
        "column_addition": 2,
        "row_edit": 10,
        "bulk_row_edit": 10,
        "row_addition": 10,
        "row_reorder": 10,
        "column_reorder": 10,
        "revert": 3,
        "reset_frequency": "daily",
        "reset_time_utc": "00:00",
        "reset_day_of_week": 0,
        "reset_day_of_month": 1,
        "reset_month": 1,
        "reset_day_of_year": 1,
        "bulk_row_removal_threshold": 3,
        "bulk_row_edit_threshold": 3,
        "bulk_row_addition_threshold": 3,
        "column_nonempty_threshold": 5,
        "revert_row_threshold": 5,
        "revert_column_threshold": 3,
        "allow_analyst_create_rules": False,
        "allow_analyst_create_csv": False,
        "allow_analyst_delete_rules": False,
        "allow_analyst_delete_csv": False,
        "require_reason_rule_creation": False,
        "require_reason_csv_creation": False,
        "require_reason_rule_deletion": False,
        "require_reason_csv_deletion": False,
    }


# ═══════════════════════════════════════════════════════════════════════════
# check_analyst_limit Tests
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.unit
def test_analyst_limit_allowed_under_max(mock_daily_limits, mock_limit_config):
    """Test: action allowed when current + action_count <= max."""
    with patch('wl_limits._read_daily_limits', return_value=mock_daily_limits):
        with patch('wl_limits._read_limit_config', return_value=mock_limit_config):
            allowed, current, max_val = wl_limits.check_analyst_limit(
                "jsmith", "row_removal", action_count=2
            )
            assert allowed is True
            assert current == 3
            assert max_val == 10


@pytest.mark.unit
def test_analyst_limit_allowed_at_boundary(mock_daily_limits, mock_limit_config):
    """Test: action allowed when current + action_count == max."""
    with patch('wl_limits._read_daily_limits', return_value=mock_daily_limits):
        with patch('wl_limits._read_limit_config', return_value=mock_limit_config):
            allowed, current, max_val = wl_limits.check_analyst_limit(
                "jsmith", "row_removal", action_count=7
            )
            assert allowed is True
            assert current == 3
            assert max_val == 10


@pytest.mark.unit
def test_analyst_limit_denied_over_max(mock_daily_limits, mock_limit_config):
    """Test: action denied when current + action_count > max."""
    with patch('wl_limits._read_daily_limits', return_value=mock_daily_limits):
        with patch('wl_limits._read_limit_config', return_value=mock_limit_config):
            allowed, current, max_val = wl_limits.check_analyst_limit(
                "jsmith", "row_removal", action_count=8
            )
            assert allowed is False
            assert current == 3
            assert max_val == 10


@pytest.mark.unit
def test_analyst_limit_disabled_when_max_is_zero(mock_daily_limits):
    """Test: action denied when max == 0 (disabled)."""
    config = {"row_removal": 0}
    with patch('wl_limits._read_daily_limits', return_value=mock_daily_limits):
        with patch('wl_limits._read_limit_config', return_value=config):
            allowed, current, max_val = wl_limits.check_analyst_limit(
                "jsmith", "row_removal"
            )
            assert allowed is False
            assert max_val == 0


@pytest.mark.unit
def test_analyst_limit_unlimited_when_max_is_neg1(mock_daily_limits):
    """Test: action always allowed when max == -1 (unlimited)."""
    config = {"row_removal": -1}
    with patch('wl_limits._read_daily_limits', return_value=mock_daily_limits):
        with patch('wl_limits._read_limit_config', return_value=config):
            allowed, current, max_val = wl_limits.check_analyst_limit(
                "jsmith", "row_removal", action_count=1000
            )
            assert allowed is True
            assert max_val == -1


@pytest.mark.unit
def test_analyst_limit_admin_exempt(mock_daily_limits, mock_limit_config):
    """Test: admin users are exempt (always True, 0, -1)."""
    with patch('wl_limits._read_daily_limits', return_value=mock_daily_limits):
        with patch('wl_limits._read_limit_config', return_value=mock_limit_config):
            allowed, current, max_val = wl_limits.check_analyst_limit(
                "admin", "row_removal", roles=["admin"]
            )
            assert allowed is True
            assert current == 0
            assert max_val == -1


@pytest.mark.unit
def test_analyst_limit_multiple_action_count(mock_daily_limits, mock_limit_config):
    """Test: multiple actions counted correctly."""
    with patch('wl_limits._read_daily_limits', return_value=mock_daily_limits):
        with patch('wl_limits._read_limit_config', return_value=mock_limit_config):
            allowed, current, max_val = wl_limits.check_analyst_limit(
                "jsmith", "row_removal", action_count=5
            )
            assert allowed is True  # 3 + 5 = 8 <= 10
            assert current == 3


@pytest.mark.unit
def test_analyst_limit_missing_user(mock_limit_config):
    """Test: missing user returns (True, 0, max)."""
    with patch('wl_limits._read_daily_limits', return_value={}):
        with patch('wl_limits._read_limit_config', return_value=mock_limit_config):
            allowed, current, max_val = wl_limits.check_analyst_limit(
                "newuser", "row_removal"
            )
            assert allowed is True
            assert current == 0
            assert max_val == 10


# ═══════════════════════════════════════════════════════════════════════════
# check_admin_limit Tests
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.unit
def test_admin_limit_separate_from_analyst(mock_daily_limits):
    """Test: admin limits use separate config."""
    config = {"rule_deletion": 5, "approval_count": 20}
    with patch('wl_limits._read_daily_limits', return_value=mock_daily_limits):
        with patch('wl_limits._read_limit_config', return_value=config):
            allowed, current, max_val = wl_limits.check_admin_limit(
                "admin", "rule_deletion"
            )
            assert allowed is True
            assert max_val == 5


@pytest.mark.unit
def test_admin_limit_respects_zero_semantics(mock_daily_limits):
    """Test: admin limits respect 0=disabled."""
    config = {"rule_deletion": 0}
    with patch('wl_limits._read_daily_limits', return_value=mock_daily_limits):
        with patch('wl_limits._read_limit_config', return_value=config):
            allowed, current, max_val = wl_limits.check_admin_limit(
                "admin", "rule_deletion"
            )
            assert allowed is False
            assert max_val == 0


@pytest.mark.unit
def test_admin_limit_respects_unlimited(mock_daily_limits):
    """Test: admin limits respect -1=unlimited."""
    config = {"approval_count": -1}
    with patch('wl_limits._read_daily_limits', return_value=mock_daily_limits):
        with patch('wl_limits._read_limit_config', return_value=config):
            allowed, current, max_val = wl_limits.check_admin_limit(
                "admin", "approval_count"
            )
            assert allowed is True
            assert max_val == -1


# ═══════════════════════════════════════════════════════════════════════════
# get_limit_status Tests
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.unit
def test_limit_status_all_action_types(mock_daily_limits, mock_limit_config):
    """Test: returns dict with entry for each action type."""
    with patch('wl_limits._read_daily_limits', return_value=mock_daily_limits):
        with patch('wl_limits._read_limit_config', return_value=mock_limit_config):
            status = wl_limits.get_limit_status("jsmith")
            assert isinstance(status, dict)
            assert "row_removal" in status
            assert "row_edit" in status
            assert "revert" in status


@pytest.mark.unit
def test_limit_status_current_count(mock_daily_limits, mock_limit_config):
    """Test: current values match daily_limits.json."""
    with patch('wl_limits._read_daily_limits', return_value=mock_daily_limits):
        with patch('wl_limits._read_limit_config', return_value=mock_limit_config):
            status = wl_limits.get_limit_status("jsmith")
            assert status["row_removal"]["current"] == 3
            assert status["row_edit"]["current"] == 5


@pytest.mark.unit
def test_limit_status_remaining_calculation(mock_daily_limits, mock_limit_config):
    """Test: remaining = max - current."""
    with patch('wl_limits._read_daily_limits', return_value=mock_daily_limits):
        with patch('wl_limits._read_limit_config', return_value=mock_limit_config):
            status = wl_limits.get_limit_status("jsmith")
            assert status["row_removal"]["remaining"] == 7  # 10 - 3
            assert status["row_edit"]["remaining"] == 5  # 10 - 5


@pytest.mark.unit
def test_limit_status_admin_exempt(mock_daily_limits, mock_limit_config):
    """Test: admin roles show -1 for max/remaining."""
    with patch('wl_limits._read_daily_limits', return_value=mock_daily_limits):
        with patch('wl_limits._read_limit_config', return_value=mock_limit_config):
            status = wl_limits.get_limit_status("admin", roles=["admin"])
            assert status["row_removal"]["max"] == -1
            assert status["row_removal"]["remaining"] == -1


# ═══════════════════════════════════════════════════════════════════════════
# increment_daily_limit Tests
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.unit
def test_increment_new_user(mock_daily_limits):
    """Test: new user entry created on increment."""
    with patch('wl_limits._read_daily_limits', return_value=mock_daily_limits):
        with patch('wl_limits._write_daily_limits', return_value=True) as mock_write:
            result = wl_limits.increment_daily_limit("newuser", "row_removal")
            assert result is True
            # Verify write was called with updated counters


@pytest.mark.unit
def test_increment_existing_user(mock_daily_limits):
    """Test: increments existing counter by amount."""
    with patch('wl_limits._read_daily_limits', return_value=mock_daily_limits):
        with patch('wl_limits._write_daily_limits', return_value=True) as mock_write:
            result = wl_limits.increment_daily_limit("jsmith", "row_removal", amount=2)
            assert result is True


@pytest.mark.unit
def test_increment_default_amount(mock_daily_limits):
    """Test: default amount=1 when not specified."""
    with patch('wl_limits._read_daily_limits', return_value=mock_daily_limits):
        with patch('wl_limits._write_daily_limits', return_value=True) as mock_write:
            result = wl_limits.increment_daily_limit("jsmith", "row_removal")
            assert result is True


@pytest.mark.unit
def test_increment_custom_amount(mock_daily_limits):
    """Test: custom amount increments correctly."""
    with patch('wl_limits._read_daily_limits', return_value=mock_daily_limits):
        with patch('wl_limits._write_daily_limits', return_value=True) as mock_write:
            result = wl_limits.increment_daily_limit("jsmith", "row_removal", amount=5)
            assert result is True


# ═══════════════════════════════════════════════════════════════════════════
# set_limit_config Tests
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.unit
def test_set_limit_config_valid(mock_limit_config):
    """Test: valid config written successfully."""
    with patch('wl_limits._get_limits_dir', return_value="/tmp"):
        with patch('builtins.open', mock_open()):
            with patch('wl_limits.file_lock'):
                with patch('os.replace'):
                    success, error = wl_limits.set_limit_config(mock_limit_config)
                    assert success is True
                    assert error == ""


@pytest.mark.unit
def test_set_limit_config_validate_required_keys(mock_limit_config):
    """Test: missing required key returns error."""
    bad_config = mock_limit_config.copy()
    del bad_config["row_removal"]

    with patch('wl_limits._get_limits_dir', return_value="/tmp"):
        success, error = wl_limits.set_limit_config(bad_config)
        assert success is False
        assert "Missing required key" in error


@pytest.mark.unit
def test_set_limit_config_validate_value_type():
    """Test: non-int value returns error."""
    bad_config = {"row_removal": "invalid"}

    with patch('wl_limits._get_limits_dir', return_value="/tmp"):
        success, error = wl_limits.set_limit_config(bad_config)
        assert success is False


@pytest.mark.unit
def test_set_limit_config_fail_closed_on_error(mock_limit_config):
    """Test: OSError returns (False, error_msg)."""
    with patch('wl_limits._get_limits_dir', return_value="/tmp"):
        with patch('builtins.open', side_effect=OSError("Write failed")):
            success, error = wl_limits.set_limit_config(mock_limit_config)
            assert success is False
            assert "Failed to write" in error


# ═══════════════════════════════════════════════════════════════════════════
# reset_daily_limits Tests
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.unit
def test_reset_all_analysts(mock_daily_limits):
    """Test: analyst=RESET_ALL_USERS resets all entries."""
    with patch('wl_limits._read_daily_limits', return_value=mock_daily_limits):
        with patch('wl_limits._write_daily_limits', return_value=True):
            success, summary = wl_limits.reset_daily_limits(analyst=RESET_ALL_USERS)
            assert success is True
            assert "jsmith" in summary
            assert "admin" in summary


@pytest.mark.unit
def test_reset_single_analyst(mock_daily_limits):
    """Test: analyst='jsmith' resets only jsmith entry."""
    with patch('wl_limits._read_daily_limits', return_value=mock_daily_limits):
        with patch('wl_limits._write_daily_limits', return_value=True):
            success, summary = wl_limits.reset_daily_limits(analyst="jsmith")
            assert success is True
            assert "jsmith" in summary


@pytest.mark.unit
def test_reset_nonexistent_analyst(mock_daily_limits):
    """Test: nonexistent analyst returns (True, {})."""
    with patch('wl_limits._read_daily_limits', return_value=mock_daily_limits):
        with patch('wl_limits._write_daily_limits', return_value=True):
            success, summary = wl_limits.reset_daily_limits(analyst="nonexistent")
            assert success is True
            assert summary == {}


@pytest.mark.unit
def test_reset_returns_summary(mock_daily_limits):
    """Test: reset returns summary of reset counts."""
    with patch('wl_limits._read_daily_limits', return_value=mock_daily_limits):
        with patch('wl_limits._write_daily_limits', return_value=True):
            success, summary = wl_limits.reset_daily_limits(analyst="jsmith")
            assert isinstance(summary, dict)
            assert summary.get("jsmith", 0) > 0


@pytest.mark.unit
def test_reset_all_vs_single_analyst(mock_daily_limits):
    """Test: RESET_ALL_USERS behavior different from single user."""
    with patch('wl_limits._read_daily_limits', return_value=mock_daily_limits.copy()):
        with patch('wl_limits._write_daily_limits', return_value=True):
            success, summary_all = wl_limits.reset_daily_limits(analyst=RESET_ALL_USERS)

    with patch('wl_limits._read_daily_limits', return_value=mock_daily_limits.copy()):
        with patch('wl_limits._write_daily_limits', return_value=True):
            success, summary_one = wl_limits.reset_daily_limits(analyst="jsmith")

    assert len(summary_all) > len(summary_one)


# ═══════════════════════════════════════════════════════════════════════════
# get_limit_error_msg Tests
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.unit
def test_error_msg_format():
    """Test: error message is human-readable string."""
    msg = wl_limits.get_limit_error_msg("jsmith", "row_removal", 3, 10)
    assert isinstance(msg, str)
    assert len(msg) > 0


@pytest.mark.unit
def test_error_msg_disabled():
    """Test: max=0 returns disabled message."""
    msg = wl_limits.get_limit_error_msg("jsmith", "row_removal", 0, 0)
    assert "not permitted" in msg.lower()


@pytest.mark.unit
def test_error_msg_remaining():
    """Test: shows remaining count when under limit."""
    msg = wl_limits.get_limit_error_msg("jsmith", "row_removal", 3, 10)
    assert "7" in msg  # 10 - 3 = 7 remaining
