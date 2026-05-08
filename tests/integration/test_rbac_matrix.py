"""
Role × Action RBAC matrix.

Pins the dispatcher's permission-gating contract for every
``GET_ACTIONS`` and ``POST_ACTIONS`` entry in
``bin/wl_handler.py``. The dispatcher (``_dispatch`` at
``wl_handler.py:1394``) returns HTTP 403 with
``{"error": "Permission denied: insufficient role"}`` whenever
the caller's role set does not intersect the action's
``required_roles``. We pin both sides of every (action, user_tier)
cell:

- **Forbidden tier × action**: the dispatcher MUST reject with the
  documented error string. The action method is never called, so
  no business-logic side effects fire.
- **Permitted tier × action**: the dispatcher MUST NOT reject for
  RBAC. The action may still fail downstream (bad payload,
  validation, missing entity) — but the rejection cannot be
  permission-denial.

This catches the entire bug class where:

- A new action is added but the wrong role tier is wired into
  ``GET_ACTIONS`` / ``POST_ACTIONS``.
- A refactor moves an action between role groups silently.
- A typo in ``EDIT_ROLES`` / ``ADMIN_ROLES`` / ``SUPERADMIN_ROLES``
  membership lets a tier escalate.

Test users (from ``conftest.WL_USERS``) and tier mapping (after
``authorize.conf`` role inheritance):

============== ========================== ==========================
User           Roles assigned             Satisfies tiers
============== ========================== ==========================
``analyst1``   ``wl_analyst_editor``      ``open``, ``edit``
``wladmin1``   ``wl_admin``               ``open``, ``edit``,
                                          ``admin``
``admin``      ``admin`` (built-in)       ``open``, ``edit``,
                                          ``admin``
``superadmin1`` ``wl_superadmin`` (which   ``open``, ``edit``,
                imports ``wl_admin``)     ``admin``, ``superadmin``
============== ========================== ==========================

Note: the built-in ``admin`` role is in ``EDIT_ROLES`` and
``ADMIN_ROLES`` but NOT ``SUPERADMIN_ROLES`` — so the built-in
admin must be rejected for superadmin-only actions. This is the
exact RBAC contract that
``feedback_use_role_specific_accounts.md`` documents and that
the Day 3 admin-limit RBAC test pinned for one specific action.
This file pins it for all 25+ tier-gated actions.

Origin
------

Ring 2 Day 4. Closes the role × action coverage gap. Prior
rings spot-checked specific RBAC pairs (e.g.,
``set_admin_limits`` analyst denial in Day 3); this ring
exhausts the matrix. ``GET_ACTIONS`` was previously unpinned at
the matrix level — every read endpoint with ``ADMIN_ROLES`` or
``SUPERADMIN_ROLES`` now has a regression test.
"""

import json

import pytest


pytestmark = pytest.mark.docker


# ─────────────────────────────────────────────────────────────────────
# Tier model
# ─────────────────────────────────────────────────────────────────────

# Each test user satisfies these tiers. Mirrors authorize.conf +
# bin/wl_constants.py role-set definitions. Kept as a literal
# table (not derived) so a test failure points at exactly which
# user/tier mapping diverged.
USER_SATISFIES = {
    "analyst1":    {"open", "edit"},
    "wladmin1":    {"open", "edit", "admin"},
    "admin":       {"open", "edit", "admin"},
    "superadmin1": {"open", "edit", "admin", "superadmin"},
}

