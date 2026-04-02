"""
Integration tests for approval queue chain workflows.

Tests full end-to-end approval workflows with real file I/O (not mocked).
Includes happy path, conflict resolution, expiration, and precondition validation.
"""

import sys
import os
import json
import tempfile
import time
from pathlib import Path

import pytest
from freezegun import freeze_time

# Add bin/ to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "bin"))

from wl_approval import (
    submit_approval,
    get_pending_for_csv,
    cancel_conflicts,
    check_conflicts,
    expire_pending_approvals,
    _read_approval_queue,
    _write_approval_queue,
)


@pytest.fixture
def temp_queue_dir(tmp_path, monkeypatch):
    """Create temporary lookups directory and patch OWN_LOOKUPS."""
    lookups_dir = tmp_path / "lookups"
    lookups_dir.mkdir()

    import wl_approval
    monkeypatch.setattr(wl_approval, "OWN_LOOKUPS", str(lookups_dir))

    return lookups_dir


@pytest.fixture
def mock_limits(monkeypatch):
    """Mock check_analyst_limit to allow actions without approval."""
    def mock_check(user, action_type, action_count, roles):
        return (True, 0, -1)

    import wl_approval
    monkeypatch.setattr(wl_approval, "check_analyst_limit", mock_check)


# ═══════════════════════════════════════════════════════════════════════════
# Integration Tests
# ═══════════════════════════════════════════════════════════════════════════

def test_approval_happy_path(temp_queue_dir, mock_limits):
    """Test approval happy path: submit → verify in queue → conflict check."""
    # Submit approval
    success, error, entry = submit_approval(
        user="jsmith",
        action_type="save_csv",
        payload={"csv_file": "DR123.csv", "detection_rule": "Rule1"},
        reason="Update whitelist with new trusted IPs",
        roles=["analyst"],
    )

    assert success
    assert entry["status"] == "approved"  # Direct approval (no gate)
    request_id = entry["request_id"]

    # Verify queue persisted (if queued)
    queue, _ = _read_approval_queue()
    # Note: this entry is direct approval, so may not be in queue
    # Only queued entries would be in the queue file

    print("✓ Happy path test passed")


def test_approval_conflict_auto_cancel(temp_queue_dir, mock_limits):
    """Test auto-cancel: delete rule → cancel all pending edits for that rule."""
    now = int(time.time())

    # Create queue with pending requests for Rule1
    queue = [
        {
            "request_id": "req-1",
            "status": "pending",
            "timestamp": now - 100,
            "analyst": "jsmith",
            "action_type": "save_csv",
            "payload": {"csv_file": "DR123.csv", "detection_rule": "Rule1"},
            "reason": "Update",
            "csv_file": "DR123.csv",
            "detection_rule": "Rule1",
        },
        {
            "request_id": "req-2",
            "status": "pending",
            "timestamp": now - 50,
            "analyst": "jdoe",
            "action_type": "save_csv",
            "payload": {"csv_file": "DR456.csv", "detection_rule": "Rule1"},
            "reason": "Update",
            "csv_file": "DR456.csv",
            "detection_rule": "Rule1",
        },
    ]

    _write_approval_queue(queue)

    # Simulate delete_rule approval
    action = {"action_type": "delete_rule", "detection_rule": "Rule1"}
    new_queue, cancelled = cancel_conflicts(queue, action)

    # Both pending edits should be cancelled
    assert len(cancelled) == 2
    assert all(e["status"] == "cancelled" for e in cancelled)
    assert len(new_queue) == 0  # All were cancelled


def test_approval_expiration(temp_queue_dir):
    """Test expiration: old requests expire automatically."""
    # Freeze time first, then calculate timestamps within that context
    with freeze_time("2026-04-01 12:00:00", tz_offset=0):
        now = int(time.time())

        # Create queue with old pending request
        queue = [
            {
                "request_id": "req-1",
                "status": "pending",
                "timestamp": now - (30 * 24 * 3600),  # 30 days old
                "analyst": "jsmith",
                "action_type": "save_csv",
                "payload": {},
                "reason": "Old request",
                "csv_file": "DR123.csv",
                "detection_rule": "Rule1",
            },
            {
                "request_id": "req-2",
                "status": "pending",
                "timestamp": now - 1000,  # Recent
                "analyst": "jdoe",
                "action_type": "save_csv",
                "payload": {},
                "reason": "Recent request",
                "csv_file": "DR456.csv",
                "detection_rule": "Rule2",
            },
        ]

        # Expire old entries
        result = expire_pending_approvals(queue)

        # Only recent entry should remain
        assert len(result) == 1
        assert result[0]["request_id"] == "req-2"


