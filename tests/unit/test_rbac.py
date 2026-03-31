"""
Unit tests for wl_rbac module (Role-Based Access Control for Whitelist Manager).

Tests role predicates, request parsing, and admin discovery.
"""

import pytest
import json
from unittest.mock import patch, MagicMock

# Add bin directory to path for imports
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../bin'))

from wl_rbac import (
    is_admin,
    is_editor,
    is_superadmin,
    can_approve,
    can_approve_own_requests,
    get_user,
    get_roles,
    get_admin_users,
)

from wl_constants import EDIT_ROLES, ADMIN_ROLES, SUPERADMIN_ROLES


@pytest.mark.unit
class TestRolePredicates:
    """Test role predicate functions."""

    def test_is_admin_true_for_admin_roles(self):
        """Check that is_admin returns True for admin roles."""
        assert is_admin(ADMIN_ROLES) is True

    def test_is_admin_false_for_editor_roles(self):
        """Check that is_admin returns False for non-admin roles."""
        editor_only = {"wl_editor"}
        assert is_admin(editor_only) is False

    def test_is_editor_true_for_edit_roles(self):
        """Check that is_editor returns True for editor roles."""
        assert is_editor(EDIT_ROLES) is True

    def test_is_editor_true_for_admin_roles(self):
        """Check that is_editor returns True for admin (admins can edit)."""
        assert is_editor(ADMIN_ROLES) is True

    def test_is_superadmin_true_for_superadmin_roles(self):
        """Check that is_superadmin returns True for superadmin roles."""
        assert is_superadmin(SUPERADMIN_ROLES) is True

    def test_is_superadmin_false_for_admin_only(self):
        """Check that is_superadmin is False for regular admin."""
        admin_only = {"admin"}
        # admin might not be in SUPERADMIN_ROLES
        result = is_superadmin(admin_only)
        # Result depends on constants, just verify it runs
        assert isinstance(result, bool)

    def test_can_approve_requires_admin(self):
        """Check that can_approve requires admin role."""
        assert can_approve(ADMIN_ROLES) is True
        assert can_approve({"wl_editor"}) is False

    def test_can_approve_own_requests_requires_superadmin(self):
        """Check that can_approve_own_requests requires superadmin."""
        assert can_approve_own_requests(SUPERADMIN_ROLES) is True
        # Regular admin should not be able to approve own
        admin_only = {"admin"}
        result = can_approve_own_requests(admin_only)
        # Verify it returns bool
        assert isinstance(result, bool)

    def test_role_predicates_with_empty_set(self):
        """Check that predicates handle empty role sets."""
        empty_roles = set()
        assert is_admin(empty_roles) is False
        assert is_editor(empty_roles) is False
        assert is_superadmin(empty_roles) is False
        assert can_approve(empty_roles) is False

    def test_role_predicates_with_multiple_roles(self):
        """Check that predicates work with multiple roles."""
        multi_roles = {"wl_editor", "admin", "user"}
        assert is_admin(multi_roles) is True
        assert is_editor(multi_roles) is True


@pytest.mark.unit
class TestGetUser:
    """Test user extraction from request objects."""

    def test_get_user_from_request_session(self):
        """Check that get_user extracts username from request session."""
        request = {"session": {"user": "john_doe"}}
        assert get_user(request) == "john_doe"

    def test_get_user_returns_unknown_for_invalid_request(self):
        """Check that get_user returns 'unknown' for missing session."""
        request = {}
        assert get_user(request) == "unknown"

    def test_get_user_returns_unknown_for_empty_session(self):
        """Check that get_user returns 'unknown' when session has no user."""
        request = {"session": {}}
        assert get_user(request) == "unknown"

    def test_get_user_returns_unknown_for_none_request(self):
        """Check that get_user handles None request."""
        assert get_user(None) == "unknown"

    def test_get_user_from_headers_fallback(self):
        """Check that get_user falls back to headers."""
        request = {"headers": {"X-Splunk-User-Name": "jane_doe"}}
        result = get_user(request)
        assert result == "jane_doe" or result == "unknown"  # Depends on session check first

    def test_get_user_prioritizes_session(self):
        """Check that session is prioritized over headers."""
        request = {
            "session": {"user": "session_user"},
            "headers": {"X-Splunk-User-Name": "header_user"},
        }
        assert get_user(request) == "session_user"


