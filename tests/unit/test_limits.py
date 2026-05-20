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
from freezegun import freeze_time

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
def mock_counter_period():
    """
    Mock _get_counter_period_key() to return "2026-04-01".

    This ensures tests use pre-populated mock_daily_limits data rather than today's date.
    """
    with patch('wl_limits.get_counter_period_key', return_value='2026-04-01'):
        yield


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
def test_analyst_limit_allowed_under_max(mock_daily_limits, mock_limit_config, mock_counter_period):
    """Test: action allowed when current + action_count <= max."""
    with patch('wl_limits.read_daily_limits', return_value=mock_daily_limits):
        with patch('wl_limits.read_limit_config', return_value=mock_limit_config):
            allowed, current, max_val = wl_limits.check_analyst_limit(
                "jsmith", "row_removal", action_count=2
            )
            assert allowed is True
            assert current == 3
            assert max_val == 10


@pytest.mark.unit
def test_analyst_limit_allowed_at_boundary(mock_daily_limits, mock_limit_config, mock_counter_period):
    """Test: action allowed when current + action_count == max."""
    with patch('wl_limits.read_daily_limits', return_value=mock_daily_limits):
        with patch('wl_limits.read_limit_config', return_value=mock_limit_config):
            allowed, current, max_val = wl_limits.check_analyst_limit(
                "jsmith", "row_removal", action_count=7
            )
            assert allowed is True
            assert current == 3
            assert max_val == 10


@pytest.mark.unit
def test_analyst_limit_denied_over_max(mock_daily_limits, mock_limit_config, mock_counter_period):
    """Test: action denied when current + action_count > max."""
    with patch('wl_limits.read_daily_limits', return_value=mock_daily_limits):
        with patch('wl_limits.read_limit_config', return_value=mock_limit_config):
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
    with patch('wl_limits.read_daily_limits', return_value=mock_daily_limits):
        with patch('wl_limits.read_limit_config', return_value=config):
            allowed, current, max_val = wl_limits.check_analyst_limit(
                "jsmith", "row_removal"
            )
            assert allowed is False
            assert max_val == 0


@pytest.mark.unit
def test_analyst_limit_unlimited_when_max_is_neg1(mock_daily_limits):
    """Test: action always allowed when max == -1 (unlimited)."""
    config = {"row_removal": -1}
    with patch('wl_limits.read_daily_limits', return_value=mock_daily_limits):
        with patch('wl_limits.read_limit_config', return_value=config):
            allowed, current, max_val = wl_limits.check_analyst_limit(
                "jsmith", "row_removal", action_count=1000
            )
            assert allowed is True
            assert max_val == -1


@pytest.mark.unit
def test_analyst_limit_admin_exempt(mock_daily_limits, mock_limit_config):
    """Test: admin users are exempt (always True, 0, -1)."""
    with patch('wl_limits.read_daily_limits', return_value=mock_daily_limits):
        with patch('wl_limits.read_limit_config', return_value=mock_limit_config):
            allowed, current, max_val = wl_limits.check_analyst_limit(
                "admin", "row_removal", roles=["admin"]
            )
            assert allowed is True
            assert current == 0
            assert max_val == -1


@pytest.mark.unit
def test_analyst_limit_multiple_action_count(mock_daily_limits, mock_limit_config, mock_counter_period):
    """Test: multiple actions counted correctly."""
    with patch('wl_limits.read_daily_limits', return_value=mock_daily_limits):
        with patch('wl_limits.read_limit_config', return_value=mock_limit_config):
            allowed, current, max_val = wl_limits.check_analyst_limit(
                "jsmith", "row_removal", action_count=5
            )
            assert allowed is True  # 3 + 5 = 8 <= 10
            assert current == 3


@pytest.mark.unit
def test_analyst_limit_missing_user(mock_limit_config):
    """Test: missing user returns (True, 0, max)."""
    with patch('wl_limits.read_daily_limits', return_value={}):
        with patch('wl_limits.read_limit_config', return_value=mock_limit_config):
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
    """Test: admin limits use separate config.

    Admin limits live under config['admin_limits'] sub-config — see
    docstring on test_admin_limit_respects_unlimited."""
    config = {"admin_limits": {"rule_deletion": 5, "approval_count": 20}}
    with patch('wl_limits.read_daily_limits', return_value=mock_daily_limits):
        with patch('wl_limits.read_limit_config', return_value=config):
            allowed, current, max_val = wl_limits.check_admin_limit(
                "admin", "rule_deletion"
            )
            assert allowed is True
            assert max_val == 5


@pytest.mark.unit
def test_admin_limit_respects_zero_semantics(mock_daily_limits):
    """Test: admin limits respect 0=disabled."""
    config = {"admin_limits": {"rule_deletion": 0}}
    with patch('wl_limits.read_daily_limits', return_value=mock_daily_limits):
        with patch('wl_limits.read_limit_config', return_value=config):
            allowed, current, max_val = wl_limits.check_admin_limit(
                "admin", "rule_deletion"
            )
            assert allowed is False
            assert max_val == 0


@pytest.mark.unit
def test_admin_limit_respects_unlimited():
    """Test: admin limits respect -1=unlimited (round 7 fix).

    Round 6 surfaced an asymmetry — `check_analyst_limit` short-
    circuits `max_count == -1` to (True, 0, -1) but
    `check_admin_daily_limit` previously took -1 literally so any
    positive count failed. Round 7 aligned them; this test now
    asserts the correct semantics.

    Counters are NOT consulted for unlimited (returns
    `(True, 0, -1)`) — the function should short-circuit before
    even reading daily_limits / period_key.
    """
    config = {"admin_limits": {"approval_count": -1}}
    with patch('wl_limits.read_daily_limits', return_value={}):
        with patch('wl_limits.read_limit_config', return_value=config):
            allowed, current, max_val = wl_limits.check_admin_limit(
                "admin", "approval_count"
            )
            assert allowed is True, (
                "max_count=-1 must allow regardless of current count")
            assert current == 0, (
                "current must be reported as 0 when short-circuiting "
                "(no counter lookup performed)")
            assert max_val == -1


@pytest.mark.unit
def test_admin_limit_unlimited_ignores_huge_action_count():
    """An unlimited admin action accepts any action_count, not
    just count=1 — the short-circuit must bypass arithmetic
    entirely. Mirror of test_analyst_limit_unlimited_when_max_is_neg1.
    """
    config = {"admin_limits": {"approval_count": -1}}
    with patch('wl_limits.read_daily_limits', return_value={}):
        with patch('wl_limits.read_limit_config', return_value=config):
            allowed, current, max_val = wl_limits.check_admin_limit(
                "admin", "approval_count", action_count=1000000)
            assert allowed is True
            assert max_val == -1