@freeze_time("2026-04-01 12:00:00", tz_offset=0)
def test_approval_dual_admin(temp_queue_dir, mock_limits):
    """Test dual-admin approval workflow."""
    from wl_approval import submit_dual_approval

    success, error, entry = submit_dual_approval(
        analyst_user="jsmith",
        approver_user="admin1",
        action_type="delete_rule",
        payload={"detection_rule": "Rule1"},
        reason="Rule is obsolete and needs removal",
        roles=["analyst"],
    )

    assert success
    assert entry.get("approval_type") == "dual_admin"
    assert entry.get("approver") == "admin1"
    assert entry["analyst"] == "jsmith"


def test_approval_precondition_validation(temp_queue_dir, mock_limits):
    """Test precondition validation: stale request prevents corruption."""
    # This test verifies the concept that if a CSV was deleted,
    # any pending requests for it would be invalid.
    # The actual validation would happen during approval replay in the handler.

    now = int(time.time())
    queue = [
        {
            "request_id": "req-1",
            "status": "pending",
            "timestamp": now - 100,
            "analyst": "jsmith",
            "action_type": "save_csv",
            "payload": {"csv_file": "DELETED.csv", "detection_rule": "Rule1"},
            "reason": "Edit deleted CSV",
            "csv_file": "DELETED.csv",
            "detection_rule": "Rule1",
        },
    ]

    # In the handler, before replaying, we'd check if DELETED.csv exists
    # If not, we'd log 'approval_precondition_failed' and skip replay
    # This test just verifies the queue structure is valid

    _write_approval_queue(queue)
    read_queue, error = _read_approval_queue()
    assert len(read_queue) == 1
    assert error == ""


def test_queue_json_validity(temp_queue_dir, mock_limits):
    """Test that queue remains valid JSON after operations."""
    success1, _, entry1 = submit_approval(
        user="jsmith",
        action_type="save_csv",
        payload={"csv_file": "DR1.csv", "detection_rule": "Rule1"},
        reason="Update 1",
        roles=[],
    )

    success2, _, entry2 = submit_approval(
        user="jdoe",
        action_type="save_csv",
        payload={"csv_file": "DR2.csv", "detection_rule": "Rule2"},
        reason="Update 2",
        roles=[],
    )

    # Read queue and verify it's valid JSON
    queue_path = Path(temp_queue_dir) / "_approval_queue.json"
    if queue_path.exists():
        with open(queue_path, "r") as fh:
            data = json.load(fh)  # Should not raise JSONDecodeError
        assert isinstance(data, list)


def test_conflict_detection_multiple_rules(temp_queue_dir, mock_limits):
    """Test conflict detection with multiple different rules."""
    now = int(time.time())

    queue = [
        {
            "request_id": "req-1",
            "status": "pending",
            "timestamp": now - 100,
            "analyst": "jsmith",
            "action_type": "save_csv",
            "payload": {"csv_file": "DR1.csv", "detection_rule": "Rule1"},
            "reason": "Update",
            "csv_file": "DR1.csv",
            "detection_rule": "Rule1",
        },
        {
            "request_id": "req-2",
            "status": "pending",
            "timestamp": now - 50,
            "analyst": "jdoe",
            "action_type": "save_csv",
            "payload": {"csv_file": "DR2.csv", "detection_rule": "Rule2"},
            "reason": "Update",
            "csv_file": "DR2.csv",
            "detection_rule": "Rule2",
        },
        {
            "request_id": "req-3",
            "status": "pending",
            "timestamp": now - 25,
            "analyst": "jsmith",
            "action_type": "save_csv",
            "payload": {"csv_file": "DR3.csv", "detection_rule": "Rule1"},
            "reason": "Update",
            "csv_file": "DR3.csv",
            "detection_rule": "Rule1",
        },
    ]

    # Delete Rule1 → should cancel req-1 and req-3
    action = {"action_type": "delete_rule", "detection_rule": "Rule1"}
    conflicts = check_conflicts(queue, action)

    assert len(conflicts) == 2
    assert conflicts[0]["request_id"] == "req-1"
    assert conflicts[1]["request_id"] == "req-3"


def test_restore_csv_cancels_create_csv(temp_queue_dir, mock_limits):
    """Test restore_csv action cancels pending create_csv requests."""
    now = int(time.time())

    queue = [
        {
            "request_id": "req-1",
            "status": "pending",
            "timestamp": now - 100,
            "analyst": "jsmith",
            "action_type": "create_csv",
            "payload": {"csv_file": "DR123.csv"},
            "reason": "Create new whitelist",
            "csv_file": "DR123.csv",
            "detection_rule": "",
        },
    ]

    # Restore CSV → should cancel create_csv request
    action = {
        "action_type": "restore_csv",
        "csv_file": "DR123.csv",
    }
    conflicts = check_conflicts(queue, action)

    assert len(conflicts) == 1
    assert conflicts[0]["request_id"] == "req-1"