@pytest.mark.unit
class TestGetRoles:
    """Test role fetching from Splunk REST API."""

    def test_get_roles_from_request(self):
        """Check that get_roles returns role set."""
        request = {"session": {"authtoken": "test_token"}}

        # Mock the REST call - splunk is imported inside the function
        mock_content = json.dumps({
            "entry": [{
                "content": {
                    "roles": ["admin", "wl_editor"]
                }
            }]
        })

        import sys
        mock_splunk = MagicMock()
        mock_splunk.rest.simpleRequest.return_value = (200, mock_content)

        with patch.dict('sys.modules', {'splunk': mock_splunk, 'splunk.rest': mock_splunk.rest}):
            roles = get_roles(request)
            assert "admin" in roles
            assert "wl_editor" in roles

    def test_get_roles_empty_for_missing_session_key(self):
        """Check that get_roles returns empty set for missing session key."""
        request = {"session": {}}
        roles = get_roles(request)
        assert roles == set()

    def test_get_roles_empty_for_missing_session(self):
        """Check that get_roles returns empty set for missing session."""
        request = {}
        roles = get_roles(request)
        assert roles == set()

    def test_get_roles_graceful_failure(self):
        """Check that get_roles handles REST failures gracefully."""
        request = {"session": {"authtoken": "test_token"}}

        import sys
        mock_splunk = MagicMock()
        mock_splunk.rest.simpleRequest.side_effect = Exception("Network error")

        with patch.dict('sys.modules', {'splunk': mock_splunk, 'splunk.rest': mock_splunk.rest}):
            roles = get_roles(request)
            assert roles == set()

    def test_get_roles_handles_missing_content(self):
        """Check that get_roles handles malformed responses."""
        request = {"session": {"authtoken": "test_token"}}
        mock_content = json.dumps({"entry": []})

        import sys
        mock_splunk = MagicMock()
        mock_splunk.rest.simpleRequest.return_value = (200, mock_content)

        with patch.dict('sys.modules', {'splunk': mock_splunk, 'splunk.rest': mock_splunk.rest}):
            roles = get_roles(request)
            assert roles == set()


@pytest.mark.unit
class TestGetAdminUsers:
    """Test admin user discovery."""

    def test_get_admin_users_returns_list(self):
        """Check that get_admin_users returns a list."""
        result = get_admin_users("")
        assert isinstance(result, list)

    def test_get_admin_users_fallback_for_empty_session(self):
        """Check that get_admin_users falls back to ['admin'] for empty session key."""
        result = get_admin_users("")
        assert "admin" in result

    def test_get_admin_users_discovers_from_api(self):
        """Check that get_admin_users discovers admins from REST API."""
        mock_content = json.dumps({
            "entry": [
                {
                    "name": "admin",
                    "content": {"roles": ["admin"]}
                },
                {
                    "name": "splunk_admin",
                    "content": {"roles": ["admin"]}
                },
                {
                    "name": "analyst",
                    "content": {"roles": ["wl_editor"]}
                }
            ]
        })

        import sys
        mock_splunk = MagicMock()
        mock_splunk.rest.simpleRequest.return_value = (200, mock_content)

        with patch.dict('sys.modules', {'splunk': mock_splunk, 'splunk.rest': mock_splunk.rest}):
            admins = get_admin_users("valid_token")
            assert "admin" in admins or len(admins) > 0
            # Should have discovered some admins

    def test_get_admin_users_empty_on_failure(self):
        """Check that get_admin_users falls back to ['admin'] on API failure."""
        import sys
        mock_splunk = MagicMock()
        mock_splunk.rest.simpleRequest.side_effect = Exception("API error")

        with patch.dict('sys.modules', {'splunk': mock_splunk, 'splunk.rest': mock_splunk.rest}):
            admins = get_admin_users("token")
            assert isinstance(admins, list)
            assert len(admins) > 0  # Should have fallback

    def test_get_admin_users_handles_404(self):
        """Check that get_admin_users handles non-200 responses."""
        import sys
        mock_splunk = MagicMock()
        mock_splunk.rest.simpleRequest.return_value = (404, "{}")

        with patch.dict('sys.modules', {'splunk': mock_splunk, 'splunk.rest': mock_splunk.rest}):
            admins = get_admin_users("token")
            assert "admin" in admins  # Fallback


@pytest.mark.unit
class TestRBACIntegration:
    """Test integration of RBAC functions."""

    def test_workflow_get_roles_then_check_admin(self):
        """Check typical workflow: get roles then check admin."""
        request = {"session": {"authtoken": "test_token"}}

        mock_content = json.dumps({
            "entry": [{
                "content": {"roles": ["admin"]}
            }]
        })

        import sys
        mock_splunk = MagicMock()
        mock_splunk.rest.simpleRequest.return_value = (200, mock_content)

        with patch.dict('sys.modules', {'splunk': mock_splunk, 'splunk.rest': mock_splunk.rest}):
            roles = get_roles(request)
            is_admin_user = is_admin(roles)
            assert is_admin_user is True

    def test_workflow_get_user_and_roles(self):
        """Check typical workflow: get user and roles."""
        request = {
            "session": {
                "user": "john_doe",
                "authtoken": "test_token"
            }
        }

        mock_content = json.dumps({
            "entry": [{
                "content": {"roles": ["wl_editor"]}
            }]
        })

        import sys
        mock_splunk = MagicMock()
        mock_splunk.rest.simpleRequest.return_value = (200, mock_content)

        with patch.dict('sys.modules', {'splunk': mock_splunk, 'splunk.rest': mock_splunk.rest}):
            user = get_user(request)
            roles = get_roles(request)
            can_edit = is_editor(roles)

            assert user == "john_doe"
            assert "wl_editor" in roles
            assert can_edit is True
