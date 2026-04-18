"""
Whitelist Manager — Layer 0: Configuration Constants & Path Helpers.

This module serves as the foundational layer for all other wl_manager modules.
It contains all magic numbers, regex patterns, role definitions, file paths, and
configuration values — ensuring a single source of truth for application configuration.

CRITICAL: This module has NO imports from wl_* modules (zero dependencies on other
wl_manager layers). It only uses Python stdlib (os, re, json).

This enables all other modules to import from wl_constants safely without risk of
circular dependencies.
"""

import os
import re
from typing import Set


__all__ = [
    # Functions
    'get_splunk_home',
    'get_detection_rules_path',
    'get_approval_queue_path',
    # App metadata
    'APP_NAME',
    # Path constants (computed at import time)
    'SPLUNK_HOME',
    'APPS_DIR',
    'OWN_LOOKUPS',
    'MAPPING_FILE',
    'APPROVAL_QUEUE_FILE',
    'TRASH_DIR',
    'TRASH_CONFIG_FILE',
    'DETECTION_RULES_FILE',
    'DAILY_LIMITS_FILE',
    'LIMIT_CONFIG_FILE',
    'NOTIFICATION_FILE',
    'VERSIONS_DIR',
    'AUDIT_LOG',
    # Limits: CSV operations
    'MAX_ROWS',
    'MAX_COLUMNS',
    'MAX_CELL_CHARS',
    'MAX_PAYLOAD_BYTES',
    'MAX_AUDIT_VALUE_LINES',
    'MAX_DIFF_ROWS',
    # Limits: Presence tracking
    'MAX_PRESENCE_USERS',
    'MAX_PRESENCE_FILES',
    # Timeouts
    'PRESENCE_TIMEOUT',
    'IDLE_TIMEOUT',
    # Rate limiting
    'RATE_WINDOW',
    'RATE_MAX_WRITES',
    'RATE_MAX_READS',
    # Audit constants
    'AUDIT_INDEX',
    'AUDIT_SOURCE',
    'AUDIT_SOURCETYPE',
    # Version control
    'MAX_VERSIONS',
    # Column names
    'EXPIRE_COLUMN_NAMES',
    # Role definitions
    'EDIT_ROLES',
    'ADMIN_ROLES',
    'SUPERADMIN_ROLES',
    'RESET_ALL_USERS',
    # Trash management
    'MIN_TRASH_RETENTION_DAYS',
    'DEFAULT_TRASH_RETENTION_DAYS',
    # Detection rules
    'MAX_DETECTION_RULES',
    'MAX_CSVS_PER_RULE',
    'MAX_TOTAL_CSV_MAPPINGS',
    # Approval queue
    'APPROVAL_EXPIRY_DAYS',
    'MAX_PENDING_REQUESTS',
    'MAX_RESOLVED_HISTORY',
    'MAX_TRACKED_ANALYSTS',
    # Notifications
    'MAX_NOTIFICATIONS_PER_USER',
    'NOTIFICATION_MAX_AGE_DAYS',
    # Default limits configuration
    'DEFAULT_LIMITS',
    'DEFAULT_ADMIN_LIMITS',
    'APPROVAL_BULK_ROW_THRESHOLD',
    'APPROVAL_BULK_EDIT_THRESHOLD',
    'APPROVAL_COLUMN_NONEMPTY_THRESHOLD',
    'APPROVAL_BULK_ADD_THRESHOLD',
    'APPROVAL_REVERT_ROW_THRESHOLD',
    'APPROVAL_REVERT_COLUMN_THRESHOLD',
    # Regex patterns (compiled at module level)
    '_CONTROL_CHAR_RE',
    '_SAFE_COLNAME_RE',
    '_SANITIZE_RE',
    # HMAC salts (single source of truth — imported by handler, migration tool, FIM)
    'COOLDOWN_HMAC_SALT',
    'FIM_HMAC_SALT',
]


# ═══════════════════════════════════════════════════════════════════════════
# Splunk Home & Path Helpers
# ═══════════════════════════════════════════════════════════════════════════

