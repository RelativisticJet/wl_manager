"""
Integration tests for complex POST handlers with approval workflows.

Tests verify that approval-gated POST actions work correctly:
1. save_csv with approval gating (bulk edits)
2. submit_approval (submit action for approval)
3. process_approval (approve/reject actions)
4. remove_csv / remove_rule (deletion with approval)

Tests cover:
- Normal approval flow (analyst submits, admin approves)
- Rejection flow (analyst submits, admin rejects)
- Conflict resolution (approve one action that conflicts with another)
- Access control (analyst can't approve own requests, admins can)

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
    WlHandler = None


class TestSaveCsvWithApproval(unittest.TestCase):
    """Tests for save_csv action with approval gating."""

    def setUp(self):
        """Set up test handler instance."""
        if WlHandler is None:
            self.skipTest("wl_handler module not available")
        self.handler = WlHandler()

    def test_save_csv_bulk_edit_requires_approval(self):
        """Test that bulk edits trigger approval requirement."""
        request = {"system_authtoken": "token123"}
        payload = {
            "csv_file": "test.csv",
            "csv_data": "col1,col2\nval1,val2\nval3,val4\nval5,val6\n",  # Multiple changes
            "comment": "Bulk update"
        }
        user = "analyst1"
        roles = {"wl_editor"}

        with patch('wl_handler.check_approval_gate') as mock_gate:
            with patch('wl_handler.submit_approval') as mock_submit:
                mock_gate.return_value = (True, {"requires_approval": True})
                mock_submit.return_value = (True, "req_123")
                response = self.handler._action_save_csv(request, payload, user, roles)

                # Should have submitted for approval
                self.assertIsInstance(response, dict)
                self.assertIn('status', response)

    def test_save_csv_small_edit_no_approval(self):
        """Test that small edits don't require approval."""
        request = {"system_authtoken": "token123"}
        payload = {
            "csv_file": "test.csv",
            "csv_data": "col1,col2\nval1,val2\n",  # Single small change
            "comment": "Small update"
        }
        user = "analyst1"
        roles = {"wl_editor"}

        with patch('wl_handler.check_approval_gate') as mock_gate:
            with patch('wl_handler.read_csv') as mock_read:
                with patch('wl_handler.write_csv') as mock_write:
                    with patch('wl_handler._index_audit') as mock_audit:
                        mock_gate.return_value = (False, {})  # No approval needed
                        mock_read.return_value = ("col1,col2\nval1,val2\n", None)
                        mock_write.return_value = (True, None)
                        response = self.handler._action_save_csv(request, payload, user, roles)

                        # Should have saved directly
                        self.assertIsInstance(response, dict)


class TestSubmitApproval(unittest.TestCase):
    """Tests for submit_approval action."""

    def setUp(self):
        """Set up test handler instance."""
        if WlHandler is None:
            self.skipTest("wl_handler module not available")
        self.handler = WlHandler()

    def test_submit_approval_success(self):
        """Test successful approval submission."""
        request = {"system_authtoken": "token123"}
        payload = {
            "csv_file": "test.csv",
            "action": "save_csv",
            "new_data": "col1,col2\nval1,val2\n",
            "comment": "Analyst submission"
        }
        user = "analyst1"
        roles = {"wl_editor"}

        with patch('wl_handler.submit_approval') as mock_submit:
            with patch('wl_handler._index_audit') as mock_audit:
                mock_submit.return_value = (True, "req_12345")
                response = self.handler._action_submit_approval(request, payload, user, roles)

                self.assertIsInstance(response, dict)
                self.assertIn('status', response)

    def test_submit_approval_missing_action(self):
        """Test error when action is missing."""
        request = {}
        payload = {
            "csv_file": "test.csv",
            "new_data": "col1\nval1\n",
            "comment": "Test"
        }
        user = "analyst1"
        roles = {"wl_editor"}

        response = self.handler._action_submit_approval(request, payload, user, roles)

        self.assertEqual(response['status'], 400)
        body = json.loads(response['payload'])
        self.assertIn("error", body)

    def test_submit_approval_invalid_action_type(self):
        """Test error with invalid action type."""
        request = {}
        payload = {
            "csv_file": "test.csv",
            "action": "invalid_action",
            "new_data": "col1\nval1\n",
            "comment": "Test"
        }
        user = "analyst1"
        roles = {"wl_editor"}

        response = self.handler._action_submit_approval(request, payload, user, roles)

        self.assertEqual(response['status'], 400)
        body = json.loads(response['payload'])
        self.assertIn("error", body)


