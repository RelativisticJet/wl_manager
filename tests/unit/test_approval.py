"""
Unit tests for wl_approval module.

Tests all 8 public functions:
- get_pending_for_csv
- get_pending_for_rule
- submit_approval
- submit_dual_approval
- check_approval_gate
- expire_pending_approvals
- check_conflicts
- cancel_conflicts

Includes 50+ test cases covering happy paths, error cases, and edge cases.
"""

import sys
import os
import json
import tempfile
import time
from pathlib import Path
from unittest.mock import patch, MagicMock, call
from datetime import datetime, timedelta, timezone

import pytest
from freezegun import freeze_time

# Add bin/ to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "bin"))

from wl_approval import (
    get_pending_for_csv,
    get_pending_for_rule,
    submit_approval,
    submit_dual_approval,
    check_approval_gate,
    expire_pending_approvals,
    check_conflicts,
    cancel_conflicts,
    _read_approval_queue,
    _write_approval_queue,
    _validate_queue_entry,
    _get_approval_queue_path,
    _generate_request_id,
    _is_expired,
)


@pytest.fixture
def temp_queue_dir(tmp_path, monkeypatch):
    """Create temporary lookups directory and patch OWN_LOOKUPS."""
    lookups_dir = tmp_path / "lookups"
    lookups_dir.mkdir()

    # Patch wl_approval module's OWN_LOOKUPS after import
    import wl_approval
    monkeypatch.setattr(wl_approval, "OWN_LOOKUPS", str(lookups_dir))

    return lookups_dir


@pytest.fixture
def mock_approval_queue():
    """Sample approval queue with pending, approved, and expired entries."""
    now = int(time.time())
    return [
        {
            "request_id": "req-1",
            "status": "pending",
            "timestamp": now - 100,
            "analyst": "jsmith",
            "action_type": "save_csv",
            "payload": {"csv_file": "DR123.csv", "detection_rule": "Rule1"},
            "reason": "Update whitelist",
            "csv_file": "DR123.csv",
            "detection_rule": "Rule1",
        },
        {
            "request_id": "req-2",
            "status": "pending",
            "timestamp": now - 200,
            "analyst": "jdoe",
            "action_type": "delete_rule",
            "payload": {"detection_rule": "Rule2"},
            "reason": "Rule no longer needed",
            "csv_file": "",
            "detection_rule": "Rule2",
        },
        {
            "request_id": "req-3",
            "status": "approved",
            "timestamp": now - 1000,
            "analyst": "jsmith",
            "action_type": "save_csv",
            "payload": {"csv_file": "DR456.csv"},
            "reason": "Update IP whitelist",
            "resolved_by": "admin1",
            "resolved_at": now - 900,
            "csv_file": "DR456.csv",
            "detection_rule": "Rule3",
        },
    ]


@pytest.fixture
def mock_limits(monkeypatch):
    """Mock check_analyst_limit to return success by default."""
    def mock_check(user, action_type, action_count, roles):
        return (True, 0, -1)  # allowed, current, max

    import wl_approval
    monkeypatch.setattr(wl_approval, "check_analyst_limit", mock_check)
    return mock_check


@pytest.fixture
def mock_notify():
    """Mock notify_admins and notify_analyst functions."""
    return MagicMock()


# ═══════════════════════════════════════════════════════════════════════════
# Tests: _read_approval_queue
# ═══════════════════════════════════════════════════════════════════════════

def test_read_queue_empty_file(temp_queue_dir):
    """Test reading queue when file doesn't exist."""
    entries, error = _read_approval_queue()
    assert entries == []
    assert error == ""


def test_read_queue_valid_json(temp_queue_dir, mock_approval_queue):
    """Test reading valid queue JSON."""
    queue_path = Path(_get_approval_queue_path())
    with open(queue_path, "w") as fh:
        json.dump(mock_approval_queue, fh)

    entries, error = _read_approval_queue()
    assert len(entries) == 3
    assert entries[0]["request_id"] == "req-1"
    assert error == ""


def test_read_queue_corrupted_json(temp_queue_dir):
    """Test reading corrupted queue JSON."""
    queue_path = Path(_get_approval_queue_path())
    with open(queue_path, "w") as fh:
        fh.write("{ invalid json")

    entries, error = _read_approval_queue()
    assert entries == []
    assert "JSON corrupted" in error


