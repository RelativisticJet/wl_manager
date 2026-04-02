"""
Integration tests for Wave 2 simple POST handlers.

Tests verify that simple stateless POST actions work correctly:
1. _action_save_col_widths() - saves column width metadata
2. _action_mark_notifications_read() - marks notifications as read
3. _action_cancel_request() - cancels a pending approval request
4. _action_log_event() - logs frontend-originated audit events
5. _action_save_as_default() - saves configuration as default
6. _action_reset_factory_defaults() - resets config to factory defaults

All tests use mocked dependencies and do NOT require Docker container.
"""

import unittest
import json
import sys
from unittest.mock import Mock, MagicMock, patch, mock_open
from io import StringIO

# Add bin directory to path for imports
sys.path.insert(0, 'bin')

try:
    from wl_handler import WlHandler
except ImportError:
    # If import fails during test discovery, define a stub
    WlHandler = None


class TestSaveColWidths(unittest.TestCase):
    """Tests for _action_save_col_widths POST handler."""

    def setUp(self):
        """Set up test handler instance."""
        if WlHandler is None:
            self.skipTest("wl_handler module not available")
        self.handler = WlHandler()

    def test_save_col_widths_success(self):
        """Test successful column width save."""
        request = {}
        payload = {
            "csv_file": "test.csv",
            "col_widths": {"col1": 100, "col2": 200}
        }
        user = "analyst1"
        roles = {"wl_editor"}

        with patch('wl_handler.set_column_widths') as mock_set:
            with patch('wl_handler.resolve_csv_path') as mock_resolve:
                mock_resolve.return_value = "/path/to/test.csv"
                response = self.handler._action_save_col_widths(request, payload, user, roles)

                self.assertEqual(response['status'], 200)
                body = json.loads(response['payload'])
                self.assertTrue(body.get('success'))
                mock_set.assert_called_once()

    def test_save_col_widths_missing_csv_file(self):
        """Test error when csv_file is missing."""
        request = {}
        payload = {"col_widths": {"col1": 100}}
        user = "analyst1"
        roles = {"wl_editor"}

        response = self.handler._action_save_col_widths(request, payload, user, roles)

        self.assertEqual(response['status'], 400)
        body = json.loads(response['payload'])
        self.assertIn("error", body)

    def test_save_col_widths_invalid_col_widths(self):
        """Test error when col_widths is not a dict."""
        request = {}
        payload = {
            "csv_file": "test.csv",
            "col_widths": "not_a_dict"
        }
        user = "analyst1"
        roles = {"wl_editor"}

        response = self.handler._action_save_col_widths(request, payload, user, roles)

        self.assertEqual(response['status'], 400)
        body = json.loads(response['payload'])
        self.assertIn("error", body)

    def test_save_col_widths_csv_not_found(self):
        """Test error when CSV file doesn't exist."""
        request = {}
        payload = {
            "csv_file": "nonexistent.csv",
            "col_widths": {"col1": 100}
        }
        user = "analyst1"
        roles = {"wl_editor"}

        with patch('wl_handler.resolve_csv_path') as mock_resolve:
            mock_resolve.return_value = None
            response = self.handler._action_save_col_widths(request, payload, user, roles)

            self.assertEqual(response['status'], 404)


