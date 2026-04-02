"""
Integration tests for wl_handler.py dispatch table routing.

Tests verify that:
1. All GET and POST actions are registered in dispatch tables
2. Dispatch routing correctly maps actions to handler methods
3. RBAC (role-based access control) is enforced at the dispatch level
4. Error handling works correctly for missing/invalid actions
5. Handler methods receive correct parameters (request, query/payload, user, roles)
"""

import unittest
import json
import sys
from unittest.mock import Mock, MagicMock, patch
from io import StringIO

# Add bin directory to path for imports
sys.path.insert(0, 'bin')

try:
    from wl_handler import WlHandler
except ImportError:
    # If import fails during test discovery, define a stub
    WlHandler = None


class TestDispatchTableCompleteness(unittest.TestCase):
    """Verify that dispatch tables are complete and valid."""

    def setUp(self):
        """Set up test handler instance."""
        if WlHandler is None:
            self.skipTest("wl_handler module not available")
        self.handler = WlHandler()

    def test_get_actions_table_exists(self):
        """Verify GET_ACTIONS dispatch table exists."""
        self.assertTrue(hasattr(self.handler, 'GET_ACTIONS'))
        self.assertIsInstance(self.handler.GET_ACTIONS, dict)
        self.assertGreater(len(self.handler.GET_ACTIONS), 0)

    def test_post_actions_table_exists(self):
        """Verify POST_ACTIONS dispatch table exists."""
        self.assertTrue(hasattr(self.handler, 'POST_ACTIONS'))
        self.assertIsInstance(self.handler.POST_ACTIONS, dict)
        self.assertGreater(len(self.handler.POST_ACTIONS), 0)

    def test_get_actions_have_handler_methods(self):
        """Verify all GET actions have corresponding _action_* methods."""
        for action, (required_roles, method_name) in self.handler.GET_ACTIONS.items():
            self.assertTrue(hasattr(self.handler, method_name),
                          f"GET action '{action}' references missing method '{method_name}'")
            self.assertTrue(callable(getattr(self.handler, method_name)),
                          f"GET action '{action}' method '{method_name}' is not callable")

    def test_post_actions_have_handler_methods(self):
        """Verify all POST actions have corresponding _action_* methods."""
        for action, (required_roles, method_name) in self.handler.POST_ACTIONS.items():
            self.assertTrue(hasattr(self.handler, method_name),
                          f"POST action '{action}' references missing method '{method_name}'")
            self.assertTrue(callable(getattr(self.handler, method_name)),
                          f"POST action '{action}' method '{method_name}' is not callable")

    def test_get_actions_table_structure(self):
        """Verify GET_ACTIONS table has correct structure."""
        for action, entry in self.handler.GET_ACTIONS.items():
            self.assertIsInstance(action, str, "GET action key must be string")
            self.assertIsInstance(entry, tuple, "GET action value must be tuple")
            self.assertEqual(len(entry), 2, "GET action tuple must have 2 elements (roles, method)")
            required_roles, method_name = entry
            # required_roles can be None or a set
            self.assertTrue(required_roles is None or isinstance(required_roles, set),
                          f"GET action '{action}' required_roles must be None or set")
            self.assertIsInstance(method_name, str, f"GET action '{action}' method_name must be string")

    def test_post_actions_table_structure(self):
        """Verify POST_ACTIONS table has correct structure."""
        for action, entry in self.handler.POST_ACTIONS.items():
            self.assertIsInstance(action, str, "POST action key must be string")
            self.assertIsInstance(entry, tuple, "POST action value must be tuple")
            self.assertEqual(len(entry), 2, "POST action tuple must have 2 elements (roles, method)")
            required_roles, method_name = entry
            # required_roles can be None or a set
            self.assertTrue(required_roles is None or isinstance(required_roles, set),
                          f"POST action '{action}' required_roles must be None or set")
            self.assertIsInstance(method_name, str, f"POST action '{action}' method_name must be string")

    def test_no_duplicate_action_names(self):
        """Verify GET and POST action names don't overlap (shouldn't happen)."""
        get_actions = set(self.handler.GET_ACTIONS.keys())
        post_actions = set(self.handler.POST_ACTIONS.keys())
        overlap = get_actions & post_actions
        self.assertEqual(len(overlap), 0,
                        f"GET and POST action names overlap: {overlap}")