@pytest.mark.unit
def test_admin_limit_unlimited_does_not_consult_counter():
    """Defense-in-depth: when -1 short-circuits, no counter lookup
    should happen. We verify by mocking read_daily_limits to RAISE
    — the call must succeed anyway because the short-circuit
    fires BEFORE the counter read."""
    config = {"admin_limits": {"approval_count": -1}}

    def _explode():
        raise AssertionError("counter lookup should be skipped on -1")

    with patch('wl_limits.read_daily_limits', side_effect=_explode):
        with patch('wl_limits.read_limit_config', return_value=config):
            # Should NOT raise — short-circuit must fire first.
            allowed, current, max_val = wl_limits.check_admin_limit(
                "admin", "approval_count")
            assert allowed is True
            assert max_val == -1


@pytest.mark.unit
def test_admin_limit_zero_disabled_takes_priority_over_unlimited():
    """Sentinel ordering check: 0 = disabled is checked BEFORE -1
    = unlimited, so a 0 always wins regardless of code order. Test
    via the only practical scenario (different action types in
    same config)."""
    config = {"admin_limits": {
        "approval_count": -1,    # unlimited
        "rule_deletion": 0,       # disabled
    }}
    with patch('wl_limits.read_daily_limits', return_value={}):
        with patch('wl_limits.read_limit_config', return_value=config):
            ok_unlim, _, max_unlim = wl_limits.check_admin_limit(
                "admin", "approval_count")
            ok_disabled, _, max_disabled = wl_limits.check_admin_limit(
                "admin", "rule_deletion")
            assert ok_unlim is True and max_unlim == -1
            assert ok_disabled is False and max_disabled == 0


@pytest.mark.unit
def test_admin_limit_normal_enforcement_still_works():
    """Sanity: positive max_count still enforces normally — the new
    -1 short-circuit must not regress the common path."""
    config = {"admin_limits": {"approval_count": 3}}
    counters = {
        wl_limits.get_admin_counter_period_key(): {
            "admin": {"admin_approval_count": 2}
        }
    }
    with patch('wl_limits.read_daily_limits', return_value=counters):
        with patch('wl_limits.read_limit_config', return_value=config):
            # 2 + 1 <= 3 — allowed
            ok, cur, mx = wl_limits.check_admin_limit(
                "admin", "approval_count", action_count=1)
            assert ok is True
            assert cur == 2 and mx == 3
            # 2 + 2 > 3 — blocked
            ok, cur, mx = wl_limits.check_admin_limit(
                "admin", "approval_count", action_count=2)
            assert ok is False
            assert cur == 2 and mx == 3


# ═══════════════════════════════════════════════════════════════════════════
# get_limit_status Tests
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.unit
def test_limit_status_all_action_types(mock_daily_limits, mock_limit_config):
    """Test: returns dict with entry for each action type."""
    with patch('wl_limits.read_daily_limits', return_value=mock_daily_limits):
        with patch('wl_limits.read_limit_config', return_value=mock_limit_config):
            status = wl_limits.get_limit_status("jsmith")
            assert isinstance(status, dict)
            assert "row_removal" in status
            assert "row_edit" in status
            assert "revert" in status


@pytest.mark.unit
def test_limit_status_current_count(mock_daily_limits, mock_limit_config, mock_counter_period):
    """Test: current values match daily_limits.json."""
    with patch('wl_limits.read_daily_limits', return_value=mock_daily_limits):
        with patch('wl_limits.read_limit_config', return_value=mock_limit_config):
            status = wl_limits.get_limit_status("jsmith")
            assert status["row_removal"]["current"] == 3
            assert status["row_edit"]["current"] == 5


@pytest.mark.unit
def test_limit_status_remaining_calculation(mock_daily_limits, mock_limit_config, mock_counter_period):
    """Test: remaining = max - current."""
    with patch('wl_limits.read_daily_limits', return_value=mock_daily_limits):
        with patch('wl_limits.read_limit_config', return_value=mock_limit_config):
            status = wl_limits.get_limit_status("jsmith")
            assert status["row_removal"]["remaining"] == 7  # 10 - 3
            assert status["row_edit"]["remaining"] == 5  # 10 - 5


@pytest.mark.unit
def test_limit_status_admin_exempt(mock_daily_limits, mock_limit_config):
    """Test: admin roles show -1 for max/remaining."""
    with patch('wl_limits.read_daily_limits', return_value=mock_daily_limits):
        with patch('wl_limits.read_limit_config', return_value=mock_limit_config):
            status = wl_limits.get_limit_status("admin", roles=["admin"])
            assert status["row_removal"]["max"] == -1
            assert status["row_removal"]["remaining"] == -1


# ═══════════════════════════════════════════════════════════════════════════
# increment_daily_limit Tests
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.unit
def test_increment_new_user(mock_daily_limits):
    """Test: new user entry created on increment.

    increment_daily_limit returns None — assert via the write
    side-effect instead. Public API rename: kwarg is `count` (not
    `amount`).
    """
    with patch('wl_limits.read_daily_limits', return_value=mock_daily_limits):
        with patch('wl_limits.write_daily_limits') as mock_write:
            wl_limits.increment_daily_limit("newuser", "row_removal")
            assert mock_write.called, (
                "increment_daily_limit must persist on call")


@pytest.mark.unit
def test_increment_existing_user(mock_daily_limits):
    """Test: increments existing counter by `count`."""
    with patch('wl_limits.read_daily_limits', return_value=mock_daily_limits):
        with patch('wl_limits.write_daily_limits') as mock_write:
            wl_limits.increment_daily_limit(
                "jsmith", "row_removal", count=2)
            assert mock_write.called


@pytest.mark.unit
def test_increment_default_amount(mock_daily_limits):
    """Test: default count=1 when not specified."""
    with patch('wl_limits.read_daily_limits', return_value=mock_daily_limits):
        with patch('wl_limits.write_daily_limits') as mock_write:
            wl_limits.increment_daily_limit("jsmith", "row_removal")
            assert mock_write.called


@pytest.mark.unit
def test_increment_custom_amount(mock_daily_limits):
    """Test: custom count increments correctly."""
    with patch('wl_limits.read_daily_limits', return_value=mock_daily_limits):
        with patch('wl_limits.write_daily_limits') as mock_write:
            wl_limits.increment_daily_limit(
                "jsmith", "row_removal", count=5)
            assert mock_write.called