def get_splunk_home() -> str:
    """
    Return the Splunk home directory.

    Reads from SPLUNK_HOME environment variable. If not set, defaults to
    "/opt/splunk" (standard Docker/Linux location).

    Returns:
        str: Absolute path to Splunk home directory.

    Note:
        This function is patchable in tests via monkeypatch.setenv("SPLUNK_HOME", ...).
        Use the returned value to compute derived paths at import time.
    """
    return os.environ.get("SPLUNK_HOME", "/opt/splunk")


def get_detection_rules_path() -> str:
    """
    Return the absolute path to the detection rules registry file.

    This JSON file tracks all detection rules (with or without CSV mappings)
    and is stored in the app's lookups directory.

    Returns:
        str: Absolute path to _detection_rules.json.
    """
    return os.path.join(OWN_LOOKUPS, DETECTION_RULES_FILE)


def get_approval_queue_path() -> str:
    """
    Return the absolute path to the approval queue file.

    This JSON file holds pending, approved, and rejected requests for
    bulk operations, rule creation, and rule deletion.

    Returns:
        str: Absolute path to _approval_queue.json.
    """
    return os.path.join(OWN_LOOKUPS, APPROVAL_QUEUE_FILE)


# ═══════════════════════════════════════════════════════════════════════════
# Eager Derived Path Constants (computed at module import time)
# ═══════════════════════════════════════════════════════════════════════════

APP_NAME: str = "wl_manager"
"""The Splunk app name."""

SPLUNK_HOME: str = get_splunk_home()
"""Root directory of Splunk installation."""

APPS_DIR: str = os.path.join(SPLUNK_HOME, "etc", "apps")
"""Directory containing all Splunk apps."""

OWN_LOOKUPS: str = os.path.join(APPS_DIR, APP_NAME, "lookups")
"""Directory where CSV lookup files and metadata are stored."""

MAPPING_FILE: str = os.path.join(OWN_LOOKUPS, "rule_csv_map.csv")
"""CSV file mapping detection rules to their associated CSV files."""

APPROVAL_QUEUE_FILE: str = "_approval_queue.json"
"""Filename of the approval queue (stored in OWN_LOOKUPS)."""

TRASH_DIR: str = "_trash"
"""Subdirectory within OWN_LOOKUPS for soft-deleted CSVs."""

TRASH_CONFIG_FILE: str = "_trash_config.json"
"""Configuration file for trash retention policy."""

DETECTION_RULES_FILE: str = "_detection_rules.json"
"""JSON file tracking all detection rules in the system."""

DAILY_LIMITS_FILE: str = "_daily_limits.json"
"""JSON file tracking daily usage counts per analyst."""

LIMIT_CONFIG_FILE: str = "_limit_config.json"
"""Configuration file for daily limits and approval thresholds."""

NOTIFICATION_FILE: str = "_notifications.json"
"""JSON file storing notifications for users."""

VERSIONS_DIR: str = "_versions"
"""Subdirectory within OWN_LOOKUPS for CSV version snapshots."""

AUDIT_LOG: str = os.path.join(SPLUNK_HOME, "var", "log", "splunk", "wl_manager_audit.log")
"""Rotating log file for audit events (backup to Splunk indexing)."""


# ═══════════════════════════════════════════════════════════════════════════
# CSV Operation Limits
# ═══════════════════════════════════════════════════════════════════════════

MAX_ROWS: int = 5000
"""Maximum number of rows allowed in a single CSV file."""

MAX_COLUMNS: int = 100
"""Maximum number of columns allowed in a single CSV file."""

MAX_CELL_CHARS: int = 1000
"""Maximum character length for a single cell value."""

MAX_PAYLOAD_BYTES: int = 10 * 1024 * 1024
"""Maximum size (in bytes) of a POST request body (10 MB)."""

MAX_AUDIT_VALUE_LINES: int = 500
"""Maximum number of field lines to include in audit event value arrays."""

MAX_DIFF_ROWS: int = 2000
"""Maximum number of rows to process with O(n²) diff matching algorithm."""


