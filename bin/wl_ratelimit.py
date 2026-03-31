"""
Rate limiting for Whitelist Manager REST API.

Provides sliding-window rate limiting per user and action type.
Module-level state: _rate_limits dict tracking timestamps.

Layer 2: imports only from wl_constants.
"""

import time
from typing import Dict, Tuple, List

__all__ = ["check_rate_limit", "reset_rate_limits"]

# Module-level state
_rate_limits: Dict[Tuple[str, str], List[float]] = {}


def check_rate_limit(user: str, action_type: str = "write") -> bool:
    """
    Check if a user action is within rate limits using sliding window.

    Sliding window: tracks timestamps of recent requests in a rolling window.
    If window is full, request is rejected.

    Args:
        user: Username
        action_type: "read" or "write"

    Returns:
        True if request allowed, False if rate limit exceeded
    """
    from wl_constants import RATE_WINDOW, RATE_MAX_WRITES, RATE_MAX_READS

    global _rate_limits
    now = time.time()
    key = (user, action_type)
    max_req = RATE_MAX_WRITES if action_type == "write" else RATE_MAX_READS

    if key not in _rate_limits:
        _rate_limits[key] = []

    # Prune timestamps outside the window
    _rate_limits[key] = [t for t in _rate_limits[key] if now - t < RATE_WINDOW]

    # Auto-cleanup stale keys to prevent memory growth
    if len(_rate_limits) > 10000:
        stale = [k for k, v in _rate_limits.items() if not v or now - v[-1] > RATE_WINDOW * 2]
        for k in stale:
            del _rate_limits[k]

    # Check if limit exceeded
    if len(_rate_limits[key]) >= max_req:
        return False

    # Record this request
    _rate_limits[key].append(now)
    return True


def reset_rate_limits() -> None:
    """
    Reset all rate limit counters. Used for testing.
    """
    global _rate_limits
    _rate_limits.clear()
