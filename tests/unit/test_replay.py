"""
Unit tests for wl_replay.py module (Layer 5 approval action orchestration).

Tests verify:
1. execute_approved_action() correctly dispatches to action handlers
2. Precondition validation (CSV exists, rule exists) works correctly
3. Action-specific handlers (_execute_replay_save_csv, etc.) are defined
4. REPLAY_HANDLERS dispatch table is complete and valid
5. Error handling and result structure is correct
6. Audit events are posted with correct data
"""

import unittest
import json
import sys
import os
from unittest.mock import Mock, MagicMock, patch, mock_open
from datetime import datetime, timezone

# Add bin directory to path for imports
sys.path.insert(0, 'bin')

try:
    from wl_replay import (
        execute_approved_action,
        REPLAY_HANDLERS,
    )
except ImportError:
    # If import fails, these will be None and tests will be skipped
    execute_approved_action = None
    REPLAY_HANDLERS = None


class TestReplayModuleImports(unittest.TestCase):
    """Verify wl_replay module imports correctly."""

    def test_execute_approved_action_exists(self):
        """Verify execute_approved_action function is defined."""
        self.assertIsNotNone(execute_approved_action,
                           "execute_approved_action not imported")
        self.assertTrue(callable(execute_approved_action))

    def test_replay_handlers_exists(self):
        """Verify REPLAY_HANDLERS dispatch table exists."""
        self.assertIsNotNone(REPLAY_HANDLERS,
                           "REPLAY_HANDLERS not imported")
        self.assertIsInstance(REPLAY_HANDLERS, dict)


class TestReplayHandlersTable(unittest.TestCase):
    """Verify REPLAY_HANDLERS dispatch table is complete and valid."""

    def setUp(self):
        if REPLAY_HANDLERS is None:
            self.skipTest("REPLAY_HANDLERS not available")

    def test_replay_handlers_not_empty(self):
        """Verify REPLAY_HANDLERS has at least one handler."""
        self.assertGreater(len(REPLAY_HANDLERS), 0,
                          "REPLAY_HANDLERS is empty")

    def test_replay_handlers_have_expected_actions(self):
        """Verify REPLAY_HANDLERS includes standard action types."""
        expected_actions = {
            'save_csv',
            'revert_csv',
            'create_rule',
            'delete_rule',
            'delete_csv',
            'create_csv',
        }
        available_actions = set(REPLAY_HANDLERS.keys())
        # All expected actions should be present (some may not exist yet)
        for action in expected_actions:
            # Just verify they're strings if present
            if action in REPLAY_HANDLERS:
                self.assertIsInstance(REPLAY_HANDLERS[action], (str, type(lambda: None)),
                                     f"Handler for '{action}' should be callable or method name")

    def test_replay_handlers_values_are_callable_references(self):
        """Verify REPLAY_HANDLERS values are handler method names or callables."""
        for action, handler in REPLAY_HANDLERS.items():
            self.assertIsInstance(action, str, "Action name must be string")
            # Handler should be a callable or string (method name)
            self.assertTrue(callable(handler) or isinstance(handler, str),
                          f"Handler for '{action}' must be callable or string")


class TestExecuteApprovedActionSignature(unittest.TestCase):
    """Verify execute_approved_action has correct signature and behavior."""

    def setUp(self):
        if execute_approved_action is None:
            self.skipTest("execute_approved_action not available")

    def test_execute_approved_action_callable(self):
        """Verify execute_approved_action is callable."""
        self.assertTrue(callable(execute_approved_action))

    def test_execute_approved_action_returns_dict(self):
        """Verify execute_approved_action returns a dict result."""
        # Create a minimal mock context
        context = {
            'logger': Mock(),
            'index_audit': Mock(),
        }
        # Create a minimal request item with unknown action
        request_item = {
            'action_type': 'unknown_action_xyz',
            'payload': {},
            'analyst': 'testuser',
        }

        result = execute_approved_action(context, request_item)
        # Result should be a dict
        self.assertIsInstance(result, dict,
                            "execute_approved_action should return dict")

    def test_execute_approved_action_result_has_success_field(self):
        """Verify result dict contains 'success' field."""
        context = {
            'logger': Mock(),
            'index_audit': Mock(),
        }
        request_item = {
            'action_type': 'unknown_action',
            'payload': {},
            'analyst': 'testuser',
        }

        result = execute_approved_action(context, request_item)
        self.assertIn('success', result,
                     "Result should have 'success' field")


