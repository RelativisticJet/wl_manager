"""
Whitelist Manager — Splunk REST Handler (the "wrapper").

This is the server-side core of the application. It intercepts every CSV
read/write, computes a structured diff (like Git), and writes an audit
event to both a Splunk index and a rotating log file.

Endpoint registered in restmap.conf:
    GET  /custom/wl_manager/wl_handler?action=<action>&...
    POST /custom/wl_manager/wl_handler   { "action": "save_csv", ... }

GET actions:
    get_rules        — list all detection rule names
    get_csvs         — list CSV files for a given rule
    get_csv_content  — return headers + rows for a CSV
    get_mapping      — return the full rule_csv_map

POST actions:
    save_csv         — write new rows, compute diff, write audit
    create_csv       — create a new CSV file for a rule + update mapping
"""

import os
import sys
import json
import csv
import difflib
import re
import traceback
import logging
import logging.handlers
import calendar
import shutil
import time
import threading
try:
    import fcntl
except ImportError:
    fcntl = None  # Windows — file locking unavailable
from contextlib import contextmanager
from collections import Counter
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# Splunk imports
# ---------------------------------------------------------------------------
from splunk.persistconn.application import PersistentServerConnectionApplication

# splunklib is the Splunk SDK — NOT bundled with Splunk by default.
# We import it lazily (inside _index_audit) so the handler still loads
# even if splunklib is not installed.  Audit events will fall back to
# the log file only in that case.

# ---------------------------------------------------------------------------
# Layer 0: Constants (imported from wl_constants module)
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.dirname(__file__))
from wl_constants import (
    APP_NAME, SPLUNK_HOME, APPS_DIR, OWN_LOOKUPS, MAPPING_FILE,
    MAX_ROWS, MAX_COLUMNS, MAX_CELL_CHARS, MAX_PAYLOAD_BYTES,
    MAX_AUDIT_VALUE_LINES, MAX_DIFF_ROWS, MAX_PRESENCE_USERS, MAX_PRESENCE_FILES,
    PRESENCE_TIMEOUT, IDLE_TIMEOUT, RATE_WINDOW, RATE_MAX_WRITES, RATE_MAX_READS,
    EDIT_ROLES, ADMIN_ROLES, SUPERADMIN_ROLES, EXPIRE_COLUMN_NAMES,
    AUDIT_INDEX, AUDIT_SOURCE, AUDIT_SOURCETYPE, VERSIONS_DIR, MAX_VERSIONS,
    AUDIT_LOG, TRASH_DIR, MIN_TRASH_RETENTION_DAYS, DEFAULT_TRASH_RETENTION_DAYS,
    TRASH_CONFIG_FILE, DETECTION_RULES_FILE, MAX_DETECTION_RULES,
    MAX_CSVS_PER_RULE, MAX_TOTAL_CSV_MAPPINGS, APPROVAL_QUEUE_FILE,
    DAILY_LIMITS_FILE, LIMIT_CONFIG_FILE, APPROVAL_EXPIRY_DAYS,
    MAX_PENDING_REQUESTS, MAX_RESOLVED_HISTORY, MAX_TRACKED_ANALYSTS,
    NOTIFICATION_FILE, MAX_NOTIFICATIONS_PER_USER, NOTIFICATION_MAX_AGE_DAYS,
    DEFAULT_LIMITS, DEFAULT_ADMIN_LIMITS,
    APPROVAL_BULK_ROW_THRESHOLD, APPROVAL_BULK_EDIT_THRESHOLD,
    APPROVAL_COLUMN_NONEMPTY_THRESHOLD, APPROVAL_BULK_ADD_THRESHOLD,
    APPROVAL_REVERT_ROW_THRESHOLD, APPROVAL_REVERT_COLUMN_THRESHOLD,
    _CONTROL_CHAR_RE, _SAFE_COLNAME_RE, _SANITIZE_RE,
    get_splunk_home, get_detection_rules_path, get_approval_queue_path,
)

# ---------------------------------------------------------------------------
# Layer 1: Logging (imported from wl_logging module)
# ---------------------------------------------------------------------------
from wl_logging import get_audit_logger

# ---------------------------------------------------------------------------
# Layer 2: Validation (imported from wl_validation module)
# ---------------------------------------------------------------------------
from wl_validation import (
    sanitize_text,
    validate_ascii_text,
    is_safe_filename,
    safe_realpath,
    build_csv_path,
    resolve_csv_path,
)

# ---------------------------------------------------------------------------
# Layer 2: Rate Limiting (imported from wl_ratelimit module)
# ---------------------------------------------------------------------------
from wl_ratelimit import check_rate_limit, reset_rate_limits

# ---------------------------------------------------------------------------
# Layer 2: RBAC (imported from wl_rbac module)
# ---------------------------------------------------------------------------
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

# ---------------------------------------------------------------------------
# Layer 2: Presence Tracking (imported from wl_presence module)
# ---------------------------------------------------------------------------
from wl_presence import report_presence, get_presence, cleanup_presence, reset_presence

# ---------------------------------------------------------------------------
# Layer 3: CSV Operations (imported from wl_csv module)
# ---------------------------------------------------------------------------
from wl_csv import (
    read_csv, write_csv, compute_diff, get_expire_column, remove_expired_rows,
    get_column_widths, set_column_widths, save_csv_pipeline, create_csv_pipeline
)

# Layer 3: Detection Rules Registry (imported from wl_rules module)
# ---------------------------------------------------------------------------
from wl_rules import (read_rules_registry, write_rules_registry, read_csv_mapping,
                      get_rule_csv_file, get_rule_for_csv, create_rule_pipeline,
                      delete_rule_pipeline, delete_csv_pipeline)

# Layer 3: Trash Management (imported from wl_trash module)
# ---------------------------------------------------------------------------
from wl_trash import (move_to_trash, list_trash, restore_from_trash,
                      restore_from_trash_pipeline, purge_trash_item, auto_cleanup_trash,
                      get_trash_dir)

# ---------------------------------------------------------------------------
# Layer 3: Version Snapshots & Manifest (imported from wl_versions module)
# ---------------------------------------------------------------------------
from wl_versions import (
    get_versions_dir, read_version_manifest, write_version_manifest,
    snapshot_version, get_versions_list, revert_csv_pipeline
)

# ---------------------------------------------------------------------------
# Layer 3: Audit Events (imported from wl_audit module)
# ---------------------------------------------------------------------------
from wl_audit import build_audit_event, post_audit_event

# ---------------------------------------------------------------------------
# Layer 3: Daily Limits & File Locking (imported from Phase 3 modules)
# ---------------------------------------------------------------------------
from wl_limits import (
    check_analyst_limit, check_admin_limit, get_limit_status,
    increment_daily_limit, set_limit_config, reset_daily_limits,
    get_limit_error_msg
)
from wl_filelock import file_lock

# ---------------------------------------------------------------------------
# Layer 3: Approval Queue (imported from Phase 3 modules)
# ---------------------------------------------------------------------------
from wl_approval import (
    get_pending_for_csv, get_pending_for_rule, submit_approval,
    submit_dual_approval, check_approval_gate, expire_pending_approvals,
    check_conflicts, cancel_conflicts
)
# Layer 5: Approval replay orchestration
from wl_replay import execute_approved_action

# ---------------------------------------------------------------------------
# Rotating file logger — backup audit trail independent of Splunk indexing
# ---------------------------------------------------------------------------
_logger = get_audit_logger()


# ═══════════════════════════════════════════════════════════════════════════
# Utility helpers
# ═══════════════════════════════════════════════════════════════════════════


# NOTE: get_expire_column, read_csv, write_csv imported from wl_csv
# NOTE: read_rules_registry, write_rules_registry imported from wl_rules


_detection_rules_lock = threading.Lock()


@contextmanager
def _detection_rules_modify():
    """Lock for atomic read-modify-write on detection rules registry."""
    with _detection_rules_lock:
        yield


# ═══════════════════════════════════════════════════════════════════════════
# Approval workflow helpers
# ═══════════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════════
# Approval Queue Helpers (wrappers around wl_approval module functions)
# ═══════════════════════════════════════════════════════════════════════════
# These wrappers provide backward compatibility with handler's existing code
# while delegating to wl_approval module which handles file locking via wl_filelock.
# ═══════════════════════════════════════════════════════════════════════════

def _read_approval_queue():
    """Read and return the approval queue list, or empty list on error.

    Wrapper around wl_approval._read_approval_queue() that converts
    tuple (list, error) to just list (for backward compatibility).
    """
    from wl_approval import _read_approval_queue as wl_read_queue
    queue, _ = wl_read_queue()
    return queue


def _write_approval_queue(queue):
    """Write the approval queue to disk atomically.

    Wrapper around wl_approval._write_approval_queue() that handles
    the tuple (success, error) return (for backward compatibility).
    """
    from wl_approval import _write_approval_queue as wl_write_queue
    success, error = wl_write_queue(queue)
    if not success:
        _logger.error(f"Failed to write approval queue: {error}")
    return success


@contextmanager
def _approval_queue_lock():
    """Context manager for approval queue operations (backward compatibility).

    The new wl_approval module uses file_lock internally from wl_filelock,
    so explicit locking in the handler is no longer needed. This is kept
    for backward compatibility with existing code.
    """
    yield  # No-op: wl_approval handles locking internally


def _cancel_conflicting_requests(queue, detection_rule, csv_file,
                                 trigger_action, trigger_request_id,
                                 audit_fn):
    """Cancel pending requests that conflict with a destructive action.

    Wrapper around wl_approval.cancel_conflicts() that also integrates with
    the handler's auditing and notification systems.

    Args:
        queue: The approval queue list.
        detection_rule: The rule that was removed/affected.
        csv_file: The CSV that was removed (or "" for rule removal).
        trigger_action: "delete_rule" or "delete_csv".
        trigger_request_id: Request ID that triggered the cancel (or "").
        audit_fn: Callable(event_dict) to write audit events.

    Returns:
        List of cancelled entries.
    """
    # Map handler's action names to wl_approval's action_type names
    action_type_map = {
        "remove_rule": "delete_rule",
        "remove_csv": "delete_csv",
    }
    action_type = action_type_map.get(trigger_action, trigger_action)

    # Build action dict for wl_approval.cancel_conflicts
    action = {
        "action_type": action_type,
        "csv_file": csv_file,
        "detection_rule": detection_rule,
        "analyst": "system",  # Required for audit tracking
    }

    # Call wl_approval.cancel_conflicts to get new queue and cancelled entries
    new_queue, cancelled_entries = cancel_conflicts(queue, action)

    # Filter out the trigger request if it's in the list
    if trigger_request_id:
        cancelled_entries = [e for e in cancelled_entries
                             if e.get("request_id") != trigger_request_id]

    if cancelled_entries:
        # Update the queue in place for caller
        queue[:] = new_queue

        # Add handler notifications
        for entry in cancelled_entries:
            entity = detection_rule if trigger_action == "remove_rule" \
                else csv_file
            _add_notification(
                entry["analyst"], "cancelled",
                "Your {} request was auto-cancelled because {} '{}' "
                "was removed".format(
                    entry["action_type"].replace("_", " "),
                    "rule" if trigger_action == "remove_rule" else "CSV",
                    entity),
                entry["request_id"],
                {"csv_file": entry.get("csv_file", ""),
                 "detection_rule": entry.get("detection_rule", ""),
                 "action_type": entry["action_type"]})

        # Write updated queue
        _write_approval_queue(new_queue)

        # Audit each cancellation
        now = int(time.time())
        for entry in cancelled_entries:
            audit_fn({
                "timestamp": now,
                "analyst": "system",
                "action": "request_auto_cancelled",
                "status": "cancelled",
                "detection_rule": entry.get("detection_rule", ""),
                "csv_file": entry.get("csv_file", ""),
                "request_id": entry["request_id"],
                "trigger_request_id": trigger_request_id,
                "comment": "Auto-cancelled due to {} approval".format(
                    trigger_action.replace("_", " ")),
            })

    return cancelled_entries


# ---------------------------------------------------------------------------
# Notification helpers (module-level)
# ---------------------------------------------------------------------------

def _get_notification_path():
    """Return path to the notifications JSON file."""
    versions_dir = os.path.join(OWN_LOOKUPS, VERSIONS_DIR)
    os.makedirs(versions_dir, exist_ok=True)
    return os.path.join(versions_dir, NOTIFICATION_FILE)


def _read_notifications():
    """Read per-user notifications dict."""
    path = _get_notification_path()
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return {}


def _write_notifications(data):
    """Write per-user notifications to disk."""
    path = _get_notification_path()
    with open(path, "w", encoding="utf-8") as fh:
        if fcntl:
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (IOError, OSError):
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            json.dump(data, fh, indent=2, default=str)
        finally:
            if fcntl:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _add_notification(for_user, notif_type, message,
                      related_request_id=None, extra=None):
    """Add a notification for a specific user.

    notif_type: 'new_request', 'approved', 'rejected', 'cancelled'
    """
    data = _read_notifications()
    user_notifs = data.get(for_user, [])

    notif = {
        "id": "notif_{}_{}".format(int(time.time() * 1000000), for_user),
        "type": notif_type,
        "message": message,
        "related_request_id": related_request_id,
        "timestamp": int(time.time()),
        "read": False,
    }
    if extra:
        notif.update(extra)

    user_notifs.insert(0, notif)  # newest first

    # Cleanup: max per user, max age
    cutoff = int(time.time()) - (NOTIFICATION_MAX_AGE_DAYS * 86400)
    user_notifs = [n for n in user_notifs if n.get("timestamp", 0) >= cutoff]
    user_notifs = user_notifs[:MAX_NOTIFICATIONS_PER_USER]

    data[for_user] = user_notifs
    _write_notifications(data)




def _notify_admins(notif_type, message, related_request_id=None,
                   extra=None, session_key=""):
    """Send notification to all admin-role users."""
    admin_users = get_admin_users(session_key)
    for admin_user in admin_users:
        _add_notification(admin_user, notif_type, message,
                          related_request_id, extra)


def _get_limit_config_path():
    """Return path to the daily limit config JSON file."""
    versions_dir = os.path.join(OWN_LOOKUPS, VERSIONS_DIR)
    os.makedirs(versions_dir, exist_ok=True)
    return os.path.join(versions_dir, LIMIT_CONFIG_FILE)


def _read_limit_config():
    """Read daily limit config, returning defaults if file doesn't exist."""
    path = _get_limit_config_path()
    if not os.path.isfile(path):
        return dict(DEFAULT_LIMITS)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            config = json.load(fh)
            # Migrate old reset_hour_utc (int 0-23) to reset_time_utc ("HH:MM")
            if "reset_hour_utc" in config and "reset_time_utc" not in config:
                h = config.pop("reset_hour_utc", 0)
                if isinstance(h, int) and 0 <= h <= 23:
                    config["reset_time_utc"] = "{:02d}:00".format(h)
                else:
                    config["reset_time_utc"] = "00:00"
            elif "reset_hour_utc" in config:
                config.pop("reset_hour_utc", None)
            # Ensure all default keys exist
            for k, v in DEFAULT_LIMITS.items():
                if k not in config:
                    config[k] = v
            return config
    except (json.JSONDecodeError, OSError):
        return dict(DEFAULT_LIMITS)


def _get_threshold(name):
    """Read an approval threshold from config, falling back to defaults."""
    config = _read_limit_config()
    return config.get(name, DEFAULT_LIMITS.get(name, 5))


def _write_limit_config(config):
    """Write daily limit config to disk."""
    path = _get_limit_config_path()
    with open(path, "w", encoding="utf-8") as fh:
        if fcntl:
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (IOError, OSError):
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            json.dump(config, fh, indent=2)
        finally:
            if fcntl:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _read_admin_limits():
    """Read admin-specific limits from the config file."""
    config = _read_limit_config()
    admin_cfg = config.get("admin_limits", {})
    # Ensure all default admin limit keys exist
    for k, v in DEFAULT_ADMIN_LIMITS.items():
        if k not in admin_cfg:
            admin_cfg[k] = v
    return admin_cfg


def _write_admin_limits(admin_limits):
    """Write admin-specific limits to the config file."""
    config = _read_limit_config()
    config["admin_limits"] = admin_limits
    _write_limit_config(config)


def _check_admin_daily_limit(user, action_type, action_count=1):
    """Check if an admin has exceeded their daily limit for an action.

    Returns (allowed, current_count, maximum).
    Uses the same counter structure as editor limits:
      counters[period_key][user][action_type]
    with "admin_" prefix on the action type.
    """
    admin_cfg = _read_admin_limits()
    max_count = admin_cfg.get(action_type,
                              DEFAULT_ADMIN_LIMITS.get(action_type, 999))
    # 0 = disabled (action not permitted at all)
    if max_count == 0:
        return False, 0, 0

    admin_action = "admin_" + action_type
    counters = _read_daily_limits()
    period_key = _get_counter_period_key()
    period_data = counters.get(period_key, {})
    user_data = period_data.get(user, {})
    current = user_data.get(admin_action, 0)

    allowed = (current + action_count) <= max_count
    return allowed, current, max_count


def _increment_admin_daily_limit(user, action_type, count=1):
    """Increment an admin's daily counter for an action type.

    Counter structure: counters[period_key][user][action_type]
    matches the existing editor counter layout.
    """
    admin_action = "admin_" + action_type
    counters = _read_daily_limits()
    period_key = _get_counter_period_key()
    if period_key not in counters:
        counters[period_key] = {}
    if user not in counters[period_key]:
        counters[period_key][user] = {}
    counters[period_key][user][admin_action] = \
        counters[period_key][user].get(admin_action, 0) + count
    _write_daily_limits(counters)


def _get_daily_limits_path():
    """Return path to the daily limits counters JSON file."""
    versions_dir = os.path.join(OWN_LOOKUPS, VERSIONS_DIR)
    os.makedirs(versions_dir, exist_ok=True)
    return os.path.join(versions_dir, DAILY_LIMITS_FILE)


def _read_daily_limits():
    """Read daily limit counters, or empty dict on error."""
    path = _get_daily_limits_path()
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return {}


def _write_daily_limits(counters):
    """Write daily limit counters to disk."""
    path = _get_daily_limits_path()
    with open(path, "w", encoding="utf-8") as fh:
        if fcntl:
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (IOError, OSError):
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            json.dump(counters, fh, indent=2)
        finally:
            if fcntl:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


# ══════════════════════════════════════════════════════════════════
# Trash / soft-delete helpers
# ══════════════════════════════════════════════════════════════════

def _generate_request_id(user, csv_file="", detection_rule=""):
    """Generate a unique approval request ID.

    Format: req_{timestamp}_{random}_{user}
    """
    import random
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y%m%d_%H%M%S")
    suffix = "{:04d}".format(random.randint(0, 9999))
    return "req_{}_{}_{}" .format(ts, suffix, user)


def _get_counter_period_key():
    """Return the counter period key based on frequency and reset schedule.

    Finds the most recent reset boundary and returns a unique key for that
    period.  The boundary is defined by:
      - reset_time_utc (HH:MM) for all frequencies
      - reset_day_of_week (0=Mon..6=Sun) for weekly
      - reset_day_of_month (1-31, clamped) for monthly
      - reset_month (1-12) + reset_day_of_year (1-31, clamped) for yearly

    Keys by frequency:
      never   -> "permanent"
      daily   -> "2026-03-03"
      weekly  -> "2026-W09-Wed"  (includes day for uniqueness)
      monthly -> "2026-03"
      yearly  -> "2026"
    """
    config = _read_limit_config()
    freq = config.get("reset_frequency", "daily")

    if freq == "never":
        return "permanent"

    now = datetime.now(timezone.utc)

    # Parse reset time
    reset_time = config.get("reset_time_utc", "00:00")
    try:
        parts = reset_time.split(":")
        rh, rm = int(parts[0]), int(parts[1])
    except (ValueError, IndexError):
        rh, rm = 0, 0

    now_time_minutes = now.hour * 60 + now.minute

    if freq == "daily":
        reset_minutes = rh * 60 + rm
        if now_time_minutes >= reset_minutes:
            return now.strftime("%Y-%m-%d")
        else:
            yesterday = now - timedelta(days=1)
            return yesterday.strftime("%Y-%m-%d")

    elif freq == "weekly":
        cfg_dow = config.get("reset_day_of_week", 0)  # 0=Mon
        if not isinstance(cfg_dow, int) or not (0 <= cfg_dow <= 6):
            cfg_dow = 0
        # How many days since the configured weekday?
        days_since = (now.weekday() - cfg_dow) % 7
        candidate = now - timedelta(days=days_since)
        boundary = candidate.replace(hour=rh, minute=rm, second=0, microsecond=0)
        if now < boundary:
            # Haven't reached reset time on this weekday yet — go back 7 days
            candidate = candidate - timedelta(days=7)
        return candidate.strftime("%G-W%V-%a")

    elif freq == "monthly":
        cfg_dom = config.get("reset_day_of_month", 1)
        if not isinstance(cfg_dom, int) or not (1 <= cfg_dom <= 31):
            cfg_dom = 1
        # Clamp to last day of current month
        last_day = calendar.monthrange(now.year, now.month)[1]
        actual_day = min(cfg_dom, last_day)
        boundary = now.replace(day=actual_day, hour=rh, minute=rm,
                               second=0, microsecond=0)
        if now >= boundary:
            return now.strftime("%Y-%m")
        else:
            # Before boundary — still in previous month's period
            prev = now.replace(day=1) - timedelta(days=1)
            return prev.strftime("%Y-%m")

    elif freq == "yearly":
        cfg_month = config.get("reset_month", 1)
        cfg_day = config.get("reset_day_of_year", 1)
        if not isinstance(cfg_month, int) or not (1 <= cfg_month <= 12):
            cfg_month = 1
        if not isinstance(cfg_day, int) or not (1 <= cfg_day <= 31):
            cfg_day = 1
        last_day = calendar.monthrange(now.year, cfg_month)[1]
        actual_day = min(cfg_day, last_day)
        try:
            boundary = now.replace(month=cfg_month, day=actual_day,
                                   hour=rh, minute=rm, second=0, microsecond=0)
        except ValueError:
            boundary = now.replace(month=cfg_month, day=1,
                                   hour=rh, minute=rm, second=0, microsecond=0)
        if now >= boundary:
            return now.strftime("%Y")
        else:
            return str(now.year - 1)

    # Fallback: daily
    return now.strftime("%Y-%m-%d")


def _check_daily_limit(user, action_type, action_count=1):
    """
    Check if user has room for action_count more items under the daily limit.
    Returns (allowed: bool, current_count: int, max_count: int).
    """
    config = _read_limit_config()
    max_count = config.get(action_type, DEFAULT_LIMITS.get(action_type, 999))

    counters = _read_daily_limits()
    today = _get_counter_period_key()

    user_counts = counters.get(today, {}).get(user, {})
    current = user_counts.get(action_type, 0)

    return current + action_count <= max_count, current, max_count