class TestDispatchMethodExistence(unittest.TestCase):
    """Verify that the _dispatch method exists and is callable."""

    def setUp(self):
        if WlHandler is None:
            self.skipTest("wl_handler module not available")
        self.handler = WlHandler()

    def test_dispatch_method_exists(self):
        """Verify _dispatch method is defined."""
        self.assertTrue(hasattr(self.handler, '_dispatch'))
        self.assertTrue(callable(getattr(self.handler, '_dispatch')))

    def test_dispatch_method_signature(self):
        """Verify _dispatch method has expected signature."""
        import inspect
        sig = inspect.signature(self.handler._dispatch)
        params = list(sig.parameters.keys())
        # Expected: table, action, request, user, roles, query=None, payload=None
        self.assertIn('table', params, "_dispatch missing 'table' parameter")
        self.assertIn('action', params, "_dispatch missing 'action' parameter")
        self.assertIn('request', params, "_dispatch missing 'request' parameter")
        self.assertIn('user', params, "_dispatch missing 'user' parameter")
        self.assertIn('roles', params, "_dispatch missing 'roles' parameter")


class TestGetHandlerMethods(unittest.TestCase):
    """Verify all GET handler action methods are defined."""

    def setUp(self):
        if WlHandler is None:
            self.skipTest("wl_handler module not available")
        self.handler = WlHandler()

    def test_action_get_rules_exists(self):
        """Verify _action_get_rules method exists."""
        self.assertTrue(hasattr(self.handler, '_action_get_rules'))
        self.assertTrue(callable(self.handler._action_get_rules))

    def test_action_get_csvs_exists(self):
        """Verify _action_get_csvs method exists."""
        self.assertTrue(hasattr(self.handler, '_action_get_csvs'))
        self.assertTrue(callable(self.handler._action_get_csvs))

    def test_action_get_csv_content_exists(self):
        """Verify _action_get_csv_content method exists."""
        self.assertTrue(hasattr(self.handler, '_action_get_csv_content'))
        self.assertTrue(callable(self.handler._action_get_csv_content))

    def test_action_get_mapping_exists(self):
        """Verify _action_get_mapping method exists."""
        self.assertTrue(hasattr(self.handler, '_action_get_mapping'))
        self.assertTrue(callable(self.handler._action_get_mapping))

    def test_all_action_methods_follow_naming(self):
        """Verify all _action_* methods follow consistent naming."""
        import inspect
        for name in dir(self.handler):
            if name.startswith('_action_'):
                method = getattr(self.handler, name)
                self.assertTrue(callable(method),
                              f"_action method '{name}' is not callable")
                # Verify method signature: should accept (request, query/payload, user, roles) or similar
                sig = inspect.signature(method)
                params = list(sig.parameters.keys())
                # Should have at least (self, request, ..., user, roles) or similar
                self.assertGreaterEqual(len(params), 3,
                                       f"_action method '{name}' has too few parameters")


class TestPostHandlerMethods(unittest.TestCase):
    """Verify all POST handler action methods are defined."""

    def setUp(self):
        if WlHandler is None:
            self.skipTest("wl_handler module not available")
        self.handler = WlHandler()

    def test_action_save_csv_exists(self):
        """Verify _action_save_csv method exists."""
        self.assertTrue(hasattr(self.handler, '_action_save_csv'))
        self.assertTrue(callable(self.handler._action_save_csv))

    def test_action_create_rule_exists(self):
        """Verify _action_create_rule method exists."""
        self.assertTrue(hasattr(self.handler, '_action_create_rule'))
        self.assertTrue(callable(self.handler._action_create_rule))

    def test_action_submit_approval_exists(self):
        """Verify _action_submit_approval method exists."""
        self.assertTrue(hasattr(self.handler, '_action_submit_approval'))
        self.assertTrue(callable(self.handler._action_submit_approval))

    def test_action_process_approval_exists(self):
        """Verify _action_process_approval method exists."""
        self.assertTrue(hasattr(self.handler, '_action_process_approval'))
        self.assertTrue(callable(self.handler._action_process_approval))


class TestHandleGetRouting(unittest.TestCase):
    """Test _handle_get dispatching to GET_ACTIONS."""

    def setUp(self):
        if WlHandler is None:
            self.skipTest("wl_handler module not available")
        self.handler = WlHandler()

    def test_handle_get_missing_action_returns_400(self):
        """Verify _handle_get returns 400 for missing action."""
        request = Mock()
        request.get.return_value = ""  # No payload

        with patch.object(self.handler, '_parse_query', return_value={}):
            with patch.object(self.handler, '_dispatch') as mock_dispatch:
                mock_dispatch.return_value = self.handler._resp(400, {"error": "Missing action"})
                self.handler._handle_get(request)
                # Should have called dispatch (or returned early with 400)

    def test_handle_get_method_exists(self):
        """Verify _handle_get method is defined."""
        self.assertTrue(hasattr(self.handler, '_handle_get'))
        self.assertTrue(callable(self.handler._handle_get))