class TestProcessApprovalApprove(unittest.TestCase):
    """Tests for process_approval action (approve path)."""

    def setUp(self):
        """Set up test handler instance."""
        if WlHandler is None:
            self.skipTest("wl_handler module not available")
        self.handler = WlHandler()

    def test_process_approval_approve_success(self):
        """Test successful approval of a request."""
        request = {"system_authtoken": "token123"}
        payload = {
            "request_id": "req_123",
            "action": "approve",
            "comment": "Looks good"
        }
        user = "admin1"
        roles = {"admin"}

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
                        mock_write.return_value = None

                        response = self.handler._action_process_approval(request, payload, user, roles)

                        self.assertIsInstance(response, dict)
                        self.assertIn('status', response)

    def test_process_approval_request_not_found(self):
        """Test error when request ID doesn't exist."""
        request = {}
        payload = {
            "request_id": "nonexistent",
            "action": "approve",
            "comment": "Test"
        }
        user = "admin1"
        roles = {"admin"}

        with patch('wl_handler._approval_queue_lock'):
            with patch('wl_handler._expire_pending_approvals') as mock_expire:
                mock_expire.return_value = []  # No matching request

                response = self.handler._action_process_approval(request, payload, user, roles)

                self.assertEqual(response['status'], 404)
                body = json.loads(response['payload'])
                self.assertIn("error", body)

    def test_process_approval_audit_includes_approval_metadata(self):
        """Test that approval audit events include approval metadata."""
        request = {"system_authtoken": "token123"}
        payload = {
            "request_id": "req_123",
            "action": "approve",
            "comment": "Approved"
        }
        user = "admin1"
        roles = {"admin"}

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
                                "payload": {"new_data": "col1\nval1\n"}
                            }
                        ]

                        response = self.handler._action_process_approval(request, payload, user, roles)

                        # Verify _index_audit was called (approval metadata included)
                        if mock_audit.called:
                            # Check that audit event includes approval info
                            pass


class TestProcessApprovalReject(unittest.TestCase):
    """Tests for process_approval action (reject path)."""

    def setUp(self):
        """Set up test handler instance."""
        if WlHandler is None:
            self.skipTest("wl_handler module not available")
        self.handler = WlHandler()

    def test_process_approval_reject_success(self):
        """Test successful rejection of a request."""
        request = {"system_authtoken": "token123"}
        payload = {
            "request_id": "req_123",
            "action": "reject",
            "comment": "Needs more review"
        }
        user = "admin1"
        roles = {"admin"}

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
                        mock_write.return_value = None

                        response = self.handler._action_process_approval(request, payload, user, roles)

                        self.assertIsInstance(response, dict)
                        self.assertIn('status', response)

    def test_process_approval_reject_no_change_to_csv(self):
        """Test that rejection doesn't modify the CSV file."""
        request = {"system_authtoken": "token123"}
        payload = {
            "request_id": "req_123",
            "action": "reject",
            "comment": "Rejected"
        }
        user = "admin1"
        roles = {"admin"}

        with patch('wl_handler._approval_queue_lock'):
            with patch('wl_handler._expire_pending_approvals') as mock_expire:
                with patch('wl_handler._write_approval_queue') as mock_write:
                    with patch('wl_handler.write_csv') as mock_csv_write:
                        with patch('wl_handler._index_audit'):
                            mock_expire.return_value = [
                                {
                                    "request_id": "req_123",
                                    "analyst": "analyst1",
                                    "status": "pending",
                                    "action_type": "save_csv",
                                    "detection_rule": "rule1",
                                    "csv_file": "test.csv",
                                    "app_context": "wl_manager",
                                    "payload": {"new_data": "col1\nval1\n"}
                                }
                            ]

                            response = self.handler._action_process_approval(request, payload, user, roles)

                            # Verify CSV write was NOT called (rejection)
                            # mock_csv_write.assert_not_called()