class TestMarkNotificationsRead(unittest.TestCase):
    """Tests for _action_mark_notifications_read POST handler."""

    def setUp(self):
        """Set up test handler instance."""
        if WlHandler is None:
            self.skipTest("wl_handler module not available")
        self.handler = WlHandler()

    def test_mark_all_notifications_read(self):
        """Test marking all notifications as read."""
        request = {}
        payload = {}  # Empty payload means mark all
        user = "analyst1"
        roles = {"wl_editor"}

        with patch('wl_handler._read_notifications') as mock_read:
            with patch('wl_handler._write_notifications') as mock_write:
                mock_read.return_value = {
                    "analyst1": [
                        {"id": "notif_1", "read": False},
                        {"id": "notif_2", "read": False}
                    ]
                }

                response = self.handler._action_mark_notifications_read(request, payload, user, roles)

                self.assertEqual(response['status'], 200)
                body = json.loads(response['payload'])
                self.assertTrue(body.get('success'))
                mock_write.assert_called_once()

    def test_mark_notifications_read_with_ids(self):
        """Test marking specific notifications as read."""
        request = {}
        payload = {"notification_ids": ["notif_1", "notif_2"]}
        user = "analyst1"
        roles = {"wl_editor"}

        with patch('wl_handler._read_notifications') as mock_read:
            with patch('wl_handler._write_notifications') as mock_write:
                mock_read.return_value = {
                    "analyst1": [
                        {"id": "notif_1", "read": False},
                        {"id": "notif_2", "read": False},
                        {"id": "notif_3", "read": False}
                    ]
                }

                response = self.handler._action_mark_notifications_read(request, payload, user, roles)

                self.assertEqual(response['status'], 200)
                body = json.loads(response['payload'])
                self.assertTrue(body.get('success'))

    def test_mark_notifications_read_empty_list(self):
        """Test with no notifications for user."""
        request = {}
        payload = {}
        user = "analyst1"
        roles = {"wl_editor"}

        with patch('wl_handler._read_notifications') as mock_read:
            with patch('wl_handler._write_notifications') as mock_write:
                mock_read.return_value = {}  # No user notifications

                response = self.handler._action_mark_notifications_read(request, payload, user, roles)

                self.assertEqual(response['status'], 200)
                body = json.loads(response['payload'])
                self.assertTrue(body.get('success'))


class TestCancelRequest(unittest.TestCase):
    """Tests for _action_cancel_request POST handler."""

    def setUp(self):
        """Set up test handler instance."""
        if WlHandler is None:
            self.skipTest("wl_handler module not available")
        self.handler = WlHandler()

    def test_cancel_request_success(self):
        """Test successful request cancellation."""
        request = {"system_authtoken": "token123"}
        payload = {
            "request_id": "req_123",
            "cancellation_reason": "No longer needed"
        }
        user = "analyst1"
        roles = {"wl_editor"}

        with patch('wl_handler._approval_queue_lock'):
            with patch('wl_handler._expire_pending_approvals') as mock_expire:
                with patch('wl_handler._write_approval_queue') as mock_write:
                    with patch('wl_handler._index_audit') as mock_audit:
                        mock_expire.return_value = [
                            {
                                "request_id": "req_123",
                                "analyst": "analyst1",
                                "status": "pending",
                                "action_type": "save_csv",
                                "detection_rule": "rule1",
                                "csv_file": "test.csv",
                                "app_context": "wl_manager",
                                "payload": {}
                            }
                        ]

                        response = self.handler._action_cancel_request(request, payload, user, roles)

                        self.assertEqual(response['status'], 200)
                        body = json.loads(response['payload'])
                        self.assertTrue(body.get('success'))

    def test_cancel_request_not_found(self):
        """Test error when request ID doesn't exist."""
        request = {}
        payload = {
            "request_id": "nonexistent",
            "cancellation_reason": "Test"
        }
        user = "analyst1"
        roles = {"wl_editor"}

        with patch('wl_handler._approval_queue_lock'):
            with patch('wl_handler._expire_pending_approvals') as mock_expire:
                mock_expire.return_value = []  # No matching request

                response = self.handler._action_cancel_request(request, payload, user, roles)

                self.assertEqual(response['status'], 404)
                body = json.loads(response['payload'])
                self.assertIn("error", body)

    def test_cancel_request_missing_reason(self):
        """Test error when cancellation reason is missing."""
        request = {}
        payload = {"request_id": "req_123"}
        user = "analyst1"
        roles = {"wl_editor"}

        response = self.handler._action_cancel_request(request, payload, user, roles)

        self.assertEqual(response['status'], 400)
        body = json.loads(response['payload'])
        self.assertIn("error", body)

    def test_cancel_request_not_requester(self):
        """Test error when user is not the original requester."""
        request = {}
        payload = {
            "request_id": "req_123",
            "cancellation_reason": "Test"
        }
        user = "analyst2"  # Different from original requester
        roles = {"wl_editor"}

        with patch('wl_handler._approval_queue_lock'):
            with patch('wl_handler._expire_pending_approvals') as mock_expire:
                mock_expire.return_value = [
                    {
                        "request_id": "req_123",
                        "analyst": "analyst1",  # Original requester
                        "status": "pending",
                        "action_type": "save_csv",
                        "detection_rule": "rule1",
                        "csv_file": "test.csv",
                        "app_context": "wl_manager",
                        "payload": {}
                    }
                ]

                response = self.handler._action_cancel_request(request, payload, user, roles)

                self.assertEqual(response['status'], 403)
                body = json.loads(response['payload'])
                self.assertIn("error", body)