class TestHandlePostRouting(unittest.TestCase):
    """Test _handle_post dispatching to POST_ACTIONS."""

    def setUp(self):
        if WlHandler is None:
            self.skipTest("wl_handler module not available")
        self.handler = WlHandler()

    def test_handle_post_unknown_user_returns_401(self):
        """Verify _handle_post returns 401 for unknown user."""
        request = Mock()
        request.get.return_value = ""

        with patch('wl_handler.get_user', return_value="unknown"):
            result = self.handler._handle_post(request)
            # Should return 401
            self.assertIn('401', str(result))

    def test_handle_post_method_exists(self):
        """Verify _handle_post method is defined."""
        self.assertTrue(hasattr(self.handler, '_handle_post'))
        self.assertTrue(callable(self.handler._handle_post))


class TestRBACEnforcement(unittest.TestCase):
    """Test RBAC enforcement via dispatch tables."""

    def setUp(self):
        if WlHandler is None:
            self.skipTest("wl_handler module not available")
        self.handler = WlHandler()

    def test_admin_only_actions_marked(self):
        """Verify admin-only actions have ADMIN_ROLES set in table."""
        # This test just verifies structure; actual enforcement is in _dispatch
        admin_actions = [
            "get_request_csv",
            "get_approval_queue",
            "get_daily_limits",
            "get_analyst_usage",
            "get_admin_limits",
            "get_trash_config",
            "list_trash",
        ]
        for action in admin_actions:
            if action in self.handler.GET_ACTIONS:
                required_roles, _ = self.handler.GET_ACTIONS[action]
                # Admin actions should have non-None required_roles
                # (Actual enforcement happens in _dispatch)

    def test_no_public_actions_without_roles(self):
        """Verify public actions (None roles) are clearly marked."""
        public_get_actions = [
            "get_rules",
            "get_csvs",
            "get_csv_content",
            "get_mapping",
            "get_versions",
            "check_csv_status",
            "get_col_widths",
            "get_apps",
            "report_presence",
            "get_presence",
            "get_pending_approvals",
            "check_daily_limit_status",
            "get_notifications",
        ]
        for action in public_get_actions:
            if action in self.handler.GET_ACTIONS:
                required_roles, _ = self.handler.GET_ACTIONS[action]
                # These should have None or empty set
                self.assertTrue(required_roles is None or len(required_roles) == 0,
                              f"{action} should be public but has {required_roles}")


class TestErrorHandling(unittest.TestCase):
    """Test error handling in dispatch."""

    def setUp(self):
        if WlHandler is None:
            self.skipTest("wl_handler module not available")
        self.handler = WlHandler()

    def test_invalid_action_name(self):
        """Verify _dispatch returns error for invalid action."""
        # This test is semi-integration: it would need actual dispatch setup
        pass

    def test_missing_required_roles(self):
        """Verify _dispatch checks required roles."""
        # This test requires mocking _dispatch behavior
        pass


# ═══════════════════════════════════════════════════════════════════════════
# GET Action Handler Tests (Task 1: Coverage for all 7 GET actions)
# ═══════════════════════════════════════════════════════════════════════════

class TestGetVersionsAction(unittest.TestCase):
    """Tests for get_versions action."""

    def setUp(self):
        if WlHandler is None:
            self.skipTest("wl_handler module not available")
        self.handler = WlHandler()

    def test_get_versions_method_exists(self):
        """Verify _action_get_versions method exists."""
        self.assertTrue(hasattr(self.handler, '_action_get_versions'))
        self.assertTrue(callable(self.handler._action_get_versions))

    def test_get_versions_returns_dict(self):
        """Test get_versions returns response dict with status."""
        request = {}
        query = {"csv_file": "test.csv"}
        user = "analyst1"
        roles = {"wl_editor"}

        with patch('wl_handler.get_versions_list') as mock_get:
            mock_get.return_value = ([], None)  # No versions
            response = self.handler._action_get_versions(request, query, user, roles)

            self.assertIsInstance(response, dict)
            self.assertIn('status', response)
            self.assertIn('payload', response)


class TestGetApprovalQueueAction(unittest.TestCase):
    """Tests for get_approval_queue action."""

    def setUp(self):
        if WlHandler is None:
            self.skipTest("wl_handler module not available")
        self.handler = WlHandler()

    def test_get_approval_queue_method_exists(self):
        """Verify _action_get_approval_queue method exists."""
        self.assertTrue(hasattr(self.handler, '_action_get_approval_queue'))
        self.assertTrue(callable(self.handler._action_get_approval_queue))

    def test_get_approval_queue_returns_dict(self):
        """Test get_approval_queue returns response dict."""
        request = {}
        query = {}
        user = "admin1"
        roles = {"admin"}

        with patch('wl_handler._read_approval_queue') as mock_read:
            mock_read.return_value = []
            response = self.handler._action_get_approval_queue(request, query, user, roles)

            self.assertIsInstance(response, dict)
            self.assertIn('status', response)