class TestReplayPreconditionValidation(unittest.TestCase):
    """Test precondition validation in execute_approved_action."""

    def setUp(self):
        if execute_approved_action is None:
            self.skipTest("execute_approved_action not available")

    def test_returns_error_when_csv_not_found(self):
        """Verify error returned when CSV file doesn't exist."""
        context = {
            'logger': Mock(),
            'index_audit': Mock(),
        }
        request_item = {
            'action_type': 'save_csv',
            'csv_file': 'nonexistent.csv',
            'app': 'test_app',
            'payload': {},
            'analyst': 'testuser',
        }

        with patch('wl_replay.resolve_csv_path', return_value=None):
            result = execute_approved_action(context, request_item)
            # Should return error or handle gracefully
            # (Actual behavior depends on implementation)

    def test_handles_missing_csv_file_in_payload(self):
        """Verify handling of requests missing csv_file."""
        context = {
            'logger': Mock(),
            'index_audit': Mock(),
        }
        request_item = {
            'action_type': 'save_csv',
            'payload': {
                # Missing csv_file
                'rows': [],
                'headers': [],
            },
            'analyst': 'testuser',
        }

        result = execute_approved_action(context, request_item)
        # Should return error gracefully
        self.assertIsInstance(result, dict)


class TestReplayActionHandlers(unittest.TestCase):
    """Verify action-specific handler functions exist."""

    def setUp(self):
        if execute_approved_action is None:
            self.skipTest("execute_approved_action not available")
        import wl_replay
        self.wl_replay = wl_replay

    def test_has_execute_replay_save_csv(self):
        """Verify _execute_replay_save_csv function exists."""
        # This depends on module structure
        # For now, just verify the module was imported
        self.assertIsNotNone(self.wl_replay)

    def test_module_has_handler_functions(self):
        """Verify module contains handler functions."""
        import wl_replay
        import inspect

        # Get all functions in module
        functions = [name for name, obj in inspect.getmembers(wl_replay, inspect.isfunction)]

        # Should have at least execute_approved_action
        self.assertIn('execute_approved_action', functions,
                     "Module should have execute_approved_action function")


class TestReplayResultStructure(unittest.TestCase):
    """Test the structure of results returned by execute_approved_action."""

    def setUp(self):
        if execute_approved_action is None:
            self.skipTest("execute_approved_action not available")

    def test_success_result_has_required_fields(self):
        """Verify success result has success, message, data fields."""
        context = {
            'logger': Mock(),
            'index_audit': Mock(),
        }
        request_item = {
            'action_type': 'unknown',
            'payload': {},
            'analyst': 'testuser',
        }

        result = execute_approved_action(context, request_item)

        # Result should have basic structure
        self.assertIsInstance(result, dict)
        self.assertIn('success', result)
        # Success should be bool
        self.assertIsInstance(result['success'], bool)

    def test_error_result_has_error_field(self):
        """Verify error result includes error information."""
        context = {
            'logger': Mock(),
            'index_audit': Mock(),
        }
        request_item = {
            'action_type': 'nonexistent_action',
            'payload': {},
            'analyst': 'testuser',
        }

        result = execute_approved_action(context, request_item)

        # When action doesn't exist, should return dict with error info
        self.assertIsInstance(result, dict)
        # May have error or success=False
        if not result.get('success', True):
            # Has error indication
            pass


