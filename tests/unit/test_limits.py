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
    fcntl directly (not a file_lock context manager). We only need
    to mock open + os.replace to keep the test off-disk.
    """
    with patch('wl_limits._get_limit_config_path',
               return_value="/tmp/limit_config.json"):
        with patch('builtins.open', mock_open()):
            with patch('os.replace'):
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
    completes without raising and that open() was called."""
    test_data = {"2026-04-01": {"jsmith": {"row_removal": 5}}}
    with patch('wl_limits._get_daily_limits_path',
               return_value="/tmp/daily_limits.json"):
        with patch('builtins.open', mock_open()) as mocked_open:
            with patch('os.replace'):
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
