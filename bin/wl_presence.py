"""
User presence tracking for Whitelist Manager.

Tracks which users are actively editing which CSV files (for collaborative awareness).
Module-level state: _presence dict.

Returns (data_dict, error_string) tuples (handler wraps in HTTP responses).

Layer 2: imports from wl_constants.
"""

import time
from datetime import datetime, timezone
from typing import Dict, Tuple, Optional, List

__all__ = ["report_presence", "get_presence", "cleanup_presence", "reset_presence"]

# Module-level state
_presence: Dict[str, Dict] = {}  # { csv_file: { user: { "last_activity": timestamp, ... } } }


def report_presence(csv_file: str, user: str, last_activity: Optional[float] = None) -> Tuple[Dict, str]:
    """
    Report that a user is actively editing a CSV.

    Returns (data_dict, error_string) where error_string is empty if successful.

    Args:
        csv_file: CSV filename being edited
        user: Username
        last_activity: Timestamp of last activity (defaults to now)

    Returns:
        ({data}, "error message" or "")
    """
    from wl_constants import (
        MAX_PRESENCE_FILES,
        MAX_PRESENCE_USERS,
        PRESENCE_TIMEOUT,
        IDLE_TIMEOUT,
    )

    global _presence

    if not csv_file or not user:
        return ({}, "csv_file and user are required")

    if last_activity is None:
        last_activity = time.time()

    # Cleanup stale presence data
    now = time.time()

    # Remove stale CSV entries
    stale_csvs = []
    for csv, users in _presence.items():
        users_to_remove = [u for u, data in users.items() if now - data["last_activity"] > PRESENCE_TIMEOUT]
        for u in users_to_remove:
            del users[u]
        if not users:
            stale_csvs.append(csv)
    for csv in stale_csvs:
        del _presence[csv]

    # Limit total tracked files
    if len(_presence) >= MAX_PRESENCE_FILES and csv_file not in _presence:
        return ({}, f"Presence tracking at limit ({MAX_PRESENCE_FILES} files)")

    # Initialize CSV entry if needed
    if csv_file not in _presence:
        _presence[csv_file] = {}

    # Limit users per CSV
    if len(_presence[csv_file]) >= MAX_PRESENCE_USERS and user not in _presence[csv_file]:
        return ({}, f"Too many users editing {csv_file} ({MAX_PRESENCE_USERS} limit)")

    # Record presence
    _presence[csv_file][user] = {
        "last_activity": last_activity,
        "idle_minutes": int((now - last_activity) / 60) if last_activity else 0,
    }

    # Build response data
    presence_list = []
    for u, data in _presence[csv_file].items():
        idle_min = int((now - data["last_activity"]) / 60)
        presence_list.append({
            "user": u,
            "idle_minutes": idle_min,
        })

    # active_users: flat list of usernames (frontend renderPresenceBar expects string array)
    active_users = [p["user"] for p in presence_list]

    return ({"presence": presence_list, "active_users": active_users}, "")


def get_presence(csv_file: str) -> Tuple[Dict, str]:
    """
    Get current presence data for a CSV file.

    Returns:
        ({presence_data}, "" or "error")
    """
    global _presence
    now = time.time()

    if csv_file not in _presence:
        return ({"presence": []}, "")

    # Build response
    presence_list = []
    for user, data in _presence[csv_file].items():
        idle_min = int((now - data["last_activity"]) / 60) if "last_activity" in data else 0
        presence_list.append({
            "user": user,
            "idle_minutes": idle_min,
        })

    return ({"presence": presence_list}, "")


def cleanup_presence(max_idle_minutes: int = 30) -> int:
    """
    Remove users who haven't been active for max_idle_minutes.

    Returns the number of users removed.

    Args:
        max_idle_minutes: Threshold for removal

    Returns:
        Number of users removed
    """
    global _presence
    now = time.time()
    removed = 0

    stale_csvs = []
    for csv_file, users in _presence.items():
        users_to_remove = [
            u for u, data in users.items()
            if now - data["last_activity"] > max_idle_minutes * 60
        ]
        for u in users_to_remove:
            del users[u]
            removed += 1
        if not users:
            stale_csvs.append(csv_file)

    for csv in stale_csvs:
        del _presence[csv]

    return removed


def reset_presence() -> None:
    """Reset all presence data. Used for testing."""
    global _presence
    _presence.clear()