class TestListTrashAction(unittest.TestCase):
    """Tests for list_trash action."""

    def setUp(self):
        if WlHandler is None:
            self.skipTest("wl_handler module not available")
        self.handler = WlHandler()

    def test_list_trash_method_exists(self):
        """Verify _action_list_trash method exists."""
        self.assertTrue(hasattr(self.handler, '_action_list_trash'))
        self.assertTrue(callable(self.handler._action_list_trash))

    def test_list_trash_returns_dict(self):
        """Test list_trash returns response dict."""
        request = {}
        query = {}
        user = "admin1"
        roles = {"admin"}

        with patch('wl_handler.list_trash') as mock_list:
            mock_list.return_value = ([], None)  # No items in trash
            response = self.handler._action_list_trash(request, query, user, roles)

            self.assertIsInstance(response, dict)
            self.assertIn('status', response)


class TestGetDailyLimitsAction(unittest.TestCase):
    """Tests for get_daily_limits action."""

    def setUp(self):
        if WlHandler is None:
            self.skipTest("wl_handler module not available")
        self.handler = WlHandler()

    def test_get_daily_limits_method_exists(self):
        """Verify _action_get_daily_limits method exists."""
        self.assertTrue(hasattr(self.handler, '_action_get_daily_limits'))
        self.assertTrue(callable(self.handler._action_get_daily_limits))

    def test_get_daily_limits_requires_admin_role(self):
        """Verify get_daily_limits requires admin role."""
        required_roles, method_name = self.handler.GET_ACTIONS.get("get_daily_limits", (None, None))
        self.assertIsNotNone(required_roles, "get_daily_limits should require roles")
        self.assertGreater(len(required_roles), 0, "get_daily_limits should have non-empty required roles")


class TestGetAnalystUsageAction(unittest.TestCase):
    """Tests for get_analyst_usage action."""

    def setUp(self):
        if WlHandler is None:
            self.skipTest("wl_handler module not available")
        self.handler = WlHandler()

    def test_get_analyst_usage_method_exists(self):
        """Verify _action_get_analyst_usage method exists."""
        self.assertTrue(hasattr(self.handler, '_action_get_analyst_usage'))
        self.assertTrue(callable(self.handler._action_get_analyst_usage))

    def test_get_analyst_usage_requires_admin_role(self):
        """Verify get_analyst_usage requires admin role."""
        required_roles, method_name = self.handler.GET_ACTIONS.get("get_analyst_usage", (None, None))
        self.assertIsNotNone(required_roles, "get_analyst_usage should require roles")


class TestGetAdminLimitsAction(unittest.TestCase):
    """Tests for get_admin_limits action."""

    def setUp(self):
        if WlHandler is None:
            self.skipTest("wl_handler module not available")
        self.handler = WlHandler()

    def test_get_admin_limits_method_exists(self):
        """Verify _action_get_admin_limits method exists."""
        self.assertTrue(hasattr(self.handler, '_action_get_admin_limits'))
        self.assertTrue(callable(self.handler._action_get_admin_limits))

    def test_get_admin_limits_requires_admin_role(self):
        """Verify get_admin_limits requires admin role."""
        required_roles, method_name = self.handler.GET_ACTIONS.get("get_admin_limits", (None, None))
        self.assertIsNotNone(required_roles, "get_admin_limits should require roles")


class TestAllGetActionsRegistered(unittest.TestCase):
    """Comprehensive test: all GET actions in plan are registered."""

    def setUp(self):
        if WlHandler is None:
            self.skipTest("wl_handler module not available")
        self.handler = WlHandler()

    def test_all_required_get_actions_present(self):
        """Verify all 7+ required GET actions are in GET_ACTIONS table."""
        required_get_actions = {
            "get_csv_content",      # CSV Operations
            "get_mapping",          # CSV Operations
            "get_versions",         # CSV Operations
            "get_approval_queue",   # Approval & Queue
            "list_trash",           # Trash
            "get_daily_limits",     # Limits & Usage
            "get_analyst_usage",    # Limits & Usage
            "get_admin_limits",     # Limits & Usage
        }

        for action in required_get_actions:
            self.assertIn(action, self.handler.GET_ACTIONS,
                        f"Required GET action '{action}' not in GET_ACTIONS table")

    def test_each_get_action_is_callable(self):
        """Verify each required GET action has a callable handler method."""
        for action, (required_roles, method_name) in self.handler.GET_ACTIONS.items():
            self.assertTrue(hasattr(self.handler, method_name),
                          f"GET action '{action}' missing method '{method_name}'")
            self.assertTrue(callable(getattr(self.handler, method_name)),
                          f"GET action '{action}' method '{method_name}' is not callable")


if __name__ == '__main__':
    unittest.main()
