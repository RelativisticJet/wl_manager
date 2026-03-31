"""
Role-Based Access Control (RBAC) for Whitelist Manager.

Provides:
- Predicates: is_admin, is_editor, can_approve, can_approve_own_requests
- Request parsing: get_user, get_roles
- Admin discovery: get_admin_users

Layer 2: imports from wl_constants and splunk.rest.
"""

from typing import Set, List, Optional

__all__ = [
    "is_admin",
    "is_editor",
    "is_superadmin",
    "can_approve",
    "can_approve_own_requests",
    "get_user",
    "get_roles",
    "get_admin_users",
]

from wl_constants import EDIT_ROLES, ADMIN_ROLES, SUPERADMIN_ROLES


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
            raiseException=False,
        )

        if status == 200:
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

    Searches for users in ADMIN_ROLES. Falls back to ["admin"] if session_key is empty or fetch fails.

    Args:
        session_key: Splunk session key

    Returns:
        List of usernames with admin roles (["admin"] as fallback)
    """
    if not session_key:
        return ["admin"]

    try:
        import splunk.rest
        import json

        status, content = splunk.rest.simpleRequest(
            "/services/authentication/users",
            sessionKey=session_key,
            getargs={"output_mode": "json", "count": "0"},
            raiseException=False,
        )

        if status == 200:
            data = json.loads(content)
            entries = data.get("entry", [])
            admins = []
            for entry in entries:
                content_data = entry.get("content", {})
                name = content_data.get("name", "")
                roles = set(content_data.get("roles", []))
                if roles & ADMIN_ROLES:
                    admins.append(name)
            return admins if admins else ["admin"]
    except Exception:
        pass

    return ["admin"]