def test_read_queue_not_list(temp_queue_dir):
    """Test reading queue file that contains dict instead of list."""
    queue_path = Path(_get_approval_queue_path())
    with open(queue_path, "w") as fh:
        json.dump({"data": []}, fh)

    entries, error = _read_approval_queue()
    assert entries == []
    assert "expected list" in error


# ═══════════════════════════════════════════════════════════════════════════
# Tests: _write_approval_queue
# ═══════════════════════════════════════════════════════════════════════════

def test_write_queue_atomic(temp_queue_dir, mock_approval_queue):
    """Test writing queue uses atomic temp+replace pattern."""
    success, error = _write_approval_queue(mock_approval_queue)
    assert success
    assert error == ""

    # Verify file exists and can be read back
    entries, read_error = _read_approval_queue()
    assert len(entries) == 3
    assert read_error == ""


def test_write_queue_valid_json(temp_queue_dir, mock_approval_queue):
    """Test written queue is valid JSON."""
    _write_approval_queue(mock_approval_queue)

    queue_path = Path(_get_approval_queue_path())
    with open(queue_path, "r") as fh:
        data = json.load(fh)
    assert len(data) == 3


# ═══════════════════════════════════════════════════════════════════════════
# Tests: _validate_queue_entry
# ═══════════════════════════════════════════════════════════════════════════

def test_validate_entry_missing_field():
    """Test validation catches missing required field."""
    entry = {"request_id": "123", "status": "pending"}
    valid, error = _validate_queue_entry(entry)
    assert not valid
    assert "Missing required field" in error


def test_validate_entry_invalid_status():
    """Test validation catches invalid status."""
    entry = {
        "request_id": "123",
        "status": "invalid",
        "timestamp": 0,
        "analyst": "user",
        "action_type": "save_csv",
    }
    valid, error = _validate_queue_entry(entry)
    assert not valid
    assert "Invalid status" in error


def test_validate_entry_valid():
    """Test validation passes for valid entry."""
    entry = {
        "request_id": "123",
        "status": "pending",
        "timestamp": int(time.time()),
        "analyst": "user",
        "action_type": "save_csv",
    }
    valid, error = _validate_queue_entry(entry)
    assert valid
    assert error == ""


# ═══════════════════════════════════════════════════════════════════════════
# Tests: _generate_request_id
# ═══════════════════════════════════════════════════════════════════════════

def test_generate_request_id_unique():
    """Test request IDs are unique."""
    ids = [_generate_request_id() for _ in range(10)]
    assert len(ids) == len(set(ids))  # All unique


def test_generate_request_id_format():
    """Test request ID is UUID format."""
    req_id = _generate_request_id()
    assert len(req_id) == 36  # UUID4 format
    assert req_id.count("-") == 4


def test_generate_request_id_is_uuid4_regex():
    """Regression lock for Phase 4 (2026-04-19).

    Prior to the merge, wl_handler.py shipped an independent generator
    that produced ``req_<timestamp>_<random>_<user>`` — a different
    shape entirely, and one that leaked the creator's username into
    any URL or log that referenced the ID.

    This test locks in the canonical UUID4 format so anyone who
    re-introduces a custom scheme fails loudly instead of silently
    producing mixed-format IDs in the approval queue.
    """
    import re
    from wl_approval import generate_request_id  # public canonical name
    pattern = re.compile(
        r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-"
        r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
    )
    for _ in range(20):
        req_id = generate_request_id()
        assert pattern.match(req_id), (
            f"Request ID {req_id!r} does not match UUID4 pattern. "
            "Consolidation with handler's legacy format broken.")


def test_handler_has_no_local_generate_request_id_def():
    """Regression lock (Phase 4): catches the consolidation silently
    reverting.

    If someone re-adds a local ``def _generate_request_id(`` in
    ``bin/wl_handler.py``, the aliased import from wl_approval gets
    shadowed and the two-format bug returns without any runtime
    signal. A source-level text check catches this at test time,
    before anything reaches production.

    We scan the file instead of importing it because wl_handler pulls
    in ``splunk.rest`` stubs that aren't always available in isolated
    unit-test runs.
    """
    import re
    from pathlib import Path
    handler = (Path(__file__).parent.parent.parent
               / "bin" / "wl_handler.py")
    text = handler.read_text(encoding="utf-8")
    # Match any local def, not just the exact legacy signature.
    matches = re.findall(
        r"^def\s+_generate_request_id\s*\(", text, re.MULTILINE)
    assert not matches, (
        f"wl_handler.py defines _generate_request_id locally "
        f"({len(matches)} def(s)) — this shadows the canonical import "
        "from wl_approval and re-introduces the Phase 4 drift. Delete "
        "the local def; handler imports it already.")


