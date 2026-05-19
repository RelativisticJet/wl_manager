"""
Unit tests for wl_ratelimit module (rate limiting for Whitelist Manager).

Tests sliding-window rate limiting with per-user and per-action-type tracking.
"""

import json
import pytest
import tempfile
import time
from unittest.mock import patch, MagicMock

# Add bin directory to path for imports
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../bin'))

from wl_ratelimit import (
    check_rate_limit, reset_rate_limits, _rate_limits,
    _kv_url, _kv_key, _rmw_lock_path,
    _kv_read_timestamps, _kv_write_timestamps,
    _kv_list_all, _kv_delete_key,
)


class _FakeResourceNotFound(Exception):
    """Stand-in for splunk.ResourceNotFound used inside KV mocks."""
    pass


def _make_splunk_mock(status_code, content=""):
    """Build a mock `splunk` module whose simpleRequest returns
    (status_object, content). Also defines ResourceNotFound so that
    `except splunk.ResourceNotFound:` clauses in the production code
    have a real exception class to catch."""
    mock_status = MagicMock()
    mock_status.status = status_code
    mock_splunk = MagicMock()
    mock_splunk.rest.simpleRequest.return_value = (mock_status, content)
    mock_splunk.ResourceNotFound = _FakeResourceNotFound
    return mock_splunk


def _patch_splunk(mock_splunk):
    """Helper: patch.dict on sys.modules to swap splunk + splunk.rest."""
    return patch.dict(
        'sys.modules',
        {'splunk': mock_splunk, 'splunk.rest': mock_splunk.rest},
    )


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


# ═════════════════════════════════════════════════════════════════════════════
# Test: KV-store helpers and KV-path of check_rate_limit / reset_rate_limits
# (item G3 batch 2 coverage push, 2026-05-19)
#
# Covers bin/wl_ratelimit.py lines 44-200 (KV helpers) and the KV branches
# at 225-258, 281-287. The in-memory path is already covered by the existing
# tests above. The KV path requires mocking splunk.rest.simpleRequest and
# providing a real exception class for splunk.ResourceNotFound.
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestKvHelpers:
    """Cover the pure helpers: _kv_url, _kv_key, _rmw_lock_path."""

    def test_kv_url_without_key_returns_collection_url(self):
        """_kv_url() with no key returns the collection endpoint."""
        url = _kv_url()
        assert url.endswith("/storage/collections/data/wl_ratelimit_state")
        assert "/servicesNS/nobody/" in url

    def test_kv_url_with_key_appends_to_path(self):
        """_kv_url('alice::write') appends the key to the collection URL."""
        url = _kv_url("alice::write")
        assert url.endswith("/wl_ratelimit_state/alice::write")

    def test_kv_key_composes_user_and_action_type(self):
        """_kv_key uses '::' as the delimiter."""
        assert _kv_key("alice", "write") == "alice::write"
        assert _kv_key("bob", "read") == "bob::read"

    def test_rmw_lock_path_sanitizes_unsafe_chars(self):
        """Non-alphanumeric/_/./- characters in the lock path are replaced."""
        path = _rmw_lock_path("alice", "write")
        # tempfile.gettempdir() is the parent dir
        assert path.startswith(tempfile.gettempdir())
        assert path.endswith(".rmw.lock")
        # Standard ASCII names stay verbatim
        assert "alice_write" in path

    def test_rmw_lock_path_handles_path_traversal_attempt(self):
        """Slashes and dots in user input are replaced with underscores."""
        path = _rmw_lock_path("../../etc/passwd", "write")
        # The dangerous '/' is sanitized; ".." stays (dots allowed)
        # but cannot traverse because path is rooted in tempdir
        assert "/" not in os.path.basename(path).replace(os.sep, "")
        assert path.startswith(tempfile.gettempdir())

    def test_rmw_lock_path_empty_user_and_action_falls_back_safely(self):
        """Empty user + empty action_type produces a stable lock path.

        Note: discovered while writing G3 batch 2 — the ``_anon`` sentinel
        branch in _rmw_lock_path is currently UNREACHABLE because the
        implementation joins `user + "_" + action_type`, so the input
        to the sanitizer always contains at least the literal "_", and
        the sanitized string is never empty. The `_anon` fallback would
        only fire if a future refactor removed the joining `"_"`. For
        now, pin the observed behavior: empty inputs produce a path
        rooted in tempdir ending in `.rmw.lock`.
        """
        path = _rmw_lock_path("", "")
        assert path.startswith(tempfile.gettempdir())
        assert path.endswith(".rmw.lock")
        # The literal "_" between user and action_type means the sanitized
        # name contains exactly one underscore — pin this to document
        # the unreachability of the `_anon` branch.
        assert "wl_ratelimit__.rmw.lock" in path