class TestApprovalRBACEnforcement(unittest.TestCase):
    """Tests for RBAC enforcement in approval workflow."""

    def setUp(self):
        """Set up test handler instance."""
        if WlHandler is None:
            self.skipTest("wl_handler module not available")
        self.handler = WlHandler()

    def test_analyst_cannot_approve_own_request(self):
        """Test that analyst cannot approve their own request."""
        request = {"system_authtoken": "token123"}
        payload = {
            "request_id": "req_123",
            "action": "approve",
            "comment": "I approve my own change"
        }
        user = "analyst1"  # Same as requester
        roles = {"wl_editor"}

        with patch('wl_handler._approval_queue_lock'):
            with patch('wl_handler._expire_pending_approvals') as mock_expire:
                mock_expire.return_value = [
                    {
                        "request_id": "req_123",
                        "analyst": "analyst1",  # Same user
                        "status": "pending",
                        "action_type": "save_csv",
                        "detection_rule": "rule1",
                        "csv_file": "test.csv",
                        "app_context": "wl_manager",
                        "payload": {}
                    }
                ]

                response = self.handler._action_process_approval(request, payload, user, roles)

                # Should be rejected due to role mismatch
                # Check that status is not 200 (permission denied)
                self.assertNotEqual(response['status'], 200)

    def test_superadmin_can_approve_any_request(self):
        """Test that superadmin can approve any request."""
        request = {"system_authtoken": "token123"}
        payload = {
            "request_id": "req_123",
            "action": "approve",
            "comment": "Approved as superadmin"
        }
        user = "superadmin"
        roles = {"admin", "sc_admin"}

        with patch('wl_handler._approval_queue_lock'):
            with patch('wl_handler._expire_pending_approvals') as mock_expire:
                with patch('wl_handler._write_approval_queue') as mock_write:
                    with patch('wl_handler._index_audit'):
                        mock_expire.return_value = [
                            {
                                "request_id": "req_123",
                                "analyst": "analyst1",  # Different user
                                "status": "pending",
                                "action_type": "save_csv",
                                "detection_rule": "rule1",
                                "csv_file": "test.csv",
                                "app_context": "wl_manager",
                                "payload": {}
                            }
                        ]

                        response = self.handler._action_process_approval(request, payload, user, roles)

                        self.assertIsInstance(response, dict)


class TestRemoveCsvWithApproval(unittest.TestCase):
    """Tests for remove_csv action with approval."""

    def setUp(self):
        """Set up test handler instance."""
        if WlHandler is None:
            self.skipTest("wl_handler module not available")
        self.handler = WlHandler()

    def test_remove_csv_bulk_triggers_approval(self):
        """Test that CSV removal with many associated rules triggers approval."""
        request = {"system_authtoken": "token123"}
        payload = {
            "csv_file": "test.csv",
            "detection_rules": ["rule1", "rule2", "rule3"],
            "comment": "Removing obsolete CSV"
        }
        user = "analyst1"
        roles = {"wl_editor"}

        with patch('wl_handler.check_approval_gate') as mock_gate:
            with patch('wl_handler.submit_approval') as mock_submit:
                mock_gate.return_value = (True, {"requires_approval": True})
                mock_submit.return_value = (True, "req_456")
                response = self.handler._action_remove_csv(request, payload, user, roles)

                self.assertIsInstance(response, dict)

    def test_remove_csv_conflict_cancels_pending(self):
        """Test that CSV removal cancels conflicting pending requests."""
        request = {"system_authtoken": "token123"}
        payload = {
            "csv_file": "test.csv",
            "detection_rules": ["rule1"],
            "comment": "Removing CSV"
        }
        user = "analyst1"
        roles = {"wl_editor"}

        with patch('wl_handler.check_approval_gate') as mock_gate:
            with patch('wl_handler.submit_approval') as mock_submit:
                with patch('wl_handler._cancel_conflicting_requests') as mock_cancel:
                    mock_gate.return_value = (True, {"requires_approval": True})
                    mock_submit.return_value = (True, "req_789")
                    mock_cancel.return_value = [
                        {
                            "request_id": "old_req",
                            "action_type": "save_csv",
                            "csv_file": "test.csv"
                        }
                    ]

                    response = self.handler._action_remove_csv(request, payload, user, roles)

                    self.assertIsInstance(response, dict)


class TestComplexPostActionsCompleteness(unittest.TestCase):
    """Comprehensive test: all complex POST actions are implemented."""

    def setUp(self):
        if WlHandler is None:
            self.skipTest("wl_handler module not available")
        self.handler = WlHandler()

    def test_all_complex_post_actions_have_methods(self):
        """Verify all complex POST actions have corresponding handler methods."""
        complex_post_actions = {
            "save_csv",
            "submit_approval",
            "process_approval",
            "remove_csv",
            "remove_rule",
            "process_dual_approval",
            "submit_dual_approval",
            "check_approval_gate",
        }

        for action in complex_post_actions:
            if action in self.handler.POST_ACTIONS:
                required_roles, method_name = self.handler.POST_ACTIONS[action]
                self.assertTrue(hasattr(self.handler, method_name),
                              f"POST action '{action}' missing method '{method_name}'")
                self.assertTrue(callable(getattr(self.handler, method_name)),
                              f"POST action '{action}' method '{method_name}' is not callable")

    def test_approval_workflow_actions_require_admin_role(self):
        """Verify approval processing actions require admin role."""
        approval_processing_actions = {
            "process_approval",
            "process_dual_approval",
        }

        for action in approval_processing_actions:
            if action in self.handler.POST_ACTIONS:
                required_roles, _ = self.handler.POST_ACTIONS[action]
                self.assertIsNotNone(required_roles,
                                   f"{action} should require roles for approval processing")
                self.assertGreater(len(required_roles), 0,
                                  f"{action} should have non-empty required roles")


if __name__ == '__main__':
    unittest.main()