# ═══════════════════════════════════════════════════════════════════════════
# Presence Tracking Limits
# ═══════════════════════════════════════════════════════════════════════════

MAX_PRESENCE_USERS: int = 10
"""Maximum number of concurrent users tracked per CSV file."""

MAX_PRESENCE_FILES: int = 200
"""Maximum number of CSV files with active presence tracking."""

PRESENCE_TIMEOUT: int = 60
"""Seconds before a user is considered absent (closed tab, no heartbeat)."""

IDLE_TIMEOUT: int = 1800
"""Seconds of no activity before a user is marked idle (default 30 minutes)."""


# ═══════════════════════════════════════════════════════════════════════════
# Rate Limiting (per action, per user, per window)
# ═══════════════════════════════════════════════════════════════════════════

RATE_WINDOW: int = 60
"""Time window (seconds) for rate limit calculations."""

RATE_MAX_WRITES: int = 30
"""Maximum POST (write) actions per user per RATE_WINDOW."""

RATE_MAX_READS: int = 120
"""Maximum GET (read) actions per user per RATE_WINDOW."""


# ═══════════════════════════════════════════════════════════════════════════
# Audit Configuration
# ═══════════════════════════════════════════════════════════════════════════

AUDIT_INDEX: str = "wl_audit"
"""Name of the Splunk index where audit events are written."""

AUDIT_SOURCE: str = "wl_manager"
"""Source field value for all audit events."""

AUDIT_SOURCETYPE: str = "wl_audit"
"""Sourcetype field value for all audit events."""


# ═══════════════════════════════════════════════════════════════════════════
# Version Control
# ═══════════════════════════════════════════════════════════════════════════

MAX_VERSIONS: int = 6
"""Maximum number of CSV versions to retain (1 current + 5 previous)."""


# ═══════════════════════════════════════════════════════════════════════════
# Column Names
# ═══════════════════════════════════════════════════════════════════════════

EXPIRE_COLUMN_NAMES: Set[str] = {
    "expires", "expire", "expiration", "expiration_date",
    "expiry", "termination", "termination_date",
}
"""Column names (case-insensitive) that are treated as expiration dates."""


# ═══════════════════════════════════════════════════════════════════════════
# Role Definitions (RBAC)
# ═══════════════════════════════════════════════════════════════════════════

EDIT_ROLES: Set[str] = {
    "wl_editor",          # Legacy analyst editor role
    "wl_analyst_editor",  # Modern analyst editor role
    "wl_admin",           # App-level administrator
    "wl_superadmin",      # System superadministrator
    "admin",              # Splunk built-in admin
    "sc_admin",           # Splunk security manager (Cloud)
}
"""Roles permitted to write (POST) to the API. All authenticated users can read (GET)."""

ADMIN_ROLES: Set[str] = {
    "admin",
    "sc_admin",
    "wl_admin",
    "wl_superadmin",
}
"""Roles permitted to approve/reject requests and access the control panel."""

SUPERADMIN_ROLES: Set[str] = {
    "wl_superadmin",
}
"""Roles permitted to manage system-level limits, trash retention, and configuration."""

RESET_ALL_USERS: str = "__all__"
"""Sentinel constant for reset_daily_limits(analyst=RESET_ALL_USERS) meaning 'reset all analysts'.

Used instead of magic string "all" to prevent sentinel value bugs (e.g., checking `if analyst:`
treats "all" as truthy, then code looks up user named "all" and fails silently).
This named constant makes intent explicit and prevents typos."""


# ═══════════════════════════════════════════════════════════════════════════
# Trash Management
# ═══════════════════════════════════════════════════════════════════════════

MIN_TRASH_RETENTION_DAYS: int = 7
"""Minimum enforced trash retention period (safety floor)."""

DEFAULT_TRASH_RETENTION_DAYS: int = 30
"""Default number of days to retain soft-deleted CSVs before auto-purge."""


# ═══════════════════════════════════════════════════════════════════════════
# Detection Rules
# ═══════════════════════════════════════════════════════════════════════════