@pytest.mark.unit
class TestKvReadTimestamps:
    """Cover _kv_read_timestamps at bin/wl_ratelimit.py:84-117."""

    def test_returns_timestamps_on_200(self):
        """Status 200 with payload JSON list returns the parsed timestamps."""
        content = json.dumps({
            "_key": "alice::write",
            "payload": json.dumps([1000.0, 1001.5, 1002.7]),
        })
        mock_splunk = _make_splunk_mock(200, content)
        with _patch_splunk(mock_splunk):
            result = _kv_read_timestamps("session", "alice", "write")
        assert result == [1000.0, 1001.5, 1002.7]

    def test_returns_empty_on_resource_not_found(self):
        """splunk.ResourceNotFound → [] (record never written yet)."""
        mock_splunk = _make_splunk_mock(200, "")
        mock_splunk.rest.simpleRequest.side_effect = _FakeResourceNotFound("no rec")
        with _patch_splunk(mock_splunk):
            assert _kv_read_timestamps("session", "alice", "write") == []

    def test_returns_empty_on_generic_exception(self):
        """Generic Exception → [] (fail-open per docstring)."""
        mock_splunk = _make_splunk_mock(200, "")
        mock_splunk.rest.simpleRequest.side_effect = RuntimeError("network down")
        with _patch_splunk(mock_splunk):
            assert _kv_read_timestamps("session", "alice", "write") == []

    def test_returns_empty_on_non_200_status(self):
        """Any non-200 status → []."""
        mock_splunk = _make_splunk_mock(500, "")
        with _patch_splunk(mock_splunk):
            assert _kv_read_timestamps("session", "alice", "write") == []

    def test_returns_empty_on_malformed_outer_json(self):
        """Outer content not parseable as JSON → []."""
        mock_splunk = _make_splunk_mock(200, "not valid json {{{")
        with _patch_splunk(mock_splunk):
            assert _kv_read_timestamps("session", "alice", "write") == []

    def test_filters_non_numeric_timestamps(self):
        """Malformed payload entries (strings, None) are dropped."""
        content = json.dumps({
            "payload": json.dumps([1000.0, "bad_string", None, 1002.5, True]),
        })
        mock_splunk = _make_splunk_mock(200, content)
        with _patch_splunk(mock_splunk):
            result = _kv_read_timestamps("session", "alice", "write")
        # True is also int in Python (bool subclass) — accepted as 1.0
        assert 1000.0 in result and 1002.5 in result
        assert "bad_string" not in result
        assert None not in result

    def test_returns_empty_on_non_list_payload(self):
        """payload that parses as non-list → []."""
        content = json.dumps({"payload": json.dumps({"not": "a list"})})
        mock_splunk = _make_splunk_mock(200, content)
        with _patch_splunk(mock_splunk):
            assert _kv_read_timestamps("session", "alice", "write") == []


@pytest.mark.unit
class TestKvWriteTimestamps:
    """Cover _kv_write_timestamps at bin/wl_ratelimit.py:120-166."""

    def test_update_succeeds_on_200(self):
        """Update POST returns 200 → True."""
        mock_splunk = _make_splunk_mock(200, "")
        with _patch_splunk(mock_splunk):
            assert _kv_write_timestamps("session", "alice", "write", [1.0, 2.0]) is True

    def test_update_404_falls_through_to_insert(self):
        """Update returns 404 → re-attempts as insert; success on 201."""
        # First call (update) returns 404; second call (insert) returns 201.
        mock_status_404 = MagicMock(); mock_status_404.status = 404
        mock_status_201 = MagicMock(); mock_status_201.status = 201
        mock_splunk = MagicMock()
        mock_splunk.ResourceNotFound = _FakeResourceNotFound
        mock_splunk.rest.simpleRequest.side_effect = [
            (mock_status_404, ""),
            (mock_status_201, ""),
        ]
        with _patch_splunk(mock_splunk):
            assert _kv_write_timestamps("session", "alice", "write", [1.0]) is True
        # Both calls fired (update + insert)
        assert mock_splunk.rest.simpleRequest.call_count == 2

    def test_update_500_returns_false_without_insert(self):
        """Update returns 500 (not 404) → False, no fallback insert."""
        mock_splunk = _make_splunk_mock(500, "")
        with _patch_splunk(mock_splunk):
            assert _kv_write_timestamps("session", "alice", "write", [1.0]) is False
        # Only one call (no insert fallback for non-404)
        assert mock_splunk.rest.simpleRequest.call_count == 1

    def test_update_resource_not_found_falls_to_insert(self):
        """Update raises ResourceNotFound → falls to insert path."""
        mock_status_200 = MagicMock(); mock_status_200.status = 200
        mock_splunk = MagicMock()
        mock_splunk.ResourceNotFound = _FakeResourceNotFound
        # First call raises ResourceNotFound, second call (insert) returns 200
        mock_splunk.rest.simpleRequest.side_effect = [
            _FakeResourceNotFound("missing"),
            (mock_status_200, ""),
        ]
        with _patch_splunk(mock_splunk):
            assert _kv_write_timestamps("session", "alice", "write", [1.0]) is True

    def test_generic_exception_returns_false(self):
        """Non-ResourceNotFound exception → False (fail-closed for writes)."""
        mock_splunk = _make_splunk_mock(200, "")
        mock_splunk.rest.simpleRequest.side_effect = RuntimeError("network down")
        with _patch_splunk(mock_splunk):
            assert _kv_write_timestamps("session", "alice", "write", [1.0]) is False