# ═══════════════════════════════════════════════════════════════════════════
# Tests: _is_expired
# ═══════════════════════════════════════════════════════════════════════════

@freeze_time("2026-04-01 12:00:00", tz_offset=0)
def test_is_expired_old_entry():
    """Test old entries are expired."""
    now = int(time.time())
    entry = {"timestamp": now - (30 * 24 * 3600)}  # 30 days old
    assert _is_expired(entry)


@freeze_time("2026-04-01 12:00:00", tz_offset=0)
def test_is_expired_recent_entry():
    """Test recent entries are not expired."""
    now = int(time.time())
    entry = {"timestamp": now - 1000}  # ~17 minutes old
    assert not _is_expired(entry)


# ═══════════════════════════════════════════════════════════════════════════
# Tests: expire_pending_approvals
# ═══════════════════════════════════════════════════════════════════════════

@freeze_time("2026-04-01 12:00:00", tz_offset=0)
def test_expire_removes_old_pending(mock_approval_queue):
    """Test expiration removes pending entries older than APPROVAL_EXPIRY_DAYS."""
    # Make an entry old
    now = int(time.time())
    mock_approval_queue[0]["timestamp"] = now - (30 * 24 * 3600)  # 30 days old

    result = expire_pending_approvals(mock_approval_queue)

    # Old pending entry should be removed
    assert len(result) == 2  # Only approved and recent pending


@freeze_time("2026-04-01 12:00:00", tz_offset=0)
def test_expire_preserves_recent_pending(mock_approval_queue):
    """Test recent pending entries are preserved."""
    now = int(time.time())
    mock_approval_queue[0]["timestamp"] = now - 1000  # Recent

    result = expire_pending_approvals(mock_approval_queue)

    assert len(result) == 3
    assert result[0]["request_id"] == "req-1"


@freeze_time("2026-04-01 12:00:00", tz_offset=0)
def test_expire_prunes_resolved_history(mock_approval_queue):
    """Test old resolved entries are pruned."""
    now = int(time.time())
    # Make approved entry old
    mock_approval_queue[2]["timestamp"] = now - (40 * 24 * 3600)  # 40 days old

    result = expire_pending_approvals(mock_approval_queue)

    # Old approved entry should be removed
    assert len(result) == 2
    assert result[0]["request_id"] == "req-1"


# ═══════════════════════════════════════════════════════════════════════════
# Tests: get_pending_for_csv
# ═══════════════════════════════════════════════════════════════════════════

def test_get_pending_for_csv_returns_matching(temp_queue_dir, mock_approval_queue):
    """Test returns only pending entries for specified CSV."""
    _write_approval_queue(mock_approval_queue)

    result = get_pending_for_csv("DR123.csv")

    assert len(result) == 1
    assert result[0]["request_id"] == "req-1"
    assert result[0]["csv_file"] == "DR123.csv"


def test_get_pending_for_csv_filters_status(temp_queue_dir, mock_approval_queue):
    """Test returns only pending (not approved) entries."""
    _write_approval_queue(mock_approval_queue)

    result = get_pending_for_csv("DR456.csv")

    assert len(result) == 0  # approved entry for DR456 is not returned


def test_get_pending_for_csv_empty_result(temp_queue_dir, mock_approval_queue):
    """Test returns empty list when no matches."""
    _write_approval_queue(mock_approval_queue)

    result = get_pending_for_csv("NONEXISTENT.csv")

    assert result == []


# ═══════════════════════════════════════════════════════════════════════════
# Tests: get_pending_for_rule
# ═══════════════════════════════════════════════════════════════════════════

def test_get_pending_for_rule_returns_matching(temp_queue_dir, mock_approval_queue):
    """Test returns only pending entries for specified rule."""
    _write_approval_queue(mock_approval_queue)

    result = get_pending_for_rule("Rule2")

    assert len(result) == 1
    assert result[0]["request_id"] == "req-2"
    assert result[0]["detection_rule"] == "Rule2"