MAX_DETECTION_RULES: int = 1000
"""Maximum number of detection rules tracked in the system."""

MAX_CSVS_PER_RULE: int = 20
"""Maximum number of CSV files that can be attached to a single detection rule."""

MAX_TOTAL_CSV_MAPPINGS: int = 5000
"""Maximum total rows in rule_csv_map.csv (across all rules)."""


# ═══════════════════════════════════════════════════════════════════════════
# Approval Queue
# ═══════════════════════════════════════════════════════════════════════════

APPROVAL_EXPIRY_DAYS: int = 30
"""Number of days before a pending approval request auto-expires."""

MAX_PENDING_REQUESTS: int = 20
"""Maximum number of pending approval requests in the queue."""

MAX_RESOLVED_HISTORY: int = 100
"""Maximum number of resolved (approved/rejected) entries to retain in history."""

MAX_TRACKED_ANALYSTS: int = 100
"""Maximum number of analysts tracked in daily usage statistics."""


# ═══════════════════════════════════════════════════════════════════════════
# Notifications
# ═══════════════════════════════════════════════════════════════════════════

MAX_NOTIFICATIONS_PER_USER: int = 20
"""Maximum notifications to store per user."""

NOTIFICATION_MAX_AGE_DAYS: int = 7
"""Maximum age (days) before a notification is auto-deleted."""


# ═══════════════════════════════════════════════════════════════════════════
# Default Daily Limits (per analyst)
# ═══════════════════════════════════════════════════════════════════════════

DEFAULT_LIMITS: dict = {
    # Per-action limits (across all CSVs)
    "row_removal": 10,
    "bulk_row_removal": 10,
    "column_removal": 2,
    "column_addition": 2,
    "row_edit": 10,
    "bulk_row_edit": 10,
    "row_addition": 10,
    "row_reorder": 10,
    "column_reorder": 10,
    "revert": 3,
    # Reset schedule (configurable)
    "reset_frequency": "daily",     # never, daily, weekly, monthly, yearly
    "reset_time_utc": "00:00",      # HH:MM in UTC
    "reset_day_of_week": 0,         # 0=Monday, ..., 6=Sunday (used by weekly)
    "reset_day_of_month": 1,        # 1-31, clamped to last day (used by monthly)
    "reset_month": 1,               # 1-12 (used by yearly)
    "reset_day_of_year": 1,         # 1-366, clamped to last day (used by yearly)
    # Approval gate thresholds (require admin approval when exceeded)
    "bulk_row_removal_threshold": 3,
    "bulk_row_edit_threshold": 3,
    "bulk_row_addition_threshold": 3,
    "column_nonempty_threshold": 5,
    "revert_row_threshold": 5,
    "revert_column_threshold": 3,
    # Analyst creation permissions (toggled from Control Panel)
    "allow_analyst_create_rules": False,
    "allow_analyst_create_csv": False,
    # Analyst deletion permissions (toggled from Control Panel)
    "allow_analyst_delete_rules": False,
    "allow_analyst_delete_csv": False,
    # Reason gates (require approval when corresponding allow_* is True)
    "require_reason_rule_creation": False,
    "require_reason_csv_creation": False,
    "require_reason_rule_deletion": False,
    "require_reason_csv_deletion": False,
}
"""Default daily limits and permissions for analysts. Customizable per-analyst via the Control Panel."""

