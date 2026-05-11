"""
Regression test for R6-F2 — admin approval_count increment gate.

The R6-F2 finding (Ring 6 Day 2, build 649, 2026-05-11) discovered
that ``_process_approval`` checked ``resp_body.get("success")`` to
decide whether to increment the admin daily-limit counter. But the
canonical approve return body in ``_process_approval_inner`` is
``{message, request_id, diff}`` — no ``success`` field. Only the
inline ``bulk_row_edit`` path (which returns the ``_save_csv``
result directly) carried ``success: true``. So the admin
``approval_count`` daily rate-limit was silently unenforced for
every approve action type except inline bulk_row_edit.

Verified live: ``wladmin1`` had 39 ``request_approved`` events in
30 days while ``_daily_limits.json`` did not exist in the container
at all. The defense-in-depth control against a compromised admin
rubber-stamping queued requests was broken.

Fix: gate on ``status == 200 and not resp_body.get("error")``
instead of ``resp_body.get("success")``. Matches the response
contract used by every approve-success path on the inner side and
by ``_fail_approval_request``'s status_code/error envelope on the
failure side.

This test pins the gate so we never silently regress. It mocks
``_process_approval_inner`` to return each shape (canonical 200
approve, 200 with success:true, 200 with error, 4xx) and verifies
``_increment_admin_daily_limit`` was called iff the gate should
fire.
"""

import contextlib
import json
import os
import sys
from unittest.mock import patch, MagicMock

import pytest

_BIN = os.path.join(os.path.dirname(__file__), "..", "..", "bin")
sys.path.insert(0, os.path.abspath(_BIN))

from wl_handler import WhitelistHandler  # noqa: E402


def _resp(status, body):
    """Mirror WhitelistHandler._resp output shape."""
    return {
        "status": status,
        "headers": {"Content-Type": "application/json"},
        "payload": json.dumps(body),
    }


@pytest.fixture
def handler():
    return WhitelistHandler(command_line=None, command_arg=None)


@pytest.fixture
def admin_request():
    return {"session": {"authtoken": "test-token"}}


@contextlib.contextmanager
def _patched_gate(handler, inner_result, *, is_superadmin=False,
                   roles=("wl_admin",)):
    """Context manager that mocks every external touchpoint of
    _process_approval except the gate logic itself. Yields the
    _increment_admin_daily_limit mock so the test can assert calls."""
    lock_mock = MagicMock()
    lock_mock.__enter__ = lambda *_: None
    lock_mock.__exit__ = lambda *_: None
    with patch.object(handler, "_process_approval_inner",
                       return_value=inner_result), \
         patch("wl_handler._approval_queue_lock",
                return_value=lock_mock), \
         patch("wl_handler.get_roles", return_value=list(roles)), \
         patch("wl_handler.is_admin", return_value=True), \
         patch("wl_handler.is_superadmin",
                return_value=is_superadmin), \
         patch("wl_handler._increment_admin_daily_limit") as mock_inc:
        yield mock_inc


def _exercise_gate(handler, admin_request, payload, inner_result):
    """Run _process_approval against a mocked inner result. Returns
    the _increment_admin_daily_limit mock for assertion."""
    with _patched_gate(handler, inner_result) as mock_inc:
        handler._process_approval(admin_request, payload, "wladmin1")
        return mock_inc


# ── Cases where the gate SHOULD fire ────────────────────────────────────

def test_canonical_approve_response_increments(handler, admin_request):
    """The canonical bulk_row_removal/column_removal/etc. approve
    return body is ``{message, request_id, diff}`` — no ``success``
    field. The PRE-FIX code missed this and never incremented.
    Post-fix, the gate fires on status=200 + no error field."""
    inner = _resp(200, {
        "message": "Request approved and executed.",
        "request_id": "abc-123",
        "diff": {"added_count": 0, "removed_count": 1},
    })
    mock = _exercise_gate(handler, admin_request,
                           {"decision": "approve"}, inner)
    mock.assert_called_once_with("wladmin1", "approval_count")


def test_inline_bulk_row_edit_response_increments(handler, admin_request):
    """The inline bulk_row_edit path returns the _save_csv result
    directly. Pre-fix this was the ONLY path that incremented; the
    fix must preserve that behaviour."""
    inner = _resp(200, {
        "success": True,
        "diff": {"edited_count": 3},
    })
    mock = _exercise_gate(handler, admin_request,
                           {"decision": "approve"}, inner)
    mock.assert_called_once_with("wladmin1", "approval_count")


# ── Cases where the gate SHOULD NOT fire ────────────────────────────────

def test_inner_returns_error_no_increment(handler, admin_request):
    """If the replay failed, the inner returns a body with ``error``
    set. The counter must not move."""
    inner = _resp(200, {"error": "Locked rows no longer found"})
    mock = _exercise_gate(handler, admin_request,
                           {"decision": "approve"}, inner)
    mock.assert_not_called()


def test_inner_4xx_no_increment(handler, admin_request):
    """A 4xx status from the inner means the request was malformed
    or the action type was unknown. Counter must not move."""
    inner = _resp(400, {"error": "Unknown approval action type"})
    mock = _exercise_gate(handler, admin_request,
                           {"decision": "approve"}, inner)
    mock.assert_not_called()


def test_reject_decision_no_increment(handler, admin_request):
    """The counter only applies to approves. Reject must not charge
    the admin's approval_count."""
    inner = _resp(200, {"message": "Request rejected.",
                         "request_id": "abc-123"})
    mock = _exercise_gate(handler, admin_request,
                           {"decision": "reject"}, inner)
    mock.assert_not_called()


def test_cancel_decision_no_increment(handler, admin_request):
    """Same as reject — cancels don't charge approval_count."""
    inner = _resp(200, {"message": "Request cancelled.",
                         "request_id": "abc-123"})
    mock = _exercise_gate(handler, admin_request,
                           {"decision": "cancel"}, inner)
    mock.assert_not_called()


# ── Role-tier asymmetry ─────────────────────────────────────────────────

def test_superadmin_approve_no_increment(handler, admin_request):
    """Superadmins are exempt from the admin daily limit — they ARE
    the policy. The increment must not fire even for canonical 200
    approve responses when the caller is superadmin."""
    inner = _resp(200, {
        "message": "Request approved and executed.",
        "request_id": "abc-123",
    })
    with _patched_gate(handler, inner, is_superadmin=True,
                        roles=("wl_superadmin",)) as mock_inc:
        handler._process_approval(admin_request,
                                    {"decision": "approve"},
                                    "superadmin1")
    mock_inc.assert_not_called()