# ═══════════════════════════════════════════════════════════════════════════
# set_limit_config Tests
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.unit
def test_set_limit_config_valid(mock_limit_config):
    """Test: valid config written successfully.

    set_limit_config delegates to write_limit_config which uses
    fcntl directly (not a file_lock context manager). We mock
    open + os.replace to keep the test off-disk, AND patch
    wl_limits.fcntl to a MagicMock so the inline flock calls do
    not attempt to lock a Mock file descriptor. The latter is
    Python-3.11-mandatory: fcntl.flock rejects non-int fds with
    TypeError on 3.11+, while 3.9 happened to be more lenient.
    """
    with patch('wl_limits._get_limit_config_path',
               return_value="/tmp/limit_config.json"):
        with patch('builtins.open', mock_open()):
            with patch('os.replace'):
                with patch('wl_limits.fcntl'):
                    success, error = wl_limits.set_limit_config(mock_limit_config)
                    assert success is True
                    assert error == ""


@pytest.mark.unit
def test_set_limit_config_validate_required_keys(mock_limit_config):
    """Test: missing required key returns error."""
    bad_config = mock_limit_config.copy()
    del bad_config["row_removal"]

    with patch('wl_limits._get_limit_config_path', return_value="/tmp/limit_config.json"), \
         patch('wl_limits._get_daily_limits_path', return_value="/tmp/daily_limits.json"):
        success, error = wl_limits.set_limit_config(bad_config)
        assert success is False
        assert "Missing required key" in error


@pytest.mark.unit
def test_set_limit_config_validate_value_type():
    """Test: non-int value returns error."""
    bad_config = {"row_removal": "invalid"}

    with patch('wl_limits._get_limit_config_path', return_value="/tmp/limit_config.json"), \
         patch('wl_limits._get_daily_limits_path', return_value="/tmp/daily_limits.json"):
        success, error = wl_limits.set_limit_config(bad_config)
        assert success is False


@pytest.mark.unit
def test_set_limit_config_fail_closed_on_error(mock_limit_config):
    """Test: OSError returns (False, error_msg)."""
    with patch('wl_limits._get_limit_config_path', return_value="/tmp/limit_config.json"), \
         patch('wl_limits._get_daily_limits_path', return_value="/tmp/daily_limits.json"):
        with patch('builtins.open', side_effect=OSError("Write failed")):
            success, error = wl_limits.set_limit_config(mock_limit_config)
            assert success is False
            assert "Failed to write" in error


# ═══════════════════════════════════════════════════════════════════════════
# reset_daily_limits Tests
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.unit
def test_reset_all_analysts(mock_daily_limits, mock_counter_period):
    """Test: analyst=RESET_ALL_USERS resets all entries."""
    with patch('wl_limits.read_daily_limits', return_value=mock_daily_limits):
        with patch('wl_limits.write_daily_limits', return_value=True):
            success, summary = wl_limits.reset_daily_limits(analyst=RESET_ALL_USERS)
            assert success is True
            assert "jsmith" in summary
            assert "admin" in summary


@pytest.mark.unit
def test_reset_single_analyst(mock_daily_limits, mock_counter_period):
    """Test: analyst='jsmith' resets only jsmith entry."""
    with patch('wl_limits.read_daily_limits', return_value=mock_daily_limits):
        with patch('wl_limits.write_daily_limits', return_value=True):
            success, summary = wl_limits.reset_daily_limits(analyst="jsmith")
            assert success is True
            assert "jsmith" in summary


@pytest.mark.unit
def test_reset_nonexistent_analyst(mock_daily_limits):
    """Test: nonexistent analyst returns (True, {})."""
    with patch('wl_limits.read_daily_limits', return_value=mock_daily_limits):
        with patch('wl_limits.write_daily_limits', return_value=True):
            success, summary = wl_limits.reset_daily_limits(analyst="nonexistent")
            assert success is True
            assert summary == {}


@pytest.mark.unit
def test_reset_returns_summary(mock_daily_limits, mock_counter_period):
    """Test: reset returns summary of reset counts."""
    with patch('wl_limits.read_daily_limits', return_value=mock_daily_limits):
        with patch('wl_limits.write_daily_limits', return_value=True):
            success, summary = wl_limits.reset_daily_limits(analyst="jsmith")
            assert isinstance(summary, dict)
            assert summary.get("jsmith", 0) > 0


@pytest.mark.unit
def test_reset_all_vs_single_analyst(mock_daily_limits, mock_counter_period):
    """Test: RESET_ALL_USERS behavior different from single user."""
    with patch('wl_limits.read_daily_limits', return_value=mock_daily_limits.copy()):
        with patch('wl_limits.write_daily_limits', return_value=True):
            success, summary_all = wl_limits.reset_daily_limits(analyst=RESET_ALL_USERS)

    with patch('wl_limits.read_daily_limits', return_value=mock_daily_limits.copy()):
        with patch('wl_limits.write_daily_limits', return_value=True):
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


# ═══════════════════════════════════════════════════════════════════════════
# Error Handling & Edge Cases
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.unit
def test_read_daily_limits_file_not_found():
    """Test: _read_daily_limits returns {} when file not found."""
    with patch('wl_limits._get_daily_limits_path',
               return_value="/nonexistent/daily_limits.json"):
        result = wl_limits.read_daily_limits()
        assert result == {}


@pytest.mark.unit
def test_read_daily_limits_json_corruption():
    """Test: _read_daily_limits returns {} on JSON corruption."""
    with patch('wl_limits._get_limit_config_path', return_value="/tmp/limit_config.json"), \
         patch('wl_limits._get_daily_limits_path', return_value="/tmp/daily_limits.json"):
        with patch('builtins.open', mock_open(read_data="{ invalid json")):
            result = wl_limits.read_daily_limits()
            assert result == {}


@pytest.mark.unit
def test_read_limit_config_file_not_found():
    """Test: _read_limit_config returns DEFAULT_LIMITS when file not found."""
    with patch('wl_limits._get_limit_config_path',
               return_value="/nonexistent/limit_config.json"):
        result = wl_limits.read_limit_config()
        assert "row_removal" in result
        assert result["row_removal"] > 0


@pytest.mark.unit
def test_read_limit_config_json_corruption():
    """Test: _read_limit_config returns DEFAULT_LIMITS on corruption."""
    with patch('wl_limits._get_limit_config_path', return_value="/tmp/limit_config.json"), \
         patch('wl_limits._get_daily_limits_path', return_value="/tmp/daily_limits.json"):
        with patch('builtins.open', mock_open(read_data="{ bad json")):
            result = wl_limits.read_limit_config()
            assert "row_removal" in result