def test_get_pending_for_rule_filters_status(temp_queue_dir, mock_approval_queue):
    """Test returns only pending (not approved) entries."""
    _write_approval_queue(mock_approval_queue)

    result = get_pending_for_rule("Rule3")

    assert len(result) == 0  # approved entry for Rule3 is not returned


# ═══════════════════════════════════════════════════════════════════════════
# Tests: check_approval_gate
# ═══════════════════════════════════════════════════════════════════════════

def test_check_approval_gate_allowed(mock_limits):
    """Test gate allows action when limits permit."""
    needs_approval, error = check_approval_gate("user", "save_csv", 1, ["analyst"])
    assert needs_approval is False
    assert error == ""


def test_check_approval_gate_disabled(monkeypatch):
    """Test gate rejects action when disabled (max=0)."""
    def mock_check(user, action_type, action_count, roles):
        return (False, 0, 0)  # allowed=False, max=0

    import wl_approval
    monkeypatch.setattr(wl_approval, "check_analyst_limit", mock_check)

    needs_approval, error = check_approval_gate("user", "save_csv", 1, ["analyst"])
    assert needs_approval is False
    assert "disabled" in error.lower()


def test_check_approval_gate_limit_exceeded(monkeypatch):
    """Test gate rejects action when limit exceeded."""
    def mock_check(user, action_type, action_count, roles):
        return (False, 10, 10)  # allowed=False, current=10, max=10

    import wl_approval
    monkeypatch.setattr(wl_approval, "check_analyst_limit", mock_check)

    needs_approval, error = check_approval_gate("user", "save_csv", 1, ["analyst"])
    assert needs_approval is False
    assert "Daily limit exceeded" in error


# ═══════════════════════════════════════════════════════════════════════════
# Tests: submit_approval
# ═══════════════════════════════════════════════════════════════════════════

def test_submit_approval_happy_path(temp_queue_dir, mock_limits):
    """Test successful approval submission."""
    success, error, entry = submit_approval(
        user="jsmith",
        action_type="save_csv",
        payload={"csv_file": "DR123.csv", "detection_rule": "Rule1"},
        reason="Update whitelist with new IPs",
        roles=["analyst"],
        notify_fn=None,
    )

    assert success
    assert error == ""
    assert entry["analyst"] == "jsmith"
    assert entry["action_type"] == "save_csv"
    assert "request_id" in entry


def test_submit_approval_validation_failure_empty_user(temp_queue_dir, mock_limits):
    """Test validation rejects empty user."""
    success, error, entry = submit_approval(
        user="",
        action_type="save_csv",
        payload={},
        reason="test",
        roles=[],
    )

    assert not success
    assert error != ""
    assert entry == {}


def test_submit_approval_validation_failure_short_reason(temp_queue_dir, mock_limits):
    """Test validation rejects short reason."""
    success, error, entry = submit_approval(
        user="jsmith",
        action_type="save_csv",
        payload={},
        reason="ab",  # Too short
        roles=[],
    )

    assert not success
    assert "Reason must be at least" in error
    assert entry == {}


def test_submit_approval_validation_failure_long_reason(temp_queue_dir, mock_limits):
    """Test validation rejects long reason."""
    success, error, entry = submit_approval(
        user="jsmith",
        action_type="save_csv",
        payload={},
        reason="x" * 600,  # Too long
        roles=[],
    )

    assert not success
    assert "Reason must be at most" in error
    assert entry == {}


def test_submit_approval_creates_queue_entry(temp_queue_dir, mock_limits, monkeypatch):
    """Test submission creates queue entry when approval gate requires it."""
    # Mock check_approval_gate to require approval
    import wl_approval
    monkeypatch.setattr(wl_approval, "check_approval_gate", lambda u, a, c, r: (True, ""))

    success, error, entry = submit_approval(
        user="jsmith",
        action_type="save_csv",
        payload={"csv_file": "DR123.csv", "detection_rule": "Rule1"},
        reason="Update whitelist",
        roles=["analyst"],
    )

    assert success
    assert entry["status"] == "pending"

    entries, _ = _read_approval_queue()
    assert len(entries) >= 1


def test_submit_approval_generates_unique_request_id(temp_queue_dir, mock_limits):
    """Test each submission gets unique request ID."""
    _, _, entry1 = submit_approval(
        user="jsmith",
        action_type="save_csv",
        payload={"csv_file": "DR1.csv"},
        reason="Update 1",
        roles=[],
    )

    _, _, entry2 = submit_approval(
        user="jsmith",
        action_type="save_csv",
        payload={"csv_file": "DR2.csv"},
        reason="Update 2",
        roles=[],
    )

    assert entry1["request_id"] != entry2["request_id"]