DEFAULT_ADMIN_LIMITS: dict = {
    # Per-action limits
    "rule_deletion": 2,         # soft-delete rules per period
    "csv_deletion": 2,          # soft-delete CSVs per period
    "approval_count": 20,       # approval actions per period
    "limit_changes": 5,         # analyst limit config changes per period
    "csv_save": 20,             # CSV save/edit operations per period
    "csv_revert": 10,           # CSV revert operations per period
    "rule_creation": 5,         # rule creations per period
    "csv_creation": 5,          # CSV creations per period
    "trash_restore": 10,        # trash restore operations per period
    "trash_purge": 5,           # permanent trash purge operations per period
    "usage_reset": 10,          # analyst usage reset operations per period
    # Reset schedule (independent from analyst reset)
    "reset_frequency": "daily",     # never, daily, weekly, monthly, yearly
    "reset_time_utc": "00:00",      # HH:MM in UTC
    "reset_day_of_week": 0,         # 0=Monday, ..., 6=Sunday (used by weekly)
    "reset_day_of_month": 1,        # 1-31, clamped to last day (used by monthly)
    "reset_month": 1,               # 1-12 (used by yearly)
    "reset_day_of_year": 1,         # 1-366, clamped to last day (used by yearly)
    # Admin permission toggles (superadmin controls)
    "allow_admin_purge_trash": True,
    "allow_admin_reset_usage": True,
}
"""Default limits and permissions for administrators. Set by superadmin only."""


# ═══════════════════════════════════════════════════════════════════════════
# Fallback Approval Thresholds (used if limit config read fails)
# ═══════════════════════════════════════════════════════════════════════════

APPROVAL_BULK_ROW_THRESHOLD: int = 3
"""Fallback: bulk row removal requires approval if count >= this."""

APPROVAL_BULK_EDIT_THRESHOLD: int = 3
"""Fallback: bulk row edit requires approval if count >= this."""

APPROVAL_COLUMN_NONEMPTY_THRESHOLD: int = 5
"""Fallback: column addition requires approval if non-empty rows >= this."""

APPROVAL_BULK_ADD_THRESHOLD: int = 3
"""Fallback: bulk row addition requires approval if count >= this."""

APPROVAL_REVERT_ROW_THRESHOLD: int = 5
"""Fallback: revert requires approval if row count >= this."""

APPROVAL_REVERT_COLUMN_THRESHOLD: int = 3
"""Fallback: revert requires approval if column changes >= this."""


# ═══════════════════════════════════════════════════════════════════════════
# Compiled Regex Patterns (eager evaluation at module load time)
# ═══════════════════════════════════════════════════════════════════════════

_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
"""Regex pattern matching C0 control characters (except tab, LF, CR).
Used to sanitize CSV cell content and user input."""

_SAFE_COLNAME_RE = re.compile(r"^(?=.*[a-zA-Z0-9])[a-zA-Z0-9_\-\.()/:#@&+]+$")
"""Regex pattern for valid column names.
Allows alphanumerics, underscore, hyphen, dot, parentheses, colon, slash, @, #, &, +.
Requires at least one alphanumeric character."""

_SANITIZE_RE = re.compile(r'[^a-zA-Z0-9_ \t.,;:!?\'"()\-/@#&+=\[\]{}%$\n\r]')
"""Regex pattern for sanitizing user-provided text fields (reasons, descriptions, comments).
ASCII-only: strips all non-ASCII characters (including Cyrillic, CJK, etc.),
control characters, backticks, backslashes, and other dangerous characters."""


# ═══════════════════════════════════════════════════════════════════════════
# HMAC Salts (single source of truth)
# ═══════════════════════════════════════════════════════════════════════════
# These are combined with the Splunk server GUID at runtime to derive
# HMAC signing keys. They MUST NOT be duplicated in other modules —
# always import from here.
#
# IMPORTANT — FIM runtime compatibility:
# wl_fim.py and wl_migrate_cooldowns.py import these constants via
# sys.path manipulation. Those scripts run OUTSIDE Splunk's normal
# module environment (FIM runs as a scripted input, migration runs
# via system python3). This module MUST keep its imports to Python
# stdlib only (os, re, typing). Adding a Splunk-specific or wl_*
# import at module level will break FIM and the migration tool
# silently (they fall back to hardcoded salts, causing drift).

COOLDOWN_HMAC_SALT: bytes = b"wl_manager_cooldown_integrity_v2"
"""Salt for cooldown rate-limit records (KV store + filesystem markers)."""

FIM_HMAC_SALT: bytes = b"wl_manager_fim_integrity_v1"
"""Salt for FIM baselines and deploy-window signatures."""