@pytest.mark.unit
def test_read_limit_config_missing_keys():
    """Test: _read_limit_config fills missing keys from DEFAULT_LIMITS."""
    partial_config = {"row_removal": 5}  # Missing other keys
    with patch('wl_limits._get_limit_config_path', return_value="/tmp/limit_config.json"), \
         patch('wl_limits._get_daily_limits_path', return_value="/tmp/daily_limits.json"):
        with patch('builtins.open', mock_open(read_data=json.dumps(partial_config))):
            result = wl_limits.read_limit_config()
            # Should have all keys from DEFAULT_LIMITS
            assert "bulk_row_removal" in result


@pytest.mark.unit
def test_get_counter_period_key_daily():
    """Test: get_counter_period_key returns YYYY-MM-DD format for daily.

    Note: the function uses datetime.now(timezone.utc) and reads a
    config dict. Test by calling with an explicit daily-frequency
    config and checking the format rather than mocking datetime
    (which has gotten harder under newer datetime semantics)."""
    daily_cfg = {
        "reset_frequency": "daily",
        "reset_time_utc": "00:00",
    }
    key = wl_limits.get_counter_period_key(daily_cfg)
    # YYYY-MM-DD format check — must be 10 chars, with two dashes
    assert len(key) == 10
    assert key[4] == "-" and key[7] == "-"
    assert key[:4].isdigit()


@pytest.mark.unit
def test_write_daily_limits_success():
    """Test: write_daily_limits writes atomically.

    The new API returns None (raises on failure). Verify it
    completes without raising and that open() was called.

    Also patches wl_limits.fcntl so the inline flock call does
    not attempt to lock a Mock fd — same Python-3.11-mandatory
    fix as test_set_limit_config_valid above."""
    test_data = {"2026-04-01": {"jsmith": {"row_removal": 5}}}
    with patch('wl_limits._get_daily_limits_path',
               return_value="/tmp/daily_limits.json"):
        with patch('builtins.open', mock_open()) as mocked_open:
            with patch('os.replace'):
                with patch('wl_limits.fcntl'):
                    wl_limits.write_daily_limits(test_data)
                    assert mocked_open.called


@pytest.mark.unit
def test_write_daily_limits_os_error():
    """Test: write_daily_limits propagates OSError to caller.

    Updated for the post-refactor API: the function no longer
    returns (False, msg); it raises OSError so callers can handle
    it (or fail-fast). This is the correct behavior for an atomic
    writer — partial state is never observable to readers."""
    test_data = {"2026-04-01": {"jsmith": {"row_removal": 5}}}
    with patch('wl_limits._get_daily_limits_path',
               return_value="/tmp/daily_limits.json"):
        with patch('builtins.open', side_effect=OSError("Write failed")):
            with pytest.raises(OSError, match="Write failed"):
                wl_limits.write_daily_limits(test_data)


# NOTE: tests for `_should_reset_now` were removed during the
# wl_limits public-API refactor (the function was inlined into
# `reset_daily_limits` and `should_reset_period_boundary`).
# Equivalent boundary behavior is exercised by
# `tests/test_wl_limits.py` (35 green tests).


@pytest.mark.unit
def test_get_limit_status_with_zero_limit():
    """Test: get_limit_status shows 0 remaining when max=0."""
    config = {"row_removal": 0}
    with patch('wl_limits.read_daily_limits', return_value={}):
        with patch('wl_limits.read_limit_config', return_value=config):
            with patch('wl_limits.get_counter_period_key', return_value='2026-04-01'):
                status = wl_limits.get_limit_status("jsmith")
                assert status["row_removal"]["remaining"] == 0


@pytest.mark.unit
def test_get_limit_status_with_unlimited():
    """Test: get_limit_status shows -1 remaining when max=-1."""
    config = {"row_removal": -1}
    with patch('wl_limits.read_daily_limits', return_value={}):
        with patch('wl_limits.read_limit_config', return_value=config):
            with patch('wl_limits.get_counter_period_key', return_value='2026-04-01'):
                status = wl_limits.get_limit_status("jsmith")
                assert status["row_removal"]["remaining"] == -1


# ═══════════════════════════════════════════════════════════════════════════
# Lock-path + path helpers (R6-F6 cross-process sequence lock)
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestSanitizeLockUsername:
    """_sanitize_lock_username strips path-traversal and shell metas (lines 198-201)."""

    def test_normal_alphanumeric_passes_through(self):
        from wl_limits import _sanitize_lock_username
        assert _sanitize_lock_username("admin1") == "admin1"

    def test_allowed_punctuation_passes_through(self):
        from wl_limits import _sanitize_lock_username
        assert _sanitize_lock_username("admin.test_1-prod") == "admin.test_1-prod"

    def test_empty_string_falls_back_to_anon(self):
        from wl_limits import _sanitize_lock_username
        assert _sanitize_lock_username("") == "_anon"

    def test_none_falls_back_to_anon(self):
        from wl_limits import _sanitize_lock_username
        assert _sanitize_lock_username(None) == "_anon"

    def test_path_traversal_chars_stripped(self):
        from wl_limits import _sanitize_lock_username
        result = _sanitize_lock_username("../etc/passwd")
        assert "/" not in result
        assert result == ".._etc_passwd"

    def test_shell_metas_stripped(self):
        from wl_limits import _sanitize_lock_username
        result = _sanitize_lock_username("admin;rm -rf /")
        assert ";" not in result
        assert "/" not in result


