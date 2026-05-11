"""
Regression test for R6-F3 — admin usage_reset increment gate.

R6-F3 (Ring 6 Day 2 bonus audit, build 650, 2026-05-11) is the
sibling finding of R6-F2: the increment gate for the admin
``usage_reset`` daily counter checked ``body.get("success")``,
but ``_reset_daily_usage_action`` returns ``{"message": "..."}``
on success — no ``success`` field. The gate never fired, so the
admin ``usage_reset`` daily rate-limit was silently unenforced.

Surfaced by a structured audit of every
``_increment_admin_daily_limit`` call site after R6-F2 was fixed.
Same root cause, same fix pattern: gate on ``status == 200 AND
not body.get("error")``.

This test pins the gate against the response contract that
``_reset_daily_usage_action`` actually emits:
  - 200 + ``{message}``        → increment (normal success path)
  - 200 + ``{message}`` (n/a)  → increment (no-usage-to-reset path)
  - 200 + ``{error}`` (block)  → no increment (self-reset block)
  - non-admin caller            → no increment (superadmin exempt)
  - non-200                     → no increment

If anyone later "simplifies" the gate back to checking
``success``, all four positive cases regress to no-increment and
this test fails immediately.
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
    return {
        "status": status,
        "headers": {"Content-Type": "application/json"},
        "payload": json.dumps(body),
    }


@pytest.fixture
def handler():
    return WhitelistHandler(command_line=None, command_arg=None)


@contextlib.contextmanager
def _patched_reset_gate(handler, inner_result, *, is_superadmin=False,
                          roles=("wl_admin",)):
    with patch.object(handler, "_reset_daily_usage_action",
                       return_value=inner_result), \
         patch("wl_handler.is_admin", return_value=True), \
         patch("wl_handler.is_superadmin",
                return_value=is_superadmin), \
         patch("wl_handler._check_admin_permission", return_value=True), \
         patch("wl_handler._check_admin_daily_limit",
                return_value=(True, 0, 100)), \
         patch("wl_handler._increment_admin_daily_limit") as mock_inc:
        yield mock_inc


def _exercise(handler, inner_result, **kwargs):
    """Drive _action_reset_daily_usage with a mocked inner result."""
    with _patched_reset_gate(handler, inner_result, **kwargs) as mock_inc:
        # The action expects (request, payload, user, roles).
        # request is unused on the success path; minimal dict.
        handler._action_reset_daily_usage(
            request={"session": {"authtoken": "t"}},
            payload={"analyst": "analyst1"},
            user="wladmin1",
            roles=["wl_admin"],
        )
        return mock_inc


# ── Cases where the gate SHOULD fire ───────────────────────────────────

def test_message_only_response_increments(handler):
    """Canonical success: ``{message: ...}`` with no error field.
    Pre-fix the gate checked ``body.get('success')`` which was
    undefined → gate never fired."""
    inner = _resp(200, {"message": "Daily usage reset for analyst1"})
    mock = _exercise(handler, inner)
    mock.assert_called_once_with("wladmin1", "usage_reset")


def test_no_usage_to_reset_response_increments(handler):
    """Even when the target had no counters, the admin still
    performed the reset action and consumes the daily slot.
    Body is ``{message: 'No usage to reset.'}`` (no error)."""
    inner = _resp(200, {"message": "No usage to reset."})
    mock = _exercise(handler, inner)
    mock.assert_called_once_with("wladmin1", "usage_reset")


# ── Cases where the gate SHOULD NOT fire ───────────────────────────────

def test_self_reset_block_no_increment(handler):
    """Self-reset is blocked at the inner with a 200 + error
    envelope. The admin attempted to reset their own counters,
    which is the very abuse pattern the rate-limit was added to
    deter — do NOT consume their daily slot for a blocked attempt.
    """
    inner = _resp(200, {
        "error": "Cannot reset your own daily usage. "
                 "Ask another admin or superadmin."
    })
    mock = _exercise(handler, inner)
    mock.assert_not_called()


def test_superadmin_no_increment(handler):
    """Superadmins are exempt from admin daily limits. The gate
    short-circuits before even reading the body."""
    inner = _resp(200, {"message": "Daily usage reset for analyst1"})
    mock = _exercise(handler, inner, is_superadmin=True,
                       roles=("wl_superadmin",))
    mock.assert_not_called()


def test_non_200_no_increment(handler):
    """If the inner returned 4xx/5xx (validation error, missing
    payload, etc.), do not charge the admin's daily slot — the
    intended action never executed."""
    inner = _resp(400, {"error": "Bad payload"})
    mock = _exercise(handler, inner)
    mock.assert_not_called()