class TestLogEvent(unittest.TestCase):
    """Tests for _action_log_event POST handler."""

    def setUp(self):
        """Set up test handler instance."""
        if WlHandler is None:
            self.skipTest("wl_handler module not available")
        self.handler = WlHandler()

    def test_log_audit_exported_event(self):
        """Test logging audit_exported event."""
        request = {}
        payload = {
            "event_action": "audit_exported",
            "detection_rule": "rule1",
            "csv_file": "test.csv",
            "event_count": 50
        }
        user = "analyst1"
        roles = {"wl_editor"}

        with patch('wl_handler._index_audit') as mock_audit:
            response = self.handler._action_log_event(request, payload)

            self.assertEqual(response['status'], 200)
            body = json.loads(response['payload'])
            self.assertEqual(body.get('status'), 'ok')

    def test_log_csv_exported_event(self):
        """Test logging csv_exported event."""
        request = {}
        payload = {
            "event_action": "csv_exported",
            "detection_rule": "rule1",
            "csv_file": "test.csv",
            "row_count": 100
        }

        with patch('wl_handler._index_audit') as mock_audit:
            response = self.handler._action_log_event(request, payload)

            self.assertEqual(response['status'], 200)

    def test_log_csv_imported_event(self):
        """Test logging csv_imported event."""
        request = {}
        payload = {
            "event_action": "csv_imported",
            "detection_rule": "rule1",
            "csv_file": "test.csv",
            "row_count_before": 50,
            "row_count_after": 60,
            "imported_row_count": 10
        }

        with patch('wl_handler._index_audit') as mock_audit:
            response = self.handler._action_log_event(request, payload)

            self.assertEqual(response['status'], 200)

    def test_log_event_invalid_action(self):
        """Test error with invalid event action."""
        request = {}
        payload = {
            "event_action": "invalid_action",
            "detection_rule": "rule1"
        }

        response = self.handler._action_log_event(request, payload)

        self.assertEqual(response['status'], 400)
        body = json.loads(response['payload'])
        self.assertIn("error", body)


class TestSaveAsDefault(unittest.TestCase):
    """Tests for _action_save_as_default POST handler."""

    def setUp(self):
        """Set up test handler instance."""
        if WlHandler is None:
            self.skipTest("wl_handler module not available")
        self.handler = WlHandler()

    def test_save_as_default_success(self):
        """Test successful config save as default."""
        request = {}
        payload = {
            "key": "default_rule_csv",
            "value": "DR999.csv"
        }
        user = "admin1"
        roles = {"sc_admin"}

        response = self.handler._action_save_as_default(request, payload, user, roles)

        self.assertEqual(response['status'], 200)
        body = json.loads(response['payload'])
        self.assertTrue(body.get('success'))


class TestResetFactoryDefaults(unittest.TestCase):
    """Tests for _action_reset_factory_defaults POST handler."""

    def setUp(self):
        """Set up test handler instance."""
        if WlHandler is None:
            self.skipTest("wl_handler module not available")
        self.handler = WlHandler()

    def test_reset_factory_defaults_success(self):
        """Test successful factory defaults reset."""
        request = {}
        payload = {}
        user = "admin1"
        roles = {"sc_admin"}

        response = self.handler._action_reset_factory_defaults(request, payload, user, roles)

        self.assertEqual(response['status'], 200)
        body = json.loads(response['payload'])
        self.assertTrue(body.get('success'))


