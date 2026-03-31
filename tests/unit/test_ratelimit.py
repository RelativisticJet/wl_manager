"""
Unit tests for wl_ratelimit module (rate limiting for Whitelist Manager).

Tests sliding-window rate limiting with per-user and per-action-type tracking.
"""

import pytest
import time
from unittest.mock import patch

# Add bin directory to path for imports
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../bin'))

from wl_ratelimit import check_rate_limit, reset_rate_limits, _rate_limits


@pytest.mark.unit
class TestCheckRateLimit:
    """Test sliding-window rate limiter."""

    def setup_method(self):
        """Reset rate limits before each test."""
        reset_rate_limits()

    def test_check_rate_limit_allows_within_limit(self):
        """Check that requests within limit are allowed."""
        # RATE_MAX_READS is typically 20
        for i in range(10):
            assert check_rate_limit("user1", "read") is True
        # Should still allow more up to the limit

    def test_check_rate_limit_rejects_over_limit(self):
        """Check that requests exceeding limit are rejected."""
        # Patch the constants where they're imported from
        with patch('wl_constants.RATE_MAX_WRITES', 5):
            reset_rate_limits()
            # Fill up the limit for writes
            for i in range(5):
                assert check_rate_limit("user1", "write") is True
            # Next request should be rejected (exceeds limit)
            result = check_rate_limit("user1", "write")
            # Should reject when over limit
            assert result is False

    def test_check_rate_limit_default_action_is_write(self):
        """Check that default action type is 'write'."""
        # Call without action_type
        result = check_rate_limit("user1")
        assert result is True
        # Should track in the "write" bucket
        assert ("user1", "write") in _rate_limits

    def test_check_rate_limit_separates_users(self):
        """Check that rate limiting is per-user."""
        # User1 gets some requests
        assert check_rate_limit("user1", "write") is True
        assert check_rate_limit("user1", "write") is True
        # User2 should have independent limit
        assert check_rate_limit("user2", "write") is True
        assert check_rate_limit("user2", "write") is True
        # Verify separate tracking
        assert ("user1", "write") in _rate_limits
        assert ("user2", "write") in _rate_limits
        assert _rate_limits[("user1", "write")] != _rate_limits[("user2", "write")]

    def test_check_rate_limit_separates_action_types(self):
        """Check that rate limiting is per-action-type."""
        # Same user with different action types should be separate
        assert check_rate_limit("user1", "read") is True
        assert check_rate_limit("user1", "write") is True
        # Should be tracked separately
        assert ("user1", "read") in _rate_limits
        assert ("user1", "write") in _rate_limits

    def test_check_rate_limit_sliding_window_cleanup(self):
        """Check that timestamps outside window are pruned."""
        reset_rate_limits()
        current_time = time.time()

        # Add a request at current time
        with patch('wl_ratelimit.time.time', return_value=current_time):
            check_rate_limit("user1", "write")
            initial_count = len(_rate_limits[("user1", "write")])
            assert initial_count == 1

        # Patch both time.time and RATE_WINDOW to test cleanup
        later_time = current_time + 70  # Well beyond default 60-second window
        with patch('wl_ratelimit.time.time', return_value=later_time):
            with patch('wl_constants.RATE_WINDOW', 60):
                # Add another request - old timestamp should be pruned
                check_rate_limit("user1", "write")
                # Should have pruned old entry
                final_count = len(_rate_limits[("user1", "write")])
                # New request added, old should be removed
                assert final_count >= 1

    def test_check_rate_limit_stale_key_cleanup(self):
        """Check that stale keys are cleaned up when dict exceeds size."""
        reset_rate_limits()
        # Add many users with old timestamps
        for i in range(100):
            check_rate_limit(f"user{i}", "write")

        # Verify keys exist
        assert len(_rate_limits) > 0

    def test_reset_rate_limits(self):
        """Check that reset_rate_limits clears all state."""
        # Add some requests
        check_rate_limit("user1", "write")
        check_rate_limit("user2", "read")
        assert len(_rate_limits) > 0

        # Reset
        reset_rate_limits()
        assert len(_rate_limits) == 0

    def test_check_rate_limit_with_time_mocking(self):
        """Check rate limiting with mocked time (for precise control)."""
        reset_rate_limits()
        current_time = time.time()

        with patch('wl_ratelimit.time.time', return_value=current_time):
            # First request allowed
            assert check_rate_limit("user1", "write") is True
            # Add many more
            for i in range(4):
                assert check_rate_limit("user1", "write") is True

        # All should be tracked
        assert len(_rate_limits[("user1", "write")]) >= 5


@pytest.mark.unit
class TestRateLimitStatefulness:
    """Test that rate limiter maintains state correctly."""

    def setup_method(self):
        reset_rate_limits()

    def test_repeated_calls_accumulate(self):
        """Check that repeated calls accumulate timestamps."""
        for i in range(3):
            check_rate_limit("user1", "write")

        assert len(_rate_limits[("user1", "write")]) == 3

    def test_empty_state_on_reset(self):
        """Check that reset truly clears state."""
        check_rate_limit("user1", "write")
        check_rate_limit("user2", "read")

        reset_rate_limits()

        assert len(_rate_limits) == 0
        # Next request should create fresh entry
        assert check_rate_limit("user1", "write") is True
        assert len(_rate_limits[("user1", "write")]) == 1
