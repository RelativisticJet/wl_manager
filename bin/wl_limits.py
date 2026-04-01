"""
Daily usage limits and enforcement for Whitelist Manager.

Manages:
- Daily usage tracking per analyst per action-type
- Limit enforcement (0=disabled, -1=unlimited, N=limit)
- Reset scheduling at configured UTC boundary times
- Admin exemptions
- Limit configuration management
- Status API for frontend progress display

Layer 3: imports from wl_constants (Layer 0), wl_rbac (Layer 2), wl_validation (Layer 2),
and wl_filelock (Layer 2).
"""

import sys
import os
import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Tuple, Optional

# Handle Splunk bin/ import limitations
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from wl_constants import (
    DEFAULT_LIMITS, DEFAULT_ADMIN_LIMITS, RESET_ALL_USERS, OWN_LOOKUPS
)
from wl_rbac import is_admin
from wl_filelock import file_lock

__all__ = [
    "check_analyst_limit",
    "check_admin_limit",
    "get_limit_status",
    "increment_daily_limit",
    "set_limit_config",
    "reset_daily_limits",
    "get_limit_error_msg",
]


def _get_limits_dir() -> str:
    """
    Get the limits configuration directory (OWN_LOOKUPS).

    Creates it if missing.

    Returns:
        Absolute path to lookups directory
    """
    os.makedirs(OWN_LOOKUPS, exist_ok=True)
    return OWN_LOOKUPS


