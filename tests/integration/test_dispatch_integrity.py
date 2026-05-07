"""
Dispatch table integrity tests — ``GET_ACTIONS`` and ``POST_ACTIONS``.

These pin the structural invariants of the handler's dispatch tables.
They are the cheapest possible bug catcher for an entire class of
silent wiring failures: action wired to wrong method, missing role
tier, duplicate action name, public action that shouldn't be public.

These tests are READ-ONLY (no state mutation, no fixture needed),
so they don't pay the ``container_state`` snapshot cost. They run
against the in-process handler imported from ``bin/wl_handler.py``,
loaded via the Splunk stubs at ``tests/stubs/``.

Origin
------

Replaces ~10 high-value scenarios from the deleted zombie tests
(see ``RING_FINDINGS.md`` R0-F2 and
``RING1_INPUT_handler_contracts.md`` "Dispatch table integrity").

The original zombie tests asserted the same invariants but never
ran for 5+ weeks because they imported a class name that didn't
exist. These rewrite the scenarios with deep contract assertions
and a runnable foundation.
"""

import os
import sys

import pytest

# Test conftest.py adds tests/stubs/ to sys.path before any test
# module is imported, so this resolves to the no-op stub even
# outside Splunk.
_BIN = os.path.join(os.path.dirname(__file__), "..", "..", "bin")
sys.path.insert(0, os.path.abspath(_BIN))

from wl_handler import WhitelistHandler  # noqa: E402


# Expected role-tier exports from the handler module. These are the
# ground truth for "is action X correctly tagged as admin?". If
# someone adds a role tier they must also update this set; failure
# to do so is a self-inflicted CI break that surfaces immediately.
from wl_handler import (  # noqa: E402
    ADMIN_ROLES, SUPERADMIN_ROLES, EDIT_ROLES,
)


# ─────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def handler() -> WhitelistHandler:
    """Module-scoped handler instance.

    No state mutation in these tests; one instance per module is
    fine and avoids per-test construction overhead.
    """
    return WhitelistHandler(command_line=None, command_arg=None)


# ─────────────────────────────────────────────────────────────────────
# Structural invariants
# ─────────────────────────────────────────────────────────────────────


class TestDispatchTablesExist:
    """Pins: handler exposes both dispatch tables.

    Catches: refactor that renames or moves the tables, breaking
    the dispatcher's ability to find them at runtime.
    """

    def test_get_actions_table_exists(self, handler):
        assert hasattr(handler, "GET_ACTIONS")
        assert isinstance(handler.GET_ACTIONS, dict)
        assert len(handler.GET_ACTIONS) > 0

    def test_post_actions_table_exists(self, handler):
        assert hasattr(handler, "POST_ACTIONS")
        assert isinstance(handler.POST_ACTIONS, dict)
        assert len(handler.POST_ACTIONS) > 0


class TestDispatchEntryShape:
    """Pins: every dispatch entry is ``(roles, method_name)`` where
    roles is None or a tuple-of-strings, method_name is a string.

    Catches: a careless edit that adds an entry with the wrong
    shape (e.g., ``(method_name, roles)`` swap, missing tuple,
    method_name set to the method object instead of its name).
    The dispatcher would crash at first call with an obscure error
    instead of failing fast.
    """

    def test_get_action_entries_have_correct_shape(self, handler):
        for action_name, entry in handler.GET_ACTIONS.items():
            assert isinstance(entry, tuple), \
                f"GET {action_name}: entry is not a tuple"
            assert len(entry) == 2, \
                f"GET {action_name}: entry has {len(entry)} elements, expected 2"
            roles, method_name = entry
            assert roles is None or isinstance(roles, (set, frozenset, tuple)), \
                f"GET {action_name}: roles must be None or a collection, got {type(roles)}"
            if isinstance(roles, (set, frozenset, tuple)):
                for role in roles:
                    assert isinstance(role, str), \
                        f"GET {action_name}: role {role} is not a string"
            assert isinstance(method_name, str), \
                f"GET {action_name}: method_name is not a string"

    def test_post_action_entries_have_correct_shape(self, handler):
        for action_name, entry in handler.POST_ACTIONS.items():
            assert isinstance(entry, tuple), \
                f"POST {action_name}: entry is not a tuple"
            assert len(entry) == 2
            roles, method_name = entry
            assert roles is None or isinstance(roles, (set, frozenset, tuple))
            if isinstance(roles, (set, frozenset, tuple)):
                for role in roles:
                    assert isinstance(role, str)
            assert isinstance(method_name, str)