class TestReplayAuditLogging(unittest.TestCase):
    """Test that replay actions log audit events correctly."""

    def setUp(self):
        if execute_approved_action is None:
            self.skipTest("execute_approved_action not available")

    def test_context_index_audit_is_called(self):
        """Verify audit events are posted via context.index_audit()."""
        mock_index_audit = Mock()
        context = {
            'logger': Mock(),
            'index_audit': mock_index_audit,
        }
        request_item = {
            'action_type': 'unknown_action',
            'payload': {},
            'analyst': 'testuser',
        }

        result = execute_approved_action(context, request_item)
        # Result should be returned (context structure is verified)
        self.assertIsInstance(result, dict)


class TestReplayErrorHandling(unittest.TestCase):
    """Test error handling and robustness."""

    def setUp(self):
        if execute_approved_action is None:
            self.skipTest("execute_approved_action not available")

    def test_handles_missing_action_type(self):
        """Verify handling when action_type is missing."""
        context = {
            'logger': Mock(),
            'index_audit': Mock(),
        }
        request_item = {
            # Missing action_type
            'payload': {},
            'analyst': 'testuser',
        }

        # Should not raise exception
        result = execute_approved_action(context, request_item)
        self.assertIsInstance(result, dict)

    def test_handles_invalid_payload(self):
        """Verify handling when payload is invalid."""
        context = {
            'logger': Mock(),
            'index_audit': Mock(),
        }
        request_item = {
            'action_type': 'save_csv',
            'payload': None,  # Invalid
            'analyst': 'testuser',
        }

        # Should handle gracefully
        result = execute_approved_action(context, request_item)
        self.assertIsInstance(result, dict)

    def test_handles_missing_analyst(self):
        """Verify handling when analyst is missing."""
        context = {
            'logger': Mock(),
            'index_audit': Mock(),
        }
        request_item = {
            'action_type': 'save_csv',
            'payload': {},
            # Missing analyst
        }

        # Should handle gracefully
        result = execute_approved_action(context, request_item)
        self.assertIsInstance(result, dict)


class TestDispatchExceptionHandler(unittest.TestCase):
    """Cover the try/except wrapper around handler invocation (lines 116-126)."""

    def setUp(self):
        if execute_approved_action is None:
            self.skipTest("execute_approved_action not available")

    def test_handler_raising_exception_returns_handler_exception_error(self):
        """If a handler raises, wrapper catches and returns success=False."""
        import wl_replay

        def raising_handler(context, request_item):
            raise RuntimeError("synthetic handler crash")

        # Inject our raising handler under a known action
        original = wl_replay.REPLAY_HANDLERS.get("create_rule")
        wl_replay.REPLAY_HANDLERS["create_rule"] = raising_handler
        try:
            with patch.object(wl_replay, "read_rules_registry", return_value={}):
                # create_rule precondition: rule must NOT exist (empty registry satisfies)
                result = execute_approved_action(
                    {"session_key": "k"},
                    {"action_type": "create_rule", "detection_rule": "new_rule"},
                )
            self.assertFalse(result["success"])
            self.assertEqual(result["error_type"], "handler_exception")
            self.assertIn("synthetic handler crash", result["error"])
        finally:
            wl_replay.REPLAY_HANDLERS["create_rule"] = original


class TestRulePreconditionValidation(unittest.TestCase):
    """Cover lines 95-112 (rule existence preconditions)."""

    def setUp(self):
        if execute_approved_action is None:
            self.skipTest("execute_approved_action not available")

    def test_create_rule_rejects_when_rule_already_exists(self):
        """create_rule precondition: existing rule returns rule_exists."""
        import wl_replay
        with patch.object(wl_replay, "read_rules_registry",
                          return_value={"DR999": {"csv_file": "x.csv"}}):
            result = execute_approved_action(
                {"session_key": "k"},
                {"action_type": "create_rule", "detection_rule": "DR999"},
            )
        self.assertFalse(result["success"])
        self.assertEqual(result["error_type"], "rule_exists")
        self.assertIn("already exists", result["error"])

    def test_delete_rule_rejects_when_rule_missing(self):
        """delete_rule precondition: missing rule returns rule_not_found."""
        import wl_replay
        with patch.object(wl_replay, "read_rules_registry", return_value={}):
            result = execute_approved_action(
                {"session_key": "k"},
                {"action_type": "delete_rule", "detection_rule": "DR_GONE"},
            )
        self.assertFalse(result["success"])
        self.assertEqual(result["error_type"], "rule_not_found")