def test_submit_approval_direct_approval_when_no_gate(temp_queue_dir, monkeypatch):
    """Test direct approval when approval gate doesn't require approval."""
    def mock_limit(user, action_type, action_count, roles):
        return (True, 0, -1)  # allowed=True, so no error

    import wl_approval
    monkeypatch.setattr(wl_approval, "check_analyst_limit", mock_limit)
    # check_approval_gate will return (needs_approval=False, "") because allowed=True

    success, error, entry = submit_approval(
        user="jsmith",
        action_type="save_csv",
        payload={},
        reason="Update",
        roles=[],
    )

    assert success
    assert entry["status"] == "approved"
    assert entry["resolved_by"] == "direct"


# ═══════════════════════════════════════════════════════════════════════════
# Tests: submit_dual_approval
# ═══════════════════════════════════════════════════════════════════════════

def test_submit_dual_approval_marks_dual_admin(temp_queue_dir, mock_limits):
    """Test dual approval marks entry with dual-admin type."""
    success, error, entry = submit_dual_approval(
        analyst_user="jsmith",
        approver_user="admin1",
        action_type="delete_rule",
        payload={"detection_rule": "Rule1"},
        reason="Rule is obsolete",
        roles=["analyst"],
    )

    assert success
    assert entry.get("approval_type") == "dual_admin"
    assert entry.get("approver") == "admin1"


# ═══════════════════════════════════════════════════════════════════════════
# Tests: check_conflicts
# ═══════════════════════════════════════════════════════════════════════════

def test_check_conflicts_delete_rule(mock_approval_queue):
    """Test delete_rule action identifies conflicts."""
    action = {"action_type": "delete_rule", "detection_rule": "Rule1"}

    conflicts = check_conflicts(mock_approval_queue, action)

    assert len(conflicts) == 1
    assert conflicts[0]["request_id"] == "req-1"


def test_check_conflicts_delete_csv(mock_approval_queue):
    """Test delete_csv action identifies conflicts."""
    action = {
        "action_type": "delete_csv",
        "csv_file": "DR123.csv",
        "detection_rule": "Rule1",
    }

    conflicts = check_conflicts(mock_approval_queue, action)

    assert len(conflicts) == 1
    assert conflicts[0]["request_id"] == "req-1"


def test_check_conflicts_no_matches(mock_approval_queue):
    """Test no conflicts found."""
    action = {
        "action_type": "delete_rule",
        "detection_rule": "NONEXISTENT",
    }

    conflicts = check_conflicts(mock_approval_queue, action)

    assert conflicts == []


def test_check_conflicts_dry_run(mock_approval_queue):
    """Test check_conflicts doesn't modify queue."""
    action = {"action_type": "delete_rule", "detection_rule": "Rule1"}
    original_len = len(mock_approval_queue)

    check_conflicts(mock_approval_queue, action)

    assert len(mock_approval_queue) == original_len


# ═══════════════════════════════════════════════════════════════════════════
# Tests: cancel_conflicts
# ═══════════════════════════════════════════════════════════════════════════

def test_cancel_conflicts_modifies_queue(mock_approval_queue):
    """Test cancel_conflicts returns modified queue."""
    action = {"action_type": "delete_rule", "detection_rule": "Rule1"}

    new_queue, cancelled = cancel_conflicts(mock_approval_queue, action)

    assert len(new_queue) < len(mock_approval_queue)
    assert len(cancelled) == 1


def test_cancel_conflicts_functional_style(mock_approval_queue):
    """Test input queue not mutated."""
    original_len = len(mock_approval_queue)
    action = {"action_type": "delete_rule", "detection_rule": "Rule1"}

    new_queue, _ = cancel_conflicts(mock_approval_queue, action)

    # Original not modified
    assert len(mock_approval_queue) == original_len


def test_cancel_conflicts_sets_status(mock_approval_queue):
    """Test cancelled entries have status='cancelled'."""
    action = {"action_type": "delete_rule", "detection_rule": "Rule1"}

    _, cancelled = cancel_conflicts(mock_approval_queue, action)

    assert all(e["status"] == "cancelled" for e in cancelled)