# ── Human-readable labels for limit_type keys ──────────────────────
_LIMIT_LABELS = {
    "row_removal": "Row removal",
    "row_addition": "Row addition",
    "row_edit": "Row editing",
    "bulk_row_removal": "Bulk row removal",
    "bulk_row_edit": "Bulk row editing",
    "column_removal": "Column removal",
    "revert": "CSV revert",
    "rule_deletion": "Rule deletion",
    "csv_deletion": "CSV deletion",
    "approval_count": "Approval",
}


def _daily_limit_error_msg(limit_type, action_count, current, maximum,
                           contact="your administrator"):
    """Build the appropriate error message for daily limits.

    When maximum == 0 the action is *disabled* (not merely exhausted).
    """
    label = _LIMIT_LABELS.get(limit_type, limit_type.replace("_", " "))
    if maximum == 0:
        return ("{} has been disabled by {}. "
                "This action is not permitted.".format(label, contact))
    over = current + action_count - maximum
    return ("Daily limit exceeded for {}. "
            "This action affects {} row(s), exceeding "
            "your daily limit by {} ({}/{} used). "
            "Contact {}.".format(
                label.lower(), action_count, over, current, maximum,
                contact))


def _increment_daily_limit(user, action_type, count=1):
    """Increment the daily limit counter for a user and action type."""
    counters = _read_daily_limits()
    today = _get_counter_period_key()

    # Clean up old period keys (keep only current period)
    # For "permanent" mode, never discard; for date-based keys, drop older ones
    if today == "permanent":
        counters = {k: v for k, v in counters.items() if k == "permanent"}
    else:
        counters = {k: v for k, v in counters.items()
                    if k == today or k >= today}
    if today not in counters:
        counters[today] = {}
    if user not in counters[today]:
        # Cap tracked analysts per day to prevent unbounded growth.
        # If cap is hit, log a warning and track under __overflow__ to
        # still enforce limits rather than silently allowing unlimited.
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
    _write_daily_limits(counters)


def _expire_pending_approvals():
    """
    Auto-reject approval requests older than APPROVAL_EXPIRY_DAYS.
    Also prune resolved entries older than RESOLVED_HISTORY_DAYS.
    Called on every queue read.

    Wrapper around wl_approval.expire_pending_approvals() that maintains
    handler compatibility while delegating the expiration logic to the
    module.

    Returns:
        The (possibly modified) queue with expired entries marked.
    """
    queue = _read_approval_queue()
    # Call wl_approval's expire_pending_approvals to mark expired entries
    queue = expire_pending_approvals(queue)
    # Write back if there were any changes
    _write_approval_queue(queue)
    return queue


def _get_pending_for_csv(csv_file):
    """Return pending approval items for a specific CSV file."""
    queue = _expire_pending_approvals()
    return [item for item in queue
            if item.get("csv_file") == csv_file and item.get("status") == "pending"]


def _count_nonempty_cells(rows, col_name):
    """Count how many rows have a non-empty value for the given column."""
    return sum(1 for r in rows if (r.get(col_name, "") or "").strip())