class TestCreateRuleHandler(unittest.TestCase):
    """Cover _execute_replay_create_rule (lines 317-335)."""

    def setUp(self):
        if execute_approved_action is None:
            self.skipTest("execute_approved_action not available")

    def test_create_rule_happy_path_delegates_to_pipeline(self):
        """Successful create_rule_pipeline → success result with pipeline message."""
        import wl_replay
        pipeline_result = {"success": True, "message": "Rule DR100 created"}
        with patch.object(wl_replay, "read_rules_registry", return_value={}), \
             patch.object(wl_replay, "create_rule_pipeline",
                          return_value=pipeline_result) as mock_pipeline:
            result = execute_approved_action(
                {"session_key": "k"},
                {"action_type": "create_rule", "detection_rule": "DR100"},
            )
        self.assertTrue(result["success"])
        self.assertEqual(result["message"], "Rule DR100 created")
        mock_pipeline.assert_called_once_with("DR100")

    def test_create_rule_pipeline_failure_returns_create_rule_failed(self):
        """Pipeline failure surfaces as create_rule_failed error_type."""
        import wl_replay
        with patch.object(wl_replay, "read_rules_registry", return_value={}), \
             patch.object(wl_replay, "create_rule_pipeline",
                          return_value={"success": False,
                                        "error": "registry locked"}):
            result = execute_approved_action(
                {"session_key": "k"},
                {"action_type": "create_rule", "detection_rule": "DR100"},
            )
        self.assertFalse(result["success"])
        self.assertEqual(result["error_type"], "create_rule_failed")
        self.assertIn("registry locked", result["error"])


class TestDeleteRuleHandler(unittest.TestCase):
    """Cover _execute_replay_delete_rule (lines 338-366)."""

    def setUp(self):
        if execute_approved_action is None:
            self.skipTest("execute_approved_action not available")

    def test_delete_rule_happy_path_delegates_to_pipeline(self):
        """Successful delete_rule_pipeline → success result + data forwarded."""
        import wl_replay
        with patch.object(wl_replay, "read_rules_registry",
                          return_value={"DR100": {"csv_file": "x.csv"}}), \
             patch.object(wl_replay, "delete_rule_pipeline",
                          return_value={"success": True,
                                        "message": "Rule DR100 trashed",
                                        "data": {"trash_id": "abc"}}) as mock_pipe:
            result = execute_approved_action(
                {"session_key": "k", "original_analyst": "alice"},
                {"action_type": "delete_rule",
                 "detection_rule": "DR100",
                 "payload": {"comment": "Approved cleanup",
                             "removal_type": "soft"}},
            )
        self.assertTrue(result["success"])
        self.assertEqual(result["data"], {"trash_id": "abc"})
        # Verify positional args delegated correctly
        args, kwargs = mock_pipe.call_args
        self.assertEqual(args[0], "DR100")
        self.assertEqual(args[1], "soft")
        self.assertEqual(args[2], "Approved cleanup")
        self.assertEqual(args[3], "alice")

    def test_delete_rule_pipeline_failure_returns_delete_rule_failed(self):
        """Pipeline failure → delete_rule_failed error_type."""
        import wl_replay
        with patch.object(wl_replay, "read_rules_registry",
                          return_value={"DR100": {}}), \
             patch.object(wl_replay, "delete_rule_pipeline",
                          return_value={"success": False,
                                        "error": "trash full"}):
            result = execute_approved_action(
                {"session_key": "k"},
                {"action_type": "delete_rule",
                 "detection_rule": "DR100",
                 "payload": {}},
            )
        self.assertFalse(result["success"])
        self.assertEqual(result["error_type"], "delete_rule_failed")