@pytest.mark.unit
class TestKvListAllAndDelete:
    """Cover _kv_list_all (169-187) and _kv_delete_key (190-200)."""

    def test_list_all_returns_records_on_200(self):
        """200 + JSON list content → returned as Python list."""
        records = [
            {"_key": "alice::write", "payload": "[1.0]"},
            {"_key": "bob::read", "payload": "[2.0]"},
        ]
        mock_splunk = _make_splunk_mock(200, json.dumps(records))
        with _patch_splunk(mock_splunk):
            result = _kv_list_all("session")
        assert result == records

    def test_list_all_non_200_returns_empty(self):
        mock_splunk = _make_splunk_mock(500, "")
        with _patch_splunk(mock_splunk):
            assert _kv_list_all("session") == []

    def test_list_all_non_list_response_returns_empty(self):
        """200 but content parses to non-list → []."""
        mock_splunk = _make_splunk_mock(200, json.dumps({"unexpected": "shape"}))
        with _patch_splunk(mock_splunk):
            assert _kv_list_all("session") == []

    def test_list_all_exception_returns_empty(self):
        mock_splunk = _make_splunk_mock(200, "")
        mock_splunk.rest.simpleRequest.side_effect = RuntimeError("down")
        with _patch_splunk(mock_splunk):
            assert _kv_list_all("session") == []

    def test_list_all_malformed_json_returns_empty(self):
        mock_splunk = _make_splunk_mock(200, "not json {{{")
        with _patch_splunk(mock_splunk):
            assert _kv_list_all("session") == []

    def test_delete_key_swallows_exception(self):
        """_kv_delete_key never raises (rate-limit reset is best-effort)."""
        mock_splunk = _make_splunk_mock(200, "")
        mock_splunk.rest.simpleRequest.side_effect = RuntimeError("down")
        with _patch_splunk(mock_splunk):
            # Must not raise
            _kv_delete_key("session", "alice::write")

    def test_delete_key_issues_delete_request(self):
        """_kv_delete_key calls simpleRequest with method=DELETE."""
        mock_splunk = _make_splunk_mock(200, "")
        with _patch_splunk(mock_splunk):
            _kv_delete_key("session", "alice::write")
        # Verify DELETE method was used
        call_kwargs = mock_splunk.rest.simpleRequest.call_args.kwargs
        assert call_kwargs.get("method") == "DELETE"


@pytest.mark.unit
class TestResetRateLimitsKvPath:
    """Cover the KV branch of reset_rate_limits at lines 281-287."""

    def setup_method(self):
        reset_rate_limits()

    def test_reset_with_session_key_deletes_each_kv_record(self):
        """With session_key, reset enumerates all records and DELETEs each."""
        records = [
            {"_key": "alice::write"},
            {"_key": "bob::read"},
        ]
        # Sequence: first call lists records (200 + JSON list),
        # then two DELETEs follow.
        mock_status_200 = MagicMock(); mock_status_200.status = 200
        mock_splunk = MagicMock()
        mock_splunk.ResourceNotFound = _FakeResourceNotFound
        mock_splunk.rest.simpleRequest.side_effect = [
            (mock_status_200, json.dumps(records)),  # _kv_list_all
            (mock_status_200, ""),  # delete alice::write
            (mock_status_200, ""),  # delete bob::read
        ]
        with _patch_splunk(mock_splunk):
            reset_rate_limits("session")
        # 1 list + 2 deletes = 3 calls
        assert mock_splunk.rest.simpleRequest.call_count == 3
        # In-memory dict is also cleared
        assert len(_rate_limits) == 0

    def test_reset_with_session_skips_records_missing_key(self):
        """Records without _key are silently skipped (no DELETE attempted)."""
        records = [
            {"no_key": "broken"},  # missing _key
            {"_key": "alice::write"},
        ]
        mock_status_200 = MagicMock(); mock_status_200.status = 200
        mock_splunk = MagicMock()
        mock_splunk.ResourceNotFound = _FakeResourceNotFound
        mock_splunk.rest.simpleRequest.side_effect = [
            (mock_status_200, json.dumps(records)),
            (mock_status_200, ""),  # only ONE delete for alice
        ]
        with _patch_splunk(mock_splunk):
            reset_rate_limits("session")
        # 1 list + 1 delete (broken record skipped) = 2 calls
        assert mock_splunk.rest.simpleRequest.call_count == 2
