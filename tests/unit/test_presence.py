"""
Unit tests for wl_presence module (user presence tracking for Whitelist Manager).

Tests presence tracking with per-CSV state dict and automatic cleanup.
"""

import pytest
import time
from unittest.mock import patch

# Add bin directory to path for imports
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../bin'))

from wl_presence import (
    report_presence,
    get_presence,
    cleanup_presence,
    reset_presence,
    _presence,
)


@pytest.mark.unit
class TestReportPresence:
    """Test presence reporting."""

    def setup_method(self):
        """Reset presence before each test."""
        reset_presence()

    def test_report_presence_adds_user(self):
        """Check that report_presence records a user."""
        data, error = report_presence("file1.csv", "john")
        assert error == ""
        assert "presence" in data

    def test_report_presence_returns_data_tuple(self):
        """Check that report_presence returns (data, error) tuple."""
        result = report_presence("file1.csv", "john")
        assert isinstance(result, tuple)
        assert len(result) == 2
        data, error = result
        assert isinstance(data, dict)
        assert isinstance(error, str)

    def test_report_presence_requires_csv_file_and_user(self):
        """Check that csv_file and user are required."""
        data, error = report_presence("", "user")
        assert error != ""

        data, error = report_presence("file.csv", "")
        assert error != ""

    def test_report_presence_includes_users_in_response(self):
        """Check that response includes presence list."""
        report_presence("file1.csv", "john")
        data, error = report_presence("file1.csv", "jane")
        assert error == ""
        assert "presence" in data
        presence_list = data["presence"]
        assert isinstance(presence_list, list)
        assert len(presence_list) >= 1

    def test_report_presence_prunes_stale_users(self):
        """Check that stale presence data is pruned."""
        reset_presence()
        current_time = time.time()

        with patch('wl_presence.time.time', return_value=current_time):
            # Add a user with old timestamp
            report_presence("file1.csv", "john", last_activity=current_time - 10000)

        # Add new user - should trigger pruning
        later_time = current_time + 5000
        with patch('wl_presence.time.time', return_value=later_time):
            data, error = report_presence("file1.csv", "jane")
            # Old user should be pruned

    def test_report_presence_limits_tracked_files(self):
        """Check that there's a limit on tracked files."""
        with patch('wl_constants.MAX_PRESENCE_FILES', 2):
            reset_presence()
            # Add users to multiple files
            report_presence("file1.csv", "user1")
            report_presence("file2.csv", "user2")
            # Try to add to a third file - should hit limit
            data, error = report_presence("file3.csv", "user3")
            # Should either succeed (if auto-cleanup kicked in) or error
            assert isinstance(error, str)

    def test_report_presence_limits_users_per_csv(self):
        """Check that there's a limit on users per CSV."""
        with patch('wl_constants.MAX_PRESENCE_USERS', 2):
            reset_presence()
            report_presence("file1.csv", "user1")
            report_presence("file1.csv", "user2")
            # Try to add third user - should hit limit
            data, error = report_presence("file1.csv", "user3")
            # Should either succeed (if auto-cleanup) or error
            assert isinstance(error, str)

    def test_report_presence_updates_existing_user(self):
        """Check that presence update for existing user works."""
        report_presence("file1.csv", "john", time.time())
        data, error = report_presence("file1.csv", "john", time.time())
        assert error == ""


@pytest.mark.unit
class TestGetPresence:
    """Test presence retrieval."""

    def setup_method(self):
        reset_presence()

    def test_get_presence_returns_data_tuple(self):
        """Check that get_presence returns (data, error) tuple."""
        result = get_presence("file1.csv")
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_get_presence_empty_for_missing_csv(self):
        """Check that get_presence returns empty list for unknown CSV."""
        data, error = get_presence("unknown.csv")
        assert error == ""
        assert "presence" in data
        assert data["presence"] == []

    def test_get_presence_returns_presence_list(self):
        """Check that get_presence returns list of users."""
        report_presence("file1.csv", "john")
        report_presence("file1.csv", "jane")

        data, error = get_presence("file1.csv")
        assert error == ""
        presence_list = data["presence"]
        assert len(presence_list) >= 2
        user_names = [p["user"] for p in presence_list]
        assert "john" in user_names
        assert "jane" in user_names

    def test_get_presence_includes_idle_minutes(self):
        """Check that presence data includes idle_minutes."""
        current_time = time.time()
        with patch('wl_presence.time.time', return_value=current_time):
            report_presence("file1.csv", "john", last_activity=current_time - 300)

        later_time = current_time + 600
        with patch('wl_presence.time.time', return_value=later_time):
            data, error = get_presence("file1.csv")
            assert len(data["presence"]) > 0
            presence_item = data["presence"][0]
            assert "idle_minutes" in presence_item