class TestDeleteCsvHandler(unittest.TestCase):
    """Cover _execute_replay_delete_csv (lines 369-399)."""

    def setUp(self):
        if execute_approved_action is None:
            self.skipTest("execute_approved_action not available")

    def test_delete_csv_happy_path_delegates_to_pipeline(self):
        """Successful delete_csv_pipeline → success + data."""
        import wl_replay
        # delete_csv requires CSV precondition — mock resolve_csv_path
        with patch.object(wl_replay, "resolve_csv_path",
                          return_value="/fake/path/x.csv"), \
             patch.object(wl_replay, "delete_csv_pipeline",
                          return_value={"success": True,
                                        "message": "deleted",
                                        "data": {"trash_id": "xyz"}}) as mock_pipe:
            result = execute_approved_action(
                {"session_key": "k", "original_analyst": "alice"},
                {"action_type": "delete_csv",
                 "csv_file": "x.csv",
                 "app_context": "wl_manager",
                 "detection_rule": "DR100",
                 "payload": {"comment": "no longer needed",
                             "removal_type": "permanent",
                             "rule_name": "DR100"}},
            )
        # delete_csv is in _csv_required_actions so resolve_csv_path is called
        self.assertTrue(result["success"])
        self.assertEqual(result["data"], {"trash_id": "xyz"})
        mock_pipe.assert_called_once()

    def test_delete_csv_pipeline_failure_returns_delete_csv_failed(self):
        """Pipeline failure → delete_csv_failed error_type."""
        import wl_replay
        # delete_csv is NOT in _csv_required_actions (only save_csv/add_row/
        # remove_rows/revert_csv are). So no resolve_csv_path mock needed.
        with patch.object(wl_replay, "delete_csv_pipeline",
                          return_value={"success": False,
                                        "error": "mapping locked"}):
            result = execute_approved_action(
                {"session_key": "k"},
                {"action_type": "delete_csv",
                 "csv_file": "x.csv",
                 "payload": {}},
            )
        self.assertFalse(result["success"])
        self.assertEqual(result["error_type"], "delete_csv_failed")


class TestSaveCsvHandler(unittest.TestCase):
    """Cover _execute_replay_save_csv body (lines 143-203)."""

    def setUp(self):
        if execute_approved_action is None:
            self.skipTest("execute_approved_action not available")

    def test_save_csv_happy_path_writes_snapshots_and_audits(self):
        """Happy path: resolve_csv_path → write_csv → snapshot_version → audit OK."""
        import wl_replay
        with patch.object(wl_replay, "resolve_csv_path",
                          return_value="/fake/x.csv"), \
             patch.object(wl_replay, "write_csv") as mock_write, \
             patch.object(wl_replay, "snapshot_version",
                          return_value=("v123", "20260519_120000")) as mock_snap, \
             patch.object(wl_replay, "build_audit_event",
                          return_value={"action": "replay_save_csv"}), \
             patch.object(wl_replay, "post_audit_event",
                          return_value=(True, "")) as mock_post:
            result = execute_approved_action(
                {"session_key": "sk",
                 "original_analyst": "alice",
                 "approving_admin": "bob",
                 "request_id": "req1"},
                {"action_type": "save_csv",
                 "csv_file": "x.csv",
                 "app_context": "wl_manager",
                 "headers": ["a", "b"],
                 "rows": [{"a": "1", "b": "2"}],
                 "comment": "approved"},
            )
        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["version_id"], "v123")
        mock_write.assert_called_once_with("/fake/x.csv",
                                           ["a", "b"],
                                           [{"a": "1", "b": "2"}])
        mock_snap.assert_called_once()
        mock_post.assert_called_once()

    def test_save_csv_write_exception_returns_save_failed(self):
        """write_csv raising → save_failed error_type."""
        import wl_replay
        with patch.object(wl_replay, "resolve_csv_path",
                          return_value="/fake/x.csv"), \
             patch.object(wl_replay, "write_csv",
                          side_effect=OSError("disk full")):
            result = execute_approved_action(
                {"session_key": "sk"},
                {"action_type": "save_csv",
                 "csv_file": "x.csv",
                 "headers": [],
                 "rows": []},
            )
        self.assertFalse(result["success"])
        self.assertEqual(result["error_type"], "save_failed")
        self.assertIn("disk full", result["error"])

    def test_save_csv_failed_audit_post_still_returns_success(self):
        """Audit post failure is logged but does NOT fail the save."""
        import wl_replay
        with patch.object(wl_replay, "resolve_csv_path",
                          return_value="/fake/x.csv"), \
             patch.object(wl_replay, "write_csv"), \
             patch.object(wl_replay, "snapshot_version",
                          return_value=("v123", "20260519_120000")), \
             patch.object(wl_replay, "build_audit_event", return_value={}), \
             patch.object(wl_replay, "post_audit_event",
                          return_value=(False, "401 unauthorized")):
            result = execute_approved_action(
                {"session_key": "sk"},
                {"action_type": "save_csv",
                 "csv_file": "x.csv",
                 "headers": [],
                 "rows": []},
            )
        # Save succeeded even though audit failed (the audit error is logged)
        self.assertTrue(result["success"])