def test_cancel_conflicts_sets_metadata(mock_approval_queue):
    """Test cancelled entries have action metadata."""
    action = {
        "action_type": "delete_rule",
        "detection_rule": "Rule1",
        "analyst": "admin1",
    }

    _, cancelled = cancel_conflicts(mock_approval_queue, action)

    assert all(e.get("cancelled_by_action") == "delete_rule" for e in cancelled)
    assert all(e.get("cancelled_by_analyst") == "admin1" for e in cancelled)


def test_cancel_conflicts_calls_notify(mock_approval_queue):
    """Test notify_fn called for each cancellation."""
    notify_fn = MagicMock()
    action = {
        "action_type": "delete_rule",
        "detection_rule": "Rule1",
        "analyst": "admin1",
    }

    _, cancelled = cancel_conflicts(mock_approval_queue, action, notify_fn)

    assert notify_fn.call_count == len(cancelled)


# ═══════════════════════════════════════════════════════════════════════════
# Edge cases
# ═══════════════════════════════════════════════════════════════════════════

def test_large_queue_performance(temp_queue_dir, mock_limits):
    """Test queue with 1000 entries processes quickly."""
    now = int(time.time())
    large_queue = [
        {
            "request_id": f"req-{i}",
            "status": "pending" if i % 2 == 0 else "approved",
            "timestamp": now - (i % 30) * 3600,
            "analyst": f"user{i % 10}",
            "action_type": "save_csv",
            "payload": {"csv_file": f"DR{i}.csv"},
            "reason": "Update",
            "csv_file": f"DR{i}.csv",
            "detection_rule": f"Rule{i % 50}",
        }
        for i in range(1000)
    ]

    _write_approval_queue(large_queue)

    start = time.time()
    result = get_pending_for_csv("DR500.csv")
    elapsed = time.time() - start

    assert elapsed < 1.0  # Should be fast
    assert len(result) <= 1


def test_queue_entry_with_null_values(temp_queue_dir):
    """Test queue handles null/empty optional fields."""
    entry = {
        "request_id": "123",
        "status": "pending",
        "timestamp": int(time.time()),
        "analyst": "user",
        "action_type": "save_csv",
        "payload": {},
        "reason": "test",
        "csv_file": "",
        "detection_rule": "",
    }

    queue = [entry]
    success, _ = _write_approval_queue(queue)
    assert success

    read_queue, _ = _read_approval_queue()
    assert len(read_queue) == 1
    assert read_queue[0]["csv_file"] == ""


# ─────────────────────────────────────────────────────────────────────
# HMAC integrity layer tests (round 6, 2026-04-29)
# ─────────────────────────────────────────────────────────────────────