# Tier required by each POST action. Mirrors POST_ACTIONS in
# wl_handler.py:1287. Hardcoded (not introspected) so divergence
# between handler dispatch and this expectation is the test's
# observable failure.
POST_ACTION_TIER = {
    # CSV Modifications
    "save_csv":               "edit",
    "add_row":                "edit",
    "remove_rows":            "edit",
    "revert_csv":             "edit",
    "save_col_widths":        "edit",
    # CSV/Rule Creation & Deletion
    "create_csv":             "edit",
    "create_rule":            "edit",
    "remove_csv":             "edit",
    "remove_rule":            "edit",
    # Approval Workflow
    "submit_approval":        "edit",
    "submit_dual_approval":   "edit",
    "process_approval":       "admin",
    "process_dual_approval":  "admin",
    "check_approval_gate":    "edit",
    "cancel_request":         "open",
    # Admin Operations
    "set_daily_limits":       "superadmin",
    "set_admin_limits":       "superadmin",
    "reset_daily_limits":     "superadmin",
    "reset_daily_usage":      "admin",
    "save_as_default":        "superadmin",
    "reset_factory_defaults": "superadmin",
    "set_trash_retention":    "admin",
    "purge_trash":            "admin",
    "restore_from_trash":     "admin",
    # Emergency Lockdown
    "activate_lockdown":      "superadmin",
    "deactivate_lockdown":    "superadmin",
    # FIM Deploy Window
    "open_deploy_window":     "superadmin",
    "close_deploy_window":    "superadmin",
    # Maintenance
    "bootstrap_csv_hashes":   "superadmin",
    # Notifications & Logging (open tier)
    "mark_notifications_read": "open",
    "log_event":              "open",
}

# Tier required by each GET action (read endpoints). Mirrors
# GET_ACTIONS in wl_handler.py:1242. Open-tier reads are not
# enumerated here — there's nothing to assert for them at the
# matrix level beyond what the open-tier fixture already
# exercises everywhere.
GET_ACTION_TIER = {
    "get_request_csv":          "admin",
    "get_approval_queue":       "admin",
    "get_daily_limits":         "admin",
    "get_analyst_usage":        "admin",
    "get_admin_limits":         "admin",
    "get_trash_config":         "admin",
    "list_trash":               "admin",
    "probe_audit_access":       "admin",
    "probe_server_info_access": "admin",
    "probe_list_users_access":  "admin",
    "get_deploy_window_status": "superadmin",
}


def _denial_cells(tier_table):
    """Yield (action, user, required_tier) triples where the user's
    tier is BELOW the action's required tier — the cells where the
    dispatcher MUST reject."""
    cells = []
    for action, required_tier in tier_table.items():
        for user, satisfies in USER_SATISFIES.items():
            if required_tier not in satisfies:
                cells.append((action, user, required_tier))
    return cells


def _id(triple):
    return "{}__{}__needs_{}".format(*triple)


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────


def _post(container_curl, action, payload, user):
    body = json.dumps({"action": action, **payload})
    proc = container_curl(
        "/services/custom/wl_manager",
        method="POST",
        data=body,
        content_type="application/json",
        check=False,
        user=user,
    )
    raw = (proc.stdout or "").strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"_raw": raw, "_returncode": proc.returncode}


def _get(container_curl, action, user, extra_query=""):
    path = "/services/custom/wl_manager?action={}{}".format(action, extra_query)
    proc = container_curl(path, check=False, user=user)
    raw = (proc.stdout or "").strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"_raw": raw, "_returncode": proc.returncode}


def _is_permission_denied(body):
    """The dispatcher's documented denial signature."""
    flat = str(body)
    return ("Permission denied" in flat
            or "insufficient role" in flat)


# ─────────────────────────────────────────────────────────────────────
# Denial matrix — POST
# ─────────────────────────────────────────────────────────────────────


POST_DENIAL_CELLS = _denial_cells(POST_ACTION_TIER)


class TestPostRBACDenialMatrix:
    """Forbidden POST tier × action: dispatcher must reject with 403.

    Sends an empty payload. The dispatcher rejects BEFORE the
    action method is called, so the absence of a required field
    can't accidentally turn into a non-permission error. The
    only legitimate response shape here is the documented
    denial.
    """

    @pytest.mark.parametrize(
        "action,user,required_tier",
        POST_DENIAL_CELLS,
        ids=[_id(c) for c in POST_DENIAL_CELLS],
    )
    def test_insufficient_tier_is_rejected(
            self, action, user, required_tier,
            container_state, container_curl):
        body = _post(container_curl, action, {}, user=user)
        assert _is_permission_denied(body), (
            "User {} (only {} tiers) was NOT denied for {} action {}: {}"
            .format(user, sorted(USER_SATISFIES[user]),
                    required_tier, action, body))