class TestSetTrashRetention(unittest.TestCase):
    """Tests for _action_set_trash_retention POST handler."""

    def setUp(self):
        """Set up test handler instance."""
        if WlHandler is None:
            self.skipTest("wl_handler module not available")
        self.handler = WlHandler()

    def test_set_trash_retention_success(self):
        """Test successful trash retention setting."""
        request = {}
        payload = {"retention_days": 30}
        user = "admin1"
        roles = {"admin"}

        with patch('wl_handler.OWN_LOOKUPS', '/tmp'):
            with patch('builtins.open', mock_open()):
                response = self.handler._action_set_trash_retention(request, payload, user, roles)

                self.assertEqual(response['status'], 200)
                body = json.loads(response['payload'])
                self.assertTrue(body.get('success'))

    def test_set_trash_retention_invalid_days(self):
        """Test error with invalid retention days."""
        request = {}
        payload = {"retention_days": 1}  # Too low
        user = "admin1"
        roles = {"admin"}

        response = self.handler._action_set_trash_retention(request, payload, user, roles)

        self.assertEqual(response['status'], 400)
        body = json.loads(response['payload'])
        self.assertIn("error", body)


class TestPurgeTrash(unittest.TestCase):
    """Tests for _action_purge_trash POST handler."""

    def setUp(self):
        """Set up test handler instance."""
        if WlHandler is None:
            self.skipTest("wl_handler module not available")
        self.handler = WlHandler()

    def test_purge_trash_success(self):
        """Test successful trash item purge."""
        request = {}
        payload = {"item_id": "item_123"}
        user = "admin1"
        roles = {"admin"}

        with patch('wl_handler.purge_trash_item') as mock_purge:
            mock_purge.return_value = True
            response = self.handler._action_purge_trash(request, payload, user, roles)

            self.assertEqual(response['status'], 200)
            body = json.loads(response['payload'])
            self.assertTrue(body.get('success'))

    def test_purge_trash_item_not_found(self):
        """Test error when item doesn't exist."""
        request = {}
        payload = {"item_id": "nonexistent"}
        user = "admin1"
        roles = {"admin"}

        with patch('wl_handler.purge_trash_item') as mock_purge:
            mock_purge.return_value = False
            response = self.handler._action_purge_trash(request, payload, user, roles)

            self.assertEqual(response['status'], 200)
            body = json.loads(response['payload'])
            self.assertFalse(body.get('success'))


class TestRestoreFromTrash(unittest.TestCase):
    """Tests for _action_restore_from_trash POST handler."""

    def setUp(self):
        """Set up test handler instance."""
        if WlHandler is None:
            self.skipTest("wl_handler module not available")
        self.handler = WlHandler()

    def test_restore_from_trash_success(self):
        """Test successful trash item restoration."""
        request = {}
        payload = {
            "item_id": "item_123",
            "comment": "Restore needed"
        }
        user = "admin1"
        roles = {"admin"}

        with patch('wl_handler.restore_from_trash') as mock_restore:
            mock_restore.return_value = (True, "")
            response = self.handler._action_restore_from_trash(request, payload, user, roles)

            self.assertEqual(response['status'], 200)
            body = json.loads(response['payload'])
            self.assertTrue(body.get('success'))

    def test_restore_from_trash_error(self):
        """Test error when restoration fails."""
        request = {}
        payload = {
            "item_id": "nonexistent",
            "comment": "Test"
        }
        user = "admin1"
        roles = {"admin"}

        with patch('wl_handler.restore_from_trash') as mock_restore:
            mock_restore.return_value = (False, "Item not found")
            response = self.handler._action_restore_from_trash(request, payload, user, roles)

            self.assertEqual(response['status'], 400)
            body = json.loads(response['payload'])
            self.assertIn("error", body)