class TestMethodResolution:
    """Pins: every dispatch method_name resolves to a callable on
    the handler instance.

    Catches: action wired to a method name that doesn't exist on
    the handler. Production failure mode is a 500 error on first
    call. This test surfaces the same bug at import time.
    """

    def test_every_get_action_method_resolves(self, handler):
        unresolved = []
        for action_name, (_, method_name) in handler.GET_ACTIONS.items():
            method = getattr(handler, method_name, None)
            if method is None or not callable(method):
                unresolved.append(f"{action_name} -> {method_name}")
        assert not unresolved, \
            f"GET actions with missing methods: {unresolved}"

    def test_every_post_action_method_resolves(self, handler):
        unresolved = []
        for action_name, (_, method_name) in handler.POST_ACTIONS.items():
            method = getattr(handler, method_name, None)
            if method is None or not callable(method):
                unresolved.append(f"{action_name} -> {method_name}")
        assert not unresolved, \
            f"POST actions with missing methods: {unresolved}"


class TestNamingConvention:
    """Pins: every dispatch method follows the ``_action_<name>``
    naming convention.

    Catches: a refactor that renames a method without updating the
    table, or a typo that points to a coincidentally-existing
    method (which would resolve but might be the wrong code path).
    """

    def test_every_get_method_uses_action_prefix(self, handler):
        for action_name, (_, method_name) in handler.GET_ACTIONS.items():
            assert method_name.startswith("_action_"), \
                f"GET {action_name}: method_name {method_name} does not start with _action_"

    def test_every_post_method_uses_action_prefix(self, handler):
        for action_name, (_, method_name) in handler.POST_ACTIONS.items():
            assert method_name.startswith("_action_"), \
                f"POST {action_name}: method_name {method_name} does not start with _action_"


class TestNoDuplicateNames:
    """Pins: no action name appears in both GET and POST tables, and
    no method_name is reused within either table.

    Catches: copy-paste errors that wire two action names to the
    same method (subtle — both work but RBAC may differ between
    them, opening a privilege escalation path), or duplicate
    action names that make dispatch ambiguous.

    Origin: action names ``check_approval_gate`` historically
    existed in both tables briefly; the second registration silently
    won. This test would have caught it at commit time.
    """

    def test_no_action_name_in_both_tables(self, handler):
        get_names = set(handler.GET_ACTIONS.keys())
        post_names = set(handler.POST_ACTIONS.keys())
        overlap = get_names & post_names
        assert not overlap, \
            f"Action names appear in BOTH GET and POST tables: {overlap}"

    def test_no_duplicate_method_names_in_get(self, handler):
        method_names = [m for (_, m) in handler.GET_ACTIONS.values()]
        seen = set()
        duplicates = set()
        for m in method_names:
            if m in seen:
                duplicates.add(m)
            seen.add(m)
        assert not duplicates, \
            f"Duplicate method names in GET_ACTIONS: {duplicates}"

    def test_no_duplicate_method_names_in_post(self, handler):
        method_names = [m for (_, m) in handler.POST_ACTIONS.values()]
        seen = set()
        duplicates = set()
        for m in method_names:
            if m in seen:
                duplicates.add(m)
            seen.add(m)
        assert not duplicates, \
            f"Duplicate method names in POST_ACTIONS: {duplicates}"


# ─────────────────────────────────────────────────────────────────────
# RBAC invariants — critical for security
# ─────────────────────────────────────────────────────────────────────


class TestRoleTierInvariants:
    """Pins: known-admin actions actually have admin roles.

    Catches: refactor that drops the role tier from a destructive
    action — silent privilege escalation. This is the security
    boundary build-641-style projection drift can create when a
    role-checking layer accepts an empty role tuple as "no check".
    """

    # Actions that MUST be SUPERADMIN-only. Hardcoded list — if a
    # new action joins this list, the test changes and the
    # security-relevant decision is visible in the diff.
    REQUIRED_SUPERADMIN_ACTIONS = {
        "set_daily_limits", "set_admin_limits",
        "reset_daily_limits", "save_as_default",
        "reset_factory_defaults", "activate_lockdown",
        "deactivate_lockdown", "open_deploy_window",
        "close_deploy_window", "bootstrap_csv_hashes",
    }

    # Actions that MUST require admin (or higher). Hardcoded list.
    REQUIRED_ADMIN_PLUS_ACTIONS = {
        "process_approval", "process_dual_approval",
        "set_trash_retention", "purge_trash",
        "restore_from_trash", "reset_daily_usage",
    }

    # Actions that MUST require edit-or-higher (analyst, admin,
    # superadmin) — write paths into CSV state.
    REQUIRED_EDIT_PLUS_ACTIONS = {
        "save_csv", "add_row", "remove_rows", "revert_csv",
        "create_csv", "create_rule", "remove_csv", "remove_rule",
        "submit_approval", "submit_dual_approval",
    }

    def test_superadmin_actions_have_superadmin_roles(self, handler):
        """If any superadmin-required action drops to admin or
        public, that's a critical security regression."""
        violators = []
        for action in self.REQUIRED_SUPERADMIN_ACTIONS:
            entry = handler.POST_ACTIONS.get(action)
            assert entry is not None, \
                f"REQUIRED_SUPERADMIN_ACTIONS lists {action} but it's not in POST_ACTIONS"
            roles, _ = entry
            if roles != SUPERADMIN_ROLES:
                violators.append(f"{action}: roles={roles}")
        assert not violators, \
            f"Superadmin actions with weakened roles: {violators}"

    def test_admin_plus_actions_have_admin_or_superadmin_roles(
            self, handler):
        violators = []
        for action in self.REQUIRED_ADMIN_PLUS_ACTIONS:
            entry = handler.POST_ACTIONS.get(action)
            assert entry is not None, \
                f"REQUIRED_ADMIN_PLUS_ACTIONS lists {action} but it's not in POST_ACTIONS"
            roles, _ = entry
            # Acceptable: ADMIN_ROLES (which already includes
            # superadmin via the role hierarchy) or SUPERADMIN_ROLES
            if roles not in (ADMIN_ROLES, SUPERADMIN_ROLES):
                violators.append(f"{action}: roles={roles}")
        assert not violators, \
            f"Admin+ actions with weakened roles: {violators}"

    def test_edit_actions_have_edit_or_higher_roles(self, handler):
        violators = []
        for action in self.REQUIRED_EDIT_PLUS_ACTIONS:
            entry = handler.POST_ACTIONS.get(action)
            assert entry is not None, \
                f"REQUIRED_EDIT_PLUS_ACTIONS lists {action} but it's not in POST_ACTIONS"
            roles, _ = entry
            # Acceptable: any role tier other than None (public)
            assert roles is not None, \
                f"{action}: write action has roles=None (public!)"
            if roles not in (EDIT_ROLES, ADMIN_ROLES,
                             SUPERADMIN_ROLES):
                violators.append(f"{action}: roles={roles}")
        assert not violators, \
            f"Edit-required actions with non-edit roles: {violators}"