# ─────────────────────────────────────────────────────────────────────
# Denial matrix — GET
# ─────────────────────────────────────────────────────────────────────


GET_DENIAL_CELLS = _denial_cells(GET_ACTION_TIER)


class TestGetRBACDenialMatrix:
    """Forbidden GET tier × action: dispatcher must reject with 403.

    Same contract as POST — the dispatcher rejects RBAC before
    the action runs, so the response is the documented denial.
    """

    @pytest.mark.parametrize(
        "action,user,required_tier",
        GET_DENIAL_CELLS,
        ids=[_id(c) for c in GET_DENIAL_CELLS],
    )
    def test_insufficient_tier_is_rejected(
            self, action, user, required_tier,
            container_state, container_curl):
        body = _get(container_curl, action, user=user)
        assert _is_permission_denied(body), (
            "User {} (only {} tiers) was NOT denied for {} action {}: {}"
            .format(user, sorted(USER_SATISFIES[user]),
                    required_tier, action, body))


# ─────────────────────────────────────────────────────────────────────
# Pass-through matrix (sample) — RBAC must NOT block the right tier
# ─────────────────────────────────────────────────────────────────────


# Sample one action per (tier, user-at-tier) where we expect the
# dispatcher to let the call through. The action might still fail
# downstream (empty payload → validation error, etc.) — but the
# failure must NOT be permission denial. This pins the symmetric
# half of the matrix without exhausting it (32 + 11 = 43 actions
# × 4 users would be 172 cells; we sample one per tier instead).
PERMITTED_SAMPLES = [
    # (method, action, user) — each user calls one representative
    # action at exactly their tier (they could also call any
    # lower-tier action, but those are covered transitively).

    # open tier — any authenticated user
    ("POST", "log_event",                 "analyst1"),
    ("POST", "mark_notifications_read",   "analyst1"),

    # edit tier — analyst+
    ("POST", "save_col_widths",           "analyst1"),
    ("POST", "check_approval_gate",       "analyst1"),

    # admin tier — wladmin+ (includes built-in admin)
    ("POST", "set_trash_retention",       "wladmin1"),
    ("POST", "set_trash_retention",       "admin"),
    ("GET",  "get_approval_queue",        "wladmin1"),
    ("GET",  "list_trash",                "admin"),

    # superadmin tier — only superadmin1
    ("POST", "set_admin_limits",          "superadmin1"),
    ("POST", "open_deploy_window",        "superadmin1"),
    ("GET",  "get_deploy_window_status",  "superadmin1"),
]


class TestRBACPermittedSamples:
    """Permitted tier × action: dispatcher must NOT reject for RBAC.

    The action may still fail for downstream reasons (bad payload,
    missing required field, business-rule violation). What we
    assert here is the negative: the dispatcher's RBAC gate did
    NOT short-circuit. Any non-permission error path is acceptable
    — that means RBAC let it through and the failure was
    business-logic.
    """

    @pytest.mark.parametrize(
        "method,action,user",
        PERMITTED_SAMPLES,
        ids=["{}__{}__{}".format(*c) for c in PERMITTED_SAMPLES],
    )
    def test_qualified_tier_passes_rbac_gate(
            self, method, action, user,
            container_state, container_curl):
        if method == "POST":
            body = _post(container_curl, action, {}, user=user)
        else:
            body = _get(container_curl, action, user=user)
        assert not _is_permission_denied(body), (
            "User {} was REJECTED at RBAC for {} {} but should have "
            "passed (action may still fail downstream — that's fine):"
            " {}".format(user, method, action, body))


# ─────────────────────────────────────────────────────────────────────
# Coverage sanity — every dispatch entry is in our tier table
# ─────────────────────────────────────────────────────────────────────


