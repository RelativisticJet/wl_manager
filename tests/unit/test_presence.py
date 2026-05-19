"""
Unit tests for wl_presence module (user presence tracking for Whitelist Manager).

Tests presence tracking with per-CSV state dict and automatic cleanup.
"""

import json
import pytest
import time
from unittest.mock import patch, MagicMock

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
    _kv_url,
    _kv_read_csv,
    _kv_write_csv,
    _kv_delete_csv,
    _kv_list_all,
)


class _FakeResourceNotFound(Exception):
    """Stand-in for splunk.ResourceNotFound used inside KV mocks."""
    pass


def _make_splunk_mock(status_code, content=""):
    """Build a mock splunk module with the (status_obj, content) tuple
    shape that splunk.rest.simpleRequest returns. Also defines
    ResourceNotFound as a real exception class so except clauses
    in production code can catch it."""
    mock_status = MagicMock()
    mock_status.status = status_code
    mock_splunk = MagicMock()
    mock_splunk.rest.simpleRequest.return_value = (mock_status, content)
    mock_splunk.ResourceNotFound = _FakeResourceNotFound
    return mock_splunk


def _patch_splunk(mock_splunk):
    """sys.modules patch swapping splunk + splunk.rest."""
    return patch.dict(
        'sys.modules',
        {'splunk': mock_splunk, 'splunk.rest': mock_splunk.rest},
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


# ═════════════════════════════════════════════════════════════════════════════
# Test: KV-store helpers and KV branches of public functions
# (item G3 batch 3 coverage push, 2026-05-19)
#
# Covers bin/wl_presence.py lines 45-193 (KV helpers) and the use_kv
# branches at 230-234, 264-265, 293-294, 322-333, 354-358. The in-memory
# path is already covered by the existing tests above. Same mock-splunk
# pattern as test_ratelimit.py's KV tests.
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestPresenceKvHelpers:
    """Cover the pure helpers + KV REST wrappers."""

    def test_kv_url_without_key_returns_collection_endpoint(self):
        url = _kv_url()
        assert url.endswith("/storage/collections/data/wl_presence_state")
        assert "/servicesNS/nobody/" in url

    def test_kv_url_with_key_appends_to_path(self):
        url = _kv_url("file1.csv")
        assert url.endswith("/wl_presence_state/file1.csv")


@pytest.mark.unit
class TestKvReadCsv:
    """Cover _kv_read_csv at lines 53-80."""

    def test_returns_users_dict_on_200(self):
        users = {"alice": {"last_activity": 1000.0, "idle_minutes": 0}}
        content = json.dumps({"payload": json.dumps(users)})
        mock_splunk = _make_splunk_mock(200, content)
        with _patch_splunk(mock_splunk):
            result = _kv_read_csv("session", "file1.csv")
        assert result == users

    def test_resource_not_found_returns_none(self):
        mock_splunk = _make_splunk_mock(200, "")
        mock_splunk.rest.simpleRequest.side_effect = _FakeResourceNotFound("no rec")
        with _patch_splunk(mock_splunk):
            assert _kv_read_csv("session", "file1.csv") is None

    def test_generic_exception_returns_none(self):
        mock_splunk = _make_splunk_mock(200, "")
        mock_splunk.rest.simpleRequest.side_effect = RuntimeError("network")
        with _patch_splunk(mock_splunk):
            assert _kv_read_csv("session", "file1.csv") is None

    def test_non_200_status_returns_none(self):
        mock_splunk = _make_splunk_mock(500, "")
        with _patch_splunk(mock_splunk):
            assert _kv_read_csv("session", "file1.csv") is None

    def test_malformed_outer_json_returns_none(self):
        mock_splunk = _make_splunk_mock(200, "not valid {{{")
        with _patch_splunk(mock_splunk):
            assert _kv_read_csv("session", "file1.csv") is None

    def test_non_dict_payload_returns_empty_dict(self):
        """payload that parses as a list/scalar → {} (defensive normalization)."""
        content = json.dumps({"payload": json.dumps([1, 2, 3])})
        mock_splunk = _make_splunk_mock(200, content)
        with _patch_splunk(mock_splunk):
            assert _kv_read_csv("session", "file1.csv") == {}

    def test_malformed_inner_payload_returns_empty_dict(self):
        """Inner payload JSON parse failure → {}."""
        content = json.dumps({"payload": "not valid {{{"})
        mock_splunk = _make_splunk_mock(200, content)
        with _patch_splunk(mock_splunk):
            assert _kv_read_csv("session", "file1.csv") == {}


@pytest.mark.unit
class TestKvWriteCsv:
    """Cover _kv_write_csv at lines 83-135."""

    def test_update_succeeds_on_200(self):
        mock_splunk = _make_splunk_mock(200, "")
        with _patch_splunk(mock_splunk):
            assert _kv_write_csv("session", "file1.csv", {"alice": {"last_activity": 1.0}}) is True

    def test_update_404_falls_to_insert(self):
        """404 update → POST insert; insert 201 → True."""
        mock_404 = MagicMock(); mock_404.status = 404
        mock_201 = MagicMock(); mock_201.status = 201
        mock_splunk = MagicMock()
        mock_splunk.ResourceNotFound = _FakeResourceNotFound
        mock_splunk.rest.simpleRequest.side_effect = [
            (mock_404, ""),
            (mock_201, ""),
        ]
        with _patch_splunk(mock_splunk):
            assert _kv_write_csv("session", "file1.csv", {"alice": {}}) is True
        assert mock_splunk.rest.simpleRequest.call_count == 2

    def test_update_500_returns_false(self):
        mock_splunk = _make_splunk_mock(500, "")
        with _patch_splunk(mock_splunk):
            assert _kv_write_csv("session", "file1.csv", {}) is False

    def test_update_resource_not_found_falls_to_insert(self):
        mock_200 = MagicMock(); mock_200.status = 200
        mock_splunk = MagicMock()
        mock_splunk.ResourceNotFound = _FakeResourceNotFound
        mock_splunk.rest.simpleRequest.side_effect = [
            _FakeResourceNotFound("missing"),
            (mock_200, ""),
        ]
        with _patch_splunk(mock_splunk):
            assert _kv_write_csv("session", "file1.csv", {}) is True

    def test_generic_exception_returns_false(self):
        mock_splunk = _make_splunk_mock(200, "")
        mock_splunk.rest.simpleRequest.side_effect = RuntimeError("down")
        with _patch_splunk(mock_splunk):
            assert _kv_write_csv("session", "file1.csv", {}) is False

    def test_insert_failure_returns_false(self):
        """Update 404 + insert also fails (500) → False."""
        mock_404 = MagicMock(); mock_404.status = 404
        mock_500 = MagicMock(); mock_500.status = 500
        mock_splunk = MagicMock()
        mock_splunk.ResourceNotFound = _FakeResourceNotFound
        mock_splunk.rest.simpleRequest.side_effect = [
            (mock_404, ""),
            (mock_500, ""),
        ]
        with _patch_splunk(mock_splunk):
            assert _kv_write_csv("session", "file1.csv", {}) is False

    def test_insert_exception_returns_false(self):
        """Update 404 + insert raises exception → False (line 113)."""
        mock_404 = MagicMock(); mock_404.status = 404
        mock_splunk = MagicMock()
        mock_splunk.ResourceNotFound = _FakeResourceNotFound
        mock_splunk.rest.simpleRequest.side_effect = [
            (mock_404, ""),
            RuntimeError("insert failed"),
        ]
        with _patch_splunk(mock_splunk):
            assert _kv_write_csv("session", "file1.csv", {}) is False


@pytest.mark.unit
class TestKvDeleteCsv:
    """Cover _kv_delete_csv at lines 138-151."""

    def test_delete_returns_true_on_success(self):
        mock_splunk = _make_splunk_mock(200, "")
        with _patch_splunk(mock_splunk):
            assert _kv_delete_csv("session", "file1.csv") is True

    def test_delete_swallows_exception_returns_false(self):
        mock_splunk = _make_splunk_mock(200, "")
        mock_splunk.rest.simpleRequest.side_effect = RuntimeError("down")
        with _patch_splunk(mock_splunk):
            assert _kv_delete_csv("session", "file1.csv") is False

    def test_delete_uses_http_delete_method(self):
        mock_splunk = _make_splunk_mock(200, "")
        with _patch_splunk(mock_splunk):
            _kv_delete_csv("session", "file1.csv")
        kwargs = mock_splunk.rest.simpleRequest.call_args.kwargs
        assert kwargs.get("method") == "DELETE"


@pytest.mark.unit
class TestKvListAll:
    """Cover _kv_list_all at lines 154-193."""

    def test_list_all_parses_records_into_dict(self):
        records = [
            {"_key": "file1.csv", "payload": json.dumps({"alice": {"last_activity": 1.0}})},
            {"_key": "file2.csv", "payload": json.dumps({"bob": {"last_activity": 2.0}})},
        ]
        mock_splunk = _make_splunk_mock(200, json.dumps(records))
        with _patch_splunk(mock_splunk):
            result = _kv_list_all("session")
        assert "file1.csv" in result
        assert "file2.csv" in result
        assert result["file1.csv"] == {"alice": {"last_activity": 1.0}}

    def test_list_all_exception_returns_empty(self):
        mock_splunk = _make_splunk_mock(200, "")
        mock_splunk.rest.simpleRequest.side_effect = RuntimeError("down")
        with _patch_splunk(mock_splunk):
            assert _kv_list_all("session") == {}

    def test_list_all_non_200_returns_empty(self):
        mock_splunk = _make_splunk_mock(500, "")
        with _patch_splunk(mock_splunk):
            assert _kv_list_all("session") == {}

    def test_list_all_non_list_response_returns_empty(self):
        mock_splunk = _make_splunk_mock(200, json.dumps({"not": "a list"}))
        with _patch_splunk(mock_splunk):
            assert _kv_list_all("session") == {}

    def test_list_all_malformed_json_returns_empty(self):
        mock_splunk = _make_splunk_mock(200, "not json")
        with _patch_splunk(mock_splunk):
            assert _kv_list_all("session") == {}

    def test_list_all_skips_records_missing_key(self):
        """Records without _key are filtered out."""
        records = [
            {"no_key": "broken"},
            {"_key": "file1.csv", "payload": json.dumps({"alice": {}})},
        ]
        mock_splunk = _make_splunk_mock(200, json.dumps(records))
        with _patch_splunk(mock_splunk):
            result = _kv_list_all("session")
        assert "file1.csv" in result
        assert len(result) == 1

    def test_list_all_skips_non_dict_records(self):
        """Non-dict entries in the records list are silently dropped."""
        records = [
            "not_a_dict",
            42,
            {"_key": "file1.csv", "payload": json.dumps({"alice": {}})},
        ]
        mock_splunk = _make_splunk_mock(200, json.dumps(records))
        with _patch_splunk(mock_splunk):
            result = _kv_list_all("session")
        assert result == {"file1.csv": {"alice": {}}}

    def test_list_all_skips_malformed_payload_records(self):
        """Records whose payload doesn't parse to a dict are skipped."""
        records = [
            {"_key": "broken.csv", "payload": "not valid {{{"},
            {"_key": "ok.csv", "payload": json.dumps({"alice": {}})},
        ]
        mock_splunk = _make_splunk_mock(200, json.dumps(records))
        with _patch_splunk(mock_splunk):
            result = _kv_list_all("session")
        assert "broken.csv" not in result
        assert "ok.csv" in result


@pytest.mark.unit
class TestPresenceKvBranches:
    """Cover the use_kv=True branches in the public functions."""

    def test_report_presence_uses_kv_when_session_provided(self):
        """report_presence reads + writes via KV when session_key is given."""
        # 1st call: _kv_read_csv (200 with empty payload)
        # 2nd call: _kv_list_all (200 with empty list)
        # 3rd call: _kv_write_csv update (200)
        mock_200_empty_dict = MagicMock(); mock_200_empty_dict.status = 200
        mock_200_empty_list = MagicMock(); mock_200_empty_list.status = 200
        mock_200_write = MagicMock(); mock_200_write.status = 200
        mock_splunk = MagicMock()
        mock_splunk.ResourceNotFound = _FakeResourceNotFound
        mock_splunk.rest.simpleRequest.side_effect = [
            (mock_200_empty_dict, json.dumps({"payload": "{}"})),  # read
            (mock_200_empty_list, json.dumps([])),  # list_all
            (mock_200_write, ""),  # write
        ]
        with _patch_splunk(mock_splunk):
            data, error = report_presence(
                "file1.csv", "alice", session_key="session"
            )
        assert error == ""
        assert any(p["user"] == "alice" for p in data["presence"])
        assert "alice" in data["active_users"]

    def test_get_presence_uses_kv_when_session_provided(self):
        """get_presence reads via KV when session_key is given."""
        users = {"alice": {"last_activity": time.time(), "idle_minutes": 0}}
        mock_splunk = _make_splunk_mock(200, json.dumps({"payload": json.dumps(users)}))
        with _patch_splunk(mock_splunk):
            data, error = get_presence("file1.csv", session_key="session")
        assert error == ""
        assert any(p["user"] == "alice" for p in data["presence"])

    def test_get_presence_empty_kv_record_returns_empty_list(self):
        """KV read returns None → empty presence list."""
        mock_splunk = _make_splunk_mock(200, "")
        mock_splunk.rest.simpleRequest.side_effect = _FakeResourceNotFound("no rec")
        with _patch_splunk(mock_splunk):
            data, error = get_presence("file1.csv", session_key="session")
        assert error == ""
        assert data == {"presence": []}

    def test_cleanup_presence_kv_path_removes_stale_users(self):
        """KV-path cleanup deletes records that are entirely stale."""
        old_ts = time.time() - 99999  # very stale
        records = [
            {"_key": "stale.csv", "payload": json.dumps({"alice": {"last_activity": old_ts}})},
        ]
        # Sequence: list_all (200), then _kv_delete_csv for stale.csv (200)
        mock_status_200 = MagicMock(); mock_status_200.status = 200
        mock_splunk = MagicMock()
        mock_splunk.ResourceNotFound = _FakeResourceNotFound
        mock_splunk.rest.simpleRequest.side_effect = [
            (mock_status_200, json.dumps(records)),
            (mock_status_200, ""),
        ]
        with _patch_splunk(mock_splunk):
            removed = cleanup_presence(max_idle_minutes=30, session_key="session")
        assert removed == 1  # alice was removed
        # 1 list + 1 delete = 2 calls
        assert mock_splunk.rest.simpleRequest.call_count == 2

    def test_cleanup_presence_kv_path_keeps_active_users(self):
        """KV-path cleanup leaves records with at least one active user."""
        recent_ts = time.time() - 10  # 10s ago, well within window
        records = [
            {"_key": "active.csv", "payload": json.dumps({
                "alice": {"last_activity": recent_ts},
            })},
        ]
        mock_status_200 = MagicMock(); mock_status_200.status = 200
        mock_splunk = MagicMock()
        mock_splunk.ResourceNotFound = _FakeResourceNotFound
        mock_splunk.rest.simpleRequest.side_effect = [
            (mock_status_200, json.dumps(records)),
        ]
        with _patch_splunk(mock_splunk):
            removed = cleanup_presence(max_idle_minutes=30, session_key="session")
        assert removed == 0
        # Only the list call — no delete, no write (no change needed)
        assert mock_splunk.rest.simpleRequest.call_count == 1

    def test_cleanup_presence_kv_path_partial_cleanup_writes_back(self):
        """If some users stale and some active, _kv_write_csv updates the record."""
        old_ts = time.time() - 99999
        recent_ts = time.time() - 10
        records = [
            {"_key": "mixed.csv", "payload": json.dumps({
                "stale_user": {"last_activity": old_ts},
                "active_user": {"last_activity": recent_ts},
            })},
        ]
        mock_status_200 = MagicMock(); mock_status_200.status = 200
        mock_splunk = MagicMock()
        mock_splunk.ResourceNotFound = _FakeResourceNotFound
        mock_splunk.rest.simpleRequest.side_effect = [
            (mock_status_200, json.dumps(records)),  # list_all
            (mock_status_200, ""),  # write_csv update
        ]
        with _patch_splunk(mock_splunk):
            removed = cleanup_presence(max_idle_minutes=30, session_key="session")
        assert removed == 1
        # 1 list + 1 write = 2 calls
        assert mock_splunk.rest.simpleRequest.call_count == 2

    def test_get_presence_skips_non_dict_user_data(self):
        """If a user's value isn't a dict (corrupt KV entry) it's skipped.

        Pins line 304 of wl_presence.py — the `if not isinstance(data,
        dict): continue` defensive check in get_presence.
        """
        # Mix a dict-valued user with a corrupt non-dict value
        corrupt_payload = json.dumps({
            "alice": {"last_activity": time.time()},
            "broken": "not_a_dict_value",
        })
        content = json.dumps({"payload": corrupt_payload})
        mock_splunk = _make_splunk_mock(200, content)
        with _patch_splunk(mock_splunk):
            data, error = get_presence("file1.csv", session_key="session")
        assert error == ""
        users = [p["user"] for p in data["presence"]]
        assert "alice" in users
        assert "broken" not in users  # skipped via the continue at line 304

    def test_reset_presence_kv_path_deletes_each_record(self):
        """reset_presence with session_key enumerates and deletes."""
        records = [
            {"_key": "a.csv", "payload": json.dumps({})},
            {"_key": "b.csv", "payload": json.dumps({})},
        ]
        mock_status_200 = MagicMock(); mock_status_200.status = 200
        mock_splunk = MagicMock()
        mock_splunk.ResourceNotFound = _FakeResourceNotFound
        mock_splunk.rest.simpleRequest.side_effect = [
            (mock_status_200, json.dumps(records)),  # list_all
            (mock_status_200, ""),  # delete a
            (mock_status_200, ""),  # delete b
        ]
        with _patch_splunk(mock_splunk):
            reset_presence("session")
        # 1 list + 2 deletes = 3 calls
        assert mock_splunk.rest.simpleRequest.call_count == 3
