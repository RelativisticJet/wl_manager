"""
Tests for `project_pending_info` — the queue-entry shape that
`_get_csv_content` and `_action_get_pending_approvals` send to the
WM frontend.

Origin: build 641 (2026-05-07). The WM approval banner displayed
"<action> by <analyst> —" with no reason text for column_removal /
remove_csv / remove_rule requests because the projection dropped
the queue entry's `comment` field on the way to the frontend, while
the auto-generated `description` field is empty for those action
types. The frontend code at `wl_approval_ui.js:405` reads
`pa.comment || pa.description || ""`, so both falsy → blank banner.

The Control Panel was unaffected because it uses the
`get_approval_queue` action which returns the queue verbatim with
no projection.

These tests pin the projection's contract so the regression cannot
silently re-occur if someone adds another endpoint that constructs
a similar shape inline.
"""

import os
import sys

import pytest

_BIN = os.path.join(os.path.dirname(__file__), "..", "..", "bin")
sys.path.insert(0, os.path.abspath(_BIN))

from wl_approval import project_pending_info  # noqa: E402


@pytest.fixture
def column_removal_entry():
    """Realistic queue entry for an analyst-submitted column_removal.

    Auto-`description` is empty (handler convention for this
    action type). The free-form analyst reason lives in `comment`.
    """
    return {
        "request_id": "68d12bbb-8f37-4106-84d9-a5d34bd87a92",
        "timestamp": 1778025844,
        "analyst": "analyst1",
        "csv_file": "DR130_priv_escalation.csv",
        "app_context": "wl_manager",
        "detection_rule": "DR130_privilege_escalation",
        "action_type": "column_removal",
        "description": "",
        "comment": "Field deprecated by GRC team",
        "status": "pending",
        "payload": {},
        "expected_mtime": None,
        "pending_highlight": {},
        "resolved_by": None,
        "resolved_at": None,
        "rejection_reason": None,
    }


def test_column_removal_comment_propagates(column_removal_entry):
    """The build-641 regression: `comment` must reach the frontend.

    If this test fails the WM banner will render "column removal by
    analyst1 —" with nothing after the dash.
    """
    out = project_pending_info(column_removal_entry, has_edit=True)
    assert out["comment"] == "Field deprecated by GRC team"
    assert "comment" in out


def test_missing_comment_yields_empty_string(column_removal_entry):
    """Resilience: queue entries written by older app versions may
    not have a `comment` field at all. Projection must default to
    empty string rather than KeyError or None (the frontend's
    `||` short-circuit treats both empty string and undefined as
    falsy, which is the desired behavior)."""
    del column_removal_entry["comment"]
    out = project_pending_info(column_removal_entry, has_edit=True)
    assert out["comment"] == ""


def test_required_fields_always_present(column_removal_entry):
    """Pin the eight contract fields the frontend banner consumes.

    Adding fields is fine; removing one breaks the WM page silently
    (no JS error, just a missing banner element)."""
    out = project_pending_info(column_removal_entry, has_edit=True)
    expected = {
        "request_id", "action_type", "description", "comment",
        "analyst", "timestamp", "pending_highlight", "payload",
    }
    assert set(out.keys()) == expected


def test_non_editor_cannot_see_payload(column_removal_entry):
    """RBAC contract: non-editors get who/when/what but not the
    row-level highlight or payload (which can carry CSV row content
    that the requester is asking to add/remove)."""
    column_removal_entry["payload"] = {"sensitive_row_data": "secret"}
    column_removal_entry["pending_highlight"] = {"row_keys": ["a"]}
    out = project_pending_info(column_removal_entry, has_edit=False)
    assert out["payload"] == {}
    assert out["pending_highlight"] == {}
    # But the public fields still flow through
    assert out["analyst"] == "analyst1"
    assert out["comment"] == "Field deprecated by GRC team"


def test_editor_sees_payload_and_highlight(column_removal_entry):
    """Symmetric check: editor view exposes payload + highlight."""
    column_removal_entry["payload"] = {"col": "ticket_id"}
    column_removal_entry["pending_highlight"] = {"col": "ticket_id"}
    out = project_pending_info(column_removal_entry, has_edit=True)
    assert out["payload"] == {"col": "ticket_id"}
    assert out["pending_highlight"] == {"col": "ticket_id"}


@pytest.mark.parametrize("action_type", [
    "column_removal", "remove_csv", "remove_rule",
    "bulk_row_removal", "bulk_row_addition", "revert",
    "csv_import_replace", "bulk_row_edit",
    "create_csv", "create_rule",
])
def test_comment_propagates_for_all_action_types(
        column_removal_entry, action_type):
    """The `comment` projection must work for every action type the
    frontend banner can render."""
    column_removal_entry["action_type"] = action_type
    out = project_pending_info(column_removal_entry, has_edit=True)
    assert out["comment"] == "Field deprecated by GRC team"
    assert out["action_type"] == action_type
