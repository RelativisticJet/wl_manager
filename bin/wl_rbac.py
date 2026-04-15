"""
Role-Based Access Control (RBAC) for Whitelist Manager.

Provides:
- Predicates: is_admin, is_editor, can_approve, can_approve_own_requests
- Request parsing: get_user, get_roles
- Admin discovery: get_admin_users

Layer 2: imports from wl_constants and splunk.rest.
"""

from typing import Set, List, Optional
import os

__all__ = [
    "is_admin",
    "is_editor",
    "is_superadmin",
    "can_approve",
    "can_approve_own_requests",
    "get_user",
    "get_roles",
    "get_admin_users",
    "get_superadmin_users",
    "read_notification_users_fallback",
]

from wl_constants import (
    EDIT_ROLES, ADMIN_ROLES, SUPERADMIN_ROLES, APPS_DIR, APP_NAME,
)


# ──────────────────────────────────────────────────────────────
# Fallback user list — for deployments where Splunk admin has not
# granted list_users capability to the app's role.
#
# Without list_users, the REST call /services/authentication/users
# returns 403 and our get_admin_users / get_superadmin_users helpers
# silently fall back to ["admin"] / [] — which means custom admin
# users MISS notifications. This fallback config file lets admins
# explicitly declare the users to notify:
#
#   local/notification_users.conf:
#     [admins]
#     users = alice, bob, carol
#
#     [superadmins]
#     users = dave, erin
#
# Format is standard Splunk stanza/key style. Edits require filesystem
# write access to the app's local/ directory — protected by normal
# filesystem permissions (typically restricted to root/splunk).
# ──────────────────────────────────────────────────────────────

_NOTIFICATION_USERS_CONF = os.path.join(
    APPS_DIR, APP_NAME, "local", "notification_users.conf")