class WhitelistHandler(PersistentServerConnectionApplication):
    """Splunk PersistentServerConnectionApplication handler with dispatch-table routing."""

    # ===================================================================
    # Dispatch Tables (class-level constants)
    # ===================================================================
    # Maps action names to (required_roles, method_name) tuples.
    # If required_roles is None, the action is public (no RBAC check).
    # Otherwise, at least one role in the set must be present.

    GET_ACTIONS = {
        # CSV Operations (read-only)
        "get_rules": (None, "_action_get_rules"),
        "get_csvs": (None, "_action_get_csvs"),
        "get_csv_content": (None, "_action_get_csv_content"),
        "get_mapping": (None, "_action_get_mapping"),
        "get_versions": (None, "_action_get_versions"),
        "check_csv_status": (None, "_action_check_csv_status"),
        "get_col_widths": (None, "_action_get_col_widths"),
        "get_apps": (None, "_action_get_apps"),

        # Presence & Activity (read-only)
        "report_presence": (None, "_action_report_presence"),
        "get_presence": (None, "_action_get_presence"),

        # User info (role detection without 403 probing)
        "get_user_info": (None, "_action_get_user_info"),

        # Approval & Queue (read-only)
        "get_pending_approvals": (None, "_action_get_pending_approvals"),
        "get_request_csv": (ADMIN_ROLES, "_action_get_request_csv"),
        "get_approval_queue": (ADMIN_ROLES, "_action_get_approval_queue"),

        # Limits & Usage (read-only)
        "check_daily_limit_status": (None, "_action_check_daily_limit_status"),
        "get_daily_limits": (ADMIN_ROLES, "_action_get_daily_limits"),
        "get_analyst_usage": (ADMIN_ROLES, "_action_get_analyst_usage"),
        "get_admin_limits": (ADMIN_ROLES, "_action_get_admin_limits"),

        # Notifications & Config (read-only)
        "get_notifications": (None, "_action_get_notifications"),
        "get_trash_config": (ADMIN_ROLES, "_action_get_trash_config"),
        "list_trash": (ADMIN_ROLES, "_action_list_trash"),
    }

    POST_ACTIONS = {
        # CSV Modifications
        "save_csv": (EDIT_ROLES, "_action_save_csv"),
        "add_row": (EDIT_ROLES, "_action_add_row"),
        "remove_rows": (EDIT_ROLES, "_action_remove_rows"),
        "revert_csv": (EDIT_ROLES, "_action_revert_csv"),
        "save_col_widths": (EDIT_ROLES, "_action_save_col_widths"),

        # CSV/Rule Creation & Deletion
        "create_csv": (EDIT_ROLES, "_action_create_csv"),
        "create_rule": (EDIT_ROLES, "_action_create_rule"),
        "remove_csv": (EDIT_ROLES, "_action_remove_csv"),
        "remove_rule": (EDIT_ROLES, "_action_remove_rule"),

        # Approval Workflow
        "submit_approval": (EDIT_ROLES, "_action_submit_approval"),
        "submit_dual_approval": (EDIT_ROLES, "_action_submit_dual_approval"),
        "process_approval": (ADMIN_ROLES, "_action_process_approval"),
        "process_dual_approval": (ADMIN_ROLES, "_action_process_dual_approval"),
        "check_approval_gate": (EDIT_ROLES, "_action_check_approval_gate"),
        "cancel_request": (None, "_action_cancel_request"),

        # Admin Operations
        "set_daily_limits": (SUPERADMIN_ROLES, "_action_set_daily_limits"),
        "set_admin_limits": (SUPERADMIN_ROLES, "_action_set_admin_limits"),
        "reset_daily_limits": (SUPERADMIN_ROLES, "_action_reset_daily_limits"),
        "reset_daily_usage": (ADMIN_ROLES, "_action_reset_daily_usage"),
        "save_as_default": (SUPERADMIN_ROLES, "_action_save_as_default"),
        "reset_factory_defaults": (SUPERADMIN_ROLES, "_action_reset_factory_defaults"),
        "set_trash_retention": (ADMIN_ROLES, "_action_set_trash_retention"),
        "purge_trash": (ADMIN_ROLES, "_action_purge_trash"),
        "restore_from_trash": (ADMIN_ROLES, "_action_restore_from_trash"),

        # Notifications & Logging
        "mark_notifications_read": (None, "_action_mark_notifications_read"),
        "log_event": (None, "_action_log_event"),

        # Debug (temporary — remove before release)
        "debug_log": (None, "_action_debug_log"),
    }

    def __init__(self, command_line, command_arg):
        super().__init__()

    # ------------------------------------------------------------------
    # Dispatch Infrastructure
    # ------------------------------------------------------------------

    def _dispatch(self, table, action, request, user, roles, query=None, payload=None):
        """
        Shared dispatcher for GET and POST actions.

        Verifies:
        1. User is known (not "unknown")
        2. Action exists in dispatch table
        3. User has required roles (if specified)
        4. Calls handler method via getattr()

        Args:
            table: Dict dispatch table (GET_ACTIONS or POST_ACTIONS)
            action: Action name (from query or payload)
            request: Splunk request object
            user: Username ("unknown" if unauthenticated)
            roles: Set of user's roles
            query: Dict of query params (for GET)
            payload: Dict of request payload (for POST)

        Returns:
            Dict with {status, headers, payload} (from _resp())
        """
        import time
        start_time = time.time()

        # Check authentication
        if user == "unknown":
            self._log_access(action, user, 401, start_time, 0)
            return self._resp(401, {"error": "Session expired or not authenticated"})

        # Check action exists
        if action not in table:
            self._log_access(action, user, 400, start_time, 0)
            valid_actions = sorted(table.keys())
            return self._resp(400, {
                "error": f"Unknown action: {action}",
                "valid_actions": valid_actions
            })

        # Extract required roles and handler name
        required_roles, handler_name = table[action]

        # Check RBAC if required
        if required_roles is not None and not roles.intersection(required_roles):
            self._log_access(action, user, 403, start_time, 0)
            return self._resp(403, {
                "error": "Permission denied: insufficient role"
            })

        # Call handler
        try:
            handler = getattr(self, handler_name)
            if table is self.GET_ACTIONS:
                response = handler(request, query, user, roles)
            else:
                response = handler(request, payload, user, roles)

            # Extract status from response
            status = response.get("status", 200)
            payload_size = len(response.get("payload", ""))
            self._log_access(action, user, status, start_time, payload_size)
            return response

        except FileNotFoundError as e:
            self._log_access(action, user, 404, start_time, 0)
            return self._resp(404, {"error": str(e)})
        except PermissionError as e:
            self._log_access(action, user, 403, start_time, 0)
            return self._resp(403, {"error": str(e)})
        except ValueError as e:
            self._log_access(action, user, 400, start_time, 0)
            return self._resp(400, {"error": str(e)})
        except IOError as e:
            self._log_access(action, user, 500, start_time, 0)
            _logger.error(f"IO error in handler {handler_name}: {e}", exc_info=True)
            return self._resp(500, {"error": "Internal server error"})
        except Exception as e:
            self._log_access(action, user, 500, start_time, 0)
            _logger.error(f"Exception in handler {handler_name}: {e}", exc_info=True)
            return self._resp(500, {"error": "Internal server error"})

    def _log_access(self, action, user, status, start_time, payload_bytes):
        """Log access event for monitoring and audit."""
        import time
        duration_ms = int((time.time() - start_time) * 1000)
        access_log = {
            "type": "access",
            "action": action,
            "user": user,
            "status": status,
            "duration_ms": duration_ms,
            "payload_bytes": payload_bytes,
            "ts": time.time(),
        }
        _logger.info(json.dumps(access_log))

    # ------------------------------------------------------------------
    # Entry point — Splunk calls this for every request
    # ------------------------------------------------------------------
    def handle(self, in_string):
        try:
            request = json.loads(in_string)
            method = request.get("method", "GET")
            user = get_user(request)

            # ── Rate limiting ────────────────────────────────────────
            action_type = "read" if method == "GET" else "write"
            if not check_rate_limit(user, action_type):
                return self._resp(429, {
                    "error": "Rate limit exceeded. Please wait before retrying."
                })

            if method == "GET":
                return self._handle_get(request)
            elif method == "POST":
                # ── Payload size limit ───────────────────────────────
                payload_str = request.get("payload", "{}")
                if len(payload_str) > MAX_PAYLOAD_BYTES:
                    return self._resp(413, {
                        "error": "Request payload too large (max 10 MB)."
                    })
                return self._handle_post(request)
            else:
                return self._resp(405, {"error": "Method not allowed"})
        except Exception as exc:
            _logger.error("Unhandled exception: %s\n%s", exc, traceback.format_exc())
            return self._resp(500, {"error": "An internal error occurred."})

    # ==================================================================
    # GET
    # ==================================================================
    def _handle_get(self, request):
        user = get_user(request)
        roles = get_roles(request)
        query = self._parse_query(request)
        action = query.get("action", "")

        if not action:
            return self._resp(400, {
                "error": "Missing or unknown action",
                "valid_actions": sorted(self.GET_ACTIONS.keys()),
            })

        return self._dispatch(self.GET_ACTIONS, action, request, user, roles, query=query)

    def _get_apps(self):
        """List installed Splunk apps that have a lookups/ directory."""
        apps = []
        try:
            for name in sorted(os.listdir(APPS_DIR)):
                app_dir = os.path.join(APPS_DIR, name)
                if not os.path.isdir(app_dir):
                    continue
                lookups_dir = os.path.join(app_dir, "lookups")
                has_lookups = os.path.isdir(lookups_dir)
                apps.append({
                    "name": name,
                    "has_lookups": has_lookups,
                })
        except OSError as exc:
            _logger.error("Failed to list apps: %s", exc)
        return self._resp(200, {
            "apps": apps,
            "default_app": APP_NAME,
        })

    def _get_rules(self):
        mapping = self._read_mapping()
        rule_set = {row["rule_name"] for row in mapping}
        # Merge in registered rules (those without CSV mappings yet)
        rule_set.update(read_rules_registry())
        rules = sorted(rule_set)
        return self._resp(200, {"rules": rules})

    def _get_csvs(self, rule):
        mapping = self._read_mapping()
        entries = [
            {"csv_file": r["csv_file"], "app_context": r.get("app_context", "")}
            for r in mapping
            if r["rule_name"] == rule
        ]
        if not entries:
            return self._resp(200, {
                "csv_files": [],
                "message": "No whitelisting exists for this detection rule",
            })
        return self._resp(200, {"csv_files": entries})

    def _get_csv_content(self, request, csv_file, app_context, tz_offset="0"):
        path = resolve_csv_path(csv_file, app_context)
        if path is None:
            # Try own lookups as fallback (with symlink check)
            if is_safe_filename(csv_file):
                fallback = os.path.join(OWN_LOOKUPS, csv_file)
                if os.path.isfile(fallback) and safe_realpath(fallback, APPS_DIR):
                    path = safe_realpath(fallback, APPS_DIR)
        if path is None:
            return self._resp(404, {"error": "CSV file not found"})

        headers, rows = read_csv(path)

        # ── Lazy version initialization for pre-existing CSVs ─────────
        # If a CSV has never been versioned (e.g. demo data, shipped with
        # the app, or migrated), create an "original" snapshot on first
        # access so its initial state is always recoverable.
        try:
            manifest, _ = read_version_manifest(path)
            if not manifest:
                _, _ = snapshot_version(path, "system", action_label="original")
        except OSError:
            pass

        # ── Auto-remove expired rows ──────────────────────────────────
        auto_removed_count = 0
        try:
            tz_offset_min = int(tz_offset)
        except (ValueError, TypeError):
            tz_offset_min = 0
        if get_expire_column(headers):
            kept, expired_count = remove_expired_rows(headers, rows, tz_offset_min)
            if expired_count:
                # Identify the expired rows (difference between original and kept)
                kept_ids = set(id(r) for r in kept)
                expired_rows = [r for r in rows if id(r) not in kept_ids]
                try:
                    write_csv(path, headers, kept)
                except OSError as exc:
                    _logger.warning("Cannot write cleaned CSV %s: %s", csv_file, exc)
                else:
                    auto_removed_count = expired_count
                    rows = kept

                    detection_rule = self._lookup_rule_for_csv(csv_file)
                    ts = int(datetime.now(timezone.utc).timestamp())
                    expired_clean = [
                        {k: v for k, v in r.items() if not k.startswith("_")}
                        for r in expired_rows
                    ]
                    value_lines = []
                    for i, entry in enumerate(expired_clean, 1):
                        for col, val in sorted(entry.items()):
                            value_lines.append("{}_row_{}: {}".format(col, i, val))

                    evt = {
                        "timestamp": ts,
                        "analyst": "system",
                        "detection_rule": detection_rule,
                        "csv_file": csv_file,
                        "app_context": app_context,
                        "comment": "Automatic expiration cleanup on load",
                        "action": "auto_removed",
                        "removed_row_count": auto_removed_count,
                        "value": value_lines,
                        "row_remove_reason": "Expired",
                    }
                    _logger.info("Auto-removed %d expired rows from %s, indexing audit event", auto_removed_count, csv_file)
                    self._index_audit(request, evt)

        # Fetch pending approvals for this CSV
        pending_approvals = _get_pending_for_csv(csv_file)
        pending_info = [{
            "request_id": p["request_id"],
            "action_type": p["action_type"],
            "description": p["description"],
            "analyst": p["analyst"],
            "timestamp": p["timestamp"],
            "pending_highlight": p.get("pending_highlight", {}),
            "payload": p.get("payload", {}),
        } for p in pending_approvals]

        return self._resp(200, {
            "csv_file": csv_file,
            "headers": headers,
            "rows": rows,
            "row_count": len(rows),
            "auto_removed_count": auto_removed_count,
            "expire_column": get_expire_column(headers) or "",
            "file_mtime": int(os.path.getmtime(path)),
            "pending_approvals": pending_info,
        })

    def _get_mapping(self, request):
        mapping = self._read_mapping()
        registered = read_rules_registry()
        roles = get_roles(request)
        user_is_admin = is_admin(roles)
        has_edit = is_editor(roles)
        reason_gates = {}
        if user_is_admin:
            can_create_rules = True
            can_create_csv = True
            can_delete_rules = True
            can_delete_csv = True
            # Admins are never gated
        else:
            cfg = _read_limit_config()
            can_create_rules = bool(
                cfg.get("allow_analyst_create_rules", False) and has_edit)
            can_create_csv = bool(
                cfg.get("allow_analyst_create_csv", False) and has_edit)
            can_delete_rules = bool(
                cfg.get("allow_analyst_delete_rules", False) and has_edit)
            can_delete_csv = bool(
                cfg.get("allow_analyst_delete_csv", False) and has_edit)
            # Reason gates only apply to analysts
            reason_gates = {
                "require_reason_rule_creation": bool(
                    can_create_rules and
                    cfg.get("require_reason_rule_creation", False)),
                "require_reason_csv_creation": bool(
                    can_create_csv and
                    cfg.get("require_reason_csv_creation", False)),
                "require_reason_rule_deletion": bool(
                    can_delete_rules and
                    cfg.get("require_reason_rule_deletion", False)),
                "require_reason_csv_deletion": bool(
                    can_delete_csv and
                    cfg.get("require_reason_csv_deletion", False)),
            }
        return self._resp(200, {
            "mapping": mapping,
            "registered_rules": registered,
            "permissions": {
                "can_create_rules": can_create_rules,
                "can_create_csv": can_create_csv,
                "can_delete_rules": can_delete_rules,
                "can_delete_csv": can_delete_csv,
                "reason_gates": reason_gates,
            },
        })

    def _get_versions(self, csv_file, app_context):
        """Return the list of available version snapshots for a CSV file."""
        if not is_safe_filename(csv_file):
            return self._resp(400, {"error": "Invalid CSV file name"})

        path = resolve_csv_path(csv_file, app_context)
        if path is None:
            fallback = os.path.join(OWN_LOOKUPS, csv_file)
            if os.path.isfile(fallback) and safe_realpath(fallback, APPS_DIR):
                path = safe_realpath(fallback, APPS_DIR)
        if path is None:
            return self._resp(200, {"csv_file": csv_file, "versions": []})

        manifest, _ = read_version_manifest(path)

        # Handle legacy manifests stored as a bare list
        if isinstance(manifest, list):
            manifest = {"versions": manifest}

        # Backfill col_count for entries created before this field existed
        versions_dir = get_versions_dir(path)
        updated = False
        for entry in manifest.get("versions", []):
            if "col_count" not in entry:
                snap = os.path.join(versions_dir, entry.get("filename", ""))
                try:
                    hdrs, _ = read_csv(snap)
                    entry["col_count"] = len([h for h in hdrs if not h.startswith("_")])
                    updated = True
                except Exception:
                    entry["col_count"] = -1
        if updated:
            _, _ = write_version_manifest(path, manifest)

        return self._resp(200, {
            "csv_file": csv_file,
            "versions": manifest.get("versions", []),
        })


    def _check_csv_status(self, csv_file, app_context):
        """Lightweight check — returns file mtime and pending approval count."""
        if not is_safe_filename(csv_file):
            return self._resp(400, {"error": "Invalid CSV file name"})

        path = resolve_csv_path(csv_file, app_context)
        if path is None:
            return self._resp(404, {"error": "CSV file not found"})

        pending = _get_pending_for_csv(csv_file)
        return self._resp(200, {
            "csv_file": csv_file,
            "file_mtime": int(os.path.getmtime(path)),
            "pending_count": len(pending),
        })

    def _get_col_widths(self, csv_file, app_context):
        """Return stored column widths for a CSV file."""
        if not is_safe_filename(csv_file):
            return self._resp(400, {"error": "Invalid CSV file name"})
        path = resolve_csv_path(csv_file, app_context)
        if path is None:
            return self._resp(200, {"col_widths": {}})
        return self._resp(200, {"col_widths": get_column_widths(path)})

    def _save_col_widths(self, payload):
        """Save column widths for a CSV file."""
        csv_file = payload.get("csv_file", "")
        app_context = payload.get("app_context", "")
        col_widths = payload.get("col_widths", {})

        if not is_safe_filename(csv_file):
            return self._resp(400, {"error": "Invalid CSV file name"})
        if not isinstance(col_widths, dict):
            return self._resp(400, {"error": "col_widths must be a dict"})
        if len(col_widths) > MAX_COLUMNS:
            return self._resp(400, {"error": "Too many column widths"})

        # Validate all values are numbers
        clean = {}
        for k, v in col_widths.items():
            if isinstance(v, (int, float)) and 50 <= v <= 300:
                clean[str(k)] = int(v)

        path = resolve_csv_path(csv_file, app_context)
        if path is None:
            return self._resp(404, {"error": "CSV file not found"})

        set_column_widths(path, clean)
        return self._resp(200, {"success": True})

    # ==================================================================
    # GET Action Wrappers (Wave 1 — Dispatch Pattern)
    # ==================================================================
    # These wrapper methods implement the _action_* interface for GET handlers.
    # They accept (self, request, query, user, roles) and delegate to existing
    # handler methods (_get_rules, _get_csvs, etc.).

    def _action_get_rules(self, request, query, user, roles):
        """GET action wrapper for get_rules."""
        return self._get_rules()

    def _action_get_csvs(self, request, query, user, roles):
        """GET action wrapper for get_csvs."""
        rule = query.get("rule", "")
        return self._get_csvs(rule)

    def _action_get_csv_content(self, request, query, user, roles):
        """GET action wrapper for get_csv_content."""
        csv_file = query.get("csv_file", "")
        app_context = query.get("app", "")
        tz_offset = query.get("tz_offset", "0")
        return self._get_csv_content(request, csv_file, app_context, tz_offset)

    def _action_get_mapping(self, request, query, user, roles):
        """GET action wrapper for get_mapping."""
        return self._get_mapping(request)

    def _action_get_versions(self, request, query, user, roles):
        """GET action wrapper for get_versions."""
        csv_file = query.get("csv_file", "")
        app_context = query.get("app", "")
        return self._get_versions(csv_file, app_context)

    def _action_check_csv_status(self, request, query, user, roles):
        """GET action wrapper for check_csv_status."""
        csv_file = query.get("csv_file", "")
        app_context = query.get("app", "")
        return self._check_csv_status(csv_file, app_context)

    def _action_get_col_widths(self, request, query, user, roles):
        """GET action wrapper for get_col_widths."""
        csv_file = query.get("csv_file", "")
        app_context = query.get("app", "")
        return self._get_col_widths(csv_file, app_context)

    def _action_get_apps(self, request, query, user, roles):
        """GET action wrapper for get_apps."""
        return self._get_apps()

    def _action_get_user_info(self, request, query, user, roles):
        """GET action: return current user's role tier and username (no 403 probing)."""
        is_admin = bool(roles & ADMIN_ROLES)
        is_superadmin = bool(roles & SUPERADMIN_ROLES)
        return self._resp(200, {
            "username": user,
            "is_admin": is_admin,
            "is_superadmin": is_superadmin,
            "roles": sorted(roles),
        })

    def _action_report_presence(self, request, query, user, roles):
        """GET action wrapper for report_presence."""
        csv_file = query.get("csv_file", "")
        if not csv_file:
            return self._resp(400, {"error": "csv_file required"})

        last_activity_str = query.get("last_activity", "")
        try:
            last_activity = float(last_activity_str) if last_activity_str else None
        except (ValueError, TypeError):
            last_activity = None

        data, error = report_presence(csv_file, user, last_activity)
        if error:
            return self._resp(400, {"error": error})
        return self._resp(200, {"csv_file": csv_file, **data})

    def _action_get_presence(self, request, query, user, roles):
        """GET action wrapper for get_presence."""
        csv_file = query.get("csv_file", "")
        if not csv_file:
            return self._resp(400, {"error": "csv_file required"})

        data, error = get_presence(csv_file)
        if error:
            return self._resp(400, {"error": error})
        return self._resp(200, {"csv_file": csv_file, **data})

    def _action_get_pending_approvals(self, request, query, user, roles):
        """GET action wrapper for get_pending_approvals."""
        csv_file = query.get("csv_file", "")
        pending = get_pending_for_csv(csv_file)
        has_edit = is_editor(roles)
        pending_info = [{
            "request_id": p["request_id"],
            "action_type": p["action_type"],
            "description": p["description"],
            "analyst": p["analyst"],
            "timestamp": p["timestamp"],
            "pending_highlight": p.get("pending_highlight", {}) if has_edit else {},
            "payload": p.get("payload", {}) if has_edit else {},
        } for p in pending]
        return self._resp(200, {"pending_approvals": pending_info})

    def _action_get_request_csv(self, request, query, user, roles):
        """GET action wrapper for get_request_csv (admin-only)."""
        request_id = query.get("request_id", "")
        if not request_id:
            return self._resp(400, {"error": "request_id is required"})
        queue = _read_approval_queue()
        target = None
        for item in queue:
            if item.get("request_id") == request_id:
                target = item
                break
        if not target:
            return self._resp(404, {"error": "Request not found"})
        stored = target.get("payload", {})
        orig = stored.get("original_payload", stored)
        headers = orig.get("headers", [])
        rows = orig.get("initial_rows", orig.get("rows", []))
        if not headers and not rows:
            return self._resp(404, {"error": "No CSV data in this request"})
        return self._resp(200, {
            "headers": headers,
            "rows": rows,
            "csv_file": target.get("csv_file", ""),
            "detection_rule": target.get("detection_rule", ""),
        })

    def _action_get_approval_queue(self, request, query, user, roles):
        """GET action wrapper for get_approval_queue (admin-only)."""
        queue = _read_approval_queue()
        return self._resp(200, {"approval_queue": queue})

    def _action_check_daily_limit_status(self, request, query, user, roles):
        """GET action wrapper for check_daily_limit_status."""
        return self._check_daily_limit_status(user)

    def _action_get_daily_limits(self, request, query, user, roles):
        """GET action wrapper for get_daily_limits (admin-only)."""
        return self._get_daily_limits_action()

    def _action_get_analyst_usage(self, request, query, user, roles):
        """GET action wrapper for get_analyst_usage (admin-only)."""
        payload = {}  # Not used for GET, but kept for signature consistency
        return self._get_analyst_usage_action(payload)

    def _action_get_admin_limits(self, request, query, user, roles):
        """GET action wrapper for get_admin_limits (admin-only)."""
        admin_limits = _read_admin_limits()
        return self._resp(200, {"admin_limits": admin_limits})

    def _action_get_notifications(self, request, query, user, roles):
        """GET action wrapper for get_notifications."""
        data = _read_notifications()
        user_notifs = data.get(user, [])
        unread_count = sum(1 for n in user_notifs if not n.get("read", True))
        return self._resp(200, {
            "notifications": user_notifs,
            "unread_count": unread_count,
        })

    def _action_get_trash_config(self, request, query, user, roles):
        """GET action wrapper for get_trash_config (admin-only)."""
        path = os.path.join(OWN_LOOKUPS, TRASH_CONFIG_FILE)
        config = {}
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    config = json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
        return self._resp(200, {"trash_config": config})

    def _action_list_trash(self, request, query, user, roles):
        """GET action wrapper for list_trash (admin-only)."""
        items, err = list_trash()
        if err:
            return self._resp(500, {"error": "Failed to list trash: " + err})
        return self._resp(200, {"trash_items": items})

    # ==================================================================
    # POST Action Wrappers (Stubs for Wave 2-3)
    # ==================================================================
    # These stubs will be implemented in subsequent waves.
    # For now, they delegate to existing POST handler methods.

    def _action_save_csv(self, request, payload, user, roles):
        """POST action wrapper for save_csv."""
        return self._save_csv(request, payload, user)

    def _action_add_row(self, request, payload, user, roles):
        """POST action wrapper for add_row (delegates to save_csv pipeline)."""
        return self._save_csv(request, payload, user)

    def _action_remove_rows(self, request, payload, user, roles):
        """POST action wrapper for remove_rows (delegates to save_csv pipeline)."""
        return self._save_csv(request, payload, user)

    def _action_revert_csv(self, request, payload, user, roles):
        """POST action wrapper for revert_csv."""
        return self._revert_csv(request, payload, user, roles=roles)

    def _action_save_col_widths(self, request, payload, user, roles):
        """POST action wrapper for save_col_widths."""
        return self._save_col_widths(payload)

    def _action_create_csv(self, request, payload, user, roles):
        """POST action wrapper for create_csv."""
        # Admins execute directly (never gated)
        if is_admin(roles):
            return self._create_csv(request, payload, user)
        # Analyst permission check
        cfg = _read_limit_config()
        if not cfg.get("allow_analyst_create_csv", False):
            return self._resp(403, {
                "error": "Creating CSV files is not permitted. "
                         "An admin must enable it in the Control Panel."})
        # Approval gate: route to queue if configured
        if cfg.get("require_reason_csv_creation", False):
            return self._submit_create_delete_approval(
                request, payload, user, "create_csv",
                "Create CSV '{}'".format(
                    payload.get("csv_file", "unknown")))
        return self._create_csv(request, payload, user)

    def _action_create_rule(self, request, payload, user, roles):
        """POST: Register a new detection rule name."""
        detection_rule = (payload.get("detection_rule") or "").strip()
        # Admins execute directly (never gated)
        if is_admin(roles):
            return self._execute_create_rule(request, detection_rule, user)
        # Analyst permission check
        cfg = _read_limit_config()
        if not cfg.get("allow_analyst_create_rules", False):
            return self._resp(403, {
                "error": "Creating detection rules is not permitted. "
                         "An admin must enable it in the Control Panel."})
        # Approval gate: route to queue if configured
        if cfg.get("require_reason_rule_creation", False):
            return self._submit_create_delete_approval(
                request, payload, user, "create_rule",
                "Create rule '{}'".format(detection_rule))
        return self._execute_create_rule(request, detection_rule, user)

    def _execute_create_rule(self, request, detection_rule, user):
        """Execute create_rule after permission/approval checks pass."""
        result = create_rule_pipeline(detection_rule)
        try:
            evt = build_audit_event(
                action="dr_created", analyst=user,
                detection_rule=detection_rule, csv_file="",
                app_context=APP_NAME, status="created",
            )
            self._index_audit(request, evt)
        except Exception as exc:
            _logger.error("Audit failed for create_rule: %s", exc)
        return self._resp(200, result)

    def _action_remove_csv(self, request, payload, user, roles):
        """POST action wrapper for remove_csv — delegates to delete_csv_pipeline."""
        csv_file = (payload.get("csv_file") or "").strip()
        rule_name = (payload.get("rule_name") or "").strip()
        removal_type = payload.get("removal_type", "")
        comment = (payload.get("comment") or "").strip()[:500]

        if not csv_file:
            return self._resp(400, {"error": "csv_file is required"})
        if not is_safe_filename(csv_file):
            return self._resp(400, {"error": "Invalid CSV filename"})
        if removal_type not in ("unlink", "permanent"):
            return self._resp(400, {
                "error": "removal_type must be 'unlink' or 'permanent'"})
        if not comment:
            return self._resp(400, {"error": "A reason is required"})

        # Analyst approval gate (skip for admins)
        if not is_admin(roles):
            cfg = _read_limit_config()
            if not cfg.get("allow_analyst_delete_csv", False):
                return self._resp(403, {
                    "error": "Removing CSV files is not permitted. "
                             "An admin must enable it in the Control Panel."})
            if cfg.get("require_reason_csv_deletion", False):
                payload["approval_reason"] = comment
                return self._submit_create_delete_approval(
                    request, payload, user, "remove_csv",
                    "Remove CSV '{}'".format(csv_file))

        # Admin daily limit for CSV deletion (soft delete)
        if removal_type == "permanent":
            if is_admin(roles) and not is_superadmin(roles):
                allowed, current, maximum = _check_admin_daily_limit(
                    user, "csv_deletion")
                if not allowed:
                    return self._resp(429, {
                        "error": _daily_limit_error_msg(
                            "csv_deletion", 1, current, maximum,
                            contact="your super-admin"),
                        "limit_type": "admin_csv_deletion",
                        "current": current,
                        "maximum": maximum,
                        "disabled": maximum == 0,
                    })

        # Call pipeline
        result = delete_csv_pipeline(
            csv_file, removal_type, comment, user,
            self.sessionKey, rule_name=rule_name)

        if not result.get("success"):
            return self._resp(404, {"error": result.get("error", "Delete failed")})

        data = result.get("data", {})
        resolved_rule = data.get("rule_name", rule_name)

        # Auto-cancel pending approval requests
        with _approval_queue_lock():
            queue = _read_approval_queue()
            if data.get("rule_also_removed"):
                _cancel_conflicting_requests(
                    queue, resolved_rule, "", "remove_rule", "",
                    lambda evt: self._index_audit(request, evt))
            else:
                _cancel_conflicting_requests(
                    queue, resolved_rule, csv_file, "remove_csv", "",
                    lambda evt: self._index_audit(request, evt))

        # Increment admin daily limit counter
        if data.get("trashed"):
            if is_admin(roles) and not is_superadmin(roles):
                _increment_admin_daily_limit(user, "csv_deletion")

        return self._resp(200, {
            "success": True,
            "message": result.get("message", ""),
            "rule_also_removed": data.get("rule_also_removed", False),
            "trashed": data.get("trashed", False),
            "trash_id": data.get("trash_id", ""),
        })

    def _action_remove_rule(self, request, payload, user, roles):
        """POST action wrapper for remove_rule — delegates to delete_rule_pipeline."""
        rule_name = (payload.get("rule_name") or "").strip()
        removal_type = payload.get("removal_type", "")
        comment = (payload.get("comment") or "").strip()[:500]

        if not rule_name:
            return self._resp(400, {"error": "rule_name is required"})
        if removal_type not in ("unlink", "permanent"):
            return self._resp(400, {
                "error": "removal_type must be 'unlink' or 'permanent'"})
        if not comment:
            return self._resp(400, {"error": "A reason is required"})

        # Analyst approval gate (skip for admins)
        if not is_admin(roles):
            cfg = _read_limit_config()
            if not cfg.get("allow_analyst_delete_rules", False):
                return self._resp(403, {
                    "error": "Removing detection rules is not permitted. "
                             "An admin must enable it in the Control Panel."})
            if cfg.get("require_reason_rule_deletion", False):
                payload["approval_reason"] = comment
                return self._submit_create_delete_approval(
                    request, payload, user, "remove_rule",
                    "Remove rule '{}'".format(rule_name))

        # Admin daily limit for rule deletion
        if removal_type == "permanent":
            if is_admin(roles) and not is_superadmin(roles):
                allowed, current, maximum = _check_admin_daily_limit(
                    user, "rule_deletion")
                if not allowed:
                    return self._resp(429, {
                        "error": _daily_limit_error_msg(
                            "rule_deletion", 1, current, maximum,
                            contact="your super-admin"),
                        "limit_type": "admin_rule_deletion",
                        "current": current,
                        "maximum": maximum,
                        "disabled": maximum == 0,
                    })

        # Dual-admin check for rules with 3+ CSVs
        _from_dual = payload.get("_from_dual_approval", False)
        if removal_type == "permanent" and not _from_dual:
            _is_superadmin = bool(roles.intersection(SUPERADMIN_ROLES))
            mapping = self._read_mapping()
            affected_csvs = [e["csv_file"] for e in mapping
                             if e.get("rule_name") == rule_name]
            csv_count = len(affected_csvs)
            if csv_count >= 3 and not _is_superadmin:
                return self._resp(403, {
                    "error": "Deleting rule '{}' with {} CSV files "
                             "requires a second admin's approval. "
                             "Please submit via the dual-approval "
                             "workflow.".format(rule_name, csv_count),
                    "requires_dual_approval": True,
                    "csv_count": csv_count,
                })

        # Call pipeline
        result = delete_rule_pipeline(
            rule_name, removal_type, comment, user, self.sessionKey)

        if not result.get("success"):
            return self._resp(404, {"error": result.get("error", "Delete failed")})

        data = result.get("data", {})

        # Auto-cancel pending approval requests
        with _approval_queue_lock():
            queue = _read_approval_queue()
            _cancel_conflicting_requests(
                queue, rule_name, "", "remove_rule", "",
                lambda evt: self._index_audit(request, evt))

        # Increment admin daily limit counter
        if data.get("trashed"):
            if is_admin(roles) and not is_superadmin(roles):
                _increment_admin_daily_limit(user, "rule_deletion")

        return self._resp(200, {
            "success": True,
            "message": result.get("message", ""),
            "affected_csvs": data.get("affected_csvs", []),
            "trashed": data.get("trashed", False),
            "trash_id": data.get("trash_id", ""),
        })

    def _action_submit_approval(self, request, payload, user, roles):
        """POST action wrapper for submit_approval."""
        return self._submit_approval(request, payload, user)

    def _action_submit_dual_approval(self, request, payload, user, roles):
        """POST action wrapper for submit_dual_approval."""
        return self._submit_dual_approval(request, payload, user)

    def _action_process_approval(self, request, payload, user, roles):
        """POST action wrapper for process_approval."""
        return self._process_approval(request, payload, user)

    def _action_process_dual_approval(self, request, payload, user, roles):
        """POST action wrapper for process_dual_approval."""
        return self._process_dual_approval(request, payload, user)

    def _action_check_approval_gate(self, request, payload, user, roles):
        """POST action wrapper for check_approval_gate."""
        return self._check_approval_gate(request, payload, user)

    def _action_cancel_request(self, request, payload, user, roles):
        """POST action wrapper for cancel_request."""
        return self._cancel_request(request, payload, user)

    def _action_set_daily_limits(self, request, payload, user, roles):
        """POST action wrapper for set_daily_limits (superadmin-only)."""
        return self._set_daily_limits_action(request, payload, user)

    def _action_set_admin_limits(self, request, payload, user, roles):
        """POST action wrapper for set_admin_limits (superadmin-only)."""
        admin = payload.get("admin", "")
        limits = payload.get("limits", {})
        admin_limits = _read_admin_limits()
        admin_limits[admin] = limits
        _write_admin_limits(admin_limits)
        return self._resp(200, {"success": True})

    def _action_reset_daily_limits(self, request, payload, user, roles):
        """POST action wrapper for reset_daily_limits (superadmin-only)."""
        return self._reset_daily_limits_action(request, user)

    def _action_reset_daily_usage(self, request, payload, user, roles):
        """POST action wrapper for reset_daily_usage (superadmin-only)."""
        return self._reset_daily_usage_action(payload, user)

    def _action_save_as_default(self, request, payload, user, roles):
        """POST action wrapper for save_as_default (superadmin-only)."""
        return self._save_as_default_action(request, user)

    def _action_reset_factory_defaults(self, request, payload, user, roles):
        """POST action wrapper for reset_factory_defaults (superadmin-only)."""
        return self._reset_factory_defaults_action(request, user)

    def _action_set_trash_retention(self, request, payload, user, roles):
        """POST action wrapper for set_trash_retention (admin-only)."""
        path = os.path.join(OWN_LOOKUPS, TRASH_CONFIG_FILE)
        config = {}
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    config = json.load(f)
            except (json.JSONDecodeError, OSError):
                pass

        retention_days = payload.get("retention_days", DEFAULT_TRASH_RETENTION_DAYS)
        if retention_days < MIN_TRASH_RETENTION_DAYS:
            return self._resp(400, {
                "error": f"Retention must be >= {MIN_TRASH_RETENTION_DAYS} days"
            })

        config["retention_days"] = retention_days
        os.makedirs(OWN_LOOKUPS, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)

        return self._resp(200, {"success": True})

    def _action_purge_trash(self, request, payload, user, roles):
        """POST action wrapper for purge_trash (admin-only)."""
        purged = purge_trash_item(payload.get("item_id", ""))
        return self._resp(200, {"success": purged})

    def _action_restore_from_trash(self, request, payload, user, roles):
        """POST action wrapper for restore_from_trash — delegates to pipeline."""
        item_id = payload.get("item_id", "")
        comment = payload.get("comment", "")
        result = restore_from_trash_pipeline(
            item_id, user, self.sessionKey, comment=comment)
        if not result.get("success"):
            return self._resp(400, {"error": result.get("error", "Restore failed")})
        return self._resp(200, {
            "success": True,
            "data": result.get("data", {}),
        })

    def _action_mark_notifications_read(self, request, payload, user, roles):
        """POST action wrapper for mark_notifications_read."""
        data = _read_notifications()
        for notif in data.get(user, []):
            notif["read"] = True
        _write_notifications(data)
        return self._resp(200, {"success": True})

    def _action_log_event(self, request, payload, user, roles):
        """POST action wrapper for log_event."""
        return self._log_event(request, payload)

    def _action_debug_log(self, request, payload, user, roles):
        """Write frontend debug entry to /tmp/wl_debug.log."""
        import datetime
        entry = payload.get("entry", {})
        entry["user"] = user
        line = "{} {}\n".format(
            datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            json.dumps(entry, default=str),
        )
        try:
            with open("/tmp/wl_debug.log", "a", encoding="utf-8") as f:
                f.write(line)
        except Exception:
            pass
        return self._resp(200, {"ok": True})

    # ==================================================================
    # POST
    # ==================================================================
    def _handle_post(self, request):
        user = get_user(request)
        roles = get_roles(request)

        # Reject unidentified users — "unknown" means the session is
        # missing or expired.  All POST actions require a real identity
        # for audit trail, rate limiting, and self-approval checks.
        if user == "unknown":
            return self._resp(401, {
                "error": "Session expired or user identity could not be "
                         "determined. Please log in again.",
            })

        payload_str = request.get("payload", "") or ""
        # Direct REST API calls (port 8089) send form-encoded payload=...
        if payload_str.startswith("payload="):
            from urllib.parse import unquote
            payload_str = unquote(payload_str[len("payload="):])
        payload = json.loads(payload_str or "{}")
        action = payload.get("action", "")

        if not action:
            return self._resp(400, {
                "error": "Missing or unknown action",
                "valid_actions": sorted(self.POST_ACTIONS.keys()),
            })

        return self._dispatch(self.POST_ACTIONS, action, request, user, roles, payload=payload)

    # ==================================================================
    # Inline methods below are being extracted to domain modules.
    # See create_rule_pipeline in wl_rules.py for the pattern.
    # ==================================================================

    # ==================================================================
    # Create CSV
    # ==================================================================
    def _create_csv(self, request, payload, user):
        """Create a new CSV file for a rule and add the mapping."""
        detection_rule = (payload.get("detection_rule") or "").strip()
        csv_filename = (payload.get("csv_file") or "").strip()
        headers_raw = payload.get("headers", [])
        app_context = (payload.get("app_context") or "").strip() or APP_NAME

        # ── Validate detection rule ───────────────────────────────────
        if not detection_rule:
            return self._resp(400, {"error": "Detection rule name is required"})
        if len(detection_rule) > 100:
            return self._resp(400, {
                "error": "Detection rule name too long: {} chars (max 100)".format(
                    len(detection_rule))
            })
        if not all(c.isalnum() or c in ("_", "-", ".", " ") for c in detection_rule):
            return self._resp(400, {
                "error": "Detection rule name can only contain letters, "
                         "numbers, underscores, hyphens, dots, and spaces"
            })
        if not any(c.isalnum() for c in detection_rule):
            return self._resp(400, {
                "error": "Detection rule name must contain at least one "
                         "letter or number"
            })

        # ── Validate headers ──────────────────────────────────────────
        if not isinstance(headers_raw, list) or not headers_raw:
            return self._resp(400, {
                "error": "At least one column header is required"
            })
        headers = []
        for h in headers_raw:
            h = str(h).strip()
            if h:
                headers.append(h)
        if not headers:
            return self._resp(400, {
                "error": "At least one non-empty column header is required"
            })
        # Block user-created "_" prefix columns (reserved for internal metadata)
        for h in headers:
            if h.startswith("_"):
                return self._resp(400, {
                    "error": "Column names starting with '_' are reserved "
                             "for internal use. Rename '{}' to remove the "
                             "underscore prefix.".format(h)
                })
        visible_headers = [h for h in headers if not h.startswith("_")]
        if len(visible_headers) > MAX_COLUMNS:
            return self._resp(400, {
                "error": "Too many columns: {} (max {})".format(
                    len(visible_headers), MAX_COLUMNS)
            })
        # Check for duplicate headers, length, and dangerous chars
        seen = set()
        for h in headers:
            if not h or not h.strip():
                return self._resp(400, {
                    "error": "Column names cannot be empty or whitespace-only."
                })
            if len(h) > 64:
                return self._resp(400, {
                    "error": "Column header '{}' too long: {} chars (max 64)".format(
                        h[:20], len(h))
                })
            if " " in h or "\t" in h:
                return self._resp(400, {
                    "error": "Column name '{}' cannot contain spaces. "
                             "Use underscores instead (e.g. 'src_ip').".format(
                                 h[:30])
                })
            if not _SAFE_COLNAME_RE.match(h):
                return self._resp(400, {
                    "error": "Column name '{}' contains invalid characters. "
                             "Only letters, numbers, and _-.()/:#@&+ are "
                             "allowed.".format(h[:30])
                })
            if h.lower() in seen:
                return self._resp(400, {
                    "error": "Duplicate column header: '{}'".format(h)
                })
            seen.add(h.lower())

        # ── Extract optional initial rows (CSV import) ───────────────
        initial_rows = payload.get("initial_rows", [])
        if not isinstance(initial_rows, list):
            return self._resp(400, {
                "error": "initial_rows must be a list"
            })
        for i, row in enumerate(initial_rows):
            if not isinstance(row, dict):
                return self._resp(400, {
                    "error": "initial_rows[{}] must be an object".format(i)
                })

        if len(initial_rows) > MAX_ROWS:
            return self._resp(400, {
                "error": "Too many rows: {} (max {})".format(
                    len(initial_rows), MAX_ROWS)
            })

        # Validate and sanitize cell values in initial_rows
        _non_ascii_re = re.compile(r'[^\x00-\x7F]')
        _corrupt_re = re.compile(r'^[?\s]+$')
        if initial_rows:
            for i, row in enumerate(initial_rows):
                for h in headers:
                    v = row.get(h, "")
                    if not isinstance(v, str):
                        v = str(v)
                    if len(v) > MAX_CELL_CHARS:
                        return self._resp(400, {
                            "error": "Cell in row {}, column '{}' exceeds {} characters".format(
                                i + 1, h[:30], MAX_CELL_CHARS)
                        })
                    if _non_ascii_re.search(v):
                        return self._resp(200, {
                            "error": "Non-ASCII characters in row {}, "
                                     "column '{}'. Only ASCII characters "
                                     "are allowed.".format(
                                         i + 1, h[:30])
                        })
                    if v.strip() and _corrupt_re.match(v.strip()):
                        return self._resp(200, {
                            "error": "Row {}, column '{}': value '{}' "
                                     "appears to be encoding corruption "
                                     "(only ? characters). Re-save the CSV "
                                     "from Excel as CSV UTF-8.".format(
                                         i + 1, h[:30], v.strip()[:20])
                        })
                    # Sanitize: strip nulls, control chars, normalize newlines
                    cleaned = v.replace("\x00", "")
                    cleaned = cleaned.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
                    cleaned = cleaned.replace("\t", " ")
                    cleaned = _CONTROL_CHAR_RE.sub("", cleaned)
                    row[h] = cleaned

            # Validate expiration dates if Expires column present
            expire_col = get_expire_column(headers)
            if expire_col:
                _VALID_EXPIRE_FMTS = ("%Y-%m-%d %H:%M", "%Y-%m-%d")
                invalid_expire_rows = []
                for i, row in enumerate(initial_rows):
                    exp_val = (row.get(expire_col) or "").strip()
                    if not exp_val:
                        continue
                    parse_val = exp_val[:-4] if exp_val.endswith(" UTC") else exp_val
                    parsed = False
                    for fmt in _VALID_EXPIRE_FMTS:
                        try:
                            datetime.strptime(parse_val, fmt)
                            parsed = True
                            break
                        except ValueError:
                            continue
                    if not parsed:
                        invalid_expire_rows.append((i + 1, exp_val))
                    if len(invalid_expire_rows) >= 5:
                        break
                if invalid_expire_rows:
                    examples = "; ".join(
                        "row {}: '{}'".format(r, v[:60]) for r, v in invalid_expire_rows
                    )
                    more = "" if len(invalid_expire_rows) < 5 else " (and possibly more)"
                    return self._resp(400, {
                        "error": "Invalid date format in '{}' column: {}{}. "
                                 "Expected: YYYY-MM-DD HH:MM or YYYY-MM-DD.".format(
                                     expire_col, examples, more)
                    })

        # ── Generate or validate CSV filename ─────────────────────────
        if not csv_filename:
            # Auto-generate from rule name: DR102_powershell -> DR102_powershell.csv
            safe_name = "".join(
                c if c.isalnum() or c in ("_", "-") else "_"
                for c in detection_rule
            )
            csv_filename = safe_name + ".csv"

        if not is_safe_filename(csv_filename):
            return self._resp(400, {"error": "Invalid CSV file name"})
        if len(csv_filename) > 100:
            return self._resp(400, {
                "error": "CSV file name too long: {} chars (max 100)".format(
                    len(csv_filename))
            })

        # ── Validate target app ─────────────────────────────────────────
        safe_app = os.path.basename(app_context)
        target_app_dir = os.path.join(APPS_DIR, safe_app)
        if not os.path.isdir(target_app_dir):
            return self._resp(400, {
                "error": "App '{}' does not exist".format(app_context)
            })
        target_lookups = os.path.join(target_app_dir, "lookups")
        if not os.path.isdir(target_lookups):
            try:
                os.makedirs(target_lookups, exist_ok=True)
            except OSError as exc:
                _logger.error("Cannot create lookups dir in '%s': %s",
                              app_context, exc)
                return self._resp(500, {
                    "error": "Cannot create lookups directory. Please check server logs."
                })

        # ── Check that the CSV file does not already exist ────────────
        csv_path = build_csv_path(csv_filename, app_context)
        if csv_path is None:
            return self._resp(400, {
                "error": "Invalid CSV file name or path"
            })
        if os.path.exists(csv_path):
            return self._resp(409, {
                "error": "CSV file '{}' already exists in app '{}'".format(
                    csv_filename, app_context)
            })

        # ── Check that the mapping doesn't already exist ──────────────
        mapping = self._read_mapping()
        rule_csv_count = 0
        for entry in mapping:
            entry_csv = entry.get("csv_file", "")
            entry_rule = entry.get("rule_name", "")
            if entry_rule == detection_rule:
                rule_csv_count += 1
            # Same file already mapped to another rule
            if entry_csv == csv_filename and entry_rule != detection_rule:
                return self._resp(409, {
                    "error": "CSV file '{}' is already attached to rule '{}'".format(
                        csv_filename, entry_rule)
                })
            # Exact same rule+file pair
            if entry_rule == detection_rule and entry_csv == csv_filename:
                return self._resp(409, {
                    "error": "Mapping already exists for '{}' -> '{}'".format(
                        detection_rule, csv_filename)
                })

        # ── Structural limits ────────────────────────────────────────
        if rule_csv_count >= MAX_CSVS_PER_RULE:
            return self._resp(400, {
                "error": "Rule '{}' already has {} CSV files (max {})".format(
                    detection_rule, rule_csv_count, MAX_CSVS_PER_RULE)
            })
        if len(mapping) >= MAX_TOTAL_CSV_MAPPINGS:
            return self._resp(400, {
                "error": "Total CSV mapping limit reached ({})".format(
                    MAX_TOTAL_CSV_MAPPINGS)
            })

        # ── Call pipeline to execute CSV creation ───────────────────────
        session_key = (request.get("system_authtoken", "") or
                       request.get("session", {}).get("authtoken", "")
                       ) if request else ""
        result = create_csv_pipeline(
            csv_path=csv_path,
            headers=headers,
            initial_rows=initial_rows,
            analyst=user,
            session_key=session_key,
            csv_file=csv_filename,
            app_context=app_context,
            detection_rule=detection_rule,
        )

        if not result.get("success"):
            _logger.error("create_csv_pipeline failed: %s", result.get("error"))
            return self._resp(500, {
                "error": result.get("error", "Failed to create CSV file")
            })

        # ── Update mapping file ─────────────────────────────────────────
        try:
            mapping.append({
                "rule_name": detection_rule,
                "csv_file": csv_filename,
                "app_context": app_context,
            })
            with open(MAPPING_FILE, "w", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(
                    fh, fieldnames=["rule_name", "csv_file", "app_context"],
                    extrasaction="ignore",
                )
                writer.writeheader()
                writer.writerows(mapping)
        except OSError as exc:
            _logger.error("Failed to update mapping: %s", exc)
            # Clean up the CSV file we just created
            try:
                os.remove(csv_path)
            except OSError:
                pass
            return self._resp(500, {
                "error": "Failed to update rule mapping. Please check server logs."
            })

        # ── Remove rule from registry if it was registered there ─────
        try:
            with _detection_rules_modify():
                registered = read_rules_registry()
                if detection_rule in registered:
                    registered.remove(detection_rule)
                    write_rules_registry(registered)
        except OSError:
            pass  # non-critical — rule just stays in both lists

        row_note = " with {} imported row(s)".format(len(initial_rows)) if initial_rows else ""
        return self._resp(200, {
            "success": True,
            "csv_file": csv_filename,
            "message": "CSV '{}' created with {} column(s){}".format(
                csv_filename, len(headers), row_note),
        })

    # _remove_rule and _remove_csv extracted to delete_rule_pipeline
    # and delete_csv_pipeline in wl_rules.py (Plan 04-07)

    def _save_csv(self, request, payload, user, _from_approval=False):
        csv_file = payload.get("csv_file", "")
        app_context = payload.get("app_context", "")
        detection_rule = payload.get("detection_rule", "")
        new_headers = payload.get("headers", [])
        new_rows = payload.get("rows", [])
        raw_comment = payload.get("comment", "")
        ascii_err = validate_ascii_text(raw_comment)
        if ascii_err:
            return self._resp(200, {"error": ascii_err})
        analyst_comment = sanitize_text(raw_comment)
        removal_reasons = payload.get("removal_reasons", [])
        if not isinstance(removal_reasons, list):
            removal_reasons = []
        if len(removal_reasons) > MAX_ROWS:
            return self._resp(400, {
                "error": "Too many removal reasons: {} (max {})".format(
                    len(removal_reasons), MAX_ROWS)
            })
        for rr in removal_reasons:
            if isinstance(rr, dict) and isinstance(rr.get("reason"), str):
                ascii_err = validate_ascii_text(rr["reason"])
                if ascii_err:
                    return self._resp(200, {"error": ascii_err})
                rr["reason"] = rr["reason"][:500]
        bulk_removal = payload.get("bulk_removal", [])
        if not isinstance(bulk_removal, list):
            bulk_removal = []
        if len(bulk_removal) > MAX_ROWS:
            return self._resp(400, {
                "error": "Too many bulk removal entries: {} (max {})".format(
                    len(bulk_removal), MAX_ROWS)
            })
        for br in bulk_removal:
            if isinstance(br, dict) and isinstance(br.get("reason"), str):
                ascii_err = validate_ascii_text(br["reason"])
                if ascii_err:
                    return self._resp(200, {"error": ascii_err})
                br["reason"] = br["reason"][:500]
        column_removal_reasons = payload.get("column_removal_reasons", [])
        if not isinstance(column_removal_reasons, list):
            column_removal_reasons = []
        if len(column_removal_reasons) > MAX_COLUMNS:
            return self._resp(400, {
                "error": "Too many column removal reasons: {} (max {})".format(
                    len(column_removal_reasons), MAX_COLUMNS)
            })
        for cr in column_removal_reasons:
            if isinstance(cr, dict) and isinstance(cr.get("reason"), str):
                ascii_err = validate_ascii_text(cr["reason"])
                if ascii_err:
                    return self._resp(200, {"error": ascii_err})
                cr["reason"] = cr["reason"][:500]
        row_reorder = payload.get("row_reorder", None)
        column_reorder = payload.get("column_reorder", None)
        column_renames = payload.get("column_renames", [])
        if not isinstance(column_renames, list):
            column_renames = []
        if len(column_renames) > MAX_COLUMNS:
            return self._resp(400, {
                "error": "Too many column renames: {} (max {})".format(
                    len(column_renames), MAX_COLUMNS)
            })
        explicit_row_add_reason = payload.get("row_add_reason", "")[:500]
        ascii_err = validate_ascii_text(explicit_row_add_reason)
        if ascii_err:
            return self._resp(200, {"error": ascii_err})
        expected_mtime = payload.get("expected_mtime", None)

        # ── Validate filename ─────────────────────────────────────────
        if not is_safe_filename(csv_file):
            return self._resp(400, {"error": "Invalid CSV file name"})

        if not detection_rule:
            return self._resp(400, {"error": "detection_rule is required"})

        # ── Validate payload types ────────────────────────────────────
        if not isinstance(new_headers, list):
            return self._resp(400, {"error": "headers must be a list"})
        if not isinstance(new_rows, list):
            return self._resp(400, {"error": "rows must be a list"})
        for i, h in enumerate(new_headers):
            if not isinstance(h, str):
                return self._resp(400, {
                    "error": "headers[{}] must be a string, got {}".format(i, type(h).__name__)
                })
        for i, row in enumerate(new_rows):
            if not isinstance(row, dict):
                return self._resp(400, {
                    "error": "rows[{}] must be a dict, got {}".format(i, type(row).__name__)
                })

        # ── Validate size limits ─────────────────────────────────────
        if len(new_rows) > MAX_ROWS:
            return self._resp(400, {
                "error": "Row limit exceeded: {} rows submitted, maximum is {}."
                         .format(len(new_rows), MAX_ROWS)
            })

        # Block user-created columns starting with "_" — reserved for
        # internal metadata (_added_by, _added_at, _review_status).
        # Without this check, a user could bypass column limits and
        # hide data from diffs/audits by using "_" prefixed names.
        INTERNAL_COLUMNS = {"_added_by", "_added_at", "_review_status"}
        for h in new_headers:
            if h.startswith("_") and h not in INTERNAL_COLUMNS:
                return self._resp(400, {
                    "error": "Column names starting with '_' are reserved "
                             "for internal use. Rename '{}' to remove the "
                             "underscore prefix.".format(h)
                })

        visible_new_headers = [h for h in new_headers if not h.startswith("_")]
        if len(visible_new_headers) > MAX_COLUMNS:
            return self._resp(400, {
                "error": "Column limit exceeded: {} columns submitted, maximum is {}."
                         .format(len(visible_new_headers), MAX_COLUMNS)
            })

        # ── Validate and sanitize cell values ───────────────────────
        _non_ascii_re = re.compile(r'[^\x00-\x7F]')
        _corrupt_re = re.compile(r'^[?\s]+$')
        for i, row in enumerate(new_rows):
            for h, v in row.items():
                if isinstance(v, str):
                    if len(v) > MAX_CELL_CHARS:
                        return self._resp(400, {
                            "error": "Cell value too long in row {}, column '{}': "
                                     "{} chars (max {}).".format(
                                         i + 1, h[:50], len(v), MAX_CELL_CHARS)
                        })
                    if _non_ascii_re.search(v):
                        return self._resp(200, {
                            "error": "Non-ASCII characters in row {}, "
                                     "column '{}'. Only ASCII characters "
                                     "are allowed.".format(
                                         i + 1, h[:50])
                        })
                    if v.strip() and _corrupt_re.match(v.strip()):
                        return self._resp(200, {
                            "error": "Row {}, column '{}': value '{}' "
                                     "appears to be encoding corruption "
                                     "(only ? characters). Re-save the CSV "
                                     "from Excel as CSV UTF-8.".format(
                                         i + 1, h[:50], v.strip()[:20])
                        })
                    # Strip null bytes, control chars, and normalize newlines
                    cleaned = v.replace("\x00", "")
                    cleaned = cleaned.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
                    cleaned = cleaned.replace("\t", " ")
                    cleaned = _CONTROL_CHAR_RE.sub("", cleaned)
                    if cleaned != v:
                        row[h] = cleaned

        # ── Validate expiration date formats ─────────────────────────
        expire_col = get_expire_column(new_headers)
        if expire_col and new_rows:
            _VALID_EXPIRE_FMTS = ("%Y-%m-%d %H:%M", "%Y-%m-%d")
            invalid_expire_rows = []
            for i, row in enumerate(new_rows):
                exp_val = (row.get(expire_col) or "").strip()
                if not exp_val:
                    continue  # empty = permanent, always valid
                # Strip " UTC" suffix for parsing
                parse_val = exp_val[:-4] if exp_val.endswith(" UTC") else exp_val
                parsed = False
                for fmt in _VALID_EXPIRE_FMTS:
                    try:
                        datetime.strptime(parse_val, fmt)
                        parsed = True
                        break
                    except ValueError:
                        continue
                if not parsed:
                    invalid_expire_rows.append((i + 1, exp_val))
                if len(invalid_expire_rows) >= 5:
                    break  # cap error reporting at 5 rows
            if invalid_expire_rows:
                examples = "; ".join(
                    "row {}: '{}'".format(r, v[:60]) for r, v in invalid_expire_rows
                )
                more = "" if len(invalid_expire_rows) < 5 else " (and possibly more)"
                return self._resp(400, {
                    "error": "Invalid date format in '{}' column: {}{}. "
                             "Expected format: YYYY-MM-DD HH:MM UTC (e.g. 2026-06-15 14:30 UTC) "
                             "or YYYY-MM-DD.".format(expire_col, examples, more),
                    "invalid_rows": [r for r, v in invalid_expire_rows],
                })

        # ── Validate header names ────────────────────────────────────
        for h in new_headers:
            if not h or not h.strip():
                return self._resp(400, {
                    "error": "Column names cannot be empty or whitespace-only."
                })
            if len(h) > 64:
                return self._resp(400, {
                    "error": "Column name too long (max 64 chars)."
                })
            if not _SAFE_COLNAME_RE.match(h):
                return self._resp(400, {
                    "error": "Column name '{}' contains invalid characters. "
                             "Only letters, numbers, and common "
                             "punctuation (_-.()/:#@&+) are allowed (no spaces).".format(
                                 h[:30])
                })

        # ── Validate column renames ──────────────────────────────────
        for cr in column_renames:
            old_n = cr.get("old_name", "")
            new_n = cr.get("new_name", "").strip()
            cr["new_name"] = new_n
            if not old_n or not new_n or old_n == new_n:
                return self._resp(400, {"error": "Invalid column rename"})
            if len(new_n) > 64:
                return self._resp(400, {
                    "error": "Column name too long (max 64 chars)."
                })
            if " " in new_n or "\t" in new_n:
                return self._resp(400, {
                    "error": "Column name '{}' cannot contain spaces. "
                             "Use underscores instead (e.g. 'src_ip').".format(
                                 new_n[:30])
                })
            if not _SAFE_COLNAME_RE.match(new_n):
                return self._resp(400, {
                    "error": "Column name '{}' contains invalid characters. "
                             "Only letters, numbers, and _-.()/:#@&+ are "
                             "allowed.".format(new_n[:30])
                })

        # ── Resolve path ──────────────────────────────────────────────
        path = resolve_csv_path(csv_file, app_context)
        if path is None:
            fallback = os.path.join(OWN_LOOKUPS, csv_file)
            if os.path.isfile(fallback) and safe_realpath(fallback, APPS_DIR):
                path = safe_realpath(fallback, APPS_DIR)
        if path is None:
            return self._resp(404, {"error": "CSV file not found"})

        # ── Acquire file-level lock for the read-modify-write cycle ───
        # (On Windows, falls through to optimistic-lock-only mode.)
        # ── Optimistic locking — reject if file changed since load ───
        if expected_mtime is not None:
            try:
                expected_int = int(expected_mtime)
            except (ValueError, TypeError):
                return self._resp(400, {
                    "error": "Invalid expected_mtime value. Please reload "
                             "the file and try again.",
                })
            try:
                current_mtime = int(os.path.getmtime(path))
                if current_mtime != expected_int:
                    return self._resp(409, {
                        "error": "Conflict: the CSV file was modified by another "
                                 "user or process since you loaded it. Please "
                                 "reload the file and try again.",
                        "current_mtime": current_mtime,
                    })
            except OSError:
                pass  # File not yet on disk (new CSV) — skip check

        # ── Read BEFORE state ─────────────────────────────────────────
        old_headers, old_rows = read_csv(path)
        if not new_headers:
            new_headers = old_headers

        # ── Reorder-only enforcement: discard cell edits when a
        #    row/column reorder is present so edits cannot piggyback ──
        if row_reorder or column_reorder:
            clean_rows = [dict(r) for r in old_rows]
            if row_reorder and isinstance(row_reorder, dict):
                fr = row_reorder.get("from_position")
                to = row_reorder.get("to_position")
                if (isinstance(fr, int) and isinstance(to, int)
                        and 1 <= fr <= len(clean_rows)
                        and 1 <= to <= len(clean_rows)):
                    moved = clean_rows.pop(fr - 1)
                    clean_rows.insert(to - 1, moved)
            if column_reorder and isinstance(column_reorder, dict):
                col = column_reorder.get("column", "")
                fr = column_reorder.get("from_position")
                to = column_reorder.get("to_position")
                if (col and isinstance(fr, int) and isinstance(to, int)
                        and col in old_headers):
                    new_headers = list(old_headers)
                    actual_idx = new_headers.index(col)
                    new_headers.pop(actual_idx)
                    vis = [h for h in new_headers if not h.startswith("_")]
                    target_col = None
                    if 1 <= to <= len(vis):
                        target_col = vis[to - 1]
                    if target_col:
                        ins_idx = new_headers.index(target_col)
                        if fr < to:
                            new_headers.insert(ins_idx + 1, col)
                        else:
                            new_headers.insert(ins_idx, col)
                    else:
                        new_headers.append(col)
            new_rows = clean_rows

        # ── Compute diff ──────────────────────────────────────────────
        diff = compute_diff(old_headers, old_rows, new_headers, new_rows)

        # Filter out rename-paired columns from add/remove diff results
        if column_renames:
            rename_old = {r["old_name"] for r in column_renames}
            rename_new = {r["new_name"] for r in column_renames}
            diff["removed_columns"] = [c for c in diff["removed_columns"] if c not in rename_old]
            diff["added_columns"] = [c for c in diff["added_columns"] if c not in rename_new]

        has_row_changes = diff["added_count"] > 0 or diff["removed_count"] > 0 or diff["edited_count"] > 0
        has_col_changes = bool(diff.get("added_columns")) or bool(diff.get("removed_columns"))
        has_rename = bool(column_renames)
        has_reorder = bool(row_reorder) or bool(column_reorder)
        if not has_row_changes and not has_col_changes and not has_rename and not has_reorder:
            return self._resp(200, {"message": "No changes detected", "diff": diff})

        # ── Full file lock — block ALL saves when approval pending ──
        if not _from_approval:
            pending = _get_pending_for_csv(csv_file)
            if pending:
                return self._resp(409, {
                    "error": "This CSV has a pending approval request and "
                             "cannot be modified until it is approved or "
                             "rejected.",
                    "pending_count": len(pending),
                })

        # ── Determine which limit actions apply to this save ──────────
        actual_edited = diff.get("edited_count", 0)
        is_bulk_edit = actual_edited >= 2
        limit_actions = []
        if bulk_removal and len(bulk_removal) >= 2:
            limit_actions.append("bulk_row_removal")
        elif bulk_removal or removal_reasons:
            limit_actions.append("row_removal")
        if column_removal_reasons:
            limit_actions.append("column_removal")
        if is_bulk_edit and actual_edited > 0:
            limit_actions.append("bulk_row_edit")
        elif actual_edited > 0 and not has_col_changes:
            limit_actions.append("row_edit")
        if diff["added_count"] > 0:
            limit_actions.append("row_addition")
        if diff.get("added_columns"):
            limit_actions.append("column_addition")
        if row_reorder:
            limit_actions.append("row_reorder")
        if column_reorder:
            limit_actions.append("column_reorder")

        # ── Compute action counts for daily limit checks ─────────────
        action_counts = {}
        for limit_action in limit_actions:
            if limit_action in ("bulk_row_removal", "row_removal"):
                action_counts[limit_action] = diff.get("removed_count", 1)
            elif limit_action == "column_removal":
                action_counts[limit_action] = len(column_removal_reasons) or 1
            elif limit_action in ("bulk_row_edit", "row_edit"):
                action_counts[limit_action] = diff.get("edited_count", 1)
            elif limit_action == "row_addition":
                action_counts[limit_action] = diff.get("added_count", 1)
            elif limit_action == "column_addition":
                action_counts[limit_action] = len(diff.get("added_columns", [])) or 1
            else:
                action_counts[limit_action] = 1

        # ── Determine if user is admin (for gate + limit exemptions) ──
        user_roles = get_roles(request) if request else set()
        is_admin_user = bool(is_admin(user_roles))

        # ── Daily limit enforcement (block only direct analyst actions,
        #    not admin-approved replays or admin direct actions) ────────
        if not _from_approval and not is_admin_user:
            for limit_action in limit_actions:
                count = action_counts.get(limit_action, 1)
                allowed, current, maximum = _check_daily_limit(
                    user, limit_action, action_count=count)
                if not allowed:
                    return self._resp(429, {
                        "error": _daily_limit_error_msg(
                            limit_action, count, current, maximum),
                        "limit_type": limit_action,
                        "current": current,
                        "maximum": maximum,
                        "disabled": maximum == 0,
                    })

        # ── Server-side approval gate enforcement ─────────────────────
        if not _from_approval and not is_admin_user:
            actual_removed = diff.get("removed_count", 0)
            if actual_removed >= _get_threshold("bulk_row_removal_threshold"):
                return self._resp(403, {
                    "error": "Removing {} rows requires admin approval. "
                             "Use the approval workflow.".format(actual_removed),
                    "requires_approval": True,
                })
            if is_bulk_edit and actual_edited >= _get_threshold("bulk_row_edit_threshold"):
                return self._resp(403, {
                    "error": "Bulk editing {} rows requires admin approval. "
                             "Use the approval workflow.".format(actual_edited),
                    "requires_approval": True,
                })
            actual_added = diff.get("added_count", 0)
            if actual_added >= _get_threshold("bulk_row_addition_threshold"):
                return self._resp(403, {
                    "error": "Adding {} rows requires admin approval. "
                             "Use the approval workflow.".format(actual_added),
                    "requires_approval": True,
                })
            for cr in column_removal_reasons:
                col = cr.get("column", "")
                nonempty = _count_nonempty_cells(old_rows, col)
                if nonempty >= _get_threshold("column_nonempty_threshold"):
                    return self._resp(403, {
                        "error": "Removing column '{}' ({} non-empty cells) "
                                 "requires admin approval. "
                                 "Use the approval workflow.".format(
                                     col, nonempty),
                        "requires_approval": True,
                    })

        # ── Call save_csv_pipeline for execution ──────────────────────
        has_comment_col = "Comment" in new_headers
        session_key = (request.get("system_authtoken", "") or
                       request.get("session", {}).get("authtoken", "")
                       ) if request else ""

        pipeline_result = save_csv_pipeline(
            csv_path=path,
            new_headers=new_headers,
            new_rows=new_rows,
            comment=analyst_comment,
            analyst=user,
            session_key=session_key,
            removal_reasons=removal_reasons,
            bulk_removal=bulk_removal,
            column_removal_reasons=column_removal_reasons,
            row_reorder=row_reorder,
            column_reorder=column_reorder,
            column_renames=column_renames,
            explicit_row_add_reason=explicit_row_add_reason,
            has_comment_col=has_comment_col,
            csv_file=csv_file,
            app_context=app_context,
            detection_rule=detection_rule,
        )

        if not pipeline_result.get("success"):
            return self._resp(500, {
                "error": pipeline_result.get("error", "Pipeline execution failed"),
            })

        # ── Increment daily limit counters (by actual change count) ───
        for limit_action in limit_actions:
            if limit_action == "bulk_row_removal":
                actual_count = diff.get("removed_count", 1)
            elif limit_action == "row_removal":
                actual_count = diff.get("removed_count", 1)
            elif limit_action == "column_removal":
                actual_count = len(column_removal_reasons) or 1
            elif limit_action == "bulk_row_edit":
                actual_count = diff.get("edited_count", 1)
            elif limit_action == "row_edit":
                actual_count = diff.get("edited_count", 1)
            elif limit_action == "row_addition":
                actual_count = diff.get("added_count", 1)
            elif limit_action == "column_addition":
                actual_count = len(diff.get("added_columns", [])) or 1
            else:
                actual_count = 1
            _increment_daily_limit(user, limit_action, count=actual_count)

        return self._resp(200, {
            "message": "CSV saved successfully",
            "diff": diff,
            "rows_before": len(old_rows),
            "rows_after": len(new_rows),
            "file_mtime": int(os.path.getmtime(path)),
        })


    def _revert_csv(self, request, payload, user, _from_approval=False,
                    roles=None):
        """Revert a CSV file to a previous version snapshot."""
        csv_file = payload.get("csv_file", "")
        app_context = payload.get("app_context", "")
        detection_rule = payload.get("detection_rule", "")
        version_filename = payload.get("version_filename", "")
        version_display = payload.get("version_display", "")
        revert_reason = payload.get("revert_reason", "")
        expected_mtime = payload.get("expected_mtime", None)

        if not revert_reason.strip():
            return self._resp(400, {"error": "A reason is required for revert"})
        ascii_err = validate_ascii_text(revert_reason)
        if ascii_err:
            return self._resp(200, {"error": ascii_err})
        if len(revert_reason) > 500:
            revert_reason = revert_reason[:500]

        if not is_safe_filename(csv_file):
            return self._resp(400, {"error": "Invalid CSV file name"})

        if not detection_rule:
            return self._resp(400, {"error": "detection_rule is required"})

        # ── Resolve current CSV path ─────────────────────────────────
        path = resolve_csv_path(csv_file, app_context)
        if path is None:
            fallback = os.path.join(OWN_LOOKUPS, csv_file)
            if os.path.isfile(fallback) and safe_realpath(fallback, APPS_DIR):
                path = safe_realpath(fallback, APPS_DIR)
        if path is None:
            return self._resp(404, {"error": "CSV file not found"})

        # ── Full file lock — block revert when approval pending ──────
        # Skip when replaying from approval — the pending request IS the
        # one being approved, so it will be resolved right after this.
        if not _from_approval:
            pending = _get_pending_for_csv(csv_file)
            if pending:
                return self._resp(409, {
                    "error": "This CSV has a pending approval request and "
                             "cannot be reverted until it is approved or "
                             "rejected.",
                    "pending_count": len(pending),
                })

        # ── Optimistic locking — reject if file changed since load ───
        # Skip when replaying from approval — the admin approves at a
        # later time, so mtime will naturally differ.
        if not _from_approval and expected_mtime is not None:
            try:
                expected_int = int(expected_mtime)
            except (ValueError, TypeError):
                return self._resp(400, {
                    "error": "Invalid expected_mtime value. Please reload "
                             "the file and try again.",
                })
            try:
                current_mtime = int(os.path.getmtime(path))
                if current_mtime != expected_int:
                    return self._resp(409, {
                        "error": "Conflict: the CSV file was modified by another "
                                 "user or process since you loaded it. Please "
                                 "reload the file and try again.",
                        "current_mtime": current_mtime,
                    })
            except OSError:
                pass

        # ── Locate the version file ──────────────────────────────────
        if not version_filename or os.path.basename(version_filename) != version_filename:
            return self._resp(400, {"error": "Invalid version filename"})

        versions_dir = get_versions_dir(path)
        version_path = os.path.join(versions_dir, version_filename)
        if not os.path.isfile(version_path):
            return self._resp(404, {"error": "Version file not found"})

        # ── Read BEFORE state (current CSV) ──────────────────────────
        old_headers, old_rows = read_csv(path)

        # ── Read the version to revert to ────────────────────────────
        new_headers, new_rows = read_csv(version_path)

        # ── Compute diff between current state and reverted version ──
        diff = compute_diff(old_headers, old_rows, new_headers, new_rows)

        # ── Daily limit enforcement for reverts ──────────────────────
        # Skip when replaying from approval — already checked at
        # submission time in _submit_approval().
        # Admins are exempt — they control these limits.
        _is_admin = roles and is_admin(roles)
        if not _from_approval and not _is_admin:
            allowed, current, maximum = _check_daily_limit(user, "revert")
            if not allowed:
                return self._resp(429, {
                    "error": _daily_limit_error_msg(
                        "revert", 1, current, maximum),
                    "limit_type": "revert",
                    "current": current,
                    "maximum": maximum,
                    "disabled": maximum == 0,
                })

        # ── Approval gate for large reverts ──────────────────────────
        # Skip when replaying from approval — the admin already approved.
        # Admins are exempt — they ARE the approvers.
        if not _from_approval and not _is_admin:
            total_row_changes = (
                diff.get("added_count", 0) +
                diff.get("removed_count", 0) +
                diff.get("edited_count", 0)
            )
            total_col_changes = (
                len(diff.get("added_columns", [])) +
                len(diff.get("removed_columns", []))
            )
            row_threshold = _get_threshold("revert_row_threshold")
            col_threshold = _get_threshold("revert_column_threshold")
            needs_approval_rows = total_row_changes >= row_threshold
            needs_approval_cols = total_col_changes >= col_threshold
            if needs_approval_rows or needs_approval_cols:
                parts = []
                if needs_approval_rows:
                    parts.append("{} rows (threshold: {})".format(
                        total_row_changes, row_threshold))
                if needs_approval_cols:
                    parts.append("{} columns (threshold: {})".format(
                        total_col_changes, col_threshold))
                return self._resp(403, {
                    "error": "This revert would change {}. "
                             "Large reverts require admin approval. "
                             "Use the approval workflow.".format(
                                 " and ".join(parts)),
                    "requires_approval": True,
                    "revert_row_changes": total_row_changes,
                    "revert_col_changes": total_col_changes,
                })

        # ── Call pipeline to execute the revert ──────────────────────
        session_key = (request.get("system_authtoken", "") or
                       request.get("session", {}).get("authtoken", "")
                       ) if request else ""
        result = revert_csv_pipeline(
            csv_path=path,
            version_filename=version_filename,
            version_display=version_display,
            revert_reason=revert_reason,
            analyst=user,
            session_key=session_key,
            csv_file=csv_file,
            app_context=app_context,
            detection_rule=detection_rule,
        )

        if not result.get("success"):
            _logger.error("revert_csv_pipeline failed: %s", result.get("error"))
            return self._resp(500, {
                "error": result.get("error", "Failed to revert CSV file")
            })

        # ── Increment daily revert counter ─────────────────────────────
        _increment_daily_limit(user, "revert")

        # Extract results from pipeline
        pipeline_data = result.get("data", {})
        pipeline_diff = result.get("diff", {})

        old_vis_hdrs = [h for h in old_headers if not h.startswith("_")]
        new_vis_hdrs = [h for h in new_headers if not h.startswith("_")]

        return self._resp(200, {
            "message": "CSV reverted successfully",
            "diff": pipeline_diff,
            "rows_before": len(old_rows),
            "rows_after": len(new_rows),
            "cols_before": len(old_vis_hdrs),
            "cols_after": len(new_vis_hdrs),
            "file_mtime": int(os.path.getmtime(path)),
        })

    # ------------------------------------------------------------------
    # Approval workflow handlers
    # ------------------------------------------------------------------

    def _extract_request_reasons(self, action_type, stored_payload):
        """Extract user-provided reason fields from a stored approval payload.

        Returns a dict with the appropriate reason fields based on action type:
          bulk_row_removal / column_removal → row_remove_reason / column_remove_reason
          bulk_row_addition                 → row_add_reason
          revert                            → revert_reason
        """
        reasons = {}
        if not stored_payload:
            return reasons
        if action_type == "bulk_row_removal":
            br = stored_payload.get("bulk_removal", [])
            if br and isinstance(br, list) and len(br) > 0:
                reasons["row_remove_reason"] = br[0].get("reason", "")[:500]
        elif action_type == "bulk_row_addition":
            reasons["row_add_reason"] = stored_payload.get(
                "row_add_reason", "")[:500]
        elif action_type == "column_removal":
            cr = stored_payload.get("column_removal_reasons", [])
            if cr and isinstance(cr, list) and len(cr) > 0:
                reasons["row_remove_reason"] = cr[0].get("reason", "")[:500]
        elif action_type == "revert":
            reasons["revert_reason"] = stored_payload.get(
                "revert_reason", "")[:500]
        elif action_type in ("create_csv", "create_rule",
                             "remove_csv", "remove_rule"):
            reason = (stored_payload.get("approval_reason") or
                      stored_payload.get("comment") or "")
            reasons["approval_reason"] = reason[:500]
        return reasons

    def _submit_create_delete_approval(self, request, payload, user,
                                        action_type, description):
        """Route a create/delete action through the approval queue."""
        reason = sanitize_text(
            payload.get("approval_reason") or payload.get("comment") or "")
        if not reason:
            return self._resp(400, {
                "error": "A reason is required for this action. "
                         "Please provide a reason for your request.",
                "requires_reason": True,
            })

        # Build approval-compatible payload
        approval_payload = {
            "action": "submit_approval",
            "approval_action_type": action_type,
            "description": reason,
            "detection_rule": payload.get("detection_rule",
                                          payload.get("rule_name", "")),
            "csv_file": payload.get("csv_file", ""),
            "app_context": payload.get("app_context", ""),
            "original_payload": payload,
            "pending_highlight": {
                "type": "create_delete",
                "action_type": action_type,
            },
        }

        return self._submit_approval(request, approval_payload, user)

    def _submit_approval(self, request, payload, user):
        """Create a pending approval request."""
        action_type = payload.get("approval_action_type", "")
        if action_type not in ("bulk_row_removal", "column_removal",
                                "csv_import_replace", "bulk_row_edit",
                                "bulk_row_addition", "revert",
                                "create_csv", "create_rule",
                                "remove_csv", "remove_rule"):
            return self._resp(400, {"error": "Invalid approval action type"})

        # Check create/delete permissions before accepting the request
        cfg = _read_limit_config()
        _perm_map = {
            "create_rule": "allow_analyst_create_rules",
            "create_csv": "allow_analyst_create_csv",
            "remove_rule": "allow_analyst_delete_rules",
            "remove_csv": "allow_analyst_delete_csv",
        }
        perm_key = _perm_map.get(action_type)
        if perm_key and not cfg.get(perm_key, False):
            return self._resp(403, {
                "error": "This operation is not permitted. "
                         "An admin must enable it in the Control Panel."
            })

        # Rule-only operations don't have a csv_file
        _rule_only_actions = {"create_rule", "remove_rule"}
        csv_file = payload.get("csv_file", "")
        if action_type in _rule_only_actions:
            if not csv_file:
                csv_file = "__rule_operation__"
        elif not is_safe_filename(csv_file):
            return self._resp(400, {"error": "Invalid CSV file name"})

        # Block if ANY pending request exists for this CSV (by any user, any action type).
        # A locked CSV cannot accept new submissions — existing requests must be resolved first.
        detection_rule = payload.get("detection_rule", "")
        queue = _expire_pending_approvals()  # Lock acquired below for write
        _rule_only = {"create_rule", "remove_rule"}
        for item in queue:
            if item["status"] != "pending":
                continue
            if action_type in _rule_only:
                # Rule operations: block if same detection_rule has a pending request
                if item.get("detection_rule", "") == detection_rule and item["action_type"] in _rule_only:
                    if item["analyst"] == user:
                        return self._resp(200, {
                            "error": "You already have a pending {} request "
                                     "for detection rule '{}'. "
                                     "Wait for it to be processed.".format(
                                         item["action_type"].replace("_", " "),
                                         detection_rule)
                        })
                    else:
                        return self._resp(200, {
                            "error": "A pending {} request by {} exists "
                                     "for detection rule '{}'. "
                                     "It must be resolved first.".format(
                                         item["action_type"].replace("_", " "),
                                         item["analyst"], detection_rule)
                        })
            else:
                # CSV operations: block if same csv_file has ANY pending request
                if item.get("csv_file") == csv_file:
                    if item["analyst"] == user:
                        return self._resp(200, {
                            "error": "You already have a pending {} request "
                                     "for this CSV. "
                                     "Wait for it to be processed.".format(
                                         item["action_type"].replace("_", " "))
                        })
                    else:
                        return self._resp(200, {
                            "error": "This CSV is locked by a pending {} request "
                                     "from {}. It must be resolved before new "
                                     "requests can be submitted.".format(
                                         item["action_type"].replace("_", " "),
                                         item["analyst"])
                        })

        # Check daily limit BEFORE allowing the request to be submitted.
        # Map approval action types to their daily-limit counter key.
        _approval_limit_map = {
            "bulk_row_removal": "bulk_row_removal",
            "bulk_row_edit": "bulk_row_edit",
            "bulk_row_addition": "row_addition",
            "column_removal": "column_removal",
            "revert": "revert",
            # csv_import_replace has no daily limit — always needs approval
        }
        limit_key = _approval_limit_map.get(action_type)
        if limit_key:
            # Determine how many rows this action will affect
            approval_count = payload.get("selected_count", 1)
            if isinstance(approval_count, (int, float)):
                approval_count = max(int(approval_count), 1)
            else:
                approval_count = 1
            allowed, current, maximum = _check_daily_limit(
                user, limit_key, action_count=approval_count)
            if not allowed:
                return self._resp(429, {
                    "error": _daily_limit_error_msg(
                        limit_key, approval_count, current, maximum),
                    "limit_type": limit_key,
                    "current": current,
                    "maximum": maximum,
                    "disabled": maximum == 0,
                })

        # Cap pending requests
        pending_count = sum(1 for item in queue if item["status"] == "pending")
        if pending_count >= MAX_PENDING_REQUESTS:
            return self._resp(429, {
                "error": "Pending request queue is full ({}/{} requests). "
                         "Please contact an admin to clear pending requests "
                         "before submitting new ones."
                         .format(pending_count, MAX_PENDING_REQUESTS),
                "pending_full": True,
            })

        request_id = _generate_request_id(user, csv_file, detection_rule)
        raw_description = payload.get("description", "")
        ascii_err = validate_ascii_text(raw_description)
        if ascii_err:
            return self._resp(200, {"error": ascii_err})
        description = sanitize_text(raw_description)

        # ── Validate original_payload size ────────────────────────────
        original_payload = payload.get("original_payload", {})
        if not isinstance(original_payload, dict):
            return self._resp(400, {"error": "original_payload must be an object"})
        try:
            payload_size = len(json.dumps(original_payload))
        except (TypeError, ValueError):
            return self._resp(400, {"error": "original_payload is not serializable"})
        if payload_size > 5 * 1024 * 1024:  # 5 MB per approval entry
            return self._resp(400, {
                "error": "Approval payload too large ({:.1f} MB, max 5 MB)".format(
                    payload_size / (1024 * 1024))
            })

        # ── Validate + sanitize text fields inside original_payload ────
        # The original_payload is stored as-is for replay, but reason
        # fields displayed in the UI must be sanitized to prevent
        # injection of misleading text or unsanitized characters.
        for _field in ("comment", "revert_reason", "row_add_reason"):
            if _field in original_payload:
                ascii_err = validate_ascii_text(original_payload.get(_field, ""))
                if ascii_err:
                    return self._resp(200, {"error": ascii_err})
                original_payload[_field] = sanitize_text(
                    original_payload.get(_field, ""))
        for cr in original_payload.get("column_removal_reasons", []):
            if isinstance(cr, dict) and "reason" in cr:
                ascii_err = validate_ascii_text(cr.get("reason", ""))
                if ascii_err:
                    return self._resp(200, {"error": ascii_err})
                cr["reason"] = sanitize_text(cr.get("reason", ""))
        for br in original_payload.get("bulk_removal", []):
            if isinstance(br, dict) and "reason" in br:
                ascii_err = validate_ascii_text(br.get("reason", ""))
                if ascii_err:
                    return self._resp(200, {"error": ascii_err})
                br["reason"] = sanitize_text(br.get("reason", ""))

        # ── Validate pending_highlight.row_keys size ─────────────────
        pending_highlight = payload.get("pending_highlight", {})
        if isinstance(pending_highlight, dict):
            row_keys = pending_highlight.get("row_keys", [])
            if isinstance(row_keys, list) and len(row_keys) > MAX_ROWS:
                return self._resp(400, {
                    "error": "Too many highlight row_keys: {} (max {})".format(
                        len(row_keys), MAX_ROWS)
                })
        else:
            pending_highlight = {}

        raw_comment = payload.get("comment", "")
        ascii_err = validate_ascii_text(raw_comment)
        if ascii_err:
            return self._resp(200, {"error": ascii_err})
        comment = sanitize_text(raw_comment)

        entry = {
            "request_id": request_id,
            "timestamp": int(time.time()),
            "analyst": user,
            "csv_file": csv_file,
            "app_context": payload.get("app_context", ""),
            "detection_rule": payload.get("detection_rule", ""),
            "action_type": action_type,
            "description": description,
            "comment": comment,
            "status": "pending",
            "payload": original_payload,
            "expected_mtime": payload.get("expected_mtime"),
            "pending_highlight": pending_highlight,
            "resolved_by": None,
            "resolved_at": None,
            "rejection_reason": None,
        }

        with _approval_queue_lock():
            # Re-read inside lock to prevent TOCTOU race
            queue = _expire_pending_approvals()
            queue.append(entry)
            _write_approval_queue(queue)

        # Audit event
        ts = int(time.time())
        orig_payload = payload.get("original_payload", {})
        hl = payload.get("pending_highlight", {})
        evt = {
            "timestamp": ts,
            "analyst": user,
            "action": "request_submitted",
            "status": "pending",
            "detection_rule": payload.get("detection_rule", ""),
            "csv_file": csv_file,
            "app_context": payload.get("app_context", ""),
            "request_id": request_id,
            "approval_action_type": action_type,
            "description": description,
            "comment": "Approval requested for {}".format(
                action_type.replace("_", " ")),
        }
        evt.update(self._extract_request_reasons(action_type, orig_payload))

        # Build value lines from highlight data so auditors can see
        # exactly which rows/columns were requested.
        req_values = []
        if action_type in ("bulk_row_removal", "bulk_row_addition",
                           "bulk_row_edit"):
            hl_headers = hl.get("headers", [])
            row_keys = hl.get("row_keys", [])
            for i, rk in enumerate(row_keys):
                row_num = i + 1
                if isinstance(rk, list) and len(rk) == len(hl_headers):
                    for h, v in zip(hl_headers, rk):
                        req_values.append("{}_row_{}: {}".format(
                            h, row_num, v))
                else:
                    req_values.append("row_{}: {}".format(
                        row_num, json.dumps(rk)))
            evt["requested_row_count"] = len(row_keys)
        elif action_type == "column_removal":
            col_name = hl.get("column_name", "")
            if col_name:
                req_values.append("column: {}".format(col_name))
                evt["requested_column"] = col_name
        elif action_type == "revert":
            ver = hl.get("version_display", hl.get("version_filename", ""))
            if ver:
                req_values.append("revert_to_version: {}".format(ver))
                evt["requested_version"] = ver
        if req_values:
            evt["value"] = req_values

        self._index_audit(request, evt)

        # Notify admins about new request (use system token for user enumeration)
        sys_key = request.get("system_authtoken", "") or \
            request.get("session", {}).get("authtoken", "")
        _notif_extra = {
            "csv_file": csv_file,
            "detection_rule": payload.get("detection_rule", ""),
            "action_type": action_type,
        }
        _notify_admins(
            "new_request",
            "{} requests {}: {}".format(
                user, action_type.replace("_", " "), description),
            request_id, extra=_notif_extra, session_key=sys_key)

        return self._resp(200, {
            "message": "Your request has been submitted for approval.",
            "request_id": request_id,
        })

    def _cancel_request(self, request, payload, user):
        """Cancel a pending approval request — only the original requester."""
        request_id = payload.get("request_id", "")
        raw_cancel = payload.get("cancellation_reason", "")
        ascii_err = validate_ascii_text(raw_cancel)
        if ascii_err:
            return self._resp(200, {"error": ascii_err})
        cancellation_reason = sanitize_text(raw_cancel)

        if not cancellation_reason.strip():
            return self._resp(400, {"error": "Cancellation reason is required"})

        with _approval_queue_lock():
            queue = _expire_pending_approvals()
            target = None
            for item in queue:
                if item["request_id"] == request_id:
                    target = item
                    break

            if not target:
                return self._resp(404, {"error": "Approval request not found"})
            if target["status"] != "pending":
                return self._resp(409, {
                    "error": "This request has already been {}".format(
                        target["status"])
                })

            # Only the original requester can cancel
            if target["analyst"] != user:
                return self._resp(403, {
                    "error": "Only the original requester can cancel this request"
                })

            now = int(time.time())
            target["status"] = "cancelled"
            target["resolved_by"] = user
            target["resolved_at"] = now
            target["cancellation_reason"] = cancellation_reason[:500]
            _write_approval_queue(queue)

        # Build value field from pending_highlight (same as request_submitted)
        stored_payload = target.get("payload", {})
        hl = target.get("pending_highlight", {})
        value_lines = []
        if hl.get("type") == "rows" and hl.get("row_keys"):
            hdrs = hl.get("headers", [])
            for ri, rk in enumerate(hl["row_keys"][:MAX_AUDIT_VALUE_LINES], 1):
                if isinstance(rk, list) and hdrs:
                    parts = []
                    for ci, v in enumerate(rk):
                        if ci < len(hdrs) and v:
                            parts.append("{}={}".format(hdrs[ci], v))
                    value_lines.append("row_{}: {}".format(ri, ", ".join(parts)))
                else:
                    value_lines.append("row_{}: {}".format(ri, json.dumps(rk)))
        elif hl.get("type") == "column":
            value_lines.append("column: {}".format(hl.get("column_name", "")))

        evt = {
            "timestamp": now,
            "analyst": user,
            "action": "request_cancelled",
            "status": "cancelled",
            "detection_rule": target["detection_rule"],
            "csv_file": target["csv_file"],
            "app_context": target["app_context"],
            "request_id": request_id,
            "requester": user,
            "approval_action_type": target["action_type"],
            "cancellation_reason": cancellation_reason[:500],
            "comment": "{} cancelled their own {} request for {}".format(
                user, target["action_type"].replace("_", " "),
                target["csv_file"]),
        }
        if value_lines:
            evt["value"] = value_lines
        # Include the original analyst reason
        evt.update(self._extract_request_reasons(
            target["action_type"], stored_payload))
        # Row/column counts for audit dashboard
        if hl.get("type") == "rows" and hl.get("row_keys"):
            evt["requested_row_count"] = len(hl["row_keys"])
        elif hl.get("type") == "column":
            evt["requested_column"] = hl.get("column_name", "")

        self._index_audit(request, evt)

        # Notify admins about cancellation (use system token for user enumeration)
        sys_key = request.get("system_authtoken", "") or \
            request.get("session", {}).get("authtoken", "")
        _notif_extra = {
            "csv_file": target["csv_file"],
            "detection_rule": target["detection_rule"],
            "action_type": target["action_type"],
        }
        _notify_admins(
            "cancelled",
            "{} cancelled their {} request".format(
                user, target["action_type"].replace("_", " ")),
            request_id, extra=_notif_extra, session_key=sys_key)

        return self._resp(200, {
            "message": "Request cancelled.",
            "request_id": request_id,
        })

    # ==================================================================
    # Dual-admin approval for destructive admin operations
    # ==================================================================

    def _submit_dual_approval(self, request, payload, user):
        """Submit a destructive admin action for second-admin approval.

        Supported action_types:
        - admin_delete_rule: soft-delete a rule with 3+ CSVs
        - admin_delete_csv: soft-delete CSV when admin daily limit exceeded
        - admin_purge_trash: permanently purge a trashed item
        """
        action_type = payload.get("action_type", "")
        raw_comment = payload.get("comment", "")
        ascii_err = validate_ascii_text(raw_comment)
        if ascii_err:
            return self._resp(200, {"error": ascii_err})
        comment = sanitize_text(raw_comment)[:500]

        valid_types = {
            "admin_delete_rule", "admin_delete_csv", "admin_purge_trash",
        }
        if action_type not in valid_types:
            return self._resp(400, {
                "error": "Invalid dual-approval action_type. "
                         "Valid: " + ", ".join(sorted(valid_types))})
        if not comment:
            return self._resp(400, {
                "error": "A reason is required"})

        # Build request metadata based on action type
        meta = {
            "rule_name": payload.get("rule_name", ""),
            "csv_file": payload.get("csv_file", ""),
            "trash_id": payload.get("trash_id", ""),
            "removal_type": payload.get("removal_type", "permanent"),
        }

        # EC2: Record current state for re-validation at approval time
        if action_type == "admin_delete_rule":
            rule_name = meta["rule_name"]
            if not rule_name:
                return self._resp(400, {
                    "error": "rule_name is required"})
            mapping = self._read_mapping()
            csv_count = len([e for e in mapping
                             if e.get("rule_name") == rule_name])
            meta["csv_count_at_submission"] = csv_count

        # EC5: Validate trash_id exists for purge requests
        if action_type == "admin_purge_trash":
            tid = meta["trash_id"]
            if not tid:
                return self._resp(400, {
                    "error": "trash_id is required"})
            # Require super-admin for purge submissions
            roles = get_roles(request)
            if not is_superadmin(roles):
                return self._resp(403, {
                    "error": "Requires super-admin role to submit "
                             "trash purge requests"})
            trash_dir = get_trash_dir()
            if not os.path.isdir(os.path.join(trash_dir, tid)):
                return self._resp(404, {
                    "error": "Trash item not found"})

        # Create the dual-approval request in the queue
        request_id = _generate_request_id(user)
        now = int(time.time())
        entry = {
            "request_id": request_id,
            "analyst": user,
            "action_type": action_type,
            "status": "pending",
            "submitted_at": now,
            "submitted_at_human": time.strftime(
                "%Y-%m-%d %H:%M:%S UTC", time.gmtime(now)),
            "comment": comment,
            "meta": meta,
            "is_dual_admin": True,
        }

        with _approval_queue_lock():
            queue = _read_approval_queue()
            queue.append(entry)
            _write_approval_queue(queue)

        # Notify other admins
        desc_map = {
            "admin_delete_rule": "delete rule '{}'".format(
                meta.get("rule_name", "")),
            "admin_delete_csv": "delete CSV '{}'".format(
                meta.get("csv_file", "")),
            "admin_purge_trash": "permanently purge '{}' from trash".format(
                meta.get("trash_id", "")[:40]),
        }
        desc = desc_map.get(action_type, action_type)
        sys_key = request.get("system_authtoken",
                              request.get("session", {}).get(
                                  "authtoken", ""))
        _notify_admins(
            "new_request",
            "{} requests dual-approval to {}: {}".format(
                user, desc, comment[:100]),
            request_id,
            extra={
                "action_type": action_type,
                "detection_rule": meta.get("rule_name", ""),
                "csv_file": meta.get("csv_file", ""),
            },
            session_key=sys_key,
        )

        self._index_audit(request, {
            "action": "dual_approval_submitted",
            "timestamp": now,
            "analyst": user,
            "approval_action_type": action_type,
            "detection_rule": meta.get("rule_name", ""),
            "csv_file": meta.get("csv_file", ""),
            "trash_id": meta.get("trash_id", ""),
            "comment": comment,
            "request_id": request_id,
        })

        return self._resp(200, {
            "success": True,
            "message": "Dual-approval request submitted. A second admin "
                       "must approve this action.",
            "request_id": request_id,
        })

    def _process_dual_approval(self, request, payload, admin_user):
        """Approve or reject a dual-admin approval request.

        Edge case mitigations:
        - EC1: Self-approval blocked (submitter cannot approve own request)
        - EC2: Re-validates state at approval time (CSV count, trash existence)
        - EC4: Daily limit NOT reset — dual-approval is additional gate, not bypass
        """
        request_id = payload.get("request_id", "")
        decision = payload.get("decision", "")
        raw_admin_comment = payload.get("admin_comment", "")
        ascii_err = validate_ascii_text(raw_admin_comment)
        if ascii_err:
            return self._resp(200, {"error": ascii_err})
        admin_comment = sanitize_text(raw_admin_comment)[:500]

        if decision not in ("approve", "reject"):
            return self._resp(400, {
                "error": "Decision must be 'approve' or 'reject'"})
        if decision == "reject" and not admin_comment:
            return self._resp(400, {
                "error": "Rejection reason is required"})

        with _approval_queue_lock():
            queue = _read_approval_queue()
            target = None
            for item in queue:
                if item["request_id"] == request_id:
                    target = item
                    break

            if not target:
                return self._resp(404, {
                    "error": "Dual-approval request not found"})
            if target["status"] != "pending":
                return self._resp(409, {
                    "error": "Already {}".format(target["status"])})
            if not target.get("is_dual_admin"):
                return self._resp(400, {
                    "error": "This is not a dual-admin request. "
                             "Use process_approval instead."})

            # EC1: Self-approval blocked
            if target["analyst"] == admin_user:
                return self._resp(403, {
                    "error": "Self-approval is not allowed. A different "
                             "admin must approve this request."})

            action_type = target["action_type"]
            meta = target.get("meta", {})
            now = int(time.time())

            if decision == "reject":
                target["status"] = "rejected"
                target["resolved_by"] = admin_user
                target["resolved_at"] = now
                target["admin_comment"] = admin_comment
                _write_approval_queue(queue)

                # Notify submitter
                _add_notification(
                    target["analyst"], "rejected",
                    "Your {} request was rejected by {}: {}".format(
                        action_type.replace("_", " "),
                        admin_user, admin_comment),
                    request_id)

                self._index_audit(request, {
                    "action": "dual_approval_rejected",
                    "timestamp": now,
                    "analyst": admin_user,
                    "requester": target["analyst"],
                    "approval_action_type": action_type,
                    "rejection_reason": admin_comment,
                    "request_id": request_id,
                })

                return self._resp(200, {
                    "success": True,
                    "message": "Dual-approval request rejected."})

            # ── APPROVE path ──────────────────────────────────────────
            # EC2: Re-validate preconditions before executing

            if action_type == "admin_delete_rule":
                rule_name = meta.get("rule_name", "")
                mapping = self._read_mapping()
                current_csvs = [e for e in mapping
                                if e.get("rule_name") == rule_name]
                if not current_csvs:
                    # Rule was already deleted or has no CSVs
                    registered = read_rules_registry()
                    if rule_name not in registered:
                        target["status"] = "failed"
                        target["failure_reason"] = "Rule no longer exists"
                        _write_approval_queue(queue)
                        return self._resp(409, {
                            "error": "Rule '{}' no longer exists".format(
                                rule_name)})

                # Execute the deletion with _from_dual_approval flag
                target["status"] = "approved"
                target["resolved_by"] = admin_user
                target["resolved_at"] = now
                target["admin_comment"] = admin_comment
                _write_approval_queue(queue)

            elif action_type == "admin_delete_csv":
                csv_file = meta.get("csv_file", "")
                mapping = self._read_mapping()
                found = any(e.get("csv_file") == csv_file for e in mapping)
                if not found:
                    target["status"] = "failed"
                    target["failure_reason"] = "CSV no longer exists"
                    _write_approval_queue(queue)
                    return self._resp(409, {
                        "error": "CSV '{}' no longer exists".format(
                            csv_file)})

                target["status"] = "approved"
                target["resolved_by"] = admin_user
                target["resolved_at"] = now
                target["admin_comment"] = admin_comment
                _write_approval_queue(queue)

            elif action_type == "admin_purge_trash":
                trash_id = meta.get("trash_id", "")
                trash_dir = get_trash_dir()
                if not os.path.isdir(os.path.join(trash_dir, trash_id)):
                    target["status"] = "failed"
                    target["failure_reason"] = "Trash item no longer exists"
                    _write_approval_queue(queue)
                    return self._resp(409, {
                        "error": "Trash item no longer exists"})

                target["status"] = "approved"
                target["resolved_by"] = admin_user
                target["resolved_at"] = now
                target["admin_comment"] = admin_comment
                _write_approval_queue(queue)

            else:
                return self._resp(400, {
                    "error": "Unknown dual-approval action type"})

        # ── Execute the approved action (outside the queue lock) ──────
        self._index_audit(request, {
            "action": "dual_approval_approved",
            "timestamp": now,
            "analyst": admin_user,
            "requester": target["analyst"],
            "approval_action_type": action_type,
            "admin_comment": admin_comment,
            "request_id": request_id,
        })

        exec_result = None
        if action_type == "admin_delete_rule":
            exec_payload = {
                "rule_name": meta.get("rule_name", ""),
                "removal_type": meta.get("removal_type", "permanent"),
                "comment": "Dual-approved by {}: {}".format(
                    admin_user, meta.get("rule_name", "")),
                "_from_dual_approval": True,
            }
            pipeline_result = delete_rule_pipeline(
                exec_payload["rule_name"],
                exec_payload["removal_type"],
                exec_payload["comment"],
                target["analyst"],
                self.sessionKey)
            exec_result = self._resp(
                200 if pipeline_result.get("success") else 400,
                pipeline_result if pipeline_result.get("success")
                else {"error": pipeline_result.get("error", "Delete failed")})

        elif action_type == "admin_delete_csv":
            exec_payload = {
                "csv_file": meta.get("csv_file", ""),
                "rule_name": meta.get("rule_name", ""),
                "removal_type": meta.get("removal_type", "permanent"),
                "comment": "Dual-approved by {}: {}".format(
                    admin_user, meta.get("csv_file", "")),
                "_from_dual_approval": True,
            }
            pipeline_result = delete_csv_pipeline(
                exec_payload["csv_file"],
                exec_payload["removal_type"],
                exec_payload["comment"],
                target["analyst"],
                self.sessionKey,
                rule_name=exec_payload.get("rule_name", ""))
            exec_result = self._resp(
                200 if pipeline_result.get("success") else 400,
                pipeline_result if pipeline_result.get("success")
                else {"error": pipeline_result.get("error", "Delete failed")})

        elif action_type == "admin_purge_trash":
            purge_comment = "Dual-approved purge by {}".format(admin_user)
            # Read metadata before purging for audit
            trash_dir = get_trash_dir()
            trash_meta = {}
            meta_path = os.path.join(
                trash_dir, meta.get("trash_id", ""), "metadata.json")
            if os.path.isfile(meta_path):
                try:
                    with open(meta_path, "r", encoding="utf-8") as fh:
                        trash_meta = json.load(fh)
                except (json.JSONDecodeError, OSError):
                    pass
            success, msg = purge_trash_item(meta.get("trash_id", ""))
            if success:
                self._index_audit(request, {
                    "action": "trash_purged",
                    "timestamp": int(time.time()),
                    "analyst": admin_user,
                    "requester": target["analyst"],
                    "item_type": trash_meta.get("item_type", ""),
                    "name": trash_meta.get("name", ""),
                    "comment": purge_comment,
                    "dual_approved": True,
                })
            exec_result = self._resp(
                200 if success else 500,
                {"success": success, "message": msg})

        # Notify submitter
        _add_notification(
            target["analyst"], "approved",
            "Your {} request was approved by {}".format(
                action_type.replace("_", " "), admin_user),
            request_id)

        return exec_result or self._resp(200, {
            "success": True,
            "message": "Dual-approval action executed."})

    def _process_approval(self, request, payload, admin_user):
        """Approve, reject, or cancel a pending approval request.

        Uses a file lock to prevent concurrent approval operations
        from racing on the same queue entry.
        """
        with _approval_queue_lock():
            result = self._process_approval_inner(
                request, payload, admin_user)

        # Increment admin approval counter on success
        decision = payload.get("decision", "")
        resp_body = json.loads(result.get("payload", "{}"))
        if decision == "approve" and resp_body.get("success"):
            admin_roles = get_roles(request)
            if is_admin(admin_roles) and \
               not is_superadmin(admin_roles):
                _increment_admin_daily_limit(admin_user, "approval_count")

        return result

    def _fail_approval_request(self, request, queue, target, admin_user,
                                fail_reason, extra_evt=None, notify=True,
                                status_code=409):
        """Mark an approval request as failed: update queue, audit, optionally notify.

        Centralizes the repeated pattern of failing an approval request.

        Args:
            request: Splunk request object (for audit posting).
            queue: The approval queue list (mutated in place).
            target: The queue entry to fail (mutated in place).
            admin_user: Admin performing the action.
            fail_reason: Human-readable failure reason.
            extra_evt: Optional dict of additional audit event fields.
            notify: Whether to send notification to analyst (default True).
            status_code: HTTP status code for response (default 409).

        Returns:
            HTTP response dict via self._resp().
        """
        now = int(time.time())
        target["status"] = "failed"
        target["resolved_by"] = admin_user
        target["resolved_at"] = now
        target["rejection_reason"] = fail_reason
        _write_approval_queue(queue)

        evt = {
            "timestamp": now, "analyst": admin_user,
            "action": "request_failed", "status": "failed",
            "detection_rule": target.get("detection_rule", ""),
            "csv_file": target.get("csv_file", ""),
            "app_context": target.get("app_context", ""),
            "request_id": target.get("request_id", ""),
            "requester": target.get("analyst", ""),
            "approval_action_type": target.get("action_type", ""),
            "failure_reason": fail_reason,
            "comment": "{} failed to approve {} request created by {}".format(
                admin_user, target.get("action_type", "").replace("_", " "),
                target.get("analyst", "")),
        }
        evt.update(self._extract_request_reasons(
            target.get("action_type", ""), target.get("payload", {})))
        if extra_evt:
            evt.update(extra_evt)
        self._index_audit(request, evt)

        if notify:
            _add_notification(
                target["analyst"], "rejected",
                "Your {} request failed: {}".format(
                    target["action_type"].replace("_", " "), fail_reason),
                target["request_id"],
                {"csv_file": target.get("csv_file", ""),
                 "detection_rule": target.get("detection_rule", ""),
                 "action_type": target.get("action_type", "")})

        return self._resp(status_code, {
            "error": fail_reason,
            "request_id": target.get("request_id", ""),
        })

    def _approve_request(self, request, queue, target, admin_user,
                          admin_comment="", extra_evt=None):
        """Mark an approval request as approved: update queue, audit, notify.

        Centralizes the repeated pattern of approving a request
        (appeared 5 times in _process_approval_inner).

        Args:
            request: Splunk request object (for audit posting).
            queue: The approval queue list (mutated in place).
            target: The queue entry to approve (mutated in place).
            admin_user: Admin performing the action.
            admin_comment: Optional admin comment.
            extra_evt: Optional dict of additional audit event fields.
        """
        now = int(time.time())
        target["status"] = "approved"
        target["resolved_by"] = admin_user
        target["resolved_at"] = now
        target["admin_comment"] = admin_comment if admin_comment else "Approved"
        _write_approval_queue(queue)

        evt = {
            "timestamp": now, "analyst": admin_user,
            "action": "request_approved", "status": "approved",
            "detection_rule": target.get("detection_rule", ""),
            "csv_file": target.get("csv_file", ""),
            "app_context": target.get("app_context", ""),
            "request_id": target.get("request_id", ""),
            "requester": target.get("analyst", ""),
            "approval_action_type": target.get("action_type", ""),
            "comment": "{} approved {} request created by {}".format(
                admin_user, target.get("action_type", "").replace("_", " "),
                target.get("analyst", "")),
        }
        evt.update(self._extract_request_reasons(
            target.get("action_type", ""), target.get("payload", {})))
        if extra_evt:
            evt.update(extra_evt)
        self._index_audit(request, evt)

        _add_notification(
            target["analyst"], "approved",
            "Your {} request was approved by {}".format(
                target["action_type"].replace("_", " "), admin_user),
            target["request_id"],
            {"csv_file": target.get("csv_file", ""),
             "detection_rule": target.get("detection_rule", ""),
             "action_type": target.get("action_type", "")})

    def _process_approval_inner(self, request, payload, admin_user):
        request_id = payload.get("request_id", "")
        decision = payload.get("decision", "")
        for _fld_name in ("rejection_reason", "cancellation_reason",
                          "admin_comment"):
            ascii_err = validate_ascii_text(payload.get(_fld_name, ""))
            if ascii_err:
                return self._resp(200, {"error": ascii_err})
        rejection_reason = sanitize_text(
            payload.get("rejection_reason", ""))
        cancellation_reason = sanitize_text(
            payload.get("cancellation_reason", ""))
        admin_comment = sanitize_text(
            payload.get("admin_comment", ""))

        if decision not in ("approve", "reject", "cancel"):
            return self._resp(400, {"error": "Decision must be approve, reject, or cancel"})
        if decision == "cancel" and not cancellation_reason.strip():
            return self._resp(400, {"error": "Cancellation reason is required"})
        if decision == "reject" and not rejection_reason.strip():
            return self._resp(400, {"error": "Rejection reason is required"})

        # Admin daily limit for approvals (not applied to super-admins)
        if decision == "approve":
            admin_roles = get_roles(request)
            if is_admin(admin_roles) and \
               not is_superadmin(admin_roles):
                allowed, current, maximum = _check_admin_daily_limit(
                    admin_user, "approval_count")
                if not allowed:
                    return self._resp(429, {
                        "error": _daily_limit_error_msg(
                            "approval_count", 1, current, maximum,
                            contact="your super-admin"),
                        "limit_type": "admin_approval_count",
                        "current": current,
                        "maximum": maximum,
                        "disabled": maximum == 0,
                    })

        queue = _expire_pending_approvals()
        target = None
        for item in queue:
            if item["request_id"] == request_id:
                target = item
                break

        if not target:
            return self._resp(404, {"error": "Approval request not found"})
        if target["status"] != "pending":
            return self._resp(409, {
                "error": "This request has already been {}".format(target["status"])
            })

        now = int(time.time())

        # Prevent self-approval — the submitter cannot approve their own request
        if decision == "approve" and target["analyst"] == admin_user:
            return self._resp(403, {
                "error": "You cannot approve your own request. "
                         "Another admin must approve it."
            })

        # ── CANCEL: mark as cancelled ────────────
        if decision == "cancel":
            # Allow cancel by original analyst OR any admin
            admin_roles = get_roles(request)
            if target["analyst"] != admin_user and \
                    not is_admin(admin_roles):
                return self._resp(403, {
                    "error": "Only the original requester or an admin can cancel this request"
                })

            target["status"] = "cancelled"
            target["resolved_by"] = admin_user
            target["resolved_at"] = now
            target["cancellation_reason"] = cancellation_reason[:500]
            _write_approval_queue(queue)

            evt = {
                "timestamp": now,
                "analyst": admin_user,
                "action": "request_cancelled",
                "status": "cancelled",
                "detection_rule": target["detection_rule"],
                "csv_file": target["csv_file"],
                "app_context": target["app_context"],
                "request_id": request_id,
                "requester": target["analyst"],
                "approval_action_type": target["action_type"],
                "cancellation_reason": cancellation_reason[:500],
                "comment": "{} cancelled {} request created by {}".format(
                    admin_user, target["action_type"].replace("_", " "),
                    target["analyst"]),
            }
            evt.update(self._extract_request_reasons(
                target["action_type"], target.get("payload", {})))
            self._index_audit(request, evt)

            return self._resp(200, {
                "message": "Request cancelled.",
                "request_id": request_id,
            })

        if decision == "reject":
            target["status"] = "rejected"
            target["resolved_by"] = admin_user
            target["resolved_at"] = now
            target["rejection_reason"] = rejection_reason[:500]
            _write_approval_queue(queue)

            evt = {
                "timestamp": now,
                "analyst": admin_user,
                "action": "request_rejected",
                "status": "rejected",
                "detection_rule": target["detection_rule"],
                "csv_file": target["csv_file"],
                "app_context": target["app_context"],
                "request_id": request_id,
                "requester": target["analyst"],
                "approval_action_type": target["action_type"],
                "rejection_reason": rejection_reason[:500],
                "comment": "{} rejected {} request created by {}".format(
                    admin_user, target["action_type"].replace("_", " "),
                    target["analyst"]),
            }
            evt.update(self._extract_request_reasons(
                target["action_type"], target.get("payload", {})))
            self._index_audit(request, evt)

            # Notify analyst about rejection
            _add_notification(
                target["analyst"], "rejected",
                "Your {} request was rejected by {}: {}".format(
                    target["action_type"].replace("_", " "),
                    admin_user, rejection_reason),
                request_id,
                {"admin_comment": rejection_reason[:500],
                 "csv_file": target["csv_file"],
                 "detection_rule": target["detection_rule"],
                 "action_type": target["action_type"]})

            return self._resp(200, {
                "message": "Request rejected.",
                "request_id": request_id,
            })

        # ── APPROVE: rebuild payload from current CSV state ────────────
        csv_file = target["csv_file"]
        app_context = target["app_context"]
        action_type = target["action_type"]
        hl = target.get("pending_highlight", {})

        # Create/delete actions don't need an existing CSV — skip path check
        _no_csv_actions = {"create_csv", "create_rule",
                           "remove_csv", "remove_rule"}

        path = None
        cur_headers = []
        cur_rows = []

        if action_type not in _no_csv_actions:
            path = resolve_csv_path(csv_file, app_context)
            if path is None:
                fallback = os.path.join(OWN_LOOKUPS, csv_file)
                if os.path.isfile(fallback) and safe_realpath(fallback, APPS_DIR):
                    path = safe_realpath(fallback, APPS_DIR)
            if path is None:
                return self._fail_approval_request(
                    request, queue, target, admin_user,
                    "CSV file no longer exists",
                    notify=False, status_code=404)

            # Read current CSV state and build a fresh payload
            cur_headers, cur_rows = read_csv(path)
        stored_payload = target.get("payload", {})
        original_analyst = target["analyst"]
        replay_payload = None

        if action_type == "bulk_row_removal":
            # Use headers stored at submission time for key matching
            lock_h = hl.get("headers") or [
                h for h in cur_headers if not h.startswith("_")
            ]
            row_keys = hl.get("row_keys", [])
            # Use Counter (not set) so duplicate identical rows are all matched
            locked_counts = Counter(json.dumps(rk) for rk in row_keys)
            keep_rows = []
            removed_entries = []
            for i, row in enumerate(cur_rows):
                key = json.dumps([row.get(h, "") for h in lock_h])
                if locked_counts.get(key, 0) > 0:
                    removed_entries.append({
                        "row_number": i + 1,
                        "row": row,
                        "reason": stored_payload.get("bulk_removal", [{}])[0]
                                  .get("reason", "Approved bulk removal"),
                    })
                    locked_counts[key] -= 1
                else:
                    keep_rows.append(row)

            requested_count = len(row_keys)
            actual_count = len(removed_entries)
            if actual_count < requested_count:
                fail_msg = ("Only {} of {} target rows still exist in CSV. "
                            "CSV was modified since submission.".format(
                                actual_count, requested_count)
                            if actual_count > 0
                            else "Locked rows no longer found in CSV")
                return self._fail_approval_request(
                    request, queue, target, admin_user, fail_msg,
                    extra_evt={"requested_count": requested_count,
                               "actual_count": actual_count})

            replay_payload = {
                "action": "save_csv",
                "csv_file": csv_file,
                "app_context": app_context,
                "detection_rule": target["detection_rule"],
                "headers": cur_headers,
                "rows": keep_rows,
                "comment": stored_payload.get("comment",
                           "Approved bulk removal"),
                "bulk_removal": removed_entries,
                "expected_mtime": None,
                "_approval_request_id": request_id,
            }

        elif action_type == "column_removal":
            col_name = hl.get("column_name", "")
            if col_name not in cur_headers:
                return self._fail_approval_request(
                    request, queue, target, admin_user,
                    "Column '{}' no longer exists".format(col_name),
                    notify=False)
            new_h = [h for h in cur_headers if h != col_name]
            new_r = [{k: v for k, v in row.items() if k != col_name}
                     for row in cur_rows]
            reason = ""
            sp_reasons = stored_payload.get("column_removal_reasons", [])
            if sp_reasons:
                reason = sp_reasons[0].get("reason", "")
            replay_payload = {
                "action": "save_csv",
                "csv_file": csv_file,
                "app_context": app_context,
                "detection_rule": target["detection_rule"],
                "headers": new_h,
                "rows": new_r,
                "comment": stored_payload.get("comment",
                           "Approved column removal"),
                "column_removal_reasons": [
                    {"column": col_name, "reason": reason}
                ],
                "expected_mtime": None,
                "_approval_request_id": request_id,
            }

        elif action_type == "bulk_row_addition":
            # The stored payload contains all rows (existing + new).
            # Identify new rows from the highlight keys and append them
            # to the *current* CSV state (which may have changed since
            # the request was submitted).
            lock_h = hl.get("headers") or [
                h for h in cur_headers if not h.startswith("_")
            ]
            added_keys = hl.get("row_keys", [])
            # Use Counter (not set) so duplicate identical rows are all matched
            added_key_counts = Counter(json.dumps(rk) for rk in added_keys)

            # Extract added rows from stored payload by matching keys.
            # Iterate in reverse so we pick the new rows appended at the end
            # (same pattern as _compute_diff's added_raw logic).
            stored_rows = stored_payload.get("rows", [])
            new_rows_to_add = []
            for row in reversed(stored_rows):
                key = json.dumps([row.get(h, "") for h in lock_h])
                if added_key_counts.get(key, 0) > 0:
                    new_rows_to_add.append(row)
                    added_key_counts[key] -= 1
            new_rows_to_add.reverse()  # restore original order

            if not new_rows_to_add:
                return self._fail_approval_request(
                    request, queue, target, admin_user,
                    "New rows could not be identified from stored payload",
                    notify=False)

            # Check for duplicates — rows that already exist in current CSV
            cur_key_counts = Counter(
                json.dumps([row.get(h, "") for h in lock_h])
                for row in cur_rows
            )
            dup_count = 0
            for row in new_rows_to_add:
                key = json.dumps([row.get(h, "") for h in lock_h])
                if cur_key_counts.get(key, 0) > 0:
                    dup_count += 1
            if dup_count:
                dup_fail_msg = ("{} of {} rows already exist in CSV. "
                                "CSV was modified since submission.".format(
                                    dup_count, len(new_rows_to_add)))
                return self._fail_approval_request(
                    request, queue, target, admin_user, dup_fail_msg,
                    extra_evt={"duplicate_count": dup_count})

            # Merge headers — use current CSV headers, add any new ones
            # from the stored payload that don't already exist
            merged_headers = list(cur_headers)
            stored_headers = stored_payload.get("headers", [])
            for h in stored_headers:
                if h not in merged_headers:
                    merged_headers.append(h)

            combined_rows = list(cur_rows) + new_rows_to_add
            replay_payload = {
                "action": "save_csv",
                "csv_file": csv_file,
                "app_context": app_context,
                "detection_rule": target["detection_rule"],
                "headers": merged_headers,
                "rows": combined_rows,
                "comment": stored_payload.get("comment",
                           "Approved row addition ({} rows)".format(
                               len(new_rows_to_add))),
                "row_add_reason": stored_payload.get("row_add_reason", ""),
                "expected_mtime": None,
                "_approval_request_id": request_id,
            }

        elif action_type == "csv_import_replace":
            # Use the stored payload as-is (contains replacement data)
            replay_payload = dict(stored_payload)
            replay_payload["expected_mtime"] = None
            replay_payload["_approval_request_id"] = request_id

        elif action_type == "bulk_row_edit":
            edit_col = stored_payload.get("bulk_edit_column", "")
            edit_val = stored_payload.get("bulk_edit_value", "")

            # Inline multi-row edits don't have a bulk_edit_column — they
            # store the full modified rows.  Replay as a full save_csv.
            if not edit_col and stored_payload.get("rows"):
                replay_payload = dict(stored_payload)
                replay_payload["_from_approval"] = True
                replay_payload["_approval_request_id"] = request_id
                replay_payload["_bulk_edit_count"] = stored_payload.get(
                    "_bulk_edit_count", 0)
                result = self._save_csv(
                    request, replay_payload, target["analyst"],
                    _from_approval=True)
                resp_body = json.loads(result.get("payload", "{}"))
                if resp_body.get("error"):
                    target["status"] = "failed"
                    target["resolved_by"] = admin_user
                    target["resolved_at"] = now
                    target["rejection_reason"] = resp_body["error"]
                    _write_approval_queue(queue)
                    return result

                # Fix counter: the diff at replay time may misclassify
                # edits as adds due to similarity drift.  Use the
                # submitted edit count (what the analyst actually did)
                # to correct the usage counters.
                submitted_count = stored_payload.get(
                    "_bulk_edit_count", 0)
                if submitted_count:
                    replay_diff = resp_body.get("diff", {})
                    drift_adds = replay_diff.get("added_count", 0)
                    drift_edits = replay_diff.get("edited_count", 0)
                    # If diff split edits into adds+edits, correct it:
                    # undo the wrong counters and set the right one
                    if drift_adds > 0 and (drift_adds + drift_edits) > 0:
                        analyst = target["analyst"]
                        # Undo the misclassified add counter
                        _increment_daily_limit(
                            analyst, "row_addition",
                            count=-drift_adds)
                        # Undo the partial edit counter
                        if drift_edits > 0:
                            _increment_daily_limit(
                                analyst, "bulk_row_edit",
                                count=-drift_edits)
                        # Set the correct total as bulk_row_edit
                        _increment_daily_limit(
                            analyst, "bulk_row_edit",
                            count=submitted_count)

                target["status"] = "approved"
                target["resolved_by"] = admin_user
                target["resolved_at"] = now
                target["admin_comment"] = admin_comment if admin_comment \
                    else "Approved"
                _write_approval_queue(queue)
                _add_notification(
                    target["analyst"], "approved",
                    "Your {} request was approved by {}".format(
                        action_type.replace("_", " "), admin_user),
                    request_id,
                    extra={"action_type": action_type,
                           "detection_rule": target.get("detection_rule", ""),
                           "csv_file": csv_file})
                self._index_audit(request, {
                    "timestamp": now, "analyst": admin_user,
                    "action": "request_approved", "status": "approved",
                    "detection_rule": target.get("detection_rule", ""),
                    "csv_file": csv_file,
                    "request_id": request_id,
                    "requester": target["analyst"],
                    "approval_action_type": action_type,
                    "edited_row_count": submitted_count or
                        resp_body.get("diff", {}).get("edited_count", 0),
                    "comment": "{} approved inline multi-edit by {}".format(
                        admin_user, target["analyst"]),
                })
                return result

            lock_h = hl.get("headers") or [
                h for h in cur_headers if not h.startswith("_")
            ]
            row_keys = hl.get("row_keys", [])
            # Use Counter (not set) so duplicate identical rows are all matched
            locked_counts = Counter(json.dumps(rk) for rk in row_keys)

            if edit_col not in cur_headers:
                return self._fail_approval_request(
                    request, queue, target, admin_user,
                    "Column '{}' no longer exists".format(edit_col),
                    notify=False)

            # Apply edit to matching rows
            edited_count = 0
            new_rows = []
            for row in cur_rows:
                key = json.dumps([row.get(h, "") for h in lock_h])
                if locked_counts.get(key, 0) > 0:
                    row = dict(row)
                    row[edit_col] = edit_val
                    edited_count += 1
                    locked_counts[key] -= 1
                new_rows.append(row)

            edit_requested = len(row_keys)
            if edited_count < edit_requested:
                edit_fail_msg = ("Only {} of {} target rows still match in "
                                 "CSV. CSV was modified since submission."
                                 .format(edited_count, edit_requested)
                                 if edited_count > 0
                                 else "Target rows no longer found in CSV")
                return self._fail_approval_request(
                    request, queue, target, admin_user, edit_fail_msg,
                    extra_evt={"requested_count": edit_requested,
                               "actual_count": edited_count})

            replay_payload = {
                "action": "save_csv",
                "csv_file": csv_file,
                "app_context": app_context,
                "detection_rule": target["detection_rule"],
                "headers": cur_headers,
                "rows": new_rows,
                "comment": "Approved bulk edit ({} rows, column '{}')".format(
                    edited_count, edit_col),
                "expected_mtime": None,
                "_approval_request_id": request_id,
                "_bulk_edit_count": edited_count,
            }

        elif action_type == "revert":
            # Reverts use _revert_csv() directly (not _save_csv), so we
            # handle the full approve/fail flow here and return early.
            revert_payload = {
                "csv_file": csv_file,
                "app_context": app_context,
                "detection_rule": target["detection_rule"],
                "version_filename": stored_payload.get("version_filename", ""),
                "version_display": stored_payload.get("version_display", ""),
                "revert_reason": stored_payload.get("revert_reason", ""),
                "expected_mtime": None,   # skip optimistic lock on replay
            }

            result = self._revert_csv(
                request, revert_payload, original_analyst,
                _from_approval=True
            )

            result_body = json.loads(result.get("payload", "{}"))
            if result.get("status", 500) >= 400:
                fail_reason = result_body.get("error", "Unknown error")
                target["status"] = "failed"
                target["resolved_by"] = admin_user
                target["resolved_at"] = now
                target["rejection_reason"] = "Execution failed: " + fail_reason
                _write_approval_queue(queue)
                _failed_evt = {
                    "timestamp": now, "analyst": admin_user,
                    "action": "request_failed", "status": "failed",
                    "detection_rule": target["detection_rule"],
                    "csv_file": csv_file, "app_context": app_context,
                    "request_id": request_id,
                    "requester": target["analyst"],
                    "approval_action_type": action_type,
                    "failure_reason": "Execution failed: " + fail_reason,
                    "comment": "{} failed to execute revert request created by {}".format(
                        admin_user, target["analyst"]),
                }
                _failed_evt.update(self._extract_request_reasons(
                    action_type, stored_payload))
                self._index_audit(request, _failed_evt)
                return self._resp(result["status"], {
                    "error": "Approval execution failed: " + fail_reason,
                    "request_id": request_id,
                })

            # Mark as approved
            target["status"] = "approved"
            target["resolved_by"] = admin_user
            target["resolved_at"] = now
            target["admin_comment"] = admin_comment if admin_comment else "Approved"
            _write_approval_queue(queue)

            self._index_audit(request, {
                "timestamp": now, "analyst": admin_user,
                "action": "request_approved", "status": "approved",
                "detection_rule": target["detection_rule"],
                "csv_file": csv_file, "app_context": app_context,
                "request_id": request_id,
                "requester": target["analyst"],
                "approval_action_type": action_type,
                "comment": "{} approved revert request created by {}".format(
                    admin_user, target["analyst"]),
            })

            _add_notification(
                target["analyst"], "approved",
                "Your revert request was approved by {}".format(admin_user),
                request_id,
                {"csv_file": target["csv_file"],
                 "detection_rule": target["detection_rule"],
                 "action_type": action_type})

            return self._resp(200, {
                "message": "Revert request approved and executed.",
                "request_id": request_id,
                "diff": result_body.get("diff", {}),
            })

        elif action_type in ("create_csv", "create_rule",
                             "remove_csv", "remove_rule"):
            # Create/delete actions: delegate to wl_replay (Layer 5).
            session_key = request.get("system_authtoken", "") or \
                request.get("session", {}).get("authtoken", "")
            replay_context = {
                "original_analyst": original_analyst,
                "approving_admin": admin_user,
                "request_id": request_id,
                "action_type": action_type,
                "session_key": session_key,
                "approved_at": now,
                "is_dual_admin": False,
            }
            replay_item = dict(target)
            replay_item["payload"] = stored_payload

            replay_result = execute_approved_action(replay_context, replay_item)

            if not replay_result.get("success"):
                fail_reason = replay_result.get("error", "Unknown error")
                return self._fail_approval_request(
                    request, queue, target, admin_user,
                    "Execution failed: " + fail_reason)

            # Mark as approved
            target["status"] = "approved"
            target["resolved_by"] = admin_user
            target["resolved_at"] = now
            target["admin_comment"] = admin_comment if admin_comment else "Approved"
            _write_approval_queue(queue)

            self._index_audit(request, {
                "timestamp": now, "analyst": admin_user,
                "action": "request_approved", "status": "approved",
                "detection_rule": target["detection_rule"],
                "csv_file": csv_file, "app_context": app_context,
                "request_id": request_id,
                "requester": target["analyst"],
                "approval_action_type": action_type,
                "comment": "{} approved {} request by {}".format(
                    admin_user, action_type.replace("_", " "),
                    target["analyst"]),
            })

            _add_notification(
                target["analyst"], "approved",
                "Your {} request was approved by {}".format(
                    action_type.replace("_", " "), admin_user),
                request_id,
                {"csv_file": target["csv_file"],
                 "detection_rule": target["detection_rule"],
                 "action_type": action_type})

            # Auto-cancel conflicting pending requests
            if action_type in ("remove_rule", "remove_csv"):
                _cancel_conflicting_requests(
                    queue, target["detection_rule"],
                    csv_file if action_type == "remove_csv" else "",
                    action_type, request_id,
                    lambda evt: self._index_audit(request, evt))

            return self._resp(200, {
                "message": "{} request approved and executed.".format(
                    action_type.replace("_", " ").title()),
                "request_id": request_id,
            })

        else:
            target["status"] = "failed"
            target["resolved_by"] = admin_user
            target["resolved_at"] = now
            target["rejection_reason"] = "Unknown action type"
            _write_approval_queue(queue)
            _failed_evt = {
                "timestamp": now, "analyst": admin_user,
                "action": "request_failed", "status": "failed",
                "detection_rule": target["detection_rule"],
                "csv_file": target["csv_file"],
                "app_context": target["app_context"],
                "request_id": request_id,
                "requester": target["analyst"],
                "approval_action_type": action_type,
                "failure_reason": "Unknown action type: " + action_type,
                "comment": "{} failed to approve request created by {}".format(
                    admin_user, target["analyst"]),
            }
            _failed_evt.update(self._extract_request_reasons(
                action_type, stored_payload))
            self._index_audit(request, _failed_evt)
            return self._resp(400, {
                "error": "Unknown approval action type: " + action_type})

        result = self._save_csv(
            request, replay_payload, original_analyst, _from_approval=True
        )

        result_body = json.loads(result.get("payload", "{}"))
        if result.get("status", 500) >= 400:
            fail_reason = result_body.get("error", "Unknown error")
            target["status"] = "failed"
            target["resolved_by"] = admin_user
            target["resolved_at"] = now
            target["rejection_reason"] = "Execution failed: " + fail_reason
            _write_approval_queue(queue)
            _failed_evt = {
                "timestamp": now, "analyst": admin_user,
                "action": "request_failed", "status": "failed",
                "detection_rule": target["detection_rule"],
                "csv_file": target["csv_file"],
                "app_context": target["app_context"],
                "request_id": request_id,
                "requester": target["analyst"],
                "approval_action_type": target["action_type"],
                "failure_reason": "Execution failed: " + fail_reason,
                "comment": "{} failed to execute {} request created by {}".format(
                    admin_user, target["action_type"].replace("_", " "),
                    target["analyst"]),
            }
            _failed_evt.update(self._extract_request_reasons(
                target["action_type"], stored_payload))
            self._index_audit(request, _failed_evt)
            return self._resp(result["status"], {
                "error": "Approval execution failed: " + fail_reason,
                "request_id": request_id,
            })

        # Mark as approved
        target["status"] = "approved"
        target["resolved_by"] = admin_user
        target["resolved_at"] = now
        target["admin_comment"] = admin_comment if admin_comment else "Approved"
        _write_approval_queue(queue)

        evt = {
            "timestamp": now,
            "analyst": admin_user,
            "action": "request_approved",
            "status": "approved",
            "detection_rule": target["detection_rule"],
            "csv_file": target["csv_file"],
            "app_context": target["app_context"],
            "request_id": request_id,
            "requester": target["analyst"],
            "approval_action_type": target["action_type"],
            "comment": "{} approved {} request created by {}".format(
                admin_user, target["action_type"].replace("_", " "),
                target["analyst"]),
        }
        evt.update(self._extract_request_reasons(
            target["action_type"], target.get("payload", {})))
        self._index_audit(request, evt)

        # Notify analyst about approval
        _add_notification(
            target["analyst"], "approved",
            "Your {} request was approved by {}".format(
                target["action_type"].replace("_", " "), admin_user),
            request_id,
            {"csv_file": target["csv_file"],
             "detection_rule": target["detection_rule"],
             "action_type": target["action_type"]})

        return self._resp(200, {
            "message": "Request approved and executed.",
            "request_id": request_id,
            "diff": result_body.get("diff", {}),
        })

    def _check_approval_gate(self, request, payload, user):
        """Check if an action requires approval based on thresholds."""
        action_type = payload.get("gate_action", "")
        csv_file = payload.get("csv_file", "")
        app_context = payload.get("app_context", "")

        requires_approval = False
        reason = ""

        if action_type == "csv_import_replace":
            requires_approval = True
            reason = "CSV import (Replace mode) always requires approval"

        elif action_type == "bulk_row_removal":
            selected_count = payload.get("selected_count", 0)
            if isinstance(selected_count, (int, float)):
                selected_count = int(selected_count)
            else:
                selected_count = 0
            if selected_count >= _get_threshold("bulk_row_removal_threshold"):
                requires_approval = True
                reason = "Removing {} rows (threshold: {})".format(
                    selected_count, _get_threshold("bulk_row_removal_threshold"))

        elif action_type == "column_removal":
            col_name = payload.get("column_name", "")
            path = resolve_csv_path(csv_file, app_context)
            if path is None:
                fallback = os.path.join(OWN_LOOKUPS, csv_file)
                if os.path.isfile(fallback) and safe_realpath(fallback, APPS_DIR):
                    path = safe_realpath(fallback, APPS_DIR)
            if path is None:
                return self._resp(404, {"error": "CSV file not found"})
            headers, rows = read_csv(path)
            total_rows = len(rows)
            nonempty = _count_nonempty_cells(rows, col_name)
            if nonempty >= _get_threshold("column_nonempty_threshold"):
                requires_approval = True
                reason = (
                    "Column '{}' has {} non-empty cells "
                    "(threshold: {} non-empty)"
                    .format(col_name, nonempty,
                            _get_threshold("column_nonempty_threshold"))
                )

        elif action_type == "bulk_row_edit":
            selected_count = payload.get("selected_count", 0)
            if isinstance(selected_count, (int, float)):
                selected_count = int(selected_count)
            else:
                selected_count = 0
            if selected_count >= _get_threshold("bulk_row_edit_threshold"):
                requires_approval = True
                reason = "Bulk editing {} rows (threshold: {})".format(
                    selected_count, _get_threshold("bulk_row_edit_threshold"))

        elif action_type == "bulk_row_addition":
            selected_count = payload.get("selected_count", 0)
            if isinstance(selected_count, (int, float)):
                selected_count = int(selected_count)
            else:
                selected_count = 0
            if selected_count >= _get_threshold("bulk_row_addition_threshold"):
                requires_approval = True
                reason = "Adding {} rows (threshold: {})".format(
                    selected_count, _get_threshold("bulk_row_addition_threshold"))

        elif action_type == "revert":
            total_changes = payload.get("total_row_changes", 0)
            if isinstance(total_changes, (int, float)):
                total_changes = int(total_changes)
            else:
                total_changes = 0
            total_col_changes = payload.get("total_col_changes", 0)
            if isinstance(total_col_changes, (int, float)):
                total_col_changes = int(total_col_changes)
            else:
                total_col_changes = 0
            row_thresh = _get_threshold("revert_row_threshold")
            col_thresh = _get_threshold("revert_column_threshold")
            parts = []
            if total_changes >= row_thresh:
                parts.append("{} rows (threshold: {})".format(
                    total_changes, row_thresh))
            if total_col_changes >= col_thresh:
                parts.append("{} columns (threshold: {})".format(
                    total_col_changes, col_thresh))
            if parts:
                requires_approval = True
                reason = "Revert would change {}".format(" and ".join(parts))

        # Also check daily limits for non-gated actions
        daily_limit_info = None
        if not requires_approval:
            limit_type = None
            limit_count = 1
            if action_type == "bulk_row_removal":
                limit_type = "bulk_row_removal" if selected_count >= 2 else "row_removal"
                limit_count = max(selected_count, 1)
            elif action_type == "column_removal":
                limit_type = "column_removal"
            elif action_type == "bulk_row_addition":
                limit_type = "row_addition"
                limit_count = max(selected_count, 1)
            elif action_type == "revert":
                limit_type = "revert"
            elif action_type == "bulk_row_edit":
                limit_type = "bulk_row_edit"
                limit_count = max(selected_count, 1)
            elif action_type == "inline_row_edit":
                limit_type = "row_edit"

            if limit_type:
                allowed, current, maximum = _check_daily_limit(
                    user, limit_type, action_count=limit_count)
                over = current + limit_count - maximum
                daily_limit_info = {
                    "allowed": allowed,
                    "current": current,
                    "maximum": maximum,
                    "limit_type": limit_type,
                    "action_count": limit_count,
                    "exceeded_by": max(over, 0),
                    "disabled": maximum == 0,
                }

        return self._resp(200, {
            "requires_approval": requires_approval,
            "reason": reason,
            "daily_limit": daily_limit_info,
        })

    def _get_approval_queue_action(self):
        """Return the full approval queue for the Control Panel."""
        queue = _expire_pending_approvals()
        sorted_queue = sorted(
            queue, key=lambda x: x.get("timestamp", 0), reverse=True
        )
        return self._resp(200, {"queue": sorted_queue})

    def _get_daily_limits_action(self):
        """Return current daily limit configuration."""
        config = _read_limit_config()
        history = config.pop("change_history", [])
        custom_defaults = config.pop("custom_defaults", None)
        return self._resp(200, {
            "limits": config,
            "defaults": dict(DEFAULT_LIMITS),
            "custom_defaults": custom_defaults,
            "change_history": history,
        })

    def _set_daily_limits_action(self, request, payload, user):
        """Update daily limit configuration with change tracking."""
        new_limits = payload.get("limits", {})
        config = _read_limit_config()

        LIMIT_KEYS = (
            "row_removal", "bulk_row_removal", "column_removal",
            "column_addition", "row_edit", "bulk_row_edit",
            "row_addition", "row_reorder", "column_reorder", "revert",
            "bulk_row_removal_threshold", "bulk_row_edit_threshold",
            "bulk_row_addition_threshold", "column_nonempty_threshold",
            "revert_row_threshold", "revert_column_threshold",
        )
        BOOL_KEYS = (
            "allow_analyst_create_rules", "allow_analyst_create_csv",
            "allow_analyst_delete_rules", "allow_analyst_delete_csv",
            "require_reason_rule_creation", "require_reason_csv_creation",
            "require_reason_rule_deletion", "require_reason_csv_deletion",
        )

        VALID_FREQUENCIES = ("never", "daily", "weekly", "monthly", "yearly")

        # Snapshot old values for diff comparison
        old_values = {}
        for key in LIMIT_KEYS:
            old_values[key] = config.get(key, DEFAULT_LIMITS.get(key, 0))
        for key in BOOL_KEYS:
            old_values[key] = config.get(key, DEFAULT_LIMITS.get(key, False))
        old_values["reset_time_utc"] = config.get(
            "reset_time_utc", DEFAULT_LIMITS.get("reset_time_utc", "00:00"))
        old_values["reset_frequency"] = config.get(
            "reset_frequency", DEFAULT_LIMITS.get("reset_frequency", "daily"))
        SCHEDULE_INT_KEYS = {
            "reset_day_of_week": (0, 6),
            "reset_day_of_month": (1, 31),
            "reset_month": (1, 12),
            "reset_day_of_year": (1, 31),
        }
        for key, (lo, hi) in SCHEDULE_INT_KEYS.items():
            old_values[key] = config.get(key, DEFAULT_LIMITS.get(key, lo))

        # Apply changes
        for key in LIMIT_KEYS:
            if key in new_limits:
                val = new_limits[key]
                if isinstance(val, int) and 0 <= val <= 100:
                    config[key] = val
        for key in BOOL_KEYS:
            if key in new_limits:
                config[key] = bool(new_limits[key])
        if "reset_time_utc" in new_limits:
            val = new_limits["reset_time_utc"]
            if isinstance(val, str) and len(val) == 5 and val[2] == ':':
                try:
                    hh, mm = int(val[:2]), int(val[3:])
                    if 0 <= hh <= 23 and 0 <= mm <= 59:
                        config["reset_time_utc"] = val
                except (ValueError, IndexError):
                    pass
        if "reset_frequency" in new_limits:
            val = new_limits["reset_frequency"]
            if val in VALID_FREQUENCIES:
                config["reset_frequency"] = val
        for key, (lo, hi) in SCHEDULE_INT_KEYS.items():
            if key in new_limits:
                val = new_limits[key]
                if isinstance(val, int) and lo <= val <= hi:
                    config[key] = val

        # Compute diff
        changes = []
        all_tracked = (list(LIMIT_KEYS) + list(BOOL_KEYS)
                       + ["reset_time_utc", "reset_frequency"]
                       + list(SCHEDULE_INT_KEYS.keys()))
        for key in all_tracked:
            old_val = old_values.get(key, 0)
            new_val = config.get(key, old_val)
            if old_val != new_val:
                changes.append({"key": key, "old": old_val, "new": new_val})

        history = config.get("change_history", [])

        if not changes:
            clean = {k: v for k, v in config.items()
                     if k not in ("change_history", "custom_defaults")}
            return self._resp(200, {
                "message": "No changes",
                "no_changes": True,
                "limits": clean,
                "change_history": history,
            })

        # Record change history entry (newest first, max 10)
        entry = {
            "timestamp": datetime.now(timezone.utc).strftime(
                "%Y-%m-%d %H:%M:%S UTC"),
            "admin": user,
            "changes": changes,
        }
        history.insert(0, entry)
        if len(history) > 10:
            history = history[:10]
        config["change_history"] = history

        _write_limit_config(config)

        # Write audit event to wl_audit index
        value_lines = []
        for c in changes:
            value_lines.append("{}: {} -> {}".format(
                c["key"], c["old"], c["new"]))
        evt = {
            "action": "limit_change",
            "timestamp": int(time.time()),
            "analyst": user,
            "change_count": len(changes),
            "value": value_lines,
        }
        self._index_audit(request, evt)

        clean = {k: v for k, v in config.items()
                 if k not in ("change_history", "custom_defaults")}
        return self._resp(200, {
            "message": "Limits changed",
            "limits": clean,
            "change_history": history,
        })

    def _reset_daily_limits_action(self, request, user):
        """Reset limits to custom defaults (or factory if no custom set)."""
        config = _read_limit_config()
        custom = config.get("custom_defaults", None)
        target = custom if custom else dict(DEFAULT_LIMITS)
        label = "custom defaults" if custom else "factory defaults"

        ALL_KEYS = list(DEFAULT_LIMITS.keys())

        old_values = {}
        for key in ALL_KEYS:
            old_values[key] = config.get(key, DEFAULT_LIMITS.get(key, 0))

        changes = []
        for key in ALL_KEYS:
            old_val = old_values[key]
            new_val = target.get(key, DEFAULT_LIMITS.get(key, 0))
            if old_val != new_val:
                changes.append({"key": key, "old": old_val, "new": new_val})

        history = config.get("change_history", [])

        if not changes:
            clean = {k: v for k, v in target.items()
                     if k in DEFAULT_LIMITS}
            return self._resp(200, {
                "message": "Limits are already at " + label,
                "no_changes": True,
                "limits": clean,
                "change_history": history,
            })

        new_config = dict(target)
        entry = {
            "timestamp": datetime.now(timezone.utc).strftime(
                "%Y-%m-%d %H:%M:%S UTC"),
            "admin": user,
            "changes": changes,
            "reset": True,
        }
        history.insert(0, entry)
        if len(history) > 10:
            history = history[:10]
        new_config["change_history"] = history
        # Preserve custom_defaults and any non-limit keys
        if custom:
            new_config["custom_defaults"] = custom

        _write_limit_config(new_config)

        value_lines = ["{}: {} -> {}".format(c["key"], c["old"], c["new"])
                       for c in changes]
        self._index_audit(request, {
            "action": "limit_reset",
            "timestamp": int(time.time()),
            "analyst": user,
            "change_count": len(changes),
            "reset_target": label,
            "value": value_lines,
        })

        clean = {k: v for k, v in new_config.items()
                 if k != "change_history" and k != "custom_defaults"}
        return self._resp(200, {
            "message": "Limits reset to " + label,
            "limits": clean,
            "change_history": history,
        })

    def _save_as_default_action(self, request, user):
        """Save current limits as custom defaults."""
        config = _read_limit_config()
        history = config.get("change_history", [])

        # Extract only limit keys (no metadata)
        snapshot = {}
        for key in DEFAULT_LIMITS:
            snapshot[key] = config.get(key, DEFAULT_LIMITS[key])

        # If snapshot matches factory defaults, clear custom defaults
        # instead of storing a redundant copy.
        if snapshot == dict(DEFAULT_LIMITS):
            config.pop("custom_defaults", None)
            _write_limit_config(config)
            clean = {k: v for k, v in config.items()
                     if k not in ("change_history", "custom_defaults")}
            return self._resp(200, {
                "message": "Current limits match factory defaults — "
                           "custom defaults cleared",
                "limits": clean,
                "custom_defaults": None,
                "change_history": history,
            })

        config["custom_defaults"] = snapshot
        _write_limit_config(config)

        self._index_audit(request, {
            "action": "limit_defaults_saved",
            "timestamp": int(time.time()),
            "analyst": user,
        })

        clean = {k: v for k, v in config.items()
                 if k not in ("change_history", "custom_defaults")}
        return self._resp(200, {
            "message": "Current limits saved as custom defaults",
            "limits": clean,
            "custom_defaults": snapshot,
            "change_history": history,
        })

    def _reset_factory_defaults_action(self, request, user):
        """Reset to hardcoded factory defaults and clear custom defaults."""
        config = _read_limit_config()
        ALL_KEYS = list(DEFAULT_LIMITS.keys())

        old_values = {}
        for key in ALL_KEYS:
            old_values[key] = config.get(key, DEFAULT_LIMITS.get(key, 0))

        changes = []
        for key in ALL_KEYS:
            old_val = old_values[key]
            new_val = DEFAULT_LIMITS[key]
            if old_val != new_val:
                changes.append({"key": key, "old": old_val, "new": new_val})

        history = config.get("change_history", [])
        had_custom = "custom_defaults" in config

        if not changes and not had_custom:
            return self._resp(200, {
                "message": "Already at factory defaults",
                "no_changes": True,
                "limits": dict(DEFAULT_LIMITS),
                "change_history": history,
            })

        new_config = dict(DEFAULT_LIMITS)
        # Do NOT copy custom_defaults — clearing them
        if changes:
            entry = {
                "timestamp": datetime.now(timezone.utc).strftime(
                    "%Y-%m-%d %H:%M:%S UTC"),
                "admin": user,
                "changes": changes,
                "reset": True,
                "factory": True,
            }
            history.insert(0, entry)
            if len(history) > 10:
                history = history[:10]
        new_config["change_history"] = history

        _write_limit_config(new_config)

        value_lines = ["{}: {} -> {}".format(c["key"], c["old"], c["new"])
                       for c in changes]
        evt = {
            "action": "limit_factory_reset",
            "timestamp": int(time.time()),
            "analyst": user,
            "change_count": len(changes),
            "cleared_custom_defaults": had_custom,
            "value": value_lines,
        }
        self._index_audit(request, evt)

        return self._resp(200, {
            "message": "Reset to factory defaults"
                       + (" and custom defaults cleared" if had_custom else ""),
            "limits": dict(DEFAULT_LIMITS),
            "custom_defaults": None,
            "change_history": history,
        })

    def _get_analyst_usage_action(self, payload):
        """Return daily usage for all analysts or a specific one."""
        analyst = payload.get("analyst", "")
        counters = _read_daily_limits()
        today = _get_counter_period_key()
        today_data = counters.get(today, {})

        # Include current limits so frontend can show limit-reached badges
        config = _read_limit_config()
        limits = {k: v for k, v in config.items()
                  if k not in ("change_history", "custom_defaults")}

        if analyst:
            return self._resp(200, {
                "date": today,
                "analyst": analyst,
                "usage": today_data.get(analyst, {}),
                "limits": limits,
            })

        # Cap response to MAX_TRACKED_ANALYSTS entries (sorted by name)
        if len(today_data) > MAX_TRACKED_ANALYSTS:
            keys = sorted(today_data.keys())[:MAX_TRACKED_ANALYSTS]
            today_data = {k: today_data[k] for k in keys}

        return self._resp(200, {
            "date": today,
            "all_analysts": today_data,
            "limits": limits,
        })

    def _reset_daily_usage_action(self, payload, admin_user):
        """Reset daily usage counters for a specific analyst or all analysts.

        Self-reset is blocked: admins cannot reset their own counters.
        Only other admins or superadmins can reset a given user's usage.
        """
        analyst = payload.get("analyst", "")
        counters = _read_daily_limits()
        today = _get_counter_period_key()

        if today not in counters:
            return self._resp(200, {"message": "No usage to reset."})

        if analyst and analyst != "all":
            # Block self-reset — defense in depth against insider threat
            if analyst == admin_user:
                return self._resp(200, {
                    "error": "Cannot reset your own daily usage. "
                             "Ask another admin or superadmin."
                })
            if analyst in counters[today]:
                del counters[today][analyst]
                _write_daily_limits(counters)
                return self._resp(200, {
                    "message": "Daily usage reset for " + analyst
                })
            return self._resp(200, {
                "message": "No usage found for " + analyst
            })

        # Reset all — exclude the caller's own counters
        own_counts = counters[today].pop(admin_user, None)
        counters[today] = {}
        if own_counts:
            counters[today][admin_user] = own_counts
        _write_daily_limits(counters)
        return self._resp(200, {
            "message": "Daily usage reset for all analysts"
                       + (" (your own usage was preserved)" if own_counts else "")
        })

    def _check_daily_limit_status(self, user):
        """Return the current user's remaining daily limits."""
        config = _read_limit_config()
        counters = _read_daily_limits()
        today = _get_counter_period_key()
        user_counts = counters.get(today, {}).get(user, {})

        result = {}
        for action_type in ("row_removal", "bulk_row_removal",
                            "column_removal", "column_addition",
                            "row_edit", "bulk_row_edit",
                            "row_addition", "row_reorder",
                            "column_reorder", "revert"):
            maximum = config.get(action_type,
                                 DEFAULT_LIMITS.get(action_type, 999))
            current = user_counts.get(action_type, 0)
            result[action_type] = {
                "current": current,
                "maximum": maximum,
                "remaining": max(0, maximum - current),
            }
        return self._resp(200, {
            "user": user,
            "date": today,
            "limits": result,
        })

    # ------------------------------------------------------------------
    # Log frontend-originated events (export / import)
    # ------------------------------------------------------------------
    def _log_event(self, request, payload):
        """Log a frontend-originated audit event (export/import)."""
        allowed_actions = {"audit_exported", "csv_exported", "csv_imported"}
        event_action = payload.get("event_action", "")
        if event_action not in allowed_actions:
            return self._resp(400, {"error": "Invalid event action"})

        user = get_user(request)
        ts = int(time.time())

        evt = {
            "timestamp":      ts,
            "analyst":        user,
            "action":         event_action,
            "detection_rule": sanitize_text(
                payload.get("detection_rule", "")),
            "csv_file":       sanitize_text(
                payload.get("csv_file", "")),
            "app_context":    sanitize_text(
                payload.get("app_context", "")),
            "status":         sanitize_text(
                payload.get("status", "success")),
            "export_file":    sanitize_text(
                payload.get("export_file", "")),
            "comment":        sanitize_text(
                payload.get("comment", "")),
        }

        if event_action == "audit_exported":
            evt["event_count"] = payload.get("event_count", 0)
        elif event_action == "csv_exported":
            evt["row_count"] = payload.get("row_count", 0)
        elif event_action == "csv_imported":
            evt["row_count_before"] = payload.get("row_count_before", 0)
            evt["row_count_after"] = payload.get("row_count_after", 0)
            evt["header_count"] = payload.get("header_count", 0)
            evt["imported_row_count"] = payload.get("imported_row_count", 0)
            evt["import_mode"] = payload.get("import_mode", "")

        self._index_audit(request, evt)
        return self._resp(200, {"status": "ok"})

    # ------------------------------------------------------------------
    # Write audit event into the wl_audit Splunk index
    # ------------------------------------------------------------------
    def _index_audit(self, request, event):
        """Write an audit event into the wl_audit Splunk index.

        Delegates to wl_audit.post_audit_event() to avoid duplicating HTTP logic.
        """
        # Use system auth token (from passSystemAuth in restmap.conf)
        # so non-admin users can still write audit events
        session_key = request.get("system_authtoken", "") or \
            request.get("session", {}).get("authtoken", "")
        if not session_key:
            return

        # post_audit_event handles truncation, serialization, HTTP posting, and errors
        success, error = post_audit_event(session_key, event)
        if not success:
            _logger.error("_index_audit error: %s", error)

    # ==================================================================
    # Internal helpers
    # ==================================================================
    def _lookup_rule_for_csv(self, csv_file):
        """Look up the detection_rule name for a given csv_file from the mapping."""
        mapping = self._read_mapping()
        for entry in mapping:
            if entry.get("csv_file") == csv_file:
                return entry.get("rule_name", "")
        return ""

    def _read_mapping(self):
        if not os.path.isfile(MAPPING_FILE):
            return []
        with open(MAPPING_FILE, "r", newline="", encoding="utf-8-sig") as fh:
            return list(csv.DictReader(fh))

    @staticmethod
    def _parse_query(request):
        """Normalize the query params (may arrive as list-of-pairs or dict)."""
        raw = request.get("query", [])
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, list):
            return dict(raw)
        return {}


    @staticmethod
    def _resp(status, body):
        return {
            "status": status,
            "headers": {"Content-Type": "application/json"},
            "payload": json.dumps(body, default=str),
        }
