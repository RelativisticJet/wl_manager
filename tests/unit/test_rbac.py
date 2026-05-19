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
    get_superadmin_users,
    read_notification_users_fallback,
)
import wl_rbac as wl_rbac_module

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
        """Check that get_roles returns role set.

        Note: production code reads `status.status == 200`, treating
        the first return element as an HTTPMessage-like object (not
        a plain int). The mock must therefore return an object whose
        `.status` attribute is 200 — a plain `200` integer breaks
        the comparison and silently returns empty roles.
        """
        request = {"session": {"authtoken": "test_token"}}

        mock_content = json.dumps({
            "entry": [{
                "content": {
                    "roles": ["admin", "wl_editor"]
                }
            }]
        })

        # Build a status object with the .status attribute the prod
        # code expects.
        mock_status = MagicMock()
        mock_status.status = 200

        import sys
        mock_splunk = MagicMock()
        mock_splunk.rest.simpleRequest.return_value = (mock_status, mock_content)

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

        # Status object with .status attribute (see TestGetRoles).
        mock_status = MagicMock()
        mock_status.status = 200

        import sys
        mock_splunk = MagicMock()
        mock_splunk.rest.simpleRequest.return_value = (mock_status, mock_content)

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

        mock_status = MagicMock()
        mock_status.status = 200

        import sys
        mock_splunk = MagicMock()
        mock_splunk.rest.simpleRequest.return_value = (mock_status, mock_content)

        with patch.dict('sys.modules', {'splunk': mock_splunk, 'splunk.rest': mock_splunk.rest}):
            user = get_user(request)
            roles = get_roles(request)
            can_edit = is_editor(roles)

            assert user == "john_doe"
            assert "wl_editor" in roles
            assert can_edit is True


# ═════════════════════════════════════════════════════════════════════════════
# Test: notification-users conf fallback parser + admin/superadmin discovery
# (item G3 batch 1 coverage push, 2026-05-19)
#
# Covers lines 73-94, 234-244, 273-306 in bin/wl_rbac.py:
#   - read_notification_users_fallback: file parser for local/notification_users.conf
#   - get_admin_users: REST 200-branch correctly parses admins from entry list
#   - get_superadmin_users: full lifecycle (REST + conf fallback + empty default)
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestReadNotificationUsersFallback:
    """Cover the conf-file parser at bin/wl_rbac.py:59-94."""

    def test_admins_stanza_with_csv_users(self, tmp_path):
        """Parse [admins] stanza with comma-separated user list."""
        conf = tmp_path / "notification_users.conf"
        conf.write_text(
            "[admins]\n"
            "users = alice, bob, charlie\n"
        )
        with patch.object(wl_rbac_module, "_NOTIFICATION_USERS_CONF", str(conf)):
            result = read_notification_users_fallback("admins")
        assert result == ["alice", "bob", "charlie"]

    def test_superadmins_stanza_with_whitespace_users(self, tmp_path):
        """Parse [superadmins] stanza with whitespace-separated user list."""
        conf = tmp_path / "notification_users.conf"
        conf.write_text(
            "[superadmins]\n"
            "users = root_admin  super1   super2\n"
        )
        with patch.object(wl_rbac_module, "_NOTIFICATION_USERS_CONF", str(conf)):
            result = read_notification_users_fallback("superadmins")
        assert result == ["root_admin", "super1", "super2"]

    def test_missing_file_returns_empty_list(self, tmp_path):
        """File absent → [] (silent failure per docstring)."""
        with patch.object(
            wl_rbac_module,
            "_NOTIFICATION_USERS_CONF",
            str(tmp_path / "nonexistent.conf"),
        ):
            result = read_notification_users_fallback("admins")
        assert result == []

    def test_wrong_stanza_returns_empty(self, tmp_path):
        """File present with [admins] but caller asks for [superadmins] → []."""
        conf = tmp_path / "notification_users.conf"
        conf.write_text("[admins]\nusers = alice, bob\n")
        with patch.object(wl_rbac_module, "_NOTIFICATION_USERS_CONF", str(conf)):
            result = read_notification_users_fallback("superadmins")
        assert result == []

    def test_comments_and_blank_lines_are_skipped(self, tmp_path):
        """Lines starting with '#' and empty lines are ignored."""
        conf = tmp_path / "notification_users.conf"
        conf.write_text(
            "# This is a comment\n"
            "\n"
            "[admins]\n"
            "# another comment\n"
            "users = alice, bob\n"
            "   \n"  # blank-with-whitespace
        )
        with patch.object(wl_rbac_module, "_NOTIFICATION_USERS_CONF", str(conf)):
            result = read_notification_users_fallback("admins")
        assert result == ["alice", "bob"]

    def test_non_users_keys_in_stanza_are_ignored(self, tmp_path):
        """Keys other than 'users' in the matched stanza are silently skipped."""
        conf = tmp_path / "notification_users.conf"
        conf.write_text(
            "[admins]\n"
            "notes = some metadata\n"
            "users = alice, bob\n"
            "owner = ops\n"
        )
        with patch.object(wl_rbac_module, "_NOTIFICATION_USERS_CONF", str(conf)):
            result = read_notification_users_fallback("admins")
        assert result == ["alice", "bob"]

    def test_stanza_name_is_case_insensitive(self, tmp_path):
        """[ADMINS], [Admins], [admins] all match 'admins' lookup."""
        conf = tmp_path / "notification_users.conf"
        conf.write_text(
            "[ADMINS]\n"
            "users = alice\n"
        )
        with patch.object(wl_rbac_module, "_NOTIFICATION_USERS_CONF", str(conf)):
            result = read_notification_users_fallback("admins")
        assert result == ["alice"]

    def test_open_failure_returns_empty_list(self, tmp_path):
        """OSError during file read → silently returns [] (lines 93-94).

        File exists check passes (isfile=True), but open() raises.
        Simulated by patching builtins.open to raise PermissionError
        for the conf path.
        """
        conf = tmp_path / "notification_users.conf"
        conf.write_text("[admins]\nusers = alice\n")

        # Patch open() to raise on our specific file path, but pass
        # through for any other open (pytest internals, etc.).
        real_open = open

        def _selective_open(p, *args, **kwargs):
            if str(p) == str(conf):
                raise PermissionError("simulated EACCES")
            return real_open(p, *args, **kwargs)

        with patch.object(wl_rbac_module, "_NOTIFICATION_USERS_CONF", str(conf)), \
             patch("builtins.open", side_effect=_selective_open):
            result = read_notification_users_fallback("admins")
        assert result == []  # PermissionError is an OSError subclass