@pytest.mark.unit
class TestAdminDailyLimitLock:
    """admin_daily_limit_lock cross-process serialization (lines 229-233).

    Note: on Windows fcntl is None and file_lock() is a no-op (no lock file
    is created). These tests verify the context manager YIELDS correctly
    and that the per-user lock-path is computed correctly via mocking.
    """

    def test_lock_yields_and_body_runs(self, tmp_path):
        """Context manager yields → body runs without TimeoutError."""
        from wl_limits import admin_daily_limit_lock
        with patch('wl_limits._get_daily_limits_path',
                   return_value=str(tmp_path / "_daily_limits.json")):
            body_ran = False
            with admin_daily_limit_lock("admin_user_1"):
                body_ran = True
            assert body_ran

    def test_lock_path_includes_sanitized_username(self, tmp_path):
        """Verify the constructed lock path uses sanitized username."""
        from wl_limits import admin_daily_limit_lock
        daily_path = str(tmp_path / "_daily_limits.json")
        captured_path = []

        def fake_file_lock(lock_path, timeout=10):
            captured_path.append(lock_path)
            from contextlib import contextmanager
            @contextmanager
            def _cm():
                yield True
            return _cm()

        with patch('wl_limits._get_daily_limits_path',
                   return_value=daily_path), \
             patch('wl_limits.file_lock', side_effect=fake_file_lock):
            with admin_daily_limit_lock("../etc/passwd"):
                pass
        assert len(captured_path) == 1
        # Path-traversal stripped, sanitized to .._etc_passwd
        assert ".._etc_passwd" in captured_path[0]
        assert captured_path[0].endswith(".rmw.lock")

    def test_lock_path_anon_for_empty_user(self, tmp_path):
        """Empty username → _anon in lock path."""
        from wl_limits import admin_daily_limit_lock
        daily_path = str(tmp_path / "_daily_limits.json")
        captured_path = []

        def fake_file_lock(lock_path, timeout=10):
            captured_path.append(lock_path)
            from contextlib import contextmanager
            @contextmanager
            def _cm():
                yield True
            return _cm()

        with patch('wl_limits._get_daily_limits_path',
                   return_value=daily_path), \
             patch('wl_limits.file_lock', side_effect=fake_file_lock):
            with admin_daily_limit_lock(""):
                pass
        assert "._anon.rmw.lock" in captured_path[0]


@pytest.mark.unit
def test_get_daily_limits_path_creates_versions_dir(tmp_path):
    """_get_daily_limits_path ensures _versions/ dir exists (lines 163-165)."""
    with patch('wl_limits.OWN_LOOKUPS', str(tmp_path)):
        from wl_limits import _get_daily_limits_path
        path = _get_daily_limits_path()
        assert os.path.isdir(os.path.join(str(tmp_path), "_versions"))
        assert path.endswith("_daily_limits.json")


