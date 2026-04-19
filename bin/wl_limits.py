"""Single source of truth for rate-limiting and daily usage counters.

Consolidated on 2026-04-19 (Phase 3a of the graphify audit). Previously,
``wl_handler.py`` shipped an independent copy of every function in this
module, with two silent drifts:

1. **Path divergence.** The handler's copies resolved to
   ``lookups/_versions/_{limit_config,daily_limits}.json`` while this
   module resolved to ``lookups/_{limit_config,daily_limits}.json``.
   Since ``wl_approval.check_approval_gate`` imports
   ``check_analyst_limit`` from this module, the approval-gate path was
   reading counters from a file that nothing ever wrote to — an
   undetected "current=0" bypass for every approval-required action.

2. **Feature drift.** The handler's ``_get_counter_period_key`` had
   full 5-frequency support (never/daily/weekly/monthly/yearly) with
   configurable reset boundaries; this module's version was hard-wired
   to daily. The handler's ``_read_limit_config`` performed an HMAC
   integrity check and migrated a legacy ``reset_hour_utc`` key; this
   module's version did neither.

After the merge:

- **One canonical path:** ``lookups/_versions/_{limit_config,daily_limits}.json``.
- **All functions here**, handler imports each as an underscore alias.
- **Regression lock:** ``tests/test_wl_limits.py`` pins checksum bytes,
  period-key boundaries, and path resolution. See CLAUDE.md
  Decision Log 2026-04-19.

Public API (grouped):

*Config I/O:*
    read_limit_config, write_limit_config, compute_config_checksum,
    read_admin_limits, write_admin_limits
*Counter I/O:*
    read_daily_limits, write_daily_limits,
    increment_daily_limit, increment_admin_daily_limit,
    reset_daily_limits
*Period keys:*
    get_counter_period_key, get_admin_counter_period_key
*Checks:*
    check_daily_limit, check_admin_daily_limit, check_admin_permission,
    check_analyst_limit, check_admin_limit, get_limit_status
*Helpers:*
    set_limit_config, get_limit_error_msg

Layer 3 dependency: imports from wl_constants (Layer 0), wl_rbac
(Layer 2), wl_filelock (Layer 2).
"""

from __future__ import annotations

import calendar
import hashlib
import hmac
import json
import logging
import os
import sys
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple

# fcntl is POSIX-only. When running on Windows (dev machines, some CI
# runners), fall back to no-op locking. Splunk's bundled Python on
# Linux containers always provides it.
try:
    import fcntl  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - Windows only
    fcntl = None  # type: ignore[assignment]

# Handle Splunk bin/ import limitations: ensure this directory is on
# sys.path so sibling modules resolve when loaded by the splunkd
# scripted-input context.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from wl_constants import (  # noqa: E402 — after sys.path insert
    DAILY_LIMITS_FILE,
    DEFAULT_ADMIN_LIMITS,
    DEFAULT_LIMITS,
    LIMIT_CONFIG_FILE,
    MAX_TRACKED_ANALYSTS,
    OWN_LOOKUPS,
    RESET_ALL_USERS,
    VERSIONS_DIR,
)
from wl_rbac import is_admin  # noqa: E402

__all__ = [
    # Config I/O
    "read_limit_config",
    "write_limit_config",
    "compute_config_checksum",
    "read_admin_limits",
    "write_admin_limits",
    # Counter I/O
    "read_daily_limits",
    "write_daily_limits",
    "increment_daily_limit",
    "increment_admin_daily_limit",
    "reset_daily_limits",
    # Period keys
    "get_counter_period_key",
    "get_admin_counter_period_key",
    # Checks
    "check_daily_limit",
    "check_admin_daily_limit",
    "check_admin_permission",
    "check_analyst_limit",
    "check_admin_limit",
    "get_limit_status",
    # Helpers
    "set_limit_config",
    "get_limit_error_msg",
]

_logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════
# Integrity checksum — anti-tamper signature on the config file
# ═══════════════════════════════════════════════════════════════════════