def read_notification_users_fallback(stanza: str) -> List[str]:
    """Read the fallback user list for a given stanza.

    Args:
        stanza: 'admins' or 'superadmins'

    Returns:
        List of usernames from the conf file, or [] if file is missing
        or the stanza isn't present. Parsing errors are silent — an
        unreadable conf file should never break the app, it just means
        the fallback isn't available.
    """
    if not os.path.isfile(_NOTIFICATION_USERS_CONF):
        return []
    try:
        current_stanza = None
        users = []
        with open(_NOTIFICATION_USERS_CONF, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("[") and line.endswith("]"):
                    current_stanza = line[1:-1].strip().lower()
                    continue
                if current_stanza == stanza.lower() and "=" in line:
                    key, val = line.split("=", 1)
                    if key.strip().lower() == "users":
                        # CSV-style, comma or whitespace separated
                        for u in val.replace(",", " ").split():
                            u = u.strip()
                            if u:
                                users.append(u)
        return users
    except (OSError, ValueError):
        return []


def is_admin(roles: Set[str]) -> bool:
    """Check if user has admin role."""
    return bool(roles & ADMIN_ROLES)


def is_editor(roles: Set[str]) -> bool:
    """Check if user can edit (analyst or admin)."""
    return bool(roles & EDIT_ROLES)


def is_superadmin(roles: Set[str]) -> bool:
    """Check if user has superadmin role (can manage other admins)."""
    return bool(roles & SUPERADMIN_ROLES)


def can_approve(roles: Set[str]) -> bool:
    """Check if user can approve requests (must be admin)."""
    return is_admin(roles)


def can_approve_own_requests(roles: Set[str]) -> bool:
    """Check if user can approve their own requests (must be superadmin)."""
    return is_superadmin(roles)


def get_user(request: dict) -> str:
    """
    Extract username from Splunk request object.

    Args:
        request: Splunk request dict (has session_key, headers)

    Returns:
        Username string (default: "unknown")
    """
    if not request:
        return "unknown"

    # Try to get from session first (standard Splunk REST)
    session = request.get("session", {})
    if isinstance(session, dict):
        user = session.get("user")
        if user:
            return user

    # Try to get from headers (sometimes present in alternative auth methods)
    headers = request.get("headers", {})
    if isinstance(headers, dict):
        user = headers.get("X-Splunk-User-Name") or headers.get("Remote-User")
        if user:
            return user

    return "unknown"


def get_roles(request: dict) -> Set[str]:
    """
    Get user's roles from Splunk.

    Fetches from /services/authentication/current-context.

    Args:
        request: Splunk request dict with session_key

    Returns:
        Set of role strings (empty set if fetch fails)
    """
    if not request:
        return set()

    session = request.get("session", {})
    if not isinstance(session, dict):
        return set()

    session_key = session.get("authtoken", "")
    if not session_key:
        return set()

    try:
        import splunk.rest
        import json

        status, content = splunk.rest.simpleRequest(
            "/services/authentication/current-context",
            sessionKey=session_key,
            getargs={"output_mode": "json"},
            raiseAllErrors=False,
        )

        if status.status == 200:
            data = json.loads(content)
            entries = data.get("entry", [])
            if entries:
                roles = entries[0].get("content", {}).get("roles", [])
                return set(roles)
    except Exception:
        pass

    return set()


def get_admin_users(session_key: str) -> List[str]:
    """
    Discover all Splunk users with admin roles.

    Preferred: REST call to /services/authentication/users filtered by
    ADMIN_ROLES. Requires the list_users capability on the session.

    Fallback 1: if REST is inaccessible (403/exception) AND the admin
    has created local/notification_users.conf with an [admins] stanza,
    use that list instead — this lets restricted deployments still
    deliver notifications to the right users without relying on REST.

    Fallback 2: if neither REST nor the conf file works, return
    ["admin"] (the built-in Splunk admin). Custom wl_admin users will
    silently miss notifications in this mode — operators should either
    grant list_users or populate the fallback conf.

    Args:
        session_key: Splunk session key

    Returns:
        List of usernames with admin roles
    """
    if session_key:
        try:
            import splunk.rest
            import json

            status, content = splunk.rest.simpleRequest(
                "/services/authentication/users",
                sessionKey=session_key,
                getargs={"output_mode": "json", "count": "0"},
                raiseAllErrors=False,
            )

            if status.status == 200:
                data = json.loads(content)
                entries = data.get("entry", [])
                admins = []
                for entry in entries:
                    content_data = entry.get("content", {})
                    name = entry.get("name", "")
                    roles = set(content_data.get("roles", []))
                    if roles & ADMIN_ROLES:
                        admins.append(name)
                if admins:
                    return admins
                # REST returned 200 with no admins found — unusual,
                # but fall through to config / hardcoded fallback.
        except Exception:
            pass

    # Fallback 1: explicit conf file for restricted deployments
    configured = read_notification_users_fallback("admins")
    if configured:
        return configured

    # Fallback 2: hardcoded built-in admin
    return ["admin"]


def get_superadmin_users(session_key: str) -> List[str]:
    """Discover all Splunk users with superadmin roles.

    Preferred: REST enumeration (requires list_users capability).

    Fallback: local/notification_users.conf with a [superadmins]
    stanza, for deployments where list_users is restricted. Without
    either, returns [] — which means superadmin-to-superadmin
    notifications (admin-limit-change, dual-unlock signals, etc.)
    are silently dropped. Operators should grant list_users or
    populate the fallback conf.

    Returns list of usernames with SUPERADMIN_ROLES.
    """
    if session_key:
        try:
            import splunk.rest
            import json

            status, content = splunk.rest.simpleRequest(
                "/services/authentication/users",
                sessionKey=session_key,
                getargs={"output_mode": "json", "count": "0"},
                raiseAllErrors=False,
            )

            if status.status == 200:
                data = json.loads(content)
                entries = data.get("entry", [])
                superadmins = []
                for entry in entries:
                    content_data = entry.get("content", {})
                    name = entry.get("name", "")
                    roles = set(content_data.get("roles", []))
                    if roles & SUPERADMIN_ROLES:
                        superadmins.append(name)
                if superadmins:
                    return superadmins
                # REST OK but no superadmins — fall through to config.
        except Exception:
            pass

    # Fallback: explicit conf file for restricted deployments
    configured = read_notification_users_fallback("superadmins")
    if configured:
        return configured

    return []