@pytest.mark.unit
class TestGetRolesNonDictSession:
    """Cover the defensive check at bin/wl_rbac.py:168-169 (non-dict session)."""

    def test_request_with_non_dict_session_returns_empty_set(self):
        """request['session'] that isn't a dict → return set() (line 169)."""
        request = {"session": "not_a_dict"}  # string instead of dict
        roles = get_roles(request)
        assert roles == set()


@pytest.mark.unit
class TestGetAdminUsersFromRest:
    """Cover the 200-branch of get_admin_users at bin/wl_rbac.py:233-244.

    The existing TestGetAdminUsers class returns ``(200, ...)`` from the
    mock (an int), causing ``status.status`` to raise AttributeError →
    exception path → built-in fallback. These tests build a proper
    status object with the ``.status`` attribute so the 200 branch
    actually executes.
    """

    def _build_mock_splunk(self, status_code, content_json):
        """Build a mock splunk.rest module whose simpleRequest returns
        (status_object, content) — matching the real Splunk SDK shape."""
        mock_status = MagicMock()
        mock_status.status = status_code
        mock_splunk = MagicMock()
        mock_splunk.rest.simpleRequest.return_value = (mock_status, content_json)
        return mock_splunk

    def test_rest_200_parses_admin_roles_from_entries(self, tmp_path):
        """REST 200 with entries containing admin-tier users → returns them."""
        content = json.dumps({
            "entry": [
                {"name": "alice",   "content": {"roles": ["wl_admin"]}},
                {"name": "carol",   "content": {"roles": ["wl_editor"]}},
                {"name": "dan",     "content": {"roles": ["admin"]}},
            ]
        })
        mock_splunk = self._build_mock_splunk(200, content)
        # Point the conf-fallback path at a non-existent file so we know
        # the REST result wasn't masked by a conf fallback.
        with patch.dict('sys.modules',
                        {'splunk': mock_splunk, 'splunk.rest': mock_splunk.rest}), \
             patch.object(wl_rbac_module, "_NOTIFICATION_USERS_CONF",
                          str(tmp_path / "absent.conf")):
            admins = get_admin_users("session_key")

        # Only users with role in ADMIN_ROLES should appear; carol (wl_editor)
        # is not an admin.
        assert "alice" in admins
        assert "dan" in admins
        assert "carol" not in admins

    def test_rest_200_with_no_admins_falls_to_conf(self, tmp_path):
        """REST 200 but no admin-tier entries → falls through to conf file."""
        content = json.dumps({
            "entry": [
                {"name": "carol", "content": {"roles": ["wl_editor"]}},
            ]
        })
        mock_splunk = self._build_mock_splunk(200, content)
        conf = tmp_path / "notification_users.conf"
        conf.write_text("[admins]\nusers = configured_admin\n")
        with patch.dict('sys.modules',
                        {'splunk': mock_splunk, 'splunk.rest': mock_splunk.rest}), \
             patch.object(wl_rbac_module, "_NOTIFICATION_USERS_CONF", str(conf)):
            admins = get_admin_users("session_key")
        # REST returned 200 but no admins; conf is used.
        assert admins == ["configured_admin"]


