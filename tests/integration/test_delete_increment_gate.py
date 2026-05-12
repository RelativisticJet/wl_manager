"""
Regression test for R6-F4 — admin rule_deletion + csv_deletion
counter gate.

R6-F4 (Ring 6 Day 3 bonus, build 651, 2026-05-12) found that the
admin `rule_deletion` and `csv_deletion` daily-rate-limit counters
were silently NOT incremented for important success paths:

- rule_deletion: the gate at wl_handler.py:2943 was
  `if data.get("trashed"):`. But delete_rule_pipeline sets
  `trashed = True` only when the rule has CSVs AND move_to_trash
  succeeds. For rules with NO CSVs (a common case), the pipeline
  returns `data: {"trashed": False, ...}` even on successful
  permanent delete, so the counter never moved.

- csv_deletion: the gate at wl_handler.py:2820 had the same
  shape. delete_csv_pipeline only sets `trashed = True` when
  move_to_trash succeeds. If move_to_trash raises (line 505-512
  of wl_rules.py), the CSV is still deleted via direct os.remove
  but trashed stays False — counter doesn't fire.

Verified live (Day 3 bonus): 6 of 7 concurrent rule_deletes
landed against a cap of 2, with no limit-rejects, because the
counter never moved past 0.

Fix: gate on `removal_type == "permanent"` instead of
`data.get("trashed")`. This is symmetric with the cap-CHECK
condition above the increment, which already keys off
removal_type. Now any successful permanent delete charges the
admin's daily counter.

Same bug class as R6-F2/F3 (gate condition checks a flag that's
only set in SOME success paths, not all of them). Third
occurrence — this is a copy-paste failure pattern in the
codebase; future increment gates should be code-reviewed
against the canonical pattern.

This test mocks delete_rule_pipeline / delete_csv_pipeline to
return each shape (trashed=True success, trashed=False success,
failure) and verifies the gate fires when it should and skips
when it shouldn't.
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


@pytest.fixture
def handler():
    return WhitelistHandler(command_line=None, command_arg=None)


@pytest.fixture
def admin_payload_rule():
    return {
        "rule_name": "test_rule",
        "removal_type": "permanent",
        "comment": "test cleanup",
    }


@pytest.fixture
def admin_payload_csv():
    return {
        "csv_file": "test.csv",
        "removal_type": "permanent",
        "comment": "test cleanup",
    }


@contextlib.contextmanager
def _patched_rule_delete(handler, *, pipeline_result, roles=("wl_admin",),
                          is_superadmin=False):
    """Patch every external touchpoint of _action_remove_rule
    except the increment-gate logic itself."""
    with patch("wl_handler.delete_rule_pipeline",
                return_value=pipeline_result), \
         patch("wl_handler.validate_ascii_text", return_value=""), \
         patch("wl_handler.is_admin", return_value=True), \
         patch("wl_handler.is_superadmin",
                return_value=is_superadmin), \
         patch("wl_handler._check_admin_daily_limit",
                return_value=(True, 0, 100)), \
         patch.object(handler, "_get_session_key",
                       return_value="test-key"), \
         patch.object(handler, "_read_mapping", return_value=[]), \
         patch.object(handler, "_index_audit"), \
         patch("wl_handler._approval_queue_lock",
                return_value=MagicMock(__enter__=lambda *_: None,
                                        __exit__=lambda *_: None)), \
         patch("wl_handler._read_approval_queue", return_value=[]), \
         patch("wl_handler._cancel_conflicting_requests"), \
         patch("wl_handler._increment_admin_daily_limit") as mock_inc:
        yield mock_inc


@contextlib.contextmanager
def _patched_csv_delete(handler, *, pipeline_result, roles=("wl_admin",),
                         is_superadmin=False):
    with patch("wl_handler.delete_csv_pipeline",
                return_value=pipeline_result), \
         patch("wl_handler.validate_ascii_text", return_value=""), \
         patch("wl_handler.is_admin", return_value=True), \
         patch("wl_handler.is_superadmin",
                return_value=is_superadmin), \
         patch("wl_handler._check_admin_daily_limit",
                return_value=(True, 0, 100)), \
         patch.object(handler, "_get_session_key",
                       return_value="test-key"), \
         patch.object(handler, "_index_audit"), \
         patch("wl_handler._approval_queue_lock",
                return_value=MagicMock(__enter__=lambda *_: None,
                                        __exit__=lambda *_: None)), \
         patch("wl_handler._read_approval_queue", return_value=[]), \
         patch("wl_handler._cancel_conflicting_requests"), \
         patch("wl_handler.resolve_csv_path", return_value=None), \
         patch("wl_handler.remove_csv_expected_hash"), \
         patch("wl_handler._increment_admin_daily_limit") as mock_inc:
        yield mock_inc


# ─── rule_deletion gate ──────────────────────────────────────────────

def test_rule_deletion_empty_csv_increments(handler, admin_payload_rule):
    """The R6-F4 bug case: empty-CSV rule deleted permanently.
    Pipeline returns trashed=False (no CSVs to move). Pre-fix the
    counter never incremented. Post-fix the counter fires on
    removal_type=permanent regardless of the trashed flag."""
    pipeline = {
        "success": True,
        "message": "Rule 'X' removed (had no CSV files)",
        "data": {"affected_csvs": [], "trashed": False, "trash_id": ""},
    }
    with _patched_rule_delete(handler, pipeline_result=pipeline) as mock_inc:
        handler._action_remove_rule(
            request={"session": {"authtoken": "t"}},
            payload=admin_payload_rule,
            user="wladmin1",
            roles={"wl_admin"})
    mock_inc.assert_called_once_with("wladmin1", "rule_deletion")


def test_rule_deletion_with_csvs_increments(handler, admin_payload_rule):
    """Normal case: rule with CSVs deleted permanently, pipeline
    returns trashed=True. Should still increment (preserves the
    pre-fix behaviour for this success path)."""
    pipeline = {
        "success": True,
        "message": "Rule 'X' moved to trash (3 CSV files)",
        "data": {"affected_csvs": ["a.csv", "b.csv", "c.csv"],
                  "trashed": True, "trash_id": "TR_123"},
    }
    with _patched_rule_delete(handler, pipeline_result=pipeline) as mock_inc:
        handler._action_remove_rule(
            request={"session": {"authtoken": "t"}},
            payload=admin_payload_rule,
            user="wladmin1",
            roles={"wl_admin"})
    mock_inc.assert_called_once_with("wladmin1", "rule_deletion")


def test_rule_deletion_unlink_no_increment(handler, admin_payload_rule):
    """Unlink (soft delete) — by design no cap is charged because
    the cap-check above also fires only for removal_type=permanent.
    Symmetric."""
    admin_payload_rule["removal_type"] = "unlink"
    pipeline = {
        "success": True,
        "message": "Rule 'X' unlinked (had no CSV files)",
        "data": {"affected_csvs": [], "trashed": False, "trash_id": ""},
    }
    with _patched_rule_delete(handler, pipeline_result=pipeline) as mock_inc:
        handler._action_remove_rule(
            request={"session": {"authtoken": "t"}},
            payload=admin_payload_rule,
            user="wladmin1",
            roles={"wl_admin"})
    mock_inc.assert_not_called()


def test_rule_deletion_pipeline_failure_no_increment(handler, admin_payload_rule):
    """If the pipeline reports success=False, the handler returns
    404 before reaching the increment block. Counter must not
    move for failed deletes."""
    pipeline = {
        "success": False,
        "error": "Rule 'X' not found in mapping or registry",
        "data": {},
    }
    with _patched_rule_delete(handler, pipeline_result=pipeline) as mock_inc:
        handler._action_remove_rule(
            request={"session": {"authtoken": "t"}},
            payload=admin_payload_rule,
            user="wladmin1",
            roles={"wl_admin"})
    mock_inc.assert_not_called()


def test_rule_deletion_superadmin_no_increment(handler, admin_payload_rule):
    """Superadmins are exempt from admin daily limits."""
    pipeline = {
        "success": True,
        "message": "Rule deleted",
        "data": {"affected_csvs": [], "trashed": False, "trash_id": ""},
    }
    with _patched_rule_delete(handler, pipeline_result=pipeline,
                                is_superadmin=True,
                                roles=("wl_superadmin",)) as mock_inc:
        handler._action_remove_rule(
            request={"session": {"authtoken": "t"}},
            payload=admin_payload_rule,
            user="superadmin1",
            roles={"wl_superadmin"})
    mock_inc.assert_not_called()


# ─── csv_deletion gate ───────────────────────────────────────────────

def test_csv_deletion_trash_failed_increments(handler, admin_payload_csv):
    """The R6-F4 bug case for CSVs: move_to_trash raised, CSV was
    deleted via direct os.remove, pipeline returns trashed=False.
    Pre-fix the counter never incremented. Post-fix it fires on
    removal_type=permanent regardless."""
    pipeline = {
        "success": True,
        "message": "CSV 'X' deleted",
        "data": {"rule_also_removed": False, "trashed": False,
                  "trash_id": ""},
    }
    with _patched_csv_delete(handler, pipeline_result=pipeline) as mock_inc:
        handler._action_remove_csv(
            request={"session": {"authtoken": "t"}},
            payload=admin_payload_csv,
            user="wladmin1",
            roles={"wl_admin"})
    mock_inc.assert_called_once_with("wladmin1", "csv_deletion")


def test_csv_deletion_trashed_increments(handler, admin_payload_csv):
    """Normal case: CSV moved to trash. Should still increment."""
    pipeline = {
        "success": True,
        "message": "CSV moved to trash",
        "data": {"rule_also_removed": False, "trashed": True,
                  "trash_id": "TR_456"},
    }
    with _patched_csv_delete(handler, pipeline_result=pipeline) as mock_inc:
        handler._action_remove_csv(
            request={"session": {"authtoken": "t"}},
            payload=admin_payload_csv,
            user="wladmin1",
            roles={"wl_admin"})
    mock_inc.assert_called_once_with("wladmin1", "csv_deletion")


def test_csv_deletion_unlink_no_increment(handler, admin_payload_csv):
    """Unlink (soft delete) for CSV — same exemption as for rules."""
    admin_payload_csv["removal_type"] = "unlink"
    pipeline = {
        "success": True,
        "message": "CSV unlinked",
        "data": {"rule_also_removed": False, "trashed": False,
                  "trash_id": ""},
    }
    with _patched_csv_delete(handler, pipeline_result=pipeline) as mock_inc:
        handler._action_remove_csv(
            request={"session": {"authtoken": "t"}},
            payload=admin_payload_csv,
            user="wladmin1",
            roles={"wl_admin"})
    mock_inc.assert_not_called()