def _read_daily_limits() -> Dict:
    """
    Read daily usage counters from disk.

    File format:
    {
        "2026-04-01": {  # period_key (date, week, or month depending on frequency)
            "jsmith": {
                "row_removal": 3,
                "bulk_row_removal": 1,
                ...
            },
            ...
        }
    }

    Returns:
        Dict of counters, empty dict on file not found, error reading, or JSON corruption.
        Fail-closed: on any error, returns {} to prevent logic errors.
    """
    limits_path = os.path.join(_get_limits_dir(), "_daily_limits.json")
    if not os.path.isfile(limits_path):
        return {}

    try:
        with open(limits_path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return {}  # Fail-closed


def _write_daily_limits(counters: Dict) -> bool:
    """
    Write daily usage counters to disk atomically.

    Uses temp file + rename pattern with file locking.

    Args:
        counters: Dict to write

    Returns:
        True on success, False on error
    """
    limits_path = os.path.join(_get_limits_dir(), "_daily_limits.json")
    temp_path = limits_path + ".tmp"

    try:
        with open(temp_path, "w", encoding="utf-8") as fh:
            with file_lock(limits_path, timeout=10):
                json.dump(counters, fh, indent=2)
        os.replace(temp_path, limits_path)
        return True
    except (OSError, IOError, Exception):
        # Clean up temp file on error
        try:
            os.remove(temp_path)
        except OSError:
            pass
        return False


def _read_limit_config() -> Dict:
    """
    Read limit configuration from disk.

    Falls back to DEFAULT_LIMITS if file not found or corrupted.

    Returns:
        Dict of limit configuration
    """
    limits_path = os.path.join(_get_limits_dir(), "_limit_config.json")
    if not os.path.isfile(limits_path):
        return DEFAULT_LIMITS.copy()

    try:
        with open(limits_path, "r", encoding="utf-8") as fh:
            config = json.load(fh)
            # Ensure all required keys present
            for key in DEFAULT_LIMITS:
                if key not in config:
                    config[key] = DEFAULT_LIMITS[key]
            return config
    except (json.JSONDecodeError, OSError):
        return DEFAULT_LIMITS.copy()  # Fail-closed to defaults


def _get_counter_period_key() -> str:
    """
    Get the period key for bucketing daily limits.

    Returns the appropriate key based on reset_frequency from config:
    - "daily": "YYYY-MM-DD" (e.g., "2026-04-01")
    - "weekly": "YYYY-WXX" (e.g., "2026-W14") — ISO week format
    - "monthly": "YYYY-MM" (e.g., "2026-04")

    For now, we use daily frequency. Future: read reset_frequency from config.

    Returns:
        Period key string
    """
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%d")  # Daily frequency


def _should_reset_now(reset_time_utc: str, reset_frequency: str) -> bool:
    """
    Check if reset boundary has been crossed.

    Compares current time to reset_time_utc and reset_frequency to determine
    if counters should be reset.

    Args:
        reset_time_utc: Time in "HH:MM" format (UTC)
        reset_frequency: "daily", "weekly", or "monthly"

    Returns:
        True if reset boundary crossed, False otherwise
    """
    # For now: simple daily check at configured time
    # Future: implement weekly/monthly logic
    now = datetime.now(timezone.utc)
    try:
        reset_hour, reset_minute = map(int, reset_time_utc.split(":"))
    except (ValueError, IndexError):
        return False  # Invalid time format

    reset_time = now.replace(hour=reset_hour, minute=reset_minute, second=0, microsecond=0)
    return now >= reset_time  # Simplistic: assume reset hasn't happened yet today


def check_analyst_limit(
    user: str,
    action_type: str,
    action_count: int = 1,
    roles: Optional[List[str]] = None
) -> Tuple[bool, int, int]:
    """
    Check if analyst can perform action_count of action_type.

    If analyst has admin role, returns (True, 0, -1) — admins are exempt.

    Args:
        user: Username
        action_type: Action type (e.g., "row_removal", "bulk_row_edit")
        action_count: Number of actions to perform (default 1)
        roles: List of user roles (for admin exemption check)

    Returns:
        Tuple of (allowed: bool, current: int, max: int):
        - allowed: True if action is allowed, False if would exceed limit
        - current: Current usage count before this action
        - max: Maximum allowed (0=disabled, -1=unlimited, N=limit)
    """
    roles_set = set(roles) if roles else set()

    # Admin exemption
    if is_admin(roles_set):
        return (True, 0, -1)

    config = _read_limit_config()
    max_count = config.get(action_type, -1)

    # Disabled: max_count == 0
    if max_count == 0:
        return (False, 0, 0)

    # Unlimited: max_count == -1
    if max_count == -1:
        return (True, 0, -1)

    # Limited: max_count > 0
    counters = _read_daily_limits()
    period_key = _get_counter_period_key()

    if period_key not in counters:
        counters[period_key] = {}
    if user not in counters[period_key]:
        counters[period_key][user] = {}

    current = counters[period_key][user].get(action_type, 0)
    allowed = (current + action_count) <= max_count

    return (allowed, current, max_count)


def check_admin_limit(
    user: str,
    action_type: str,
    action_count: int = 1
) -> Tuple[bool, int, int]:
    """
    Check if admin can perform action_count of admin-specific action_type.

    Admin limits use DEFAULT_ADMIN_LIMITS instead of DEFAULT_LIMITS.

    Args:
        user: Username
        action_type: Admin action type (e.g., "rule_deletion", "approval_count")
        action_count: Number of actions (default 1)

    Returns:
        Tuple of (allowed: bool, current: int, max: int)
    """
    config = _read_limit_config()
    max_count = config.get(action_type, -1)

    # Disabled: max_count == 0
    if max_count == 0:
        return (False, 0, 0)

    # Unlimited: max_count == -1
    if max_count == -1:
        return (True, 0, -1)

    # Limited: max_count > 0
    counters = _read_daily_limits()
    period_key = _get_counter_period_key()

    if period_key not in counters:
        counters[period_key] = {}
    if user not in counters[period_key]:
        counters[period_key][user] = {}

    current = counters[period_key][user].get(action_type, 0)
    allowed = (current + action_count) <= max_count

    return (allowed, current, max_count)


def get_limit_status(user: str, roles: Optional[List[str]] = None) -> Dict:
    """
    Get limit status for user across all action types.

    Returns dict with structure:
    {
        "row_removal": {
            "current": 3,
            "max": 10,
            "remaining": 7
        },
        ...
    }

    For admin users, max and remaining are -1 (unlimited).

    Args:
        user: Username
        roles: List of user roles

    Returns:
        Dict mapping action_type to {current, max, remaining}
    """
    roles_set = set(roles) if roles else set()
    config = _read_limit_config()
    counters = _read_daily_limits()
    period_key = _get_counter_period_key()

    status = {}

    for action_type in DEFAULT_LIMITS:
        if action_type.startswith(("reset_", "allow_", "require_")):
            continue  # Skip non-action keys

        max_count = config.get(action_type, -1)

        # Admin exempt
        if is_admin(roles_set):
            status[action_type] = {
                "current": 0,
                "max": -1,
                "remaining": -1
            }
            continue

        # Get current count
        if period_key not in counters:
            counters[period_key] = {}
        current = counters[period_key].get(user, {}).get(action_type, 0)

        # Calculate remaining
        if max_count == 0:
            remaining = 0
        elif max_count == -1:
            remaining = -1
        else:
            remaining = max(0, max_count - current)

        status[action_type] = {
            "current": current,
            "max": max_count,
            "remaining": remaining
        }

    return status


def increment_daily_limit(user: str, action_type: str, amount: int = 1) -> bool:
    """
    Increment daily usage counter for user/action_type by amount.

    Called after action successfully completes. Uses file locking for atomic updates.

    Args:
        user: Username
        action_type: Action type
        amount: Amount to increment (default 1)

    Returns:
        True on success, False on error
    """
    counters = _read_daily_limits()
    period_key = _get_counter_period_key()

    if period_key not in counters:
        counters[period_key] = {}
    if user not in counters[period_key]:
        counters[period_key][user] = {}

    counters[period_key][user][action_type] = counters[period_key][user].get(action_type, 0) + amount

    return _write_daily_limits(counters)


def set_limit_config(config: Dict) -> Tuple[bool, str]:
    """
    Write new limit configuration atomically.

    Validates all required keys present and values are non-negative integers.

    Args:
        config: Configuration dict to write

    Returns:
        Tuple of (success: bool, error_msg: str).
        On success: (True, "")
        On error: (False, error_message)
    """
    # Validate required keys and types
    for key in DEFAULT_LIMITS:
        if key not in config:
            return (False, f"Missing required key: {key}")

        value = config[key]
        if isinstance(value, bool):
            continue  # Boolean values OK for allow_* and require_* keys
        if isinstance(value, str):
            continue  # String values OK for reset_* keys
        if not isinstance(value, int) or (isinstance(value, int) and value < -1):
            return (False, f"Invalid value for {key}: must be int >= -1")

    # Write atomically
    limits_path = os.path.join(_get_limits_dir(), "_limit_config.json")
    temp_path = limits_path + ".tmp"

    try:
        with open(temp_path, "w", encoding="utf-8") as fh:
            with file_lock(limits_path, timeout=10):
                json.dump(config, fh, indent=2)
        os.replace(temp_path, limits_path)
        return (True, "")
    except (OSError, IOError) as e:
        try:
            os.remove(temp_path)
        except OSError:
            pass
        return (False, f"Failed to write limit config: {str(e)}")


def reset_daily_limits(analyst: Optional[str] = None) -> Tuple[bool, Dict]:
    """
    Reset daily usage counters.

    Args:
        analyst: Specific analyst to reset, or RESET_ALL_USERS to reset all, or None (reset all)

    Returns:
        Tuple of (success: bool, summary: dict) where summary = {analyst: count_before_reset, ...}
    """
    counters = _read_daily_limits()
    period_key = _get_counter_period_key()

    if period_key not in counters:
        return (True, {})

    summary = {}

    if analyst == RESET_ALL_USERS or analyst is None:
        # Reset all analysts
        for user in list(counters[period_key].keys()):
            summary[user] = len(counters[period_key][user])
        counters[period_key] = {}
    else:
        # Reset single analyst
        if analyst in counters[period_key]:
            summary[analyst] = len(counters[period_key][analyst])
            del counters[period_key][analyst]

    return (_write_daily_limits(counters), summary)


def get_limit_error_msg(user: str, action_type: str, current: int, max_int: int) -> str:
    """
    Format human-readable error message for limit exceeded.

    Args:
        user: Username
        action_type: Action type
        current: Current usage count
        max_int: Maximum allowed (0=disabled, -1=unlimited, N=limit)

    Returns:
        Formatted error message for API response
    """
    if max_int == 0:
        return f"The '{action_type}' action is not permitted."

    remaining = max(0, max_int - current)
    return f"You have {remaining} {action_type} operations remaining today. This request would require more."