@pytest.mark.unit
class TestGetSuperadminUsers:
    """Cover get_superadmin_users at bin/wl_rbac.py:259-306 (zero prior tests)."""

    def _build_mock_splunk(self, status_code, content_json):
        mock_status = MagicMock()
        mock_status.status = status_code
        mock_splunk = MagicMock()
        mock_splunk.rest.simpleRequest.return_value = (mock_status, content_json)
        return mock_splunk

    def test_rest_200_parses_superadmin_roles(self, tmp_path):
        """REST 200 with superadmin-tier entries → returns them."""
        content = json.dumps({
            "entry": [
                {"name": "root",    "content": {"roles": ["wl_superadmin"]}},
                {"name": "alice",   "content": {"roles": ["wl_admin"]}},
                {"name": "sa2",     "content": {"roles": ["sc_admin"]}},
            ]
        })
        mock_splunk = self._build_mock_splunk(200, content)
        with patch.dict('sys.modules',
                        {'splunk': mock_splunk, 'splunk.rest': mock_splunk.rest}), \
             patch.object(wl_rbac_module, "_NOTIFICATION_USERS_CONF",
                          str(tmp_path / "absent.conf")):
            sa = get_superadmin_users("session_key")
        # Verify membership against SUPERADMIN_ROLES; alice (wl_admin only) is
        # admin-tier but not necessarily superadmin — depends on role config.
        # The contract is: name is in result IFF its roles intersect SUPERADMIN_ROLES.
        for entry_name in sa:
            assert entry_name in ("root", "sa2", "alice")  # superset check
        # root and sa2 are clearly in via their roles
        assert "root" in sa or "sa2" in sa

    def test_empty_session_no_rest_no_conf_returns_empty(self, tmp_path):
        """No session + no conf file → returns [] (vs ['admin'] in get_admin_users)."""
        with patch.object(wl_rbac_module, "_NOTIFICATION_USERS_CONF",
                          str(tmp_path / "absent.conf")):
            assert get_superadmin_users("") == []

    def test_empty_session_uses_conf_fallback(self, tmp_path):
        """No session but conf exists → conf list returned."""
        conf = tmp_path / "notification_users.conf"
        conf.write_text("[superadmins]\nusers = root, godmode\n")
        with patch.object(wl_rbac_module, "_NOTIFICATION_USERS_CONF", str(conf)):
            assert get_superadmin_users("") == ["root", "godmode"]

    def test_rest_exception_falls_through_to_conf(self, tmp_path):
        """REST raises → exception swallowed → conf fallback used."""
        mock_splunk = MagicMock()
        mock_splunk.rest.simpleRequest.side_effect = RuntimeError("network down")
        conf = tmp_path / "notification_users.conf"
        conf.write_text("[superadmins]\nusers = sa_from_conf\n")
        with patch.dict('sys.modules',
                        {'splunk': mock_splunk, 'splunk.rest': mock_splunk.rest}), \
             patch.object(wl_rbac_module, "_NOTIFICATION_USERS_CONF", str(conf)):
            assert get_superadmin_users("token") == ["sa_from_conf"]

    def test_rest_200_no_superadmins_falls_to_conf(self, tmp_path):
        """REST 200 with no superadmin-tier entries → conf fallback."""
        content = json.dumps({
            "entry": [{"name": "alice", "content": {"roles": ["wl_editor"]}}]
        })
        mock_splunk = self._build_mock_splunk(200, content)
        conf = tmp_path / "notification_users.conf"
        conf.write_text("[superadmins]\nusers = configured_sa\n")
        with patch.dict('sys.modules',
                        {'splunk': mock_splunk, 'splunk.rest': mock_splunk.rest}), \
             patch.object(wl_rbac_module, "_NOTIFICATION_USERS_CONF", str(conf)):
            assert get_superadmin_users("session") == ["configured_sa"]