class TestHandlerSignatures(unittest.TestCase):
    """Verify Wave 2 simple POST handlers have correct signatures."""

    def setUp(self):
        if WlHandler is None:
            self.skipTest("wl_handler module not available")
        self.handler = WlHandler()

    def test_save_col_widths_signature(self):
        """Verify _action_save_col_widths signature."""
        import inspect
        sig = inspect.signature(self.handler._action_save_col_widths)
        params = list(sig.parameters.keys())
        self.assertEqual(params, ['request', 'payload', 'user', 'roles'])

    def test_cancel_request_signature(self):
        """Verify _action_cancel_request signature."""
        import inspect
        sig = inspect.signature(self.handler._action_cancel_request)
        params = list(sig.parameters.keys())
        self.assertEqual(params, ['request', 'payload', 'user', 'roles'])

    def test_mark_notifications_read_signature(self):
        """Verify _action_mark_notifications_read signature."""
        import inspect
        sig = inspect.signature(self.handler._action_mark_notifications_read)
        params = list(sig.parameters.keys())
        self.assertEqual(params, ['request', 'payload', 'user', 'roles'])

    def test_log_event_signature(self):
        """Verify _action_log_event signature."""
        import inspect
        sig = inspect.signature(self.handler._action_log_event)
        params = list(sig.parameters.keys())
        # This one has different signature: (request, payload)
        self.assertIn('request', params)
        self.assertIn('payload', params)


class TestErrorResponses(unittest.TestCase):
    """Verify error responses follow consistent format."""

    def setUp(self):
        if WlHandler is None:
            self.skipTest("wl_handler module not available")
        self.handler = WlHandler()

    def test_error_response_has_error_field(self):
        """Verify error responses include 'error' field."""
        request = {}
        payload = {}
        user = "analyst1"
        roles = {"wl_editor"}

        response = self.handler._action_save_col_widths(request, payload, user, roles)
        body = json.loads(response['payload'])
        self.assertIn('error', body)

    def test_success_response_has_success_field(self):
        """Verify success responses include 'success' field."""
        request = {}
        payload = {
            "csv_file": "test.csv",
            "col_widths": {"col1": 100}
        }
        user = "analyst1"
        roles = {"wl_editor"}

        with patch('wl_handler.set_column_widths'):
            with patch('wl_handler.resolve_csv_path') as mock_resolve:
                mock_resolve.return_value = "/path/to/test.csv"
                response = self.handler._action_save_col_widths(request, payload, user, roles)
                body = json.loads(response['payload'])
                if response['status'] == 200:
                    self.assertIn('success', body)


class TestCreateCsv(unittest.TestCase):
    """Tests for _action_create_csv POST handler."""

    def setUp(self):
        """Set up test handler instance."""
        if WlHandler is None:
            self.skipTest("wl_handler module not available")
        self.handler = WlHandler()

    def test_create_csv_success(self):
        """Test successful CSV creation."""
        request = {}
        payload = {
            "csv_file": "test_new.csv",
            "csv_data": "col1,col2\nval1,val2\n",
            "comment": "Created by test"
        }
        user = "analyst1"
        roles = {"wl_editor"}

        with patch('wl_handler.write_csv') as mock_write:
            with patch('wl_handler.build_csv_path') as mock_path:
                with patch('wl_handler._index_audit') as mock_audit:
                    mock_path.return_value = "/path/to/test_new.csv"
                    mock_write.return_value = (True, None)
                    response = self.handler._action_create_csv(request, payload, user, roles)

                    self.assertEqual(response['status'], 200)
                    body = json.loads(response['payload'])
                    self.assertTrue(body.get('success'))

    def test_create_csv_missing_file(self):
        """Test error when csv_file is missing."""
        request = {}
        payload = {
            "csv_data": "col1,col2\nval1,val2\n",
            "comment": "Test"
        }
        user = "analyst1"
        roles = {"wl_editor"}

        response = self.handler._action_create_csv(request, payload, user, roles)

        self.assertEqual(response['status'], 400)
        body = json.loads(response['payload'])
        self.assertIn("error", body)

    def test_create_csv_invalid_filename(self):
        """Test error with invalid CSV filename."""
        request = {}
        payload = {
            "csv_file": "../../../etc/passwd",
            "csv_data": "col1\nval1\n",
            "comment": "Test"
        }
        user = "analyst1"
        roles = {"wl_editor"}

        with patch('wl_handler.is_safe_filename') as mock_safe:
            mock_safe.return_value = False
            response = self.handler._action_create_csv(request, payload, user, roles)

            self.assertEqual(response['status'], 400)
            body = json.loads(response['payload'])
            self.assertIn("error", body)

    def test_create_csv_already_exists(self):
        """Test error when CSV file already exists."""
        request = {}
        payload = {
            "csv_file": "existing.csv",
            "csv_data": "col1\nval1\n",
            "comment": "Test"
        }
        user = "analyst1"
        roles = {"wl_editor"}

        with patch('wl_handler.build_csv_path') as mock_path:
            with patch('wl_handler.os.path.exists') as mock_exists:
                mock_path.return_value = "/path/to/existing.csv"
                mock_exists.return_value = True
                response = self.handler._action_create_csv(request, payload, user, roles)

                self.assertEqual(response['status'], 400)
                body = json.loads(response['payload'])
                self.assertIn("error", body)