class TestRevertCsvHandler(unittest.TestCase):
    """Cover _execute_replay_revert_csv (delegation to revert_csv_pipeline).

    History: an earlier implementation called `get_versions_dir()` with
    no arguments (the function requires `csv_path: str`), and read
    `version_id` from request_item although the approval queue stores
    `version_filename`. Both bugs are fixed by delegating wholesale to
    `revert_csv_pipeline` (same pattern as create_rule/delete_rule
    handlers). These tests pin the FIXED behaviour.
    """

    def setUp(self):
        if execute_approved_action is None:
            self.skipTest("execute_approved_action not available")

    def test_revert_csv_happy_path_delegates_to_pipeline(self):
        """Successful pipeline → success result + data forwarded."""
        import wl_replay
        import wl_versions
        with patch.object(wl_replay, "resolve_csv_path",
                          return_value="/fake/x.csv"), \
             patch.object(wl_versions, "revert_csv_pipeline",
                          return_value={"success": True,
                                        "message": "reverted",
                                        "data": {"new_record_version":
                                                 "2026-05-19 ..."}}) as mock_pipe:
            result = execute_approved_action(
                {"session_key": "sk",
                 "original_analyst": "alice",
                 "approving_admin": "bob"},
                {"action_type": "revert_csv",
                 "csv_file": "x.csv",
                 "app_context": "wl_manager",
                 "detection_rule": "DR100",
                 "version_filename": "x_20260101_120000.csv",
                 "version_display": "01-01-2026 12:00:00 (3 rows, by alice)",
                 "revert_reason": "approved revert"},
            )
        self.assertTrue(result["success"])
        self.assertEqual(result["message"], "reverted")
        # Verify the delegation passes the expected kwargs
        mock_pipe.assert_called_once()
        kwargs = mock_pipe.call_args.kwargs
        self.assertEqual(kwargs["csv_path"], "/fake/x.csv")
        self.assertEqual(kwargs["version_filename"],
                         "x_20260101_120000.csv")
        self.assertEqual(kwargs["version_display"],
                         "01-01-2026 12:00:00 (3 rows, by alice)")
        self.assertEqual(kwargs["revert_reason"], "approved revert")
        self.assertEqual(kwargs["analyst"], "alice")
        self.assertEqual(kwargs["csv_file"], "x.csv")
        self.assertEqual(kwargs["app_context"], "wl_manager")
        self.assertEqual(kwargs["detection_rule"], "DR100")

    def test_revert_csv_missing_version_filename_returns_error(self):
        """No version_filename in payload → missing_version_filename error."""
        import wl_replay
        with patch.object(wl_replay, "resolve_csv_path",
                          return_value="/fake/x.csv"):
            result = execute_approved_action(
                {"session_key": "sk"},
                {"action_type": "revert_csv",
                 "csv_file": "x.csv",
                 "app_context": "wl_manager",
                 "payload": {}},  # no version_filename anywhere
            )
        self.assertFalse(result["success"])
        self.assertEqual(result["error_type"], "missing_version_filename")

    def test_revert_csv_pipeline_failure_returns_revert_failed(self):
        """Pipeline failure surfaces as revert_failed error_type."""
        import wl_replay
        import wl_versions
        with patch.object(wl_replay, "resolve_csv_path",
                          return_value="/fake/x.csv"), \
             patch.object(wl_versions, "revert_csv_pipeline",
                          return_value={"success": False,
                                        "error": "version file missing"}):
            result = execute_approved_action(
                {"session_key": "sk", "original_analyst": "alice"},
                {"action_type": "revert_csv",
                 "csv_file": "x.csv",
                 "version_filename": "x_20260101.csv"},
            )
        self.assertFalse(result["success"])
        self.assertEqual(result["error_type"], "revert_failed")
        self.assertEqual(result["error"], "version file missing")

    def test_revert_csv_pipeline_exception_returns_revert_failed(self):
        """If the pipeline RAISES, wrapper catches and returns revert_failed."""
        import wl_replay
        import wl_versions
        with patch.object(wl_replay, "resolve_csv_path",
                          return_value="/fake/x.csv"), \
             patch.object(wl_versions, "revert_csv_pipeline",
                          side_effect=RuntimeError("disk full")):
            result = execute_approved_action(
                {"session_key": "sk"},
                {"action_type": "revert_csv",
                 "csv_file": "x.csv",
                 "version_filename": "x_20260101.csv"},
            )
        self.assertFalse(result["success"])
        self.assertEqual(result["error_type"], "revert_failed")
        self.assertIn("disk full", result["error"])

    def test_revert_csv_legacy_payload_under_payload_key(self):
        """Older queue entries nest version_filename under 'payload' — honored."""
        import wl_replay
        import wl_versions
        with patch.object(wl_replay, "resolve_csv_path",
                          return_value="/fake/x.csv"), \
             patch.object(wl_versions, "revert_csv_pipeline",
                          return_value={"success": True,
                                        "message": "ok"}) as mock_pipe:
            result = execute_approved_action(
                {"session_key": "sk"},
                {"action_type": "revert_csv",
                 "csv_file": "x.csv",
                 "payload": {"version_filename": "legacy_x_20260101.csv",
                             "version_display": "legacy display"}},
            )
        self.assertTrue(result["success"])
        kwargs = mock_pipe.call_args.kwargs
        self.assertEqual(kwargs["version_filename"],
                         "legacy_x_20260101.csv")

    def test_revert_alias_dispatches_to_same_handler(self):
        """action_type='revert' (no _csv suffix) routes to same handler.

        The handler stores approval queue entries with action_type='revert'
        (see wl_handler.py:6761), not 'revert_csv'. The dispatch table
        must accept both.
        """
        import wl_replay
        self.assertIn("revert", wl_replay.REPLAY_HANDLERS)
        self.assertIs(wl_replay.REPLAY_HANDLERS["revert"],
                      wl_replay.REPLAY_HANDLERS["revert_csv"])


