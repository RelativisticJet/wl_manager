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
from wl_csv import read_csv, write_csv, compute_diff, get_expire_column, remove_expired_rows

# ---------------------------------------------------------------------------
# Layer 3: Rules Registry and CSV Mapping (imported from wl_rules module)
# ---------------------------------------------------------------------------
from wl_rules import read_rules_registry, write_rules_registry, read_csv_mapping, get_rule_csv_file

# ---------------------------------------------------------------------------
# Layer 3: Trash Management (imported from wl_trash module)
# ---------------------------------------------------------------------------
from wl_trash import (
    move_to_trash, list_trash, restore_from_trash, purge_trash_item,
    auto_cleanup_trash
)

# ---------------------------------------------------------------------------
# Rotating file logger — backup audit trail independent of Splunk indexing
# ---------------------------------------------------------------------------
_logger = get_audit_logger()


# ═══════════════════════════════════════════════════════════════════════════
# Utility helpers
# ═══════════════════════════════════════════════════════════════════════════




# ═══════════════════════════════════════════════════════════════════════════
# Detection rule registry helpers
# ═══════════════════════════════════════════════════════════════════════════



def read_rules_registry():
    """Read the list of registered detection rule names."""
    path = _get_detection_rules_path()
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def write_rules_registry(rules):
    """Write the detection rules list to disk."""
    path = _get_detection_rules_path()
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(rules, fh, indent=2)


# ═══════════════════════════════════════════════════════════════════════════
# Version-control helpers
# ═══════════════════════════════════════════════════════════════════════════

def _get_versions_dir(csv_path):
    """Return the _versions/ directory for a given CSV path, creating it if needed."""
    parent = os.path.dirname(csv_path)
    versions_dir = os.path.join(parent, VERSIONS_DIR)
    os.makedirs(versions_dir, exist_ok=True)
    return versions_dir


def _get_version_manifest_path(csv_path):
    """Return path to the versions manifest JSON for a CSV file."""
    base = os.path.splitext(os.path.basename(csv_path))[0]
    versions_dir = _get_versions_dir(csv_path)
    return os.path.join(versions_dir, base + "_versions.json")


def _read_version_manifest(csv_path):
    """Read and return the version manifest as a list, or empty list on error."""
    manifest_path = _get_version_manifest_path(csv_path)
    if not os.path.isfile(manifest_path):
        return []
    try:
        with open(manifest_path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return []


def _write_version_manifest(csv_path, manifest):
    """Write the manifest list to disk with file locking to prevent corruption."""
    manifest_path = _get_version_manifest_path(csv_path)
    with open(manifest_path, "w", encoding="utf-8") as fh:
        if fcntl:
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (IOError, OSError):
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            json.dump(manifest, fh, indent=2)
        finally:
            if fcntl:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