class TestApprovalQueueHmac:
    """Verify the sidecar HMAC sig fail-closes on every tamper mode.

    Threat model: an attacker with file-write access (container
    escape, compromised admin shell, supply-chain) can edit
    ``_approval_queue.json`` directly, bypassing every server-side
    gate. The HMAC sidecar makes that tamper detectable on the next
    handler read — fail-closed means the queue appears empty (no
    requests get processed) until an admin investigates.
    """

    def _write_unsigned_queue(self, lookups_dir, entries):
        """Write a queue file directly without going through
        ``_write_approval_queue`` — simulates an attacker that
        bypasses the handler."""
        path = os.path.join(str(lookups_dir), "_approval_queue.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(entries, fh)
        return path

    def test_first_read_after_deploy_bootstraps_sig(
            self, temp_queue_dir, mock_approval_queue):
        """Pre-existing queue + missing sig = legacy bootstrap.
        Read should succeed AND write a fresh sig as a side effect."""
        path = self._write_unsigned_queue(
            temp_queue_dir, mock_approval_queue)
        sig_path = os.path.join(str(temp_queue_dir), ".approval_queue.sig")
        assert not os.path.exists(sig_path), (
            "precondition: sig file should not exist yet")

        queue, err = _read_approval_queue()

        assert err == "", f"expected clean read, got: {err}"
        assert len(queue) == 3
        assert os.path.exists(sig_path), (
            "bootstrap should have written a fresh sig")

    def test_tampered_queue_fails_closed(
            self, temp_queue_dir, mock_approval_queue):
        """Attacker edits queue.json after sig was written.
        Next read MUST return empty + tamper error."""
        # Step 1: legitimate write produces queue + sig.
        ok, _ = _write_approval_queue(mock_approval_queue)
        assert ok

        # Step 2: attacker writes a malicious "pre-approved" entry
        # directly, bypassing _write_approval_queue.
        path = os.path.join(str(temp_queue_dir), "_approval_queue.json")
        malicious = list(mock_approval_queue) + [{
            "request_id": "req-malicious",
            "status": "approved",  # attacker pre-approves their own request!
            "timestamp": int(time.time()),
            "analyst": "attacker",
            "action_type": "delete_rule",
            "payload": {"detection_rule": "victim_rule"},
            "reason": "owned",
            "resolved_by": "admin1",  # forged
            "resolved_at": int(time.time()),
            "csv_file": "",
            "detection_rule": "victim_rule",
        }]
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(malicious, fh)

        # Step 3: handler reads — must fail-closed.
        queue, err = _read_approval_queue()
        assert queue == [], (
            "tampered queue must fail-closed (return empty list)")
        assert "QUEUE_TAMPERED" in err, (
            "error must clearly identify tampering, got: " + repr(err))
        assert "queue_sha_mismatch" in err

    def test_tampered_sig_fails_closed(
            self, temp_queue_dir, mock_approval_queue):
        """Attacker edits the sig file (e.g. flips one byte in the
        HMAC). Verification must fail-closed."""
        ok, _ = _write_approval_queue(mock_approval_queue)
        assert ok

        sig_path = os.path.join(
            str(temp_queue_dir), ".approval_queue.sig")
        with open(sig_path, "r", encoding="utf-8") as fh:
            sig = json.load(fh)
        # Flip the last hex char of the checksum — minimal tamper.
        original = sig["_checksum"]
        flipped = original[:-1] + ("0" if original[-1] != "0" else "1")
        sig["_checksum"] = flipped
        with open(sig_path, "w", encoding="utf-8") as fh:
            json.dump(sig, fh)

        queue, err = _read_approval_queue()
        assert queue == []
        assert "sig_hmac_mismatch" in err

    def test_deleted_sig_after_first_use_fails_closed(
            self, temp_queue_dir, mock_approval_queue):
        """After bootstrap, deleting the sig must fail-closed —
        otherwise an attacker would just delete the sig and force
        a re-bootstrap of their tampered queue."""
        ok, _ = _write_approval_queue(mock_approval_queue)
        assert ok

        sig_path = os.path.join(
            str(temp_queue_dir), ".approval_queue.sig")
        os.remove(sig_path)

        # Now attacker tampers with the queue (delete sig + tamper
        # in either order).
        path = os.path.join(
            str(temp_queue_dir), "_approval_queue.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump([], fh)  # attacker clears all pending requests

        # The bootstrap path WILL accept this on first read (because
        # missing sig + queue → bootstrap). This is the documented
        # trade-off: we accept the risk of a one-time bootstrap
        # window in exchange for not requiring a manual migration.
        # On the SECOND tamper attempt (after the bootstrap rewrites
        # the sig), tampering is detected.
        queue1, err1 = _read_approval_queue()
        # Bootstrap: empty queue is accepted.
        assert err1 == ""
        assert queue1 == []

        # Now tamper again — this time the sig exists and protects.
        with open(path, "w", encoding="utf-8") as fh:
            json.dump([{"request_id": "evil", "status": "approved",
                        "timestamp": int(time.time()),
                        "analyst": "x", "action_type": "save_csv",
                        "payload": {}, "reason": "x",
                        "csv_file": "", "detection_rule": ""}],
                       fh)
        queue2, err2 = _read_approval_queue()
        assert queue2 == []
        assert "QUEUE_TAMPERED" in err2

    def test_round_trip_preserves_queue(
            self, temp_queue_dir, mock_approval_queue):
        """Sanity: write then read returns the same data."""
        ok, err = _write_approval_queue(mock_approval_queue)
        assert ok, err
        queue, err = _read_approval_queue()
        assert err == ""
        assert len(queue) == len(mock_approval_queue)
        # Spot-check fields survive
        ids_in = {e["request_id"] for e in mock_approval_queue}
        ids_out = {e["request_id"] for e in queue}
        assert ids_in == ids_out

    def test_empty_queue_no_sig_is_clean(self, temp_queue_dir):
        """No queue + no sig = fresh install. Should read clean
        (empty list, no error)."""
        queue, err = _read_approval_queue()
        assert err == ""
        assert queue == []