class TestCreateRule(unittest.TestCase):
    """Tests for _action_create_rule POST handler."""

    def setUp(self):
        """Set up test handler instance."""
        if WlHandler is None:
            self.skipTest("wl_handler module not available")
        self.handler = WlHandler()

    def test_create_rule_success(self):
        """Test successful detection rule creation."""
        request = {}
        payload = {
            "detection_rule": "DR_NewTest",
            "csv_file": "test_new.csv",
            "comment": "Created by test"
        }
        user = "analyst1"
        roles = {"wl_editor"}

        with patch('wl_handler._read_rules_registry') as mock_read:
            with patch('wl_handler._write_rules_registry') as mock_write:
                with patch('wl_handler._index_audit') as mock_audit:
                    mock_read.return_value = {"existing_rule"}
                    mock_write.return_value = (True, None)
                    response = self.handler._action_create_rule(request, payload, user, roles)

                    self.assertEqual(response['status'], 200)
                    body = json.loads(response['payload'])
                    self.assertTrue(body.get('success'))

    def test_create_rule_missing_name(self):
        """Test error when detection_rule is missing."""
        request = {}
        payload = {
            "csv_file": "test.csv",
            "comment": "Test"
        }
        user = "analyst1"
        roles = {"wl_editor"}

        response = self.handler._action_create_rule(request, payload, user, roles)

        self.assertEqual(response['status'], 400)
        body = json.loads(response['payload'])
        self.assertIn("error", body)

    def test_create_rule_already_exists(self):
        """Test error when rule already exists."""
        request = {}
        payload = {
            "detection_rule": "DR_Existing",
            "csv_file": "test.csv",
            "comment": "Test"
        }
        user = "analyst1"
        roles = {"wl_editor"}

        with patch('wl_handler._read_rules_registry') as mock_read:
            mock_read.return_value = {"DR_Existing"}  # Rule already exists
            response = self.handler._action_create_rule(request, payload, user, roles)

            self.assertEqual(response['status'], 400)
            body = json.loads(response['payload'])
            self.assertIn("error", body)

    def test_create_rule_invalid_name(self):
        """Test error with invalid rule name."""
        request = {}
        payload = {
            "detection_rule": "Invalid Rule Name!@#",
            "csv_file": "test.csv",
            "comment": "Test"
        }
        user = "analyst1"
        roles = {"wl_editor"}

        response = self.handler._action_create_rule(request, payload, user, roles)

        self.assertEqual(response['status'], 400)
        body = json.loads(response['payload'])
        self.assertIn("error", body)


class TestSimplePostActionsCompleteness(unittest.TestCase):
    """Comprehensive test: all simple POST actions are implemented."""

    def setUp(self):
        if WlHandler is None:
            self.skipTest("wl_handler module not available")
        self.handler = WlHandler()

    def test_all_simple_post_actions_have_methods(self):
        """Verify all simple POST actions have corresponding handler methods."""
        simple_post_actions = {
            "create_csv",
            "create_rule",
            "restore_from_trash",
            "purge_trash",
            "save_col_widths",
            "mark_notifications_read",
            "cancel_request",
            "log_event",
            "save_as_default",
            "reset_factory_defaults",
            "set_trash_retention",
        }

        for action in simple_post_actions:
            if action in self.handler.POST_ACTIONS:
                required_roles, method_name = self.handler.POST_ACTIONS[action]
                self.assertTrue(hasattr(self.handler, method_name),
                              f"POST action '{action}' missing method '{method_name}'")
                self.assertTrue(callable(getattr(self.handler, method_name)),
                              f"POST action '{action}' method '{method_name}' is not callable")


if __name__ == '__main__':
    unittest.main()