class TestMatrixCoverage:
    """Pins that the matrix's tier tables don't drift behind
    ``POST_ACTIONS`` / ``GET_ACTIONS``.

    If a new action is added to the dispatch tables in
    ``wl_handler.py`` but never gets a tier classification here,
    Ring 2's RBAC matrix has a gap. This test fails immediately
    and points at the missing entry — forcing the new action to
    pick a tier rather than silently ship without coverage.

    Implementation: imports ``POST_ACTIONS`` / ``GET_ACTIONS``
    via the already-running container's REST surface is hard,
    so we read the canonical source file directly. This gives
    us the same drift signal without needing to import the
    module (which would fail outside the container).
    """

    HANDLER_PATH = "bin/wl_handler.py"

    def _extract_dispatch_actions(self, table_name):
        """Return the set of action keys declared in the named
        dispatch table. Parses the Python source by string match
        on quoted keys — accepts the structure that's been stable
        across many Splunk versions."""
        import os, re
        repo_root = os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))))
        src_path = os.path.join(repo_root, self.HANDLER_PATH)
        with open(src_path, "r", encoding="utf-8") as f:
            src = f.read()
        # Find the table definition block
        m = re.search(
            table_name + r"\s*=\s*\{(.*?)\n    \}",
            src, re.DOTALL)
        assert m is not None, (
            "Couldn't locate {} block in {}".format(
                table_name, src_path))
        block = m.group(1)
        # Pull out keys: lines like `        "action_name": (TIER, ...)`
        return set(re.findall(r'^\s*"([a-z_]+)"\s*:\s*\(',
                              block, re.MULTILINE))

    def test_every_post_action_has_a_tier_classification(self):
        declared = self._extract_dispatch_actions("POST_ACTIONS")
        classified = set(POST_ACTION_TIER.keys())
        missing = declared - classified
        extra = classified - declared
        assert not missing, (
            "POST actions in handler but missing from "
            "POST_ACTION_TIER (Ring 2 Day 4 matrix gap): {}. "
            "Add each to POST_ACTION_TIER with the appropriate "
            "tier classification.".format(sorted(missing)))
        assert not extra, (
            "POST_ACTION_TIER references actions not in the "
            "handler dispatch table (stale Day 4 matrix): {}. "
            "Either remove from POST_ACTION_TIER or add to "
            "POST_ACTIONS.".format(sorted(extra)))

    def test_every_admin_or_superadmin_get_action_has_a_tier(self):
        """GET tier table only enumerates non-open actions. Verify
        no admin/superadmin GET endpoint slipped past us."""
        declared = self._extract_dispatch_actions("GET_ACTIONS")
        # Read the source again to find which entries are tier-gated.
        # We need to filter out (None, ...) entries because those
        # are open-tier and intentionally absent from
        # GET_ACTION_TIER.
        import os, re
        repo_root = os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))))
        src_path = os.path.join(repo_root, self.HANDLER_PATH)
        with open(src_path, "r", encoding="utf-8") as f:
            src = f.read()
        m = re.search(
            r"GET_ACTIONS\s*=\s*\{(.*?)\n    \}", src, re.DOTALL)
        assert m is not None
        block = m.group(1)
        gated_actions = set(re.findall(
            r'^\s*"([a-z_]+)"\s*:\s*\((ADMIN_ROLES|SUPERADMIN_ROLES)',
            block, re.MULTILINE))
        # gated_actions is now {(name, tier_const)}; flatten
        gated_names = {name for name, _ in
                       re.findall(
                           r'^\s*"([a-z_]+)"\s*:\s*\((ADMIN_ROLES|SUPERADMIN_ROLES)',
                           block, re.MULTILINE)}
        classified = set(GET_ACTION_TIER.keys())
        missing = gated_names - classified
        extra = classified - gated_names
        assert not missing, (
            "Tier-gated GET actions missing from GET_ACTION_TIER: "
            "{}. Add each with appropriate tier.".format(
                sorted(missing)))
        assert not extra, (
            "GET_ACTION_TIER references actions not gated in the "
            "handler: {}. Either remove or update tier.".format(
                sorted(extra)))