# Salt pinned at v1. Changing this invalidates every existing
# deployment's ``_limit_config.json`` and requires a migration.
# Locked by tests/test_wl_limits.py::TestChecksumRegressionLock.
_CONFIG_INTEGRITY_SALT: bytes = b"wl_manager_config_integrity_v1"


def compute_config_checksum(config_data: Dict) -> str:
    """Compute HMAC-SHA256 checksum over a config dict.

    Detects corruption and naive manual edits. Not cryptographically
    secure against attackers with source access (the salt is a literal)
    — it raises the bar for accidental drift, not for a determined
    attacker. The ``wl_fim`` + ``wl_fim_watch`` pair handles attacker
    detection at a different layer.

    The ``_checksum`` key is always stripped before hashing so a signed
    registry can be re-verified without the signature self-referencing.
    """
    filtered = {k: v for k, v in config_data.items() if k != "_checksum"}
    payload = json.dumps(filtered, sort_keys=True, default=str)
    return hmac.new(
        _CONFIG_INTEGRITY_SALT,
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


# ═══════════════════════════════════════════════════════════════════════
# Canonical path resolution — both files live under _versions/
# ═══════════════════════════════════════════════════════════════════════


def _get_limit_config_path() -> str:
    versions_dir = os.path.join(OWN_LOOKUPS, VERSIONS_DIR)
    os.makedirs(versions_dir, exist_ok=True)
    return os.path.join(versions_dir, LIMIT_CONFIG_FILE)


def _get_daily_limits_path() -> str:
    versions_dir = os.path.join(OWN_LOOKUPS, VERSIONS_DIR)
    os.makedirs(versions_dir, exist_ok=True)
    return os.path.join(versions_dir, DAILY_LIMITS_FILE)


# ═══════════════════════════════════════════════════════════════════════
# Limit config I/O
# ═══════════════════════════════════════════════════════════════════════


def read_limit_config() -> Dict:
    """Read the limit config with integrity verification and migration.

    Returns a dict populated with all ``DEFAULT_LIMITS`` keys (missing
    keys are backfilled). On corruption, returns ``dict(DEFAULT_LIMITS)``.

    Integrity check: if ``_checksum`` is present and does not match,
    logs a warning but still returns the data — this preserves the
    handler's historical tolerant behavior (a tamper that locks the
    app out of its own config is worse than one that logs loudly).

    Migration: the legacy ``reset_hour_utc`` (int 0-23) is rewritten
    to the current ``reset_time_utc`` ("HH:MM") format.
    """
    path = _get_limit_config_path()
    if not os.path.isfile(path):
        return dict(DEFAULT_LIMITS)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            config = json.load(fh)

        stored_checksum = config.pop("_checksum", None)
        if stored_checksum is not None:
            expected = compute_config_checksum(config)
            if stored_checksum != expected:
                _logger.warning(
                    "CONFIG_INTEGRITY_FAILED path=%s "
                    "stored=%s expected=%s — possible tampering "
                    "or corruption", path,
                    stored_checksum[:12], expected[:12])

        # Migrate reset_hour_utc (int) -> reset_time_utc ("HH:MM")
        if "reset_hour_utc" in config and "reset_time_utc" not in config:
            h = config.pop("reset_hour_utc", 0)
            if isinstance(h, int) and 0 <= h <= 23:
                config["reset_time_utc"] = "{:02d}:00".format(h)
            else:
                config["reset_time_utc"] = "00:00"
        elif "reset_hour_utc" in config:
            # Both keys present; legacy wins if new is explicitly absent
            # — but here new is present, so just drop the legacy.
            config.pop("reset_hour_utc", None)

        # Backfill any missing default keys
        for k, v in DEFAULT_LIMITS.items():
            if k not in config:
                config[k] = v
        return config
    except (json.JSONDecodeError, OSError):
        return dict(DEFAULT_LIMITS)


def write_limit_config(config: Dict) -> None:
    """Write the limit config with a fresh integrity checksum.

    Stale ``_checksum`` is dropped before re-signing. Uses exclusive
    file-lock via fcntl when available; on Windows, locks are best-
    effort (the dev machine is not a production write target).
    """
    path = _get_limit_config_path()
    config.pop("_checksum", None)
    config["_checksum"] = compute_config_checksum(config)
    with open(path, "w", encoding="utf-8") as fh:
        if fcntl is not None:
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (IOError, OSError):
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            json.dump(config, fh, indent=2)
        finally:
            if fcntl is not None:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def read_admin_limits() -> Dict:
    """Read admin-specific limits (the ``admin_limits`` sub-config).

    Backfills any missing keys from ``DEFAULT_ADMIN_LIMITS``.
    ``change_history`` (if present) is preserved — it is tracked
    outside the default schema.
    """
    config = read_limit_config()
    admin_cfg = config.get("admin_limits", {}) or {}
    for k, v in DEFAULT_ADMIN_LIMITS.items():
        if k not in admin_cfg:
            admin_cfg[k] = v
    return admin_cfg


def write_admin_limits(admin_limits: Dict) -> None:
    """Write admin-specific limits back into the main config."""
    config = read_limit_config()
    config["admin_limits"] = admin_limits
    write_limit_config(config)


# ═══════════════════════════════════════════════════════════════════════
# Daily-limit counter I/O
# ═══════════════════════════════════════════════════════════════════════


def read_daily_limits() -> Dict:
    """Return the full counter map ``{period_key: {user: {action: n}}}``.

    Returns ``{}`` on missing file, parse error, or OS error. Callers
    treat ``{}`` as "no usage yet" — fail-open on read is deliberate
    (the alternative fails all requests when the file is momentarily
    unreadable during writes).
    """
    path = _get_daily_limits_path()
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return {}


def write_daily_limits(counters: Dict) -> None:
    """Write the counter map atomically under fcntl lock."""
    path = _get_daily_limits_path()
    with open(path, "w", encoding="utf-8") as fh:
        if fcntl is not None:
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (IOError, OSError):
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            json.dump(counters, fh, indent=2)
        finally:
            if fcntl is not None:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


# ═══════════════════════════════════════════════════════════════════════
# Period-key bucketing (5 reset frequencies)
# ═══════════════════════════════════════════════════════════════════════


def get_counter_period_key(config: Optional[Dict] = None) -> str:
    """Return the counter bucket key for the current instant.

    Given the reset schedule in ``config`` (or the main analyst config
    if None), finds the most recent reset boundary and returns a key
    unique to that period. Keys by frequency:

    - ``never``   -> ``"permanent"``
    - ``daily``   -> ``"YYYY-MM-DD"``
    - ``weekly``  -> ``"YYYY-Www-Day"`` (ISO year-week-day)
    - ``monthly`` -> ``"YYYY-MM"``
    - ``yearly``  -> ``"YYYY"``

    Unknown frequencies fall back to daily. Invalid ``reset_time_utc``
    falls back to ``00:00``.
    """
    if config is None:
        config = read_limit_config()
    freq = config.get("reset_frequency", "daily")

    if freq == "never":
        return "permanent"

    now = datetime.now(timezone.utc)

    reset_time = config.get("reset_time_utc", "00:00")
    try:
        parts = reset_time.split(":")
        rh, rm = int(parts[0]), int(parts[1])
    except (ValueError, IndexError, AttributeError):
        rh, rm = 0, 0

    now_time_minutes = now.hour * 60 + now.minute

    if freq == "daily":
        reset_minutes = rh * 60 + rm
        if now_time_minutes >= reset_minutes:
            return now.strftime("%Y-%m-%d")
        yesterday = now - timedelta(days=1)
        return yesterday.strftime("%Y-%m-%d")

    if freq == "weekly":
        cfg_dow = config.get("reset_day_of_week", 0)
        if not isinstance(cfg_dow, int) or not (0 <= cfg_dow <= 6):
            cfg_dow = 0
        days_since = (now.weekday() - cfg_dow) % 7
        candidate = now - timedelta(days=days_since)
        boundary = candidate.replace(
            hour=rh, minute=rm, second=0, microsecond=0)
        if now < boundary:
            candidate = candidate - timedelta(days=7)
        return candidate.strftime("%G-W%V-%a")

    if freq == "monthly":
        cfg_dom = config.get("reset_day_of_month", 1)
        if not isinstance(cfg_dom, int) or not (1 <= cfg_dom <= 31):
            cfg_dom = 1
        last_day = calendar.monthrange(now.year, now.month)[1]
        actual_day = min(cfg_dom, last_day)
        boundary = now.replace(
            day=actual_day, hour=rh, minute=rm, second=0, microsecond=0)
        if now >= boundary:
            return now.strftime("%Y-%m")
        prev = now.replace(day=1) - timedelta(days=1)
        return prev.strftime("%Y-%m")

    if freq == "yearly":
        cfg_month = config.get("reset_month", 1)
        cfg_day = config.get("reset_day_of_year", 1)
        if not isinstance(cfg_month, int) or not (1 <= cfg_month <= 12):
            cfg_month = 1
        if not isinstance(cfg_day, int) or not (1 <= cfg_day <= 31):
            cfg_day = 1
        last_day = calendar.monthrange(now.year, cfg_month)[1]
        actual_day = min(cfg_day, last_day)
        try:
            boundary = now.replace(
                month=cfg_month, day=actual_day,
                hour=rh, minute=rm, second=0, microsecond=0)
        except ValueError:
            boundary = now.replace(
                month=cfg_month, day=1,
                hour=rh, minute=rm, second=0, microsecond=0)
        if now >= boundary:
            return now.strftime("%Y")
        return str(now.year - 1)

    # Unknown frequency: fall back to daily
    return now.strftime("%Y-%m-%d")


def get_admin_counter_period_key() -> str:
    """Return the period key based on the ADMIN reset schedule.

    Independent from the analyst schedule — admins may have monthly
    buckets while analysts reset daily, or vice versa.
    """
    admin_cfg = read_admin_limits()
    return get_counter_period_key(config=admin_cfg)


# ═══════════════════════════════════════════════════════════════════════
# Limit checks (analyst + admin)
# ═══════════════════════════════════════════════════════════════════════


def check_daily_limit(
    user: str,
    action_type: str,
    action_count: int = 1,
) -> Tuple[bool, int, int]:
    """Check if user has room for ``action_count`` under the daily limit.

    Returns ``(allowed, current, max_count)``. Does NOT exempt admins
    — caller is responsible for the exemption (use
    ``check_analyst_limit`` for the exemption-aware wrapper).
    """
    config = read_limit_config()
    max_count = config.get(action_type, DEFAULT_LIMITS.get(action_type, 999))

    counters = read_daily_limits()
    period_key = get_counter_period_key(config=config)

    user_counts = counters.get(period_key, {}).get(user, {})
    current = user_counts.get(action_type, 0)

    return (current + action_count) <= max_count, current, max_count


def check_admin_daily_limit(
    user: str,
    action_type: str,
    action_count: int = 1,
) -> Tuple[bool, int, int]:
    """Check an admin-specific limit.

    Admin limits live in ``config['admin_limits']`` and counters are
    tracked under ``admin_<action_type>`` to avoid collision with the
    analyst namespace. A ``max_count`` of ``0`` means the action is
    disabled (not merely exhausted) — returns ``(False, 0, 0)``.
    """
    admin_cfg = read_admin_limits()
    max_count = admin_cfg.get(
        action_type, DEFAULT_ADMIN_LIMITS.get(action_type, 999))
    if max_count == 0:
        return False, 0, 0

    admin_action = "admin_" + action_type
    counters = read_daily_limits()
    period_key = get_admin_counter_period_key()
    period_data = counters.get(period_key, {})
    user_data = period_data.get(user, {})
    current = user_data.get(admin_action, 0)

    allowed = (current + action_count) <= max_count
    return allowed, current, max_count


def check_admin_permission(permission_key: str) -> bool:
    """Return whether an admin-permission toggle is enabled.

    Falls back to ``DEFAULT_ADMIN_LIMITS`` default if missing; that
    default is ``True`` for all current toggles (fail-open on read,
    fail-closed on write is handled elsewhere).
    """
    admin_cfg = read_admin_limits()
    return bool(admin_cfg.get(
        permission_key, DEFAULT_ADMIN_LIMITS.get(permission_key, True)))


# ═══════════════════════════════════════════════════════════════════════
# Counter mutations
# ═══════════════════════════════════════════════════════════════════════


def increment_daily_limit(
    user: str,
    action_type: str,
    count: int = 1,
) -> None:
    """Increment the counter for ``(user, action_type)`` by ``count``.

    Maintenance:
    - Old period keys are pruned (for ``never`` mode, only ``permanent``
      is kept; for date-based keys, only keys >= the current key are
      kept).
    - A hard cap of ``MAX_TRACKED_ANALYSTS`` per period prevents
      unbounded growth under attack — overflow users are tracked under
      a shared ``__overflow__`` bucket so limits still enforce.
    """
    counters = read_daily_limits()
    today = get_counter_period_key()

    if today == "permanent":
        counters = {k: v for k, v in counters.items() if k == "permanent"}
    else:
        counters = {k: v for k, v in counters.items()
                    if k == today or k >= today}

    if today not in counters:
        counters[today] = {}

    if user not in counters[today]:
        if len(counters[today]) >= MAX_TRACKED_ANALYSTS:
            _logger.warning(
                "MAX_TRACKED_ANALYSTS (%d) reached — tracking '%s' "
                "under overflow bucket", MAX_TRACKED_ANALYSTS, user)
            user = "__overflow__"
            if user not in counters[today]:
                counters[today][user] = {}
        else:
            counters[today][user] = {}

    prev = counters[today][user].get(action_type, 0)
    counters[today][user][action_type] = prev + count
    write_daily_limits(counters)


def increment_admin_daily_limit(
    user: str,
    action_type: str,
    count: int = 1,
) -> None:
    """Increment an admin counter. Uses ``admin_`` action prefix.

    Counter layout matches ``increment_daily_limit`` but buckets under
    the admin period-key, so analyst/admin schedules can differ.
    """
    admin_action = "admin_" + action_type
    counters = read_daily_limits()
    period_key = get_admin_counter_period_key()
    if period_key not in counters:
        counters[period_key] = {}
    if user not in counters[period_key]:
        counters[period_key][user] = {}
    counters[period_key][user][admin_action] = (
        counters[period_key][user].get(admin_action, 0) + count)
    write_daily_limits(counters)


def reset_daily_limits(
    analyst: Optional[str] = None,
) -> Tuple[bool, Dict]:
    """Reset counters for the CURRENT period key.

    Args:
        analyst: ``None`` or ``RESET_ALL_USERS`` -> reset everyone;
            otherwise reset only the named analyst.

    Returns:
        ``(success, summary)`` where ``summary`` maps each reset user
        to the number of action-types they had counts for (a rough
        measure of "how much activity was wiped").
    """
    counters = read_daily_limits()
    period_key = get_counter_period_key()

    if period_key not in counters:
        return True, {}

    summary: Dict[str, int] = {}

    if analyst == RESET_ALL_USERS or analyst is None:
        for u in list(counters[period_key].keys()):
            summary[u] = len(counters[period_key][u])
        counters[period_key] = {}
    else:
        if analyst in counters[period_key]:
            summary[analyst] = len(counters[period_key][analyst])
            del counters[period_key][analyst]

    try:
        write_daily_limits(counters)
        return True, summary
    except OSError:
        return False, summary


# ═══════════════════════════════════════════════════════════════════════
# Backward-compatible wrappers (pre-merge public API)
# ═══════════════════════════════════════════════════════════════════════


def check_analyst_limit(
    user: str,
    action_type: str,
    action_count: int = 1,
    roles: Optional[List[str]] = None,
) -> Tuple[bool, int, int]:
    """Analyst limit check with admin-role exemption.

    Used by ``wl_approval.check_approval_gate``. Admins are exempt
    (return ``(True, 0, -1)``) — they gate themselves through
    ``check_admin_daily_limit``.
    """
    roles_set = set(roles) if roles else set()
    if is_admin(roles_set):
        return True, 0, -1

    config = read_limit_config()
    max_count = config.get(action_type, DEFAULT_LIMITS.get(action_type, -1))

    if max_count == 0:
        return False, 0, 0
    if max_count == -1:
        return True, 0, -1

    counters = read_daily_limits()
    period_key = get_counter_period_key(config=config)
    current = counters.get(period_key, {}).get(user, {}).get(action_type, 0)
    allowed = (current + action_count) <= max_count
    return allowed, current, max_count


def check_admin_limit(
    user: str,
    action_type: str,
    action_count: int = 1,
) -> Tuple[bool, int, int]:
    """Backward-compat wrapper — delegates to ``check_admin_daily_limit``.

    The pre-merge version of this function read the MAIN config (not
    the ``admin_limits`` sub-config) — a dormant bug since no caller
    invoked it. The merge aligns it with the handler's historical
    semantics.
    """
    return check_admin_daily_limit(user, action_type, action_count)


def get_limit_status(
    user: str,
    roles: Optional[List[str]] = None,
) -> Dict:
    """Return a per-action usage summary for ``user``.

    Shape: ``{action: {current, max, remaining}}``. For admin users,
    every entry is ``{0, -1, -1}`` (unlimited).
    """
    roles_set = set(roles) if roles else set()
    config = read_limit_config()
    counters = read_daily_limits()
    period_key = get_counter_period_key(config=config)

    status: Dict[str, Dict[str, int]] = {}

    for action_type in DEFAULT_LIMITS:
        if action_type.startswith(("reset_", "allow_", "require_")):
            continue
        max_count = config.get(action_type, -1)

        if is_admin(roles_set):
            status[action_type] = {"current": 0, "max": -1, "remaining": -1}
            continue

        current = counters.get(period_key, {}).get(user, {}).get(
            action_type, 0)

        if max_count == 0:
            remaining = 0
        elif max_count == -1:
            remaining = -1
        else:
            remaining = max(0, max_count - current)

        status[action_type] = {
            "current": current,
            "max": max_count,
            "remaining": remaining,
        }

    return status


def set_limit_config(config: Dict) -> Tuple[bool, str]:
    """Validate and persist a limit config. Returns ``(success, error)``.

    Validation rules (mirrored from the pre-merge impl):
    - Every ``DEFAULT_LIMITS`` key must be present.
    - Bool values pass (for ``allow_*`` / ``require_*``).
    - String values pass (for ``reset_*``).
    - Int values must be >= -1.
    """
    for key in DEFAULT_LIMITS:
        if key not in config:
            return False, f"Missing required key: {key}"
        value = config[key]
        if isinstance(value, bool):
            continue
        if isinstance(value, str):
            continue
        if not isinstance(value, int) or value < -1:
            return False, f"Invalid value for {key}: must be int >= -1"

    try:
        write_limit_config(config)
        return True, ""
    except OSError as exc:
        return False, f"Failed to write limit config: {exc}"


def get_limit_error_msg(
    user: str,
    action_type: str,
    current: int,
    max_int: int,
) -> str:
    """Format a human-readable limit-exceeded message."""
    if max_int == 0:
        return f"The '{action_type}' action is not permitted."
    remaining = max(0, max_int - current)
    return (f"You have {remaining} {action_type} operations remaining "
            f"today. This request would require more.")