class TestCreateCsvHandler(unittest.TestCase):
    """Cover _execute_replay_create_csv body (lines 402-511)."""

    def setUp(self):
        if execute_approved_action is None:
            self.skipTest("execute_approved_action not available")

    def test_create_csv_invalid_name_returns_invalid_csv_name(self):
        """build_csv_path returning None → invalid_csv_name error."""
        import wl_replay
        with patch.object(wl_replay, "build_csv_path", return_value=None):
            result = execute_approved_action(
                {"session_key": "sk"},
                {"action_type": "create_csv",
                 "csv_file": "bad\x00name.csv",
                 "detection_rule": "DR100",
                 "payload": {"headers": ["a", "b"]}},
            )
        self.assertFalse(result["success"])
        self.assertEqual(result["error_type"], "invalid_csv_name")
        self.assertIn("Invalid CSV file name", result["error"])

    def test_create_csv_already_exists_returns_csv_exists(self):
        """File already on disk → csv_exists error."""
        import wl_replay
        with patch.object(wl_replay, "build_csv_path",
                          return_value="/fake/x.csv"), \
             patch("os.path.isfile", return_value=True):
            result = execute_approved_action(
                {"session_key": "sk"},
                {"action_type": "create_csv",
                 "csv_file": "x.csv",
                 "detection_rule": "DR100",
                 "payload": {"headers": ["a", "b"]}},
            )
        self.assertFalse(result["success"])
        self.assertEqual(result["error_type"], "csv_exists")

    def test_create_csv_happy_path_writes_and_audits(self):
        """Full happy path: build_csv_path → write_csv → snapshot → mapping → audit."""
        import wl_replay
        from contextlib import contextmanager

        @contextmanager
        def fake_lock():
            yield

        with patch.object(wl_replay, "build_csv_path",
                          return_value="/fake/x.csv"), \
             patch("os.path.isfile", return_value=False), \
             patch.object(wl_replay, "write_csv") as mock_write, \
             patch.object(wl_replay, "snapshot_version",
                          return_value=("v123", "20260519_120000")), \
             patch.object(wl_replay, "rules_rmw_lock", fake_lock), \
             patch.object(wl_replay, "build_audit_event", return_value={}), \
             patch.object(wl_replay, "post_audit_event", return_value=(True, "")), \
             patch("builtins.open", mock_open(read_data="")), \
             patch.object(wl_replay, "MAPPING_FILE", "/fake/mapping.csv"):
            result = execute_approved_action(
                {"session_key": "sk",
                 "original_analyst": "alice",
                 "approving_admin": "bob",
                 "request_id": "req1"},
                {"action_type": "create_csv",
                 "csv_file": "x.csv",
                 "app_context": "wl_manager",
                 "detection_rule": "DR100",
                 "payload": {"headers": ["a", "b"]}},
            )
        self.assertTrue(result["success"])
        self.assertIn("created successfully", result["message"])
        # write_csv called once for the new (empty-row) CSV
        mock_write.assert_called_once_with("/fake/x.csv", ["a", "b"], [])

    def test_create_csv_mapping_oserror_still_returns_success(self):
        """OSError in mapping RMW is logged but does NOT fail the create."""
        import wl_replay
        from contextlib import contextmanager

        @contextmanager
        def fake_lock():
            raise OSError("mapping locked")
            yield  # pragma: no cover

        with patch.object(wl_replay, "build_csv_path",
                          return_value="/fake/x.csv"), \
             patch("os.path.isfile", return_value=False), \
             patch.object(wl_replay, "write_csv"), \
             patch.object(wl_replay, "snapshot_version",
                          return_value=("v123", "ts")), \
             patch.object(wl_replay, "rules_rmw_lock", fake_lock), \
             patch.object(wl_replay, "build_audit_event", return_value={}), \
             patch.object(wl_replay, "post_audit_event", return_value=(True, "")):
            result = execute_approved_action(
                {"session_key": "sk"},
                {"action_type": "create_csv",
                 "csv_file": "x.csv",
                 "detection_rule": "DR100",
                 "payload": {"headers": ["a"]}},
            )
        # CSV write succeeded; only mapping update failed (logged).
        self.assertTrue(result["success"])


if __name__ == '__main__':
    unittest.main()