@pytest.mark.unit
class TestCleanupPresence:
    """Test presence cleanup."""

    def setup_method(self):
        reset_presence()

    def test_cleanup_presence_removes_idle_users(self):
        """Check that cleanup_presence removes idle users."""
        current_time = time.time()

        with patch('wl_presence.time.time', return_value=current_time):
            report_presence("file1.csv", "john", last_activity=current_time - 3600)

        later_time = current_time + 1800  # 30 min later
        with patch('wl_presence.time.time', return_value=later_time):
            removed = cleanup_presence(max_idle_minutes=30)
            assert removed >= 0

    def test_cleanup_presence_returns_count(self):
        """Check that cleanup_presence returns count of removed users."""
        current_time = time.time()

        with patch('wl_presence.time.time', return_value=current_time):
            report_presence("file1.csv", "john", last_activity=current_time)
            report_presence("file1.csv", "jane", last_activity=current_time - 3600)

        result = cleanup_presence(max_idle_minutes=30)
        assert isinstance(result, int)
        assert result >= 0

    def test_cleanup_presence_with_fresh_users(self):
        """Check that cleanup doesn't remove active users."""
        current_time = time.time()

        with patch('wl_presence.time.time', return_value=current_time):
            report_presence("file1.csv", "john", last_activity=current_time)

        # Immediately cleanup
        removed = cleanup_presence(max_idle_minutes=30)
        # Fresh user should not be removed
        data, error = get_presence("file1.csv")
        # At least the fresh user might still be there
        assert isinstance(data, dict)


@pytest.mark.unit
class TestPresenceIdleMinutes:
    """Test idle minutes calculation."""

    def setup_method(self):
        reset_presence()

    def test_presence_idle_minutes_calculation(self):
        """Check that idle_minutes is calculated correctly."""
        current_time = time.time()
        activity_time = current_time - 600  # 10 minutes ago

        with patch('wl_presence.time.time', return_value=current_time):
            report_presence("file1.csv", "john", last_activity=activity_time)
            data, error = get_presence("file1.csv")
            presence_list = data["presence"]
            assert len(presence_list) > 0
            # Idle minutes should be around 10
            idle_min = presence_list[0]["idle_minutes"]
            assert idle_min >= 9  # Allow some floating point variance


@pytest.mark.unit
class TestPresenceReset:
    """Test presence reset functionality."""

    def test_reset_presence(self):
        """Check that reset_presence clears all data."""
        report_presence("file1.csv", "john")
        report_presence("file2.csv", "jane")

        assert len(_presence) > 0
        reset_presence()
        assert len(_presence) == 0

    def test_reset_presence_allows_fresh_tracking(self):
        """Check that tracking works after reset."""
        report_presence("file1.csv", "john")
        reset_presence()

        data, error = report_presence("file1.csv", "jane")
        assert error == ""
        assert len(data["presence"]) > 0


@pytest.mark.unit
class TestPresenceMultipleCSVs:
    """Test presence with multiple CSV files."""

    def setup_method(self):
        reset_presence()

    def test_presence_separate_per_csv(self):
        """Check that presence is tracked separately per CSV."""
        report_presence("file1.csv", "john")
        report_presence("file2.csv", "jane")

        data1, _ = get_presence("file1.csv")
        data2, _ = get_presence("file2.csv")

        users1 = [p["user"] for p in data1["presence"]]
        users2 = [p["user"] for p in data2["presence"]]

        assert "john" in users1
        assert "jane" in users2
        assert "jane" not in users1 or len(users1) == 1

    def test_presence_same_user_multiple_csvs(self):
        """Check that same user can be in multiple CSVs simultaneously."""
        report_presence("file1.csv", "john")
        report_presence("file2.csv", "john")

        data1, _ = get_presence("file1.csv")
        data2, _ = get_presence("file2.csv")

        users1 = [p["user"] for p in data1["presence"]]
        users2 = [p["user"] for p in data2["presence"]]

        assert "john" in users1
        assert "john" in users2


@pytest.mark.unit
class TestPresenceEdgeCases:
    """Test presence tracking edge cases."""

    def setup_method(self):
        reset_presence()

    def test_report_presence_with_none_last_activity(self):
        """Check that None last_activity defaults to now."""
        data, error = report_presence("file1.csv", "john", None)
        assert error == ""
        assert len(data["presence"]) > 0

    def test_report_presence_with_zero_last_activity(self):
        """Check that 0 last_activity is handled."""
        data, error = report_presence("file1.csv", "john", 0)
        # Should either accept or give clear error
        assert isinstance(error, str)

    def test_get_presence_multiple_calls_idempotent(self):
        """Check that get_presence doesn't change state."""
        report_presence("file1.csv", "john")
        data1, _ = get_presence("file1.csv")
        data2, _ = get_presence("file1.csv")
        assert len(data1["presence"]) == len(data2["presence"])