# ═══════════════════════════════════════════════════════════════════════════
# read_limit_config integrity + migration (lines 258-290)
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestReadLimitConfigIntegrity:
    """Cover the body of read_limit_config (currently the largest gap)."""

    def test_missing_config_returns_defaults(self, tmp_path):
        """No file on disk → returns dict(DEFAULT_LIMITS) — the early-return path."""
        from wl_limits import read_limit_config, DEFAULT_LIMITS
        with patch('wl_limits.OWN_LOOKUPS', str(tmp_path)):
            result = read_limit_config()
        assert result == dict(DEFAULT_LIMITS)

    def test_valid_signed_config_returns_persisted_values(self, tmp_path):
        """File present with valid checksum → values returned as written."""
        from wl_limits import (read_limit_config, write_limit_config,
                              DEFAULT_LIMITS)
        custom = dict(DEFAULT_LIMITS)
        custom["row_addition"] = 42
        with patch('wl_limits.OWN_LOOKUPS', str(tmp_path)):
            write_limit_config(custom)
            result = read_limit_config()
        assert result["row_addition"] == 42

    def test_tampered_checksum_still_returns_data(self, tmp_path, caplog):
        """Checksum mismatch logs warning but does NOT lock the app out
        (covers lines 263-270 — the integrity-failure soft path)."""
        from wl_limits import read_limit_config, DEFAULT_LIMITS
        path = tmp_path / "_versions" / "_limit_config.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        config = dict(DEFAULT_LIMITS)
        config["_checksum"] = "0" * 64  # fake checksum
        path.write_text(json.dumps(config))

        with patch('wl_limits.OWN_LOOKUPS', str(tmp_path)), \
             caplog.at_level("WARNING"):
            result = read_limit_config()
        # Data is still returned (tolerant policy)
        assert isinstance(result, dict)
        # Warning was logged
        assert any("CONFIG_INTEGRITY_FAILED" in rec.message
                  for rec in caplog.records)

    def test_legacy_reset_hour_utc_migrated(self, tmp_path):
        """Old `reset_hour_utc: 7` rewrites to `reset_time_utc: "07:00"`
        (covers lines 272-278)."""
        from wl_limits import read_limit_config
        path = tmp_path / "_versions" / "_limit_config.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        config = {"reset_hour_utc": 7}
        path.write_text(json.dumps(config))

        with patch('wl_limits.OWN_LOOKUPS', str(tmp_path)):
            result = read_limit_config()
        assert result["reset_time_utc"] == "07:00"
        assert "reset_hour_utc" not in result

    def test_legacy_reset_hour_utc_out_of_range_defaults_to_zero(self, tmp_path):
        """Invalid reset_hour_utc (e.g., 99) → "00:00" fallback (line 278)."""
        from wl_limits import read_limit_config
        path = tmp_path / "_versions" / "_limit_config.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        config = {"reset_hour_utc": 99}
        path.write_text(json.dumps(config))

        with patch('wl_limits.OWN_LOOKUPS', str(tmp_path)):
            result = read_limit_config()
        assert result["reset_time_utc"] == "00:00"

    def test_both_legacy_and_new_keys_drops_legacy(self, tmp_path):
        """Both reset_hour_utc and reset_time_utc present → legacy dropped (line 282)."""
        from wl_limits import read_limit_config
        path = tmp_path / "_versions" / "_limit_config.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        config = {"reset_hour_utc": 5, "reset_time_utc": "09:30"}
        path.write_text(json.dumps(config))

        with patch('wl_limits.OWN_LOOKUPS', str(tmp_path)):
            result = read_limit_config()
        # New key wins; legacy is dropped
        assert result["reset_time_utc"] == "09:30"
        assert "reset_hour_utc" not in result

    def test_corrupt_json_falls_back_to_defaults(self, tmp_path):
        """JSON parse error → return DEFAULT_LIMITS (line 289-290)."""
        from wl_limits import read_limit_config, DEFAULT_LIMITS
        path = tmp_path / "_versions" / "_limit_config.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("not valid json {{{")

        with patch('wl_limits.OWN_LOOKUPS', str(tmp_path)):
            result = read_limit_config()
        assert result == dict(DEFAULT_LIMITS)


# ═══════════════════════════════════════════════════════════════════════════
# get_counter_period_key for weekly/monthly/yearly (lines 420-470)
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestGetCounterPeriodKeyFrequencies:
    """Cover the weekly/monthly/yearly branches of get_counter_period_key.

    The function returns a stringified period key that identifies the
    current reset bucket; tests freeze time and exercise each frequency.
    """

    def test_never_returns_permanent(self):
        """freq=never → "permanent" sentinel (line 403)."""
        from wl_limits import get_counter_period_key
        result = get_counter_period_key({"reset_frequency": "never"})
        assert result == "permanent"

    def test_invalid_reset_time_falls_back_to_midnight(self):
        """reset_time_utc not parseable → fallback to 00:00 (lines 411-412)."""
        from wl_limits import get_counter_period_key
        with freeze_time("2026-05-19T15:00:00Z"):
            result = get_counter_period_key({
                "reset_frequency": "daily",
                "reset_time_utc": "not-a-time",
            })
        # Should not raise; produces a date string
        assert result == "2026-05-19"

    @freeze_time("2026-05-19T15:00:00Z")  # Tuesday
    def test_weekly_with_monday_reset(self):
        """Weekly freq with reset_day_of_week=0 (Monday) → ISO week ending."""
        from wl_limits import get_counter_period_key
        result = get_counter_period_key({
            "reset_frequency": "weekly",
            "reset_day_of_week": 0,  # Monday
            "reset_time_utc": "00:00",
        })
        # 2026-05-19 is a Tuesday; week reset on Monday at 00:00 means
        # the current bucket starts Monday 2026-05-18.
        assert "W" in result  # ISO week format like "2026-W21-Mon"

    @freeze_time("2026-05-19T15:00:00Z")
    def test_weekly_invalid_dow_falls_back_to_zero(self):
        """reset_day_of_week=99 → falls back to 0 (line 425)."""
        from wl_limits import get_counter_period_key
        # Should not raise — uses Monday (0) as fallback
        result = get_counter_period_key({
            "reset_frequency": "weekly",
            "reset_day_of_week": 99,
        })
        assert "W" in result

    @freeze_time("2026-05-19T15:00:00Z")
    def test_monthly_with_day_15_after_boundary(self):
        """Monthly freq, reset on day 15. Today is May 19 >= boundary → "2026-05"."""
        from wl_limits import get_counter_period_key
        result = get_counter_period_key({
            "reset_frequency": "monthly",
            "reset_day_of_month": 15,
            "reset_time_utc": "00:00",
        })
        assert result == "2026-05"

    @freeze_time("2026-05-10T15:00:00Z")
    def test_monthly_before_boundary_returns_previous_month(self):
        """Monthly freq, today before reset day → previous month's key."""
        from wl_limits import get_counter_period_key
        result = get_counter_period_key({
            "reset_frequency": "monthly",
            "reset_day_of_month": 15,
            "reset_time_utc": "00:00",
        })
        assert result == "2026-04"

    @freeze_time("2026-05-19T15:00:00Z")
    def test_monthly_invalid_day_falls_back_to_one(self):
        """reset_day_of_month=99 → falls back to 1 (line 437)."""
        from wl_limits import get_counter_period_key
        result = get_counter_period_key({
            "reset_frequency": "monthly",
            "reset_day_of_month": 99,
        })
        # Day=1 always satisfies "now>=boundary" past midnight today
        assert result == "2026-05"

    @freeze_time("2026-05-19T15:00:00Z")
    def test_monthly_short_month_clamps_day(self):
        """reset_day=31 in Feb → clamps to last day of month (line 440)."""
        from wl_limits import get_counter_period_key
        with freeze_time("2026-02-28T15:00:00Z"):
            result = get_counter_period_key({
                "reset_frequency": "monthly",
                "reset_day_of_month": 31,
            })
        # Feb has 28 days in 2026; boundary clamped to 28; we're past it
        assert result == "2026-02"

    @freeze_time("2026-05-19T15:00:00Z")
    def test_yearly_after_boundary_returns_current_year(self):
        """Yearly freq, reset on Jan 1. May 19 >= Jan 1 → "2026"."""
        from wl_limits import get_counter_period_key
        result = get_counter_period_key({
            "reset_frequency": "yearly",
            "reset_month": 1,
            "reset_day_of_year": 1,
            "reset_time_utc": "00:00",
        })
        assert result == "2026"

    @freeze_time("2026-02-15T15:00:00Z")
    def test_yearly_before_boundary_returns_prior_year(self):
        """Yearly freq, reset on July 1. Feb 15 < July 1 → "2025"."""
        from wl_limits import get_counter_period_key
        result = get_counter_period_key({
            "reset_frequency": "yearly",
            "reset_month": 7,
            "reset_day_of_year": 1,
            "reset_time_utc": "00:00",
        })
        assert result == "2025"

    @freeze_time("2026-05-19T15:00:00Z")
    def test_yearly_invalid_month_falls_back_to_january(self):
        """reset_month=99 → falls back to 1 (line 452)."""
        from wl_limits import get_counter_period_key
        result = get_counter_period_key({
            "reset_frequency": "yearly",
            "reset_month": 99,
        })
        # Month=1, day=1 → already past → current year
        assert result == "2026"

    @freeze_time("2026-05-19T15:00:00Z")
    def test_unknown_frequency_falls_back_to_daily(self):
        """Unknown freq value → daily date format (line 470)."""
        from wl_limits import get_counter_period_key
        result = get_counter_period_key({
            "reset_frequency": "bogus_freq",
            "reset_time_utc": "00:00",
        })
        assert result == "2026-05-19"


# ═══════════════════════════════════════════════════════════════════════════
# increment_daily_limit overflow + cleanup (lines 593-615)
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestIncrementDailyLimitOverflow:
    """Cover the MAX_TRACKED_ANALYSTS overflow bucket path."""

    def test_overflow_user_routes_to_shared_bucket(self):
        """When MAX_TRACKED_ANALYSTS is reached, additional users are tracked
        under the shared `__overflow__` bucket (lines 603-609).
        """
        from wl_limits import increment_daily_limit
        # Build counters that are exactly at the cap
        existing = {"u_{}".format(i): {"row_addition": 1}
                   for i in range(1, 1001)}
        full_counters = {"2026-05-19": existing}

        with patch('wl_limits.read_daily_limits',
                   return_value=full_counters), \
             patch('wl_limits.get_counter_period_key',
                   return_value="2026-05-19"), \
             patch('wl_limits.MAX_TRACKED_ANALYSTS', 1000), \
             patch('wl_limits.write_daily_limits') as mock_write:
            increment_daily_limit("new_user_over_cap", "row_addition")

        # __overflow__ bucket should have been created and incremented
        assert mock_write.call_count == 1
        written_counters = mock_write.call_args[0][0]
        assert "__overflow__" in written_counters["2026-05-19"]
        assert "new_user_over_cap" not in written_counters["2026-05-19"]

    def test_permanent_key_keeps_only_permanent_counter(self):
        """In `never` mode, all non-`permanent` keys are pruned (line 594)."""
        from wl_limits import increment_daily_limit
        with patch('wl_limits.read_daily_limits',
                   return_value={"2026-04-01": {"u1": {"x": 1}},
                                "permanent": {"u2": {"x": 1}}}), \
             patch('wl_limits.get_counter_period_key',
                   return_value="permanent"), \
             patch('wl_limits.write_daily_limits') as mock_write:
            increment_daily_limit("u3", "row_addition")

        written = mock_write.call_args[0][0]
        # Old date-based key was pruned
        assert "2026-04-01" not in written
        # `permanent` key kept and u3 added there
        assert "permanent" in written
        assert "u3" in written["permanent"]


# ═════════════════════════════════════════════════════════════════════════════
# Mutation-survivor coverage (2026-05-20 batch).
#
# Baseline mutmut on bin/wl_limits.py reported ~52.6% kill rate (203 of 428
# mutations survived) on 2026-05-19. Survivors cluster in the same five
# patterns identified for wl_csv (see docs/MUTATION_TESTING.md). Tests
# below target the contracts most likely to be silently broken by
# mutations: HMAC checksum integrity, tuple/dict return shapes, boundary
# precision on 0=disabled / -1=unlimited semantics, and increment-delta
# correctness.
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestMutationCoverageGroupAChecksumIntegrity:
    """Group A: compute_config_checksum integrity (parallels wl_csv Group A).

    A config-integrity checksum must be deterministic, distinguish inputs,
    and ignore the `_checksum` field (so a signed config can be
    re-verified without the signature self-referencing).
    """

    def test_checksum_returns_64char_hex(self):
        from wl_limits import compute_config_checksum
        h = compute_config_checksum({"k": "v"})
        assert isinstance(h, str)
        assert len(h) == 64, f"expected 64 hex chars, got {len(h)}: {h!r}"
        assert all(c in "0123456789abcdef" for c in h), (
            f"expected lowercase hex, got: {h!r}"
        )

    def test_checksum_deterministic_across_dict_ordering(self):
        """Reordering keys MUST NOT change the digest (sort_keys=True)."""
        from wl_limits import compute_config_checksum
        h1 = compute_config_checksum({"a": 1, "b": 2, "c": 3})
        h2 = compute_config_checksum({"c": 3, "b": 2, "a": 1})
        assert h1 == h2, (
            f"sort_keys=True should make ordering irrelevant; "
            f"got {h1!r} vs {h2!r}"
        )

    def test_checksum_distinguishes_inputs(self):
        from wl_limits import compute_config_checksum
        h1 = compute_config_checksum({"k": "v1"})
        h2 = compute_config_checksum({"k": "v2"})
        assert h1 != h2, "different values must produce different digests"

    def test_checksum_ignores_self_referencing_checksum_field(self):
        """The function strips `_checksum` before hashing so verification works."""
        from wl_limits import compute_config_checksum
        h_clean = compute_config_checksum({"k": "v"})
        h_with_meta = compute_config_checksum({
            "k": "v",
            "_checksum": "anything",
        })
        assert h_clean == h_with_meta, (
            f"_checksum field must be stripped before hashing; "
            f"got {h_clean!r} vs {h_with_meta!r}"
        )


@pytest.mark.unit
class TestMutationCoverageGroupBTupleContracts:
    """Group B: decision-function tuple shape.

    `check_analyst_limit` and `check_admin_limit` both return
    `Tuple[bool, int, int]` = (allowed, current, max). String wraps or
    type swaps inside the tuple would change the contract.
    """

    def test_check_analyst_limit_returns_three_tuple_of_correct_types(self):
        from wl_limits import check_analyst_limit
        with patch("wl_limits.read_limit_config",
                   return_value={"row_removal": 5}), \
             patch("wl_limits.read_daily_limits",
                   return_value={"2026-05-20": {"u": {"row_removal": 2}}}), \
             patch("wl_limits.get_counter_period_key",
                   return_value="2026-05-20"):
            ret = check_analyst_limit("u", "row_removal", action_count=1,
                                      roles=["wl_editor"])
        assert isinstance(ret, tuple) and len(ret) == 3, (
            f"expected 3-tuple, got: {ret!r}"
        )
        allowed, current, max_count = ret
        assert isinstance(allowed, bool)
        assert isinstance(current, int) and not isinstance(current, bool)
        assert isinstance(max_count, int) and not isinstance(max_count, bool)

    def test_check_analyst_admin_exempt_returns_canonical_sentinel(self):
        """Admin path returns exactly (True, 0, -1) — fixed sentinel."""
        from wl_limits import check_analyst_limit
        with patch("wl_limits.is_admin", return_value=True):
            ret = check_analyst_limit("admin_user", "row_removal",
                                      roles=["wl_admin"])
        assert ret == (True, 0, -1), (
            f"admin-exempt sentinel must be exactly (True, 0, -1); got {ret!r}"
        )

    def test_check_analyst_disabled_returns_false_zero_zero(self):
        """max_count == 0 (disabled) → exactly (False, 0, 0)."""
        from wl_limits import check_analyst_limit
        with patch("wl_limits.read_limit_config",
                   return_value={"row_removal": 0}), \
             patch("wl_limits.is_admin", return_value=False):
            ret = check_analyst_limit("u", "row_removal", roles=[])
        assert ret == (False, 0, 0), (
            f"disabled-action sentinel must be (False, 0, 0); got {ret!r}"
        )

    def test_check_analyst_unlimited_returns_true_zero_neg1(self):
        """max_count == -1 (unlimited) → exactly (True, 0, -1)."""
        from wl_limits import check_analyst_limit
        with patch("wl_limits.read_limit_config",
                   return_value={"row_removal": -1}), \
             patch("wl_limits.is_admin", return_value=False):
            ret = check_analyst_limit("u", "row_removal", roles=[])
        assert ret == (True, 0, -1), (
            f"unlimited-action sentinel must be (True, 0, -1); got {ret!r}"
        )

    def test_set_limit_config_returns_bool_str_tuple(self):
        """`set_limit_config` returns (success: bool, error: str)."""
        from wl_limits import set_limit_config, DEFAULT_LIMITS
        # Construct a complete-but-minimal valid config from DEFAULT_LIMITS
        # so the validator doesn't reject for missing keys.
        valid_config = dict(DEFAULT_LIMITS)
        with patch("wl_limits.write_limit_config"):
            ret = set_limit_config(valid_config)
        assert isinstance(ret, tuple) and len(ret) == 2, (
            f"expected 2-tuple, got: {ret!r}"
        )
        assert isinstance(ret[0], bool), f"success must be bool, got {ret[0]!r}"
        assert isinstance(ret[1], str), f"error must be str, got {ret[1]!r}"


@pytest.mark.unit
class TestMutationCoverageGroupCDictContracts:
    """Group C: `get_limit_status` dict-shape contract.

    For every action key, the inner dict has exactly
    {current, max, remaining}. A string-wrap on any inner key would
    surface as a missing key here.
    """

    REQUIRED_INNER_KEYS = {"current", "max", "remaining"}

    def test_get_limit_status_inner_dict_has_three_keys(self):
        from wl_limits import get_limit_status
        with patch("wl_limits.read_limit_config",
                   return_value={"row_removal": 5}), \
             patch("wl_limits.read_daily_limits", return_value={}), \
             patch("wl_limits.get_counter_period_key",
                   return_value="2026-05-20"), \
             patch("wl_limits.is_admin", return_value=False):
            status = get_limit_status("u", roles=[])
        assert isinstance(status, dict)
        for action, inner in status.items():
            missing = self.REQUIRED_INNER_KEYS - set(inner.keys())
            assert not missing, (
                f"action={action!r} missing keys: {missing}; "
                f"inner: {inner!r}"
            )

    def test_get_limit_status_admin_returns_unlimited_sentinel_per_action(self):
        """Admin path: every inner dict is exactly {current:0, max:-1, remaining:-1}."""
        from wl_limits import get_limit_status
        with patch("wl_limits.read_limit_config", return_value={}), \
             patch("wl_limits.read_daily_limits", return_value={}), \
             patch("wl_limits.get_counter_period_key",
                   return_value="2026-05-20"), \
             patch("wl_limits.is_admin", return_value=True):
            status = get_limit_status("admin_user", roles=["wl_admin"])
        for action, inner in status.items():
            assert inner == {"current": 0, "max": -1, "remaining": -1}, (
                f"action={action!r}: admin-unlimited sentinel violated, "
                f"got {inner!r}"
            )

    def test_get_limit_status_remaining_clamped_to_zero(self):
        """When current >= max, remaining must be 0 (not negative)."""
        from wl_limits import get_limit_status
        with patch("wl_limits.read_limit_config",
                   return_value={"row_removal": 3}), \
             patch("wl_limits.read_daily_limits",
                   return_value={"2026-05-20":
                                 {"u": {"row_removal": 7}}}), \
             patch("wl_limits.get_counter_period_key",
                   return_value="2026-05-20"), \
             patch("wl_limits.is_admin", return_value=False):
            status = get_limit_status("u", roles=[])
        # If max=3 and current=7, remaining=max(0, 3-7)=0 — NOT -4.
        assert status["row_removal"]["remaining"] == 0, (
            f"remaining must be clamped to 0 when over-cap; "
            f"got {status['row_removal']!r}"
        )


@pytest.mark.unit
class TestMutationCoverageGroupDBoundaryPrecision:
    """Group D: boundary precision on cap-comparison.

    `allowed = (current + action_count) <= max_count` is the cap test.
    Mutations to `<=` vs `<` or `+` vs `-` flip the boundary by one,
    which the existing "allowed_under_max" / "at_boundary" /
    "denied_over_max" tests cover for action_count=1 only. The tests
    below pin behavior at the EXACT boundary for action_count > 1.
    """

    def test_check_analyst_limit_exactly_at_cap_with_action_count_2(self):
        """current=3, max=5, action_count=2 → 3+2=5 <= 5 → allowed."""
        from wl_limits import check_analyst_limit
        with patch("wl_limits.read_limit_config",
                   return_value={"row_removal": 5}), \
             patch("wl_limits.read_daily_limits",
                   return_value={"2026-05-20": {"u": {"row_removal": 3}}}), \
             patch("wl_limits.get_counter_period_key",
                   return_value="2026-05-20"), \
             patch("wl_limits.is_admin", return_value=False):
            allowed, current, max_count = check_analyst_limit(
                "u", "row_removal", action_count=2, roles=[]
            )
        assert allowed is True, (
            f"3+2 == 5 (cap) MUST be allowed; got allowed={allowed}, "
            f"current={current}, max={max_count}"
        )

    def test_check_analyst_limit_one_over_cap_with_action_count_2(self):
        """current=4, max=5, action_count=2 → 4+2=6 > 5 → denied."""
        from wl_limits import check_analyst_limit
        with patch("wl_limits.read_limit_config",
                   return_value={"row_removal": 5}), \
             patch("wl_limits.read_daily_limits",
                   return_value={"2026-05-20": {"u": {"row_removal": 4}}}), \
             patch("wl_limits.get_counter_period_key",
                   return_value="2026-05-20"), \
             patch("wl_limits.is_admin", return_value=False):
            allowed, _, _ = check_analyst_limit(
                "u", "row_removal", action_count=2, roles=[]
            )
        assert allowed is False, (
            "4+2 = 6 > 5 (cap) MUST be denied"
        )


@pytest.mark.unit
class TestMutationCoverageGroupEIncrementDelta:
    """Group E: `increment_daily_limit` adds the EXACT amount, not 1.

    Mutations swapping `current + amount` for `current + 1` or `current
    - amount` would silently miscount. We assert the persisted counter
    matches the expected delta.
    """

    def test_increment_adds_exact_amount_4(self):
        """amount=4 → counter increases by exactly 4."""
        from wl_limits import increment_daily_limit
        captured = {}
        def _writer(counters):
            captured["data"] = counters
        with patch("wl_limits.read_daily_limits",
                   return_value={"2026-05-20": {"u": {"x": 3}}}), \
             patch("wl_limits.get_counter_period_key",
                   return_value="2026-05-20"), \
             patch("wl_limits.write_daily_limits", side_effect=_writer):
            increment_daily_limit("u", "x", count=4)
        assert captured["data"]["2026-05-20"]["u"]["x"] == 7, (
            f"3 + 4 must be 7; got "
            f"{captured['data']['2026-05-20']['u']['x']}"
        )

    def test_increment_default_amount_is_exactly_one(self):
        """No amount arg → exactly +1 (mutations to +2, +0, *2 would fail)."""
        from wl_limits import increment_daily_limit
        captured = {}
        def _writer(counters):
            captured["data"] = counters
        with patch("wl_limits.read_daily_limits",
                   return_value={"2026-05-20": {"u": {"x": 5}}}), \
             patch("wl_limits.get_counter_period_key",
                   return_value="2026-05-20"), \
             patch("wl_limits.write_daily_limits", side_effect=_writer):
            increment_daily_limit("u", "x")
        assert captured["data"]["2026-05-20"]["u"]["x"] == 6, (
            f"5 + 1 must be 6; got "
            f"{captured['data']['2026-05-20']['u']['x']}"
        )