class TestPublicActionsAreIntentional:
    """Pins: every action with ``roles=None`` is on a documented
    allow-list of intentionally-public actions.

    Catches: a refactor that accidentally drops the role tier
    from a destructive action, making it callable by anonymous
    users. The naming convention can hide this — ``_action_save_X``
    sounds dangerous but ``_action_log_X`` sounds safe; both could
    be made public by mistake.

    Origin: build 573-575 added several public read-only actions
    (notifications, presence, lockdown status). Without an
    explicit allow-list, the next reviewer can't tell whether a
    new public action is legitimate or a regression.
    """

    # Documented public GET actions — read-only data the UI needs
    # before authentication is fully resolved (e.g., to show the
    # bell on a dashboard the user just navigated to).
    INTENTIONALLY_PUBLIC_GETS = {
        "get_rules", "get_csvs", "get_csv_content", "get_mapping",
        "get_versions", "check_csv_status", "get_col_widths",
        "get_apps", "report_presence", "get_presence",
        "get_user_info", "get_pending_approvals",
        "check_daily_limit_status", "get_notifications",
        "get_lockdown_status",
    }

    # Documented public POST actions — small set, each individually
    # justified.
    INTENTIONALLY_PUBLIC_POSTS = {
        # Marks the user's own notifications as read — RBAC happens
        # inside the handler (only marks notifications addressed
        # to the calling user)
        "mark_notifications_read",
        # Frontend audit logging for client-side events. Server
        # validates the action name against an allow-list before
        # writing to wl_audit, so a hostile caller can't forge
        # arbitrary audit content
        "log_event",
        # Cancel one's own pending request. Handler enforces the
        # "must be the requester" check; there's no public state
        # mutation possible
        "cancel_request",
    }

    def test_public_get_actions_match_allow_list(self, handler):
        actual_public_gets = {
            action for action, (roles, _) in handler.GET_ACTIONS.items()
            if roles is None
        }
        unexpected = actual_public_gets - self.INTENTIONALLY_PUBLIC_GETS
        missing = self.INTENTIONALLY_PUBLIC_GETS - actual_public_gets
        assert not unexpected, \
            (f"GET actions newly made public without allow-list "
             f"update: {unexpected}. If these are legitimate, add "
             f"them to INTENTIONALLY_PUBLIC_GETS with a comment "
             f"explaining why public is safe.")
        assert not missing, \
            (f"GET actions removed from public set but allow-list "
             f"not updated: {missing}. Remove them from the "
             f"allow-list.")

    def test_public_post_actions_match_allow_list(self, handler):
        actual_public_posts = {
            action for action, (roles, _) in handler.POST_ACTIONS.items()
            if roles is None
        }
        unexpected = actual_public_posts - self.INTENTIONALLY_PUBLIC_POSTS
        missing = self.INTENTIONALLY_PUBLIC_POSTS - actual_public_posts
        assert not unexpected, \
            (f"POST actions newly made public without allow-list "
             f"update: {unexpected}. SECURITY-SENSITIVE — review "
             f"whether public access is intended.")
        assert not missing, \
            f"POST actions removed from public set: {missing}"
