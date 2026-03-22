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
# Constants — adjust if your layout differs
# ---------------------------------------------------------------------------
APP_NAME = "wl_manager"
SPLUNK_HOME = os.environ.get("SPLUNK_HOME", "/opt/splunk")
APPS_DIR = os.path.join(SPLUNK_HOME, "etc", "apps")
OWN_LOOKUPS = os.path.join(APPS_DIR, APP_NAME, "lookups")
MAPPING_FILE = os.path.join(OWN_LOOKUPS, "rule_csv_map.csv")
AUDIT_INDEX = "wl_audit"
AUDIT_SOURCE = "wl_manager"
AUDIT_SOURCETYPE = "wl_audit"
VERSIONS_DIR = "_versions"
MAX_VERSIONS = 6
MAX_ROWS = 5000
MAX_COLUMNS = 100
MAX_CELL_CHARS = 1000
MAX_PAYLOAD_BYTES = 10 * 1024 * 1024  # 10 MB max POST body
MAX_AUDIT_VALUE_LINES = 500           # cap value arrays in audit events
MAX_DIFF_ROWS = 2000                  # max rows for O(n²) diff matching
MAX_PRESENCE_USERS = 10               # max tracked users per CSV
MAX_PRESENCE_FILES = 200              # max tracked CSV files
PRESENCE_TIMEOUT = 60   # seconds before a user is considered gone (closed tab)
IDLE_TIMEOUT = 1800     # 30 minutes — user present but not interacting

# Rate limiting: per-action sliding window
_rate_limits = {}       # { (user, action): [timestamp, ...] }
RATE_WINDOW = 60        # seconds
RATE_MAX_WRITES = 30    # max POST actions per user per window
RATE_MAX_READS = 120    # max GET actions per user per window

# Column names treated as expiration dates (case-insensitive matching).
EXPIRE_COLUMN_NAMES = {
    "expires", "expire", "expiration", "expiration_date",
    "expiry", "termination", "termination_date",
}

# Roles allowed to WRITE (POST). Everyone authenticated can READ (GET).
# Both old (wl_editor) and new (wl_analyst_editor) names accepted.
EDIT_ROLES = {"wl_editor", "wl_analyst_editor", "wl_admin", "admin", "sc_admin"}

# Roles allowed to APPROVE/REJECT requests and access the Control Panel.
ADMIN_ROLES = {"admin", "sc_admin", "wl_admin"}

# Detection rule registry (rules without CSV mappings)
DETECTION_RULES_FILE = "_detection_rules.json"
MAX_DETECTION_RULES = 1000
MAX_CSVS_PER_RULE = 20            # max CSV files attached to one detection rule
MAX_TOTAL_CSV_MAPPINGS = 5000     # max rows in rule_csv_map.csv

# Approval queue constants
APPROVAL_QUEUE_FILE = "_approval_queue.json"
DAILY_LIMITS_FILE = "_daily_limits.json"
LIMIT_CONFIG_FILE = "_limit_config.json"
APPROVAL_EXPIRY_DAYS = 30
MAX_PENDING_REQUESTS = 20     # max pending approval requests
MAX_RESOLVED_HISTORY = 100    # max resolved entries kept in history
MAX_TRACKED_ANALYSTS = 100    # max analysts tracked in daily usage

# Notification constants
NOTIFICATION_FILE = "_notifications.json"
MAX_NOTIFICATIONS_PER_USER = 20
NOTIFICATION_MAX_AGE_DAYS = 7

# Regex to strip C0 control characters (except tab, LF, CR which are handled separately)
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# Allowed characters in column names: letters, digits, underscore, hyphen, dot, space, parentheses, colon, slash
_SAFE_COLNAME_RE = re.compile(r"^(?=.*[a-zA-Z0-9])[a-zA-Z0-9_\-\. ()/:#@&+]+$")

# Default daily limits per analyst (across all CSVs)
DEFAULT_LIMITS = {
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
    "reset_frequency": "daily",   # never, daily, weekly, monthly, yearly
    "reset_time_utc": "00:00",
    "reset_day_of_week": 0,       # 0=Monday .. 6=Sunday (used by weekly)
    "reset_day_of_month": 1,      # 1-31, clamped to last day (used by monthly)
    "reset_month": 1,             # 1-12 (used by yearly)
    "reset_day_of_year": 1,       # 1-31, clamped to last day (used by yearly)
    # Approval gate thresholds (configurable via Control Panel)
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
    # Reason gates — require approval for create/delete
    # (only effective when corresponding allow_* is True)
    "require_reason_rule_creation": False,
    "require_reason_csv_creation": False,
    "require_reason_rule_deletion": False,
    "require_reason_csv_deletion": False,
}

# Fallback constants (used only if config read fails)
APPROVAL_BULK_ROW_THRESHOLD = 3
APPROVAL_BULK_EDIT_THRESHOLD = 3
APPROVAL_COLUMN_NONEMPTY_THRESHOLD = 5
APPROVAL_BULK_ADD_THRESHOLD = 3
APPROVAL_REVERT_ROW_THRESHOLD = 5
APPROVAL_REVERT_COLUMN_THRESHOLD = 3

# ---------------------------------------------------------------------------
# Rotating file logger — backup audit trail independent of Splunk indexing
# ---------------------------------------------------------------------------
AUDIT_LOG = os.path.join(SPLUNK_HOME, "var", "log", "splunk", "wl_manager_audit.log")
_logger = logging.getLogger("wl_manager_audit")
if not _logger.handlers:
    _logger.setLevel(logging.INFO)
    try:
        _fh = logging.handlers.RotatingFileHandler(
            AUDIT_LOG, maxBytes=10 * 1024 * 1024, backupCount=5
        )
        _fh.setFormatter(logging.Formatter("%(message)s"))
        _logger.addHandler(_fh)
    except OSError:
        # If the log directory is not writable (e.g. Docker bind mount),
        # fall back to stderr so messages reach splunkd.log
        _sh = logging.StreamHandler(sys.stderr)
        _sh.setFormatter(logging.Formatter("wl_manager_audit: %(message)s"))
        _logger.addHandler(_sh)


# In-memory presence tracker:
# { "csv_file": { "user": {"seen": heartbeat_ts, "activity": last_action_ts} } }
_presence = {}


# ═══════════════════════════════════════════════════════════════════════════
# Utility helpers
# ═══════════════════════════════════════════════════════════════════════════

# Regex for sanitizing user-provided text fields (reasons, descriptions, comments).
# Allows alphanumerics, common punctuation, and whitespace.
# Strips control characters, backticks, backslashes, and other potentially
# dangerous characters that could be used for injection.
_SANITIZE_RE = re.compile(r'[^\w\s.,;:!?\'"()\-/@#&+=\[\]{}%$€£¥°–—…\n\r]', re.UNICODE)


def _sanitize_text(text, max_length=500):
    """Sanitize a user-provided text field.

    Strips disallowed characters, collapses whitespace, and truncates.
    """
    if not text or not isinstance(text, str):
        return ""
    cleaned = _SANITIZE_RE.sub("", text)
    # Collapse multiple whitespace into single spaces
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length]
    return cleaned


def _find_expire_column(headers):
    """Return the first header that matches an expiration column name, or None."""
    for h in headers:
        if h.lower() in EXPIRE_COLUMN_NAMES:
            return h
    return None


def _safe_filename(name):
    """Return True only if *name* is a plain CSV filename (no traversal)."""
    if not name or not isinstance(name, str):
        return False
    if os.path.basename(name) != name:
        return False
    if name.startswith("."):
        return False
    if not name.lower().endswith(".csv"):
        return False
    # Stem (without .csv) must contain at least one alphanumeric character
    stem = name[:-4]
    if not stem or not any(c.isalnum() for c in stem):
        return False
    return True


def _check_rate_limit(user, action_type="write"):
    """
    Sliding-window rate limiter. Returns True if request is allowed.
    action_type: "read" or "write"
    """
    global _rate_limits
    now = time.time()
    key = (user, action_type)
    max_req = RATE_MAX_WRITES if action_type == "write" else RATE_MAX_READS

    if key not in _rate_limits:
        _rate_limits[key] = []

    # Prune old entries and cap memory
    _rate_limits[key] = [t for t in _rate_limits[key] if now - t < RATE_WINDOW]

    # Prune stale keys across all users (prevent memory growth)
    if len(_rate_limits) > 10000:
        stale = [k for k, v in _rate_limits.items() if not v or now - v[-1] > RATE_WINDOW * 2]
        for k in stale:
            del _rate_limits[k]

    if len(_rate_limits[key]) >= max_req:
        return False

    _rate_limits[key].append(now)
    return True


def _safe_realpath(path, allowed_base):
    """
    Resolve symlinks and verify the real path is under allowed_base.
    Returns the resolved path or None if it escapes the allowed directory.
    """
    real = os.path.realpath(path)
    real_base = os.path.realpath(allowed_base)
    if not real.startswith(real_base + os.sep) and real != real_base:
        return None
    return real


def _build_csv_path(csv_file, app_context=""):
    """
    Build the absolute path to a lookup CSV without checking existence.

    Returns the safe path or None if the filename is invalid or a symlink
    escape is detected.  Used by both _resolve_csv_path (which adds an
    existence check) and deletion code (which needs the path before
    checking isfile itself).
    """
    if not _safe_filename(csv_file):
        return None

    if app_context:
        safe_app = os.path.basename(app_context)  # prevent traversal
        lookups_dir = os.path.join(APPS_DIR, safe_app, "lookups")
        path = os.path.join(lookups_dir, csv_file)
    else:
        path = os.path.join(OWN_LOOKUPS, csv_file)

    # Symlink protection: ensure path stays under the apps directory
    # Use normpath (not realpath) so we can build paths for files that
    # may or may not exist yet.
    normed = os.path.normpath(path)
    if not normed.startswith(os.path.normpath(APPS_DIR)):
        _logger.warning("Path escape blocked: %s", path)
        return None

    return normed


def _resolve_csv_path(csv_file, app_context=""):
    """
    Build the absolute path to a lookup CSV.

    If *app_context* is provided (e.g. "SplunkEnterpriseSecuritySuite"),
    the CSV is looked up under that app's lookups/ folder.  Otherwise
    we fall back to the wl_manager app's own lookups/ folder.
    """
    path = _build_csv_path(csv_file, app_context)
    if path is None:
        return None

    if not os.path.isfile(path):
        return None

    # Symlink protection: ensure resolved path stays under the apps directory
    safe = _safe_realpath(path, APPS_DIR)
    if safe is None:
        _logger.warning("Symlink escape blocked: %s -> %s", path, os.path.realpath(path))
        return None

    return safe


def _read_csv(filepath):
    """Read a CSV and return (headers: list[str], rows: list[dict])."""
    with open(filepath, "r", newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        headers = list(reader.fieldnames or [])
        rows = [dict(row) for row in reader]
    return headers, rows


def _write_csv(filepath, headers, rows):
    """Overwrite a CSV with the given headers and rows."""
    with open(filepath, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


# ═══════════════════════════════════════════════════════════════════════════
# Detection rule registry helpers
# ═══════════════════════════════════════════════════════════════════════════

def _get_detection_rules_path():
    return os.path.join(OWN_LOOKUPS, DETECTION_RULES_FILE)


def _read_detection_rules():
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


def _write_detection_rules(rules):
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


@contextmanager
def _csv_file_lock(csv_path):
    """Acquire an exclusive lock on a CSV file for the read-modify-write cycle.

    Uses a separate .lock file next to the CSV to avoid interfering with
    readers.  On Windows (no fcntl), this is a no-op — optimistic locking
    via expected_mtime still provides protection.
    """
    if not fcntl:
        yield
        return
    lock_path = csv_path + ".lock"
    fh = open(lock_path, "w")  # noqa: SIM115
    try:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (IOError, OSError):
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        fh.close()
        try:
            os.remove(lock_path)
        except OSError:
            pass


def _get_col_widths_path(csv_path):
    """Return path to the column widths JSON for a CSV file."""
    base = os.path.splitext(os.path.basename(csv_path))[0]
    versions_dir = _get_versions_dir(csv_path)
    return os.path.join(versions_dir, base + "_colwidths.json")


def _read_col_widths(csv_path):
    """Read column widths dict from disk, or empty dict on error."""
    widths_path = _get_col_widths_path(csv_path)
    if not os.path.isfile(widths_path):
        return {}
    try:
        with open(widths_path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return {}


def _write_col_widths(csv_path, widths):
    """Write column widths dict to disk."""
    widths_path = _get_col_widths_path(csv_path)
    with open(widths_path, "w", encoding="utf-8") as fh:
        json.dump(widths, fh, indent=2)


def _snapshot_version(csv_path, analyst, action_label="save"):
    """
    Create a timestamped snapshot of the CSV and update the manifest.

    Copies the current CSV to _versions/ with a timestamped name, appends
    an entry to the manifest, and prunes the oldest entry if more than
    MAX_VERSIONS exist.
    """
    now = datetime.now(timezone.utc)
    ts_file = now.strftime("%Y%m%d_%H%M%S")
    ts_display = now.strftime("%d-%m-%Y %H:%M:%S")
    ts_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    base = os.path.splitext(os.path.basename(csv_path))[0]
    versions_dir = _get_versions_dir(csv_path)
    snapshot_name = "{}_{}.csv".format(base, ts_file)
    snapshot_path = os.path.join(versions_dir, snapshot_name)

    shutil.copy2(csv_path, snapshot_path)

    # Count rows and visible columns in the snapshot
    try:
        hdrs, rows = _read_csv(snapshot_path)
        row_count = len(rows)
        col_count = len([h for h in hdrs if not h.startswith("_")])
    except Exception:
        row_count = -1
        col_count = -1

    manifest = _read_version_manifest(csv_path)
    manifest.append({
        "timestamp": ts_iso,
        "display": ts_display,
        "filename": snapshot_name,
        "analyst": analyst,
        "action": action_label,
        "row_count": row_count,
        "col_count": col_count,
    })

    # Keep only the last MAX_VERSIONS entries
    while len(manifest) > MAX_VERSIONS:
        oldest = manifest.pop(0)
        old_path = os.path.join(versions_dir, oldest["filename"])
        try:
            os.remove(old_path)
        except OSError:
            pass

    _write_version_manifest(csv_path, manifest)
    return snapshot_name, ts_display


# ═══════════════════════════════════════════════════════════════════════════
# Approval workflow helpers
# ═══════════════════════════════════════════════════════════════════════════

def _get_approval_queue_path():
    """Return path to the global approval queue JSON file."""
    versions_dir = os.path.join(OWN_LOOKUPS, VERSIONS_DIR)
    os.makedirs(versions_dir, exist_ok=True)
    return os.path.join(versions_dir, APPROVAL_QUEUE_FILE)


def _read_approval_queue():
    """Read and return the approval queue list, or empty list on error."""
    path = _get_approval_queue_path()
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return []


def _write_approval_queue(queue):
    """Write the approval queue to disk with file locking."""
    path = _get_approval_queue_path()
    with open(path, "w", encoding="utf-8") as fh:
        if fcntl:
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (IOError, OSError):
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            json.dump(queue, fh, indent=2, default=str)
        finally:
            if fcntl:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


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


def _get_admin_users(session_key=""):
    """Discover all Splunk users that have an ADMIN_ROLES role."""
    admin_users = {"admin"}  # fallback: always include default admin
    try:
        import splunk.rest as rest
        if not session_key:
            return admin_users
        response, content = rest.simpleRequest(
            "/services/authentication/users",
            sessionKey=session_key,
            getargs={"output_mode": "json", "count": "0"},
        )
        data = json.loads(content)
        for entry in data.get("entry", []):
            user_roles = set(entry.get("content", {}).get("roles", []))
            if user_roles.intersection(ADMIN_ROLES):
                admin_users.add(entry["name"])
    except Exception as exc:
        _logger.warning("Failed to discover admin users: %s", exc)
    return admin_users


def _notify_admins(notif_type, message, related_request_id=None,
                   extra=None, session_key=""):
    """Send notification to all admin-role users."""
    admin_users = _get_admin_users(session_key)
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
    Also prune resolved entries older than 30 days.
    Called on every queue read.
    Returns the (possibly modified) queue.
    """
    queue = _read_approval_queue()
    now = time.time()
    changed = False

    for item in queue:
        if item["status"] == "pending":
            age_days = (now - item["timestamp"]) / 86400
            if age_days > APPROVAL_EXPIRY_DAYS:
                item["status"] = "expired"
                item["resolved_by"] = "system"
                item["resolved_at"] = int(now)
                item["rejection_reason"] = (
                    "Expired after {} days without action".format(APPROVAL_EXPIRY_DAYS)
                )
                changed = True

    # Prune resolved entries older than 30 days
    cutoff = now - (30 * 86400)
    before_len = len(queue)
    queue = [item for item in queue
             if item["status"] == "pending"
             or (item.get("resolved_at") or now) > cutoff]
    if len(queue) != before_len:
        changed = True

    # Cap resolved history at MAX_RESOLVED_HISTORY (keep newest)
    pending = [item for item in queue if item["status"] == "pending"]
    resolved = [item for item in queue if item["status"] != "pending"]
    if len(resolved) > MAX_RESOLVED_HISTORY:
        resolved.sort(key=lambda x: x.get("resolved_at") or 0, reverse=True)
        resolved = resolved[:MAX_RESOLVED_HISTORY]
        queue = pending + resolved
        changed = True

    if changed:
        _write_approval_queue(queue)
    return queue


def _get_pending_for_csv(csv_file):
    """Return pending approval items for a specific CSV file."""
    queue = _expire_pending_approvals()
    return [item for item in queue
            if item["csv_file"] == csv_file and item["status"] == "pending"]


def _count_nonempty_cells(rows, col_name):
    """Count how many rows have a non-empty value for the given column."""
    return sum(1 for r in rows if (r.get(col_name, "") or "").strip())


def _remove_expired_rows(headers, rows, tz_offset_minutes=0):
    """
    Filter out rows where an expiration column contains a past date/time.

    Returns (kept_rows, expired_rows) where:
        kept_rows    — rows that are still valid (empty = permanent)
        expired_rows — rows that were removed due to expiration

    Supports two date formats:
        UTC (new):    ``YYYY-MM-DD HH:MM UTC``  — " UTC" suffix, compared against UTC now
        Legacy local: ``YYYY-MM-DD HH:MM``      — no suffix, compared against user's
                      local time derived from *tz_offset_minutes*

    Also tolerates date-only variants (``YYYY-MM-DD UTC`` / ``YYYY-MM-DD``).
    """
    expire_col = _find_expire_column(headers)
    if not expire_col:
        return rows, []

    now_utc = datetime.now(timezone.utc)

    # Legacy fallback: convert UTC "now" to user's local time
    user_offset = timedelta(minutes=-tz_offset_minutes)
    user_tz = timezone(user_offset)
    now_local = now_utc.astimezone(user_tz).replace(tzinfo=None)

    kept = []
    expired = []

    for row in rows:
        exp_val = (row.get(expire_col) or "").strip()
        if not exp_val:
            kept.append(row)
            continue

        # Detect UTC format (" UTC" suffix)
        is_utc = exp_val.endswith(" UTC")
        parse_val = exp_val[:-4] if is_utc else exp_val

        parsed = False
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                exp_date = datetime.strptime(parse_val, fmt)
                parsed = True
                break
            except ValueError:
                continue

        if not parsed:
            kept.append(row)
            continue

        if is_utc:
            # UTC value — compare directly against UTC now
            exp_date = exp_date.replace(tzinfo=timezone.utc)
            if exp_date < now_utc:
                expired.append(row)
            else:
                kept.append(row)
        else:
            # Legacy naive local — compare against user's local time
            if exp_date < now_local:
                expired.append(row)
            else:
                kept.append(row)

    return kept, expired


def _compute_diff(old_headers, old_rows, new_headers, new_rows):
    """
    Compare old vs new CSV content and return a structured diff.

    Returns dict with keys:
        added           — list of row dicts that are new
        removed         — list of row dicts that were deleted
        edited          — list of dicts with keys: old_row, new_row, row_num,
                          changed_fields (list of {field, before, after})
        added_count     — int
        removed_count   — int
        edited_count    — int
        added_columns   — list of column names added
        removed_columns — list of column names removed
        text_diff       — list of unified-diff lines (Git-style)
    """
    all_headers = list(dict.fromkeys(old_headers + new_headers))

    # Only compare visible (non-metadata) columns for diff detection.
    # Internal _ columns (_added_by, _added_at, _review_status) are
    # bookkeeping and should not trigger change events.
    visible_headers = [h for h in all_headers if not h.startswith("_")]

    # ── Detect column-level changes ─────────────────────────────
    old_vis = [h for h in old_headers if not h.startswith("_")]
    new_vis = [h for h in new_headers if not h.startswith("_")]
    old_vis_set = set(old_vis)
    new_vis_set = set(new_vis)
    removed_columns = [h for h in old_vis if h not in new_vis_set]
    added_columns = [h for h in new_vis if h not in old_vis_set]

    # Use only headers common to both old and new for row identity
    # matching and edit detection.  This prevents false "edited" events
    # when columns are added or removed (missing column defaults to ""
    # via .get(), causing every row key to mismatch).
    common_headers = [h for h in visible_headers
                      if h in old_vis_set and h in new_vis_set]

    def _row_key(row):
        return tuple(row.get(h, "") for h in common_headers)

    # Count-based (multiset) comparison so duplicate rows are handled
    # correctly.  A simple set loses count information: if old has 2
    # copies of key X and new has 4, the set approach sees X in both
    # and reports zero adds.  Counter-based logic detects the 2 extras.
    old_key_counts = Counter(_row_key(r) for r in old_rows)
    new_key_counts = Counter(_row_key(r) for r in new_rows)

    # Build added_raw: rows in new whose key count exceeds old's count.
    # Iterate in REVERSE because the frontend appends new rows at the end.
    # Forward iteration would pick pre-existing duplicates from the front
    # instead of the actually-new rows from the back.
    _add_remaining = Counter()
    for k in new_key_counts:
        excess = new_key_counts[k] - old_key_counts.get(k, 0)
        if excess > 0:
            _add_remaining[k] = excess
    added_raw = []
    for r in reversed(new_rows):
        k = _row_key(r)
        if _add_remaining.get(k, 0) > 0:
            added_raw.append(r)
            _add_remaining[k] -= 1
    added_raw.reverse()  # restore original (append) order

    # Build removed_raw: rows in old whose key count exceeds new's count
    _rem_remaining = Counter()
    for k in old_key_counts:
        excess = old_key_counts[k] - new_key_counts.get(k, 0)
        if excess > 0:
            _rem_remaining[k] = excess
    removed_raw = []
    for r in old_rows:
        k = _row_key(r)
        if _rem_remaining.get(k, 0) > 0:
            removed_raw.append(r)
            _rem_remaining[k] -= 1

    # ── Detect edits: similarity-based matching ─────────────────
    # A row is "edited" when most of its fields stay the same and
    # only a few change.  We pair removed_raw entries with added_raw
    # entries that share the most unchanged visible fields, requiring
    # at least half the fields to match (to avoid pairing completely
    # different rows that merely ended up at the same position).
    edited = []

    paired_old_ids = set()   # id() of paired old row objects
    paired_new_ids = set()   # id() of paired new row objects

    def _field_overlap(old_row, new_row):
        """Return (matching_count, total_fields, changed_fields_list)."""
        matching = 0
        changed = []
        for h in common_headers:
            ov = old_row.get(h, "")
            nv = new_row.get(h, "")
            if ov == nv:
                matching += 1
            else:
                changed.append({"field": h, "before": ov, "after": nv})
        return matching, len(common_headers), changed

    # For each added row, find the best-matching removed row
    # Guard against O(n²×m) explosion: skip edit detection if
    # both sides exceed MAX_DIFF_ROWS (treat all as pure adds/removes)
    used_removed_indices = set()
    skip_edit_detection = (len(added_raw) > MAX_DIFF_ROWS
                           or len(removed_raw) > MAX_DIFF_ROWS)

    if not skip_edit_detection:
      for new_row in added_raw:
        new_k = _row_key(new_row)
        best_score = -1
        best_idx = -1
        best_changed = []

        for ri, old_row in enumerate(removed_raw):
            if ri in used_removed_indices:
                continue
            matching, total, changed = _field_overlap(old_row, new_row)
            if matching > best_score:
                best_score = matching
                best_idx = ri
                best_changed = changed

        # Require at least half the fields to be unchanged
        if best_idx >= 0 and best_score >= len(common_headers) / 2:
            old_row = removed_raw[best_idx]
            old_k = _row_key(old_row)
            used_removed_indices.add(best_idx)

            # Find 1-based positions in old_rows and new_rows
            old_pos = 0
            for idx_o, r in enumerate(old_rows):
                if _row_key(r) == old_k:
                    old_pos = idx_o + 1
                    break
            new_pos = 0
            for idx_n, r in enumerate(new_rows):
                if _row_key(r) == new_k:
                    new_pos = idx_n + 1
                    break

            edited.append({
                "old_row": old_row,
                "new_row": new_row,
                "old_row_num": old_pos,
                "row_num": new_pos,
                "changed_fields": best_changed,
            })
            paired_old_ids.add(id(old_row))
            paired_new_ids.add(id(new_row))

    # Remove paired rows from added/removed lists (by identity, not key,
    # so duplicate rows aren't all removed when only one was paired)
    added = [r for r in added_raw if id(r) not in paired_new_ids]
    removed = [r for r in removed_raw if id(r) not in paired_old_ids]

    # Text-based unified diff (like `git diff`)
    def _rows_to_lines(headers, rows):
        lines = [",".join(headers)]
        for r in rows:
            lines.append(",".join(r.get(h, "") for h in headers))
        return lines

    # Use only visible headers for the text diff so metadata columns
    # don't pollute the human-readable output.
    old_lines = _rows_to_lines(old_vis, old_rows)
    new_lines = _rows_to_lines(new_vis, new_rows)
    text_diff = list(
        difflib.unified_diff(
            old_lines, new_lines, fromfile="before", tofile="after", lineterm=""
        )
    )

    return {
        "added": added,
        "removed": removed,
        "edited": edited,
        "added_count": len(added),
        "removed_count": len(removed),
        "edited_count": len(edited),
        "added_columns": added_columns,
        "removed_columns": removed_columns,
        "text_diff": text_diff,
    }


# ═══════════════════════════════════════════════════════════════════════════
# REST Handler
# ═══════════════════════════════════════════════════════════════════════════

class WhitelistHandler(PersistentServerConnectionApplication):
    """Splunk PersistentServerConnectionApplication handler."""

    def __init__(self, command_line, command_arg):
        super().__init__()

    # ------------------------------------------------------------------
    # Entry point — Splunk calls this for every request
    # ------------------------------------------------------------------
    def handle(self, in_string):
        try:
            request = json.loads(in_string)
            method = request.get("method", "GET")
            user = self._get_user(request)

            # ── Rate limiting ────────────────────────────────────────
            action_type = "read" if method == "GET" else "write"
            if not _check_rate_limit(user, action_type):
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
        query = self._parse_query(request)
        action = query.get("action", "")

        if action == "get_rules":
            return self._get_rules()

        if action == "get_csvs":
            return self._get_csvs(query.get("rule", ""))

        if action == "get_csv_content":
            return self._get_csv_content(
                request, query.get("csv_file", ""), query.get("app", ""),
                query.get("tz_offset", "0"),
            )

        if action == "get_mapping":
            return self._get_mapping(request)

        if action == "get_versions":
            return self._get_versions(query.get("csv_file", ""), query.get("app", ""))

        if action == "check_csv_status":
            return self._check_csv_status(query.get("csv_file", ""), query.get("app", ""))

        if action == "report_presence":
            return self._report_presence(
                request, query.get("csv_file", ""),
                self._get_user(request),
                query.get("last_activity", "")
            )

        if action == "get_col_widths":
            return self._get_col_widths(query.get("csv_file", ""), query.get("app", ""))

        if action == "get_apps":
            return self._get_apps()

        if action == "check_daily_limit_status":
            user = self._get_user(request)
            return self._check_daily_limit_status(user)

        if action == "get_pending_approvals":
            csv_file = query.get("csv_file", "")
            pending = _get_pending_for_csv(csv_file)
            roles = self._get_roles(request)
            has_edit = bool(roles.intersection(EDIT_ROLES))
            pending_info = [{
                "request_id": p["request_id"],
                "action_type": p["action_type"],
                "description": p["description"],
                "analyst": p["analyst"],
                "timestamp": p["timestamp"],
                # Only expose row-level details to editors/admins
                "pending_highlight": p.get("pending_highlight", {}) if has_edit else {},
                "payload": p.get("payload", {}) if has_edit else {},
            } for p in pending]
            return self._resp(200, {"pending_approvals": pending_info})

        if action == "get_request_csv":
            # Allow admins to download CSV data from a pending/resolved request
            roles = self._get_roles(request)
            if not roles.intersection(ADMIN_ROLES):
                return self._resp(403, {
                    "error": "Only admins can access request CSV data"})
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
                return self._resp(404, {
                    "error": "No CSV data in this request"})
            return self._resp(200, {
                "headers": headers,
                "rows": rows,
                "csv_file": target.get("csv_file", ""),
                "detection_rule": target.get("detection_rule", ""),
            })

        if action == "get_notifications":
            user = self._get_user(request)
            data = _read_notifications()
            user_notifs = data.get(user, [])
            unread_count = sum(
                1 for n in user_notifs if not n.get("read", True))
            return self._resp(200, {
                "notifications": user_notifs,
                "unread_count": unread_count,
            })

        return self._resp(400, {
            "error": "Missing or unknown action",
            "valid_actions": [
                "get_rules", "get_csvs", "get_csv_content", "get_mapping",
                "get_versions", "check_csv_status", "report_presence",
                "get_col_widths", "check_daily_limit_status",
                "get_pending_approvals", "get_apps",
                "get_notifications", "get_request_csv"
            ],
        })

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
        rule_set.update(_read_detection_rules())
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
        path = _resolve_csv_path(csv_file, app_context)
        if path is None:
            # Try own lookups as fallback (with symlink check)
            if _safe_filename(csv_file):
                fallback = os.path.join(OWN_LOOKUPS, csv_file)
                if os.path.isfile(fallback) and _safe_realpath(fallback, APPS_DIR):
                    path = _safe_realpath(fallback, APPS_DIR)
        if path is None:
            return self._resp(404, {"error": "CSV file not found"})

        headers, rows = _read_csv(path)

        # ── Auto-remove expired rows ──────────────────────────────────
        auto_removed_count = 0
        try:
            tz_offset_min = int(tz_offset)
        except (ValueError, TypeError):
            tz_offset_min = 0
        if _find_expire_column(headers):
            kept, expired = _remove_expired_rows(headers, rows, tz_offset_min)
            if expired:
                try:
                    _write_csv(path, headers, kept)
                except OSError as exc:
                    _logger.warning("Cannot write cleaned CSV %s: %s", csv_file, exc)
                else:
                    auto_removed_count = len(expired)
                    rows = kept

                    detection_rule = self._lookup_rule_for_csv(csv_file)
                    ts = int(datetime.now(timezone.utc).timestamp())
                    expired_clean = [
                        {k: v for k, v in r.items() if not k.startswith("_")}
                        for r in expired
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
                        "remove_reason": "Expired",
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
            "expire_column": _find_expire_column(headers) or "",
            "file_mtime": int(os.path.getmtime(path)),
            "pending_approvals": pending_info,
        })

    def _get_mapping(self, request):
        mapping = self._read_mapping()
        registered = _read_detection_rules()
        roles = self._get_roles(request)
        is_admin = bool(roles.intersection(ADMIN_ROLES))
        has_edit = bool(roles.intersection(EDIT_ROLES))
        reason_gates = {}
        if is_admin:
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
        if not _safe_filename(csv_file):
            return self._resp(400, {"error": "Invalid CSV file name"})

        path = _resolve_csv_path(csv_file, app_context)
        if path is None:
            fallback = os.path.join(OWN_LOOKUPS, csv_file)
            if os.path.isfile(fallback) and _safe_realpath(fallback, APPS_DIR):
                path = _safe_realpath(fallback, APPS_DIR)
        if path is None:
            return self._resp(200, {"csv_file": csv_file, "versions": []})

        manifest = _read_version_manifest(path)

        # Backfill col_count for entries created before this field existed
        versions_dir = _get_versions_dir(path)
        updated = False
        for entry in manifest:
            if "col_count" not in entry:
                snap = os.path.join(versions_dir, entry.get("filename", ""))
                try:
                    hdrs, _ = _read_csv(snap)
                    entry["col_count"] = len([h for h in hdrs if not h.startswith("_")])
                    updated = True
                except Exception:
                    entry["col_count"] = -1
        if updated:
            _write_version_manifest(path, manifest)

        return self._resp(200, {"csv_file": csv_file, "versions": manifest})

    def _report_presence(self, request, csv_file, user, last_activity=""):
        """Track which users are viewing a CSV and return the active user list."""
        global _presence
        if not csv_file:
            return self._resp(400, {"error": "csv_file required"})

        # Validate username length to prevent memory abuse
        if len(user) > 100:
            return self._resp(400, {"error": "Invalid user"})

        # Parse last_activity from client (epoch seconds)
        try:
            client_activity = float(last_activity) if last_activity else 0
        except (ValueError, TypeError):
            client_activity = 0

        now = datetime.now(timezone.utc).timestamp()

        # Prune stale CSV files first to bound total memory
        if len(_presence) > MAX_PRESENCE_FILES:
            stale_files = []
            for f, users in _presence.items():
                if all(now - u_data.get("seen", 0) >= PRESENCE_TIMEOUT
                       for u_data in users.values()):
                    stale_files.append(f)
            for f in stale_files:
                del _presence[f]
            if len(_presence) > MAX_PRESENCE_FILES:
                by_age = sorted(
                    _presence.items(),
                    key=lambda x: max(
                        (d.get("seen", 0) for d in x[1].values()), default=0
                    ))
                for f, _ in by_age[:len(_presence) - MAX_PRESENCE_FILES]:
                    del _presence[f]

        if csv_file not in _presence:
            _presence[csv_file] = {}

        file_users = _presence[csv_file]

        # Prune users whose tab is gone (no heartbeat in PRESENCE_TIMEOUT)
        gone = [u for u, d in file_users.items()
                if now - d.get("seen", 0) >= PRESENCE_TIMEOUT]
        for u in gone:
            del file_users[u]

        # Prune users who are idle (heartbeat alive but no activity
        # in IDLE_TIMEOUT) — free up slots for active analysts
        idle = [u for u, d in file_users.items()
                if now - d.get("activity", 0) >= IDLE_TIMEOUT]
        for u in idle:
            del file_users[u]

        # If the current user was just pruned for idleness, tell them
        if user in idle:
            return self._resp(200, {
                "csv_file": csv_file,
                "idle_kicked": True,
                "error": "Your session was released due to 30 minutes "
                         "of inactivity.",
            })

        # Cap users per file — reject new user if full
        if user not in file_users and len(file_users) >= MAX_PRESENCE_USERS:
            return self._resp(409, {
                "error": "Maximum number of simultaneous users ("
                         + str(MAX_PRESENCE_USERS)
                         + ") reached for this CSV file. "
                         "Please try again later.",
                "csv_file": csv_file,
                "presence_full": True,
            })

        # Update this user's entry
        activity_ts = client_activity if client_activity else now
        file_users[user] = {"seen": now, "activity": activity_ts}

        # Build active user list
        active = sorted(file_users.keys())

        return self._resp(200, {
            "csv_file": csv_file,
            "active_users": active,
        })

    def _check_csv_status(self, csv_file, app_context):
        """Lightweight check — returns file mtime and pending approval count."""
        if not _safe_filename(csv_file):
            return self._resp(400, {"error": "Invalid CSV file name"})

        path = _resolve_csv_path(csv_file, app_context)
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
        if not _safe_filename(csv_file):
            return self._resp(400, {"error": "Invalid CSV file name"})
        path = _resolve_csv_path(csv_file, app_context)
        if path is None:
            return self._resp(200, {"col_widths": {}})
        return self._resp(200, {"col_widths": _read_col_widths(path)})

    def _save_col_widths(self, payload):
        """Save column widths for a CSV file."""
        csv_file = payload.get("csv_file", "")
        app_context = payload.get("app_context", "")
        col_widths = payload.get("col_widths", {})

        if not _safe_filename(csv_file):
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

        path = _resolve_csv_path(csv_file, app_context)
        if path is None:
            return self._resp(404, {"error": "CSV file not found"})

        _write_col_widths(path, clean)
        return self._resp(200, {"success": True})

    # ==================================================================
    # POST
    # ==================================================================
    def _handle_post(self, request):
        user = self._get_user(request)
        roles = self._get_roles(request)

        payload = json.loads(request.get("payload", "{}"))
        action = payload.get("action", "")

        # Column widths — any authenticated user can save (display preference)
        if action == "save_col_widths":
            return self._save_col_widths(payload)

        # Audit logging for frontend actions (export/import) — edit roles only
        if action == "log_event":
            if not roles.intersection(EDIT_ROLES | ADMIN_ROLES):
                return self._resp(403, {"error": "Permission denied"})
            return self._log_event(request, payload)

        # Notification actions — any authenticated user
        if action == "mark_notifications_read":
            notif_ids = payload.get("notification_ids", [])
            data = _read_notifications()
            user_notifs = data.get(user, [])
            for n in user_notifs:
                if notif_ids == "all" or n["id"] in notif_ids:
                    n["read"] = True
            data[user] = user_notifs
            _write_notifications(data)
            return self._resp(200, {"success": True})

        # ── Approval workflow actions ─────────────────────────────────
        # submit_approval and check_approval_gate require EDIT_ROLES
        if action == "submit_approval":
            if not roles.intersection(EDIT_ROLES):
                return self._resp(403, {"error": "Permission denied"})
            return self._submit_approval(request, payload, user)

        if action == "check_approval_gate":
            if not roles.intersection(EDIT_ROLES):
                return self._resp(403, {"error": "Permission denied"})
            return self._check_approval_gate(request, payload, user)

        # Cancel own request — any authenticated user who owns the request
        if action == "cancel_request":
            if not roles.intersection(EDIT_ROLES | ADMIN_ROLES):
                return self._resp(403, {"error": "Permission denied"})
            return self._cancel_request(request, payload, user)

        # Admin-only approval management actions
        if action == "process_approval":
            if not roles.intersection(ADMIN_ROLES):
                return self._resp(403, {
                    "error": "Only admin, sc_admin, or wl_admin roles can process approvals"
                })
            return self._process_approval(request, payload, user)

        if action == "get_approval_queue":
            if not roles.intersection(ADMIN_ROLES):
                return self._resp(403, {
                    "error": "Only admin, sc_admin, or wl_admin roles can view the approval queue"
                })
            return self._get_approval_queue_action()

        if action == "get_daily_limits":
            if not roles.intersection(ADMIN_ROLES):
                return self._resp(403, {
                    "error": "Only admin, sc_admin, or wl_admin roles can view daily limits"
                })
            return self._get_daily_limits_action()

        if action == "set_daily_limits":
            if not roles.intersection(ADMIN_ROLES):
                return self._resp(403, {
                    "error": "Only admin, sc_admin, or wl_admin roles can set daily limits"
                })
            return self._set_daily_limits_action(request, payload, user)

        if action == "get_analyst_usage":
            if not roles.intersection(ADMIN_ROLES):
                return self._resp(403, {
                    "error": "Only admin, sc_admin, or wl_admin roles can view analyst usage"
                })
            return self._get_analyst_usage_action(payload)

        if action == "reset_daily_usage":
            if not roles.intersection(ADMIN_ROLES):
                return self._resp(403, {
                    "error": "Only admin, sc_admin, or wl_admin roles can reset daily usage"
                })
            return self._reset_daily_usage_action(payload, user)

        if action == "reset_daily_limits":
            if not roles.intersection(ADMIN_ROLES):
                return self._resp(403, {
                    "error": "Only admin, sc_admin, or wl_admin roles "
                             "can reset limits"
                })
            return self._reset_daily_limits_action(request, user)

        if action == "save_as_default":
            if not roles.intersection(ADMIN_ROLES):
                return self._resp(403, {
                    "error": "Only admin, sc_admin, or wl_admin roles "
                             "can save custom defaults"
                })
            return self._save_as_default_action(request, user)

        if action == "reset_factory_defaults":
            if not roles.intersection(ADMIN_ROLES):
                return self._resp(403, {
                    "error": "Only admin, sc_admin, or wl_admin roles "
                             "can reset to factory defaults"
                })
            return self._reset_factory_defaults_action(request, user)

        if action == "create_rule":
            is_admin = bool(roles.intersection(ADMIN_ROLES))
            if not is_admin:
                cfg = _read_limit_config()
                if not cfg.get("allow_analyst_create_rules", False):
                    return self._resp(403, {
                        "error": "Creating new detection rules is currently "
                                 "restricted to admins. An administrator has "
                                 "disabled this permission for analysts."
                    })
                if not roles.intersection(EDIT_ROLES):
                    return self._resp(403, {
                        "error": "Permission denied. Your account requires "
                                 "one of these roles: "
                                 + ", ".join(sorted(EDIT_ROLES))
                    })
                if cfg.get("require_reason_rule_creation", False):
                    return self._submit_create_delete_approval(
                        request, payload, user, "create_rule",
                        "Create detection rule '{}'".format(
                            payload.get("detection_rule", "")))
            return self._create_rule(request, payload, user)

        if action == "create_csv":
            is_admin = bool(roles.intersection(ADMIN_ROLES))
            if not is_admin:
                cfg = _read_limit_config()
                if not cfg.get("allow_analyst_create_csv", False):
                    return self._resp(403, {
                        "error": "Creating new CSV files is currently "
                                 "restricted to admins. An administrator has "
                                 "disabled this permission for analysts."
                    })
                if not roles.intersection(EDIT_ROLES):
                    return self._resp(403, {
                        "error": "Permission denied. Your account requires "
                                 "one of these roles: "
                                 + ", ".join(sorted(EDIT_ROLES))
                    })
                if cfg.get("require_reason_csv_creation", False):
                    return self._submit_create_delete_approval(
                        request, payload, user, "create_csv",
                        "Create CSV '{}' for rule '{}'".format(
                            payload.get("csv_file", ""),
                            payload.get("detection_rule", "")))
            return self._create_csv(request, payload, user)

        if action == "remove_rule":
            is_admin = bool(roles.intersection(ADMIN_ROLES))
            if not is_admin:
                cfg = _read_limit_config()
                if not cfg.get("allow_analyst_delete_rules", False):
                    return self._resp(403, {
                        "error": "Removing detection rules is currently "
                                 "restricted to admins. An administrator has "
                                 "disabled this permission for analysts."
                    })
                if not roles.intersection(EDIT_ROLES):
                    return self._resp(403, {
                        "error": "Permission denied. Your account requires "
                                 "one of these roles: "
                                 + ", ".join(sorted(EDIT_ROLES))
                    })
                if cfg.get("require_reason_rule_deletion", False):
                    return self._submit_create_delete_approval(
                        request, payload, user, "remove_rule",
                        "Remove detection rule '{}'".format(
                            payload.get("rule_name", "")))
            return self._remove_rule(request, payload, user)

        if action == "remove_csv":
            is_admin = bool(roles.intersection(ADMIN_ROLES))
            if not is_admin:
                cfg = _read_limit_config()
                if not cfg.get("allow_analyst_delete_csv", False):
                    return self._resp(403, {
                        "error": "Removing CSV files is currently "
                                 "restricted to admins. An administrator has "
                                 "disabled this permission for analysts."
                    })
                if not roles.intersection(EDIT_ROLES):
                    return self._resp(403, {
                        "error": "Permission denied. Your account requires "
                                 "one of these roles: "
                                 + ", ".join(sorted(EDIT_ROLES))
                    })
                if cfg.get("require_reason_csv_deletion", False):
                    return self._submit_create_delete_approval(
                        request, payload, user, "remove_csv",
                        "Remove CSV '{}' from rule '{}'".format(
                            payload.get("csv_file", ""),
                            payload.get("rule_name", "")))
            return self._remove_csv(request, payload, user)

        # ── RBAC check for data-modifying actions ─────────────────────
        if not roles.intersection(EDIT_ROLES):
            return self._resp(403, {
                "error": (
                    "Permission denied. "
                    "Your account requires one of these roles: "
                    + ", ".join(sorted(EDIT_ROLES))
                )
            })

        if action == "save_csv":
            return self._save_csv(request, payload, user)

        if action == "revert_csv":
            return self._revert_csv(request, payload, user)

        return self._resp(400, {
            "error": "Unknown POST action. Valid: save_csv, revert_csv, "
                     "create_csv, remove_rule, remove_csv, save_col_widths, "
                     "submit_approval, check_approval_gate, process_approval, "
                     "get_approval_queue, get_daily_limits, set_daily_limits, "
                     "get_analyst_usage, reset_daily_usage"
        })

    # ==================================================================
    # Create Detection Rule
    # ==================================================================
    def _create_rule(self, request, payload, user):
        """Register a new detection rule name (without creating a CSV yet)."""
        detection_rule = (payload.get("detection_rule") or "").strip()

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

        # Check if rule already exists in mapping or registry
        mapping = self._read_mapping()
        if any(e.get("rule_name") == detection_rule for e in mapping):
            return self._resp(409, {
                "error": "Rule '{}' already exists in CSV mapping".format(
                    detection_rule)
            })
        registered = _read_detection_rules()
        if detection_rule in registered:
            return self._resp(409, {
                "error": "Rule '{}' is already registered".format(detection_rule)
            })
        if len(registered) >= MAX_DETECTION_RULES:
            return self._resp(400, {
                "error": "Maximum number of registered rules reached ({})".format(
                    MAX_DETECTION_RULES)
            })

        # Persist the rule name
        registered.append(detection_rule)
        try:
            _write_detection_rules(registered)
        except OSError as exc:
            _logger.error("Failed to write detection rules: %s", exc)
            return self._resp(500, {
                "error": "Failed to save detection rule. Please check server logs."
            })

        # Audit event
        ts = int(datetime.now(timezone.utc).timestamp())
        self._index_audit(request, {
            "timestamp": ts,
            "action": "dr_created",
            "status": "created",
            "analyst": user,
            "detection_rule": detection_rule,
            "app_context": APP_NAME,
        })

        return self._resp(200, {
            "success": True,
            "detection_rule": detection_rule,
            "message": "Detection rule '{}' registered".format(detection_rule),
        })

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
        if len(headers) > MAX_COLUMNS:
            return self._resp(400, {
                "error": "Too many columns: {} (max {})".format(
                    len(headers), MAX_COLUMNS)
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
            if not _SAFE_COLNAME_RE.match(h):
                return self._resp(400, {
                    "error": "Column name '{}' contains invalid characters. "
                             "Only letters, numbers, spaces, and common "
                             "punctuation (_-.()/:#@&+) are allowed.".format(
                                 h[:30])
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
                    # Sanitize: strip nulls, control chars, normalize newlines
                    cleaned = v.replace("\x00", "")
                    cleaned = cleaned.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
                    cleaned = cleaned.replace("\t", " ")
                    cleaned = _CONTROL_CHAR_RE.sub("", cleaned)
                    row[h] = cleaned

            # Validate expiration dates if Expires column present
            expire_col = _find_expire_column(headers)
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

        if not _safe_filename(csv_filename):
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
        csv_path = _build_csv_path(csv_filename, app_context)
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

        # ── Create the CSV file with headers only (no rows) ──────────
        try:
            _write_csv(csv_path, headers, initial_rows)
        except OSError as exc:
            _logger.error("Failed to create CSV %s: %s", csv_filename, exc)
            return self._resp(500, {
                "error": "Failed to create CSV file. Please check server logs."
            })

        # ── Append mapping to rule_csv_map.csv ────────────────────────
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
            registered = _read_detection_rules()
            if detection_rule in registered:
                registered.remove(detection_rule)
                _write_detection_rules(registered)
        except OSError:
            pass  # non-critical — rule just stays in both lists

        # ── Audit event ───────────────────────────────────────────────
        ts = int(datetime.now(timezone.utc).timestamp())
        self._index_audit(request, {
            "timestamp": ts,
            "action": "csv_created",
            "status": "created",
            "analyst": user,
            "detection_rule": detection_rule,
            "csv_file": csv_filename,
            "app_context": app_context,
            "column_count": len(headers),
            "columns": headers,
            "imported_row_count": len(initial_rows),
        })

        row_note = " with {} imported row(s)".format(len(initial_rows)) if initial_rows else ""
        return self._resp(200, {
            "success": True,
            "csv_file": csv_filename,
            "message": "CSV '{}' created with {} column(s){}".format(
                csv_filename, len(headers), row_note),
        })

    # ------------------------------------------------------------------
    # Remove detection rule (unlink or permanent delete)
    # ------------------------------------------------------------------
    def _remove_rule(self, request, payload, user):
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

        mapping = self._read_mapping()
        affected_entries = [e for e in mapping
                           if e.get("rule_name") == rule_name]
        affected_csvs = [e["csv_file"] for e in affected_entries]

        if not affected_csvs:
            # Check if it's a registered rule without CSVs
            registered = _read_detection_rules()
            if rule_name in registered:
                registered.remove(rule_name)
                _write_detection_rules(registered)
                self._index_audit(request, {
                    "action": "rule_removed",
                    "removal_type": removal_type,
                    "timestamp": int(time.time()),
                    "analyst": user,
                    "detection_rule": rule_name,
                    "csv_count": 0,
                    "csv_files": "",
                    "comment": comment,
                })
                return self._resp(200, {
                    "success": True,
                    "message": "Rule '{}' removed (had no CSV files)".format(
                        rule_name),
                })
            return self._resp(404, {
                "error": "Rule '{}' not found in mapping or registry".format(
                    rule_name)})

        # Remove matching rows from rule_csv_map.csv
        new_mapping = [e for e in mapping
                       if e.get("rule_name") != rule_name]
        with open(MAPPING_FILE, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(
                fh, fieldnames=["rule_name", "csv_file", "app_context"],
                extrasaction="ignore")
            writer.writeheader()
            writer.writerows(new_mapping)

        # Also remove from detection rules registry if present
        registered = _read_detection_rules()
        if rule_name in registered:
            registered.remove(rule_name)
            _write_detection_rules(registered)

        deleted_files = []
        if removal_type == "permanent":
            for entry in affected_entries:
                csv_name = entry["csv_file"]
                app_ctx = entry.get("app_context", "")
                csv_path = _build_csv_path(csv_name, app_ctx)
                if csv_path and os.path.isfile(csv_path):
                    try:
                        os.remove(csv_path)
                        deleted_files.append(csv_name)
                    except OSError:
                        pass  # log but continue

        self._index_audit(request, {
            "action": "rule_removed",
            "removal_type": removal_type,
            "timestamp": int(time.time()),
            "analyst": user,
            "detection_rule": rule_name,
            "csv_count": len(affected_csvs),
            "csv_files": ", ".join(affected_csvs),
            "deleted_files": ", ".join(deleted_files) if deleted_files else "",
            "comment": comment,
        })

        verb = "permanently deleted" if removal_type == "permanent" \
            else "unlinked"
        return self._resp(200, {
            "success": True,
            "message": "Rule '{}' {} ({} CSV file{})".format(
                rule_name, verb, len(affected_csvs),
                "s" if len(affected_csvs) != 1 else ""),
            "affected_csvs": affected_csvs,
            "deleted_files": deleted_files,
        })

    # ------------------------------------------------------------------
    # Remove CSV file (unlink or permanent delete)
    # ------------------------------------------------------------------
    def _remove_csv(self, request, payload, user):
        csv_file = (payload.get("csv_file") or "").strip()
        rule_name = (payload.get("rule_name") or "").strip()
        removal_type = payload.get("removal_type", "")
        comment = (payload.get("comment") or "").strip()[:500]

        if not csv_file:
            return self._resp(400, {"error": "csv_file is required"})
        if not _safe_filename(csv_file):
            return self._resp(400, {"error": "Invalid CSV filename"})
        if removal_type not in ("unlink", "permanent"):
            return self._resp(400, {
                "error": "removal_type must be 'unlink' or 'permanent'"})
        if not comment:
            return self._resp(400, {"error": "A reason is required"})

        mapping = self._read_mapping()

        # Find the specific entry (capture app_context for cross-app support)
        found_entry = None
        for e in mapping:
            if e.get("csv_file") == csv_file:
                if not rule_name:
                    rule_name = e.get("rule_name", "")
                found_entry = e
                break

        if not found_entry:
            return self._resp(404, {
                "error": "CSV '{}' not found in mapping".format(csv_file)})

        app_context = found_entry.get("app_context", "")

        # Check if this is the last CSV for the rule
        rule_csvs = [e["csv_file"] for e in mapping
                     if e.get("rule_name") == rule_name]
        rule_also_removed = (len(rule_csvs) == 1)

        # Remove the CSV entry from mapping
        new_mapping = [e for e in mapping
                       if not (e.get("csv_file") == csv_file
                               and e.get("rule_name") == rule_name)]
        with open(MAPPING_FILE, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(
                fh, fieldnames=["rule_name", "csv_file", "app_context"],
                extrasaction="ignore")
            writer.writeheader()
            writer.writerows(new_mapping)

        deleted = False
        if removal_type == "permanent":
            csv_path = _build_csv_path(csv_file, app_context)
            if csv_path and os.path.isfile(csv_path):
                try:
                    os.remove(csv_path)
                    deleted = True
                except OSError:
                    pass

        self._index_audit(request, {
            "action": "csv_removed",
            "removal_type": removal_type,
            "timestamp": int(time.time()),
            "analyst": user,
            "detection_rule": rule_name,
            "csv_file": csv_file,
            "app_context": app_context,
            "rule_also_removed": rule_also_removed,
            "file_deleted": deleted,
            "comment": comment,
        })

        verb = "permanently deleted" if removal_type == "permanent" \
            else "unlinked"
        msg = "CSV '{}' {}".format(csv_file, verb)
        if rule_also_removed:
            msg += " (last CSV — rule '{}' also removed)".format(rule_name)

        return self._resp(200, {
            "success": True,
            "message": msg,
            "rule_also_removed": rule_also_removed,
        })

    def _save_csv(self, request, payload, user, _from_approval=False):
        csv_file = payload.get("csv_file", "")
        app_context = payload.get("app_context", "")
        detection_rule = payload.get("detection_rule", "")
        new_headers = payload.get("headers", [])
        new_rows = payload.get("rows", [])
        analyst_comment = _sanitize_text(payload.get("comment", ""))
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
        expected_mtime = payload.get("expected_mtime", None)

        # ── Validate filename ─────────────────────────────────────────
        if not _safe_filename(csv_file):
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
        if len(new_headers) > MAX_COLUMNS:
            return self._resp(400, {
                "error": "Column limit exceeded: {} columns submitted, maximum is {}."
                         .format(len(new_headers), MAX_COLUMNS)
            })

        # ── Validate and sanitize cell values ───────────────────────
        for i, row in enumerate(new_rows):
            for h, v in row.items():
                if isinstance(v, str):
                    if len(v) > MAX_CELL_CHARS:
                        return self._resp(400, {
                            "error": "Cell value too long in row {}, column '{}': "
                                     "{} chars (max {}).".format(
                                         i + 1, h[:50], len(v), MAX_CELL_CHARS)
                        })
                    # Strip null bytes, control chars, and normalize newlines
                    cleaned = v.replace("\x00", "")
                    cleaned = cleaned.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
                    cleaned = cleaned.replace("\t", " ")
                    cleaned = _CONTROL_CHAR_RE.sub("", cleaned)
                    if cleaned != v:
                        row[h] = cleaned

        # ── Validate expiration date formats ─────────────────────────
        expire_col = _find_expire_column(new_headers)
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
                             "Only letters, numbers, spaces, and common "
                             "punctuation (_-.()/:#@&+) are allowed.".format(
                                 h[:30])
                })

        # ── Validate column renames ──────────────────────────────────
        for cr in column_renames:
            old_n = cr.get("old_name", "")
            new_n = cr.get("new_name", "")
            if not old_n or not new_n or old_n == new_n:
                return self._resp(400, {"error": "Invalid column rename"})
            if not new_n.strip():
                return self._resp(400, {
                    "error": "Column names cannot be empty or whitespace-only."
                })
            if len(new_n) > 64:
                return self._resp(400, {
                    "error": "Column name too long (max 64 chars)."
                })
            if not _SAFE_COLNAME_RE.match(new_n):
                return self._resp(400, {
                    "error": "Column name '{}' contains invalid characters. "
                             "Only letters, numbers, spaces, and common "
                             "punctuation (_-.()/:#@&+) are allowed.".format(
                                 new_n[:30])
                })

        # ── Resolve path ──────────────────────────────────────────────
        path = _resolve_csv_path(csv_file, app_context)
        if path is None:
            fallback = os.path.join(OWN_LOOKUPS, csv_file)
            if os.path.isfile(fallback) and _safe_realpath(fallback, APPS_DIR):
                path = _safe_realpath(fallback, APPS_DIR)
        if path is None:
            return self._resp(404, {"error": "CSV file not found"})

        # ── Acquire file-level lock for the read-modify-write cycle ───
        # (On Windows, falls through to optimistic-lock-only mode.)
        return self._save_csv_locked(
            path, csv_file, app_context, detection_rule,
            expected_mtime, new_headers, new_rows,
            analyst_comment, removal_reasons, bulk_removal,
            column_removal_reasons, row_reorder, column_reorder,
            column_renames, explicit_row_add_reason, user, request,
            payload, _from_approval,
        )

    def _save_csv_locked(
        self, path, csv_file, app_context, detection_rule,
        expected_mtime, new_headers, new_rows,
        analyst_comment, removal_reasons, bulk_removal,
        column_removal_reasons, row_reorder, column_reorder,
        column_renames, explicit_row_add_reason, user, request,
        payload=None, _from_approval=False,
    ):
        """Inner save logic wrapped in a file lock."""
        with _csv_file_lock(path):
            return self._save_csv_inner(
                path, csv_file, app_context, detection_rule,
                expected_mtime, new_headers, new_rows,
                analyst_comment, removal_reasons, bulk_removal,
                column_removal_reasons, row_reorder, column_reorder,
                column_renames, explicit_row_add_reason, user, request,
                payload, _from_approval,
            )

    def _save_csv_inner(
        self, path, csv_file, app_context, detection_rule,
        expected_mtime, new_headers, new_rows,
        analyst_comment, removal_reasons, bulk_removal,
        column_removal_reasons, row_reorder, column_reorder,
        column_renames, explicit_row_add_reason, user, request,
        payload=None, _from_approval=False,
    ):
        # ── Optimistic locking — reject if file changed since load ───
        if expected_mtime is not None:
            try:
                current_mtime = int(os.path.getmtime(path))
                if current_mtime != int(expected_mtime):
                    return self._resp(409, {
                        "error": "Conflict: the CSV file was modified by another "
                                 "user or process since you loaded it. Please "
                                 "reload the file and try again.",
                        "current_mtime": current_mtime,
                    })
            except (ValueError, TypeError, OSError):
                pass  # If mtime check fails, proceed without locking

        # ── Read BEFORE state ─────────────────────────────────────────
        old_headers, old_rows = _read_csv(path)
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
                    # Rebuild visible index mapping to find insert point
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
        diff = _compute_diff(old_headers, old_rows, new_headers, new_rows)

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
        # Server-side: use actual diff count rather than trusting client
        bulk_edit_count = diff.get("edited_count", 0) if \
            payload.get("_bulk_edit_count", 0) else 0
        limit_actions = []
        if bulk_removal and len(bulk_removal) >= 2:
            limit_actions.append("bulk_row_removal")
        elif bulk_removal or removal_reasons:
            limit_actions.append("row_removal")
        if column_removal_reasons:
            limit_actions.append("column_removal")
        if bulk_edit_count and diff["edited_count"] > 0:
            limit_actions.append("bulk_row_edit")
        elif diff["edited_count"] > 0 and not has_col_changes:
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

        # ── Daily limit enforcement (block only direct actions, not
        #    admin-approved replays — those were checked at submission) ─
        if not _from_approval:
            for limit_action in limit_actions:
                count = action_counts.get(limit_action, 1)
                allowed, current, maximum = _check_daily_limit(
                    user, limit_action, action_count=count)
                if not allowed:
                    over = current + count - maximum
                    return self._resp(429, {
                        "error": "Daily limit exceeded for {}. "
                                 "This action affects {} rows, exceeding "
                                 "your daily limit by {} ({}/{} used). "
                                 "Contact your administrator.".format(
                                     limit_action.replace("_", " "),
                                     count, over, current, maximum),
                        "limit_type": limit_action,
                        "current": current,
                        "maximum": maximum,
                    })

        # ── Server-side approval gate enforcement ─────────────────────
        # Prevent direct API callers from bypassing the approval workflow.
        if not _from_approval:
            # Bulk row removal gate
            actual_removed = diff.get("removed_count", 0)
            if actual_removed >= _get_threshold("bulk_row_removal_threshold"):
                return self._resp(403, {
                    "error": "Removing {} rows requires admin approval. "
                             "Use the approval workflow.".format(actual_removed),
                    "requires_approval": True,
                })
            # Bulk row edit gate
            actual_edited = diff.get("edited_count", 0)
            if bulk_edit_count and actual_edited >= _get_threshold("bulk_row_edit_threshold"):
                return self._resp(403, {
                    "error": "Bulk editing {} rows requires admin approval. "
                             "Use the approval workflow.".format(actual_edited),
                    "requires_approval": True,
                })
            # Bulk row addition gate
            actual_added = diff.get("added_count", 0)
            if actual_added >= _get_threshold("bulk_row_addition_threshold"):
                return self._resp(403, {
                    "error": "Adding {} rows requires admin approval. "
                             "Use the approval workflow.".format(actual_added),
                    "requires_approval": True,
                })
            # NOTE: Individual inline edits (no _bulk_edit_count) are NOT
            # subject to an approval gate.  They are governed by the
            # "row_edit" daily limit enforced above (lines 1522-1535).
            # Only the dedicated Bulk Edit feature (which sets
            # _bulk_edit_count) triggers the bulk_row_edit approval gate.
            # Column removal gate (non-empty cells)
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

        # ── Stamp row-level history on newly added rows ──────────────
        ts_now = str(int(datetime.now(timezone.utc).timestamp()))

        # Use object identity (id) to stamp only truly new rows, not
        # pre-existing rows that happen to have the same visible content.
        added_ids = {id(entry) for entry in diff["added"]}

        for row in new_rows:
            if id(row) in added_ids:
                row["_added_by"] = user
                row["_added_at"] = ts_now

        # Ensure metadata columns are in the header list for CSV write
        write_headers = list(new_headers)
        for meta in ("_added_by", "_added_at"):
            if meta not in write_headers:
                write_headers.append(meta)

        # ── Write AFTER state ─────────────────────────────────────────
        _write_csv(path, write_headers, new_rows)

        # ── Snapshot version ─────────────────────────────────────────
        try:
            _snapshot_version(path, user, action_label="save")
        except OSError as exc:
            _logger.warning("Failed to snapshot version for %s: %s", csv_file, exc)

        # ── Build a removal-reason lookup for quick matching ─────────
        # Strip _ metadata columns so keys match between the frontend's
        # row snapshot and the diff's removed entries (read from disk).
        def _visible_key(row):
            cleaned = {k: v for k, v in row.items() if not k.startswith("_")}
            return json.dumps(cleaned, sort_keys=True, default=str)

        reason_map = {}
        for rr in removal_reasons:
            rr_row = rr.get("row", {})
            reason_map[_visible_key(rr_row)] = rr.get("reason", "")

        # ── Common audit fields ──────────────────────────────────────
        ts = int(datetime.now(timezone.utc).timestamp())
        has_comment_col = "Comment" in new_headers

        # If per-row Comment column exists, the summary comment should
        # say so (the per-action events carry each row's own comment).
        summary_comment = analyst_comment
        if has_comment_col and (not analyst_comment or analyst_comment == "__per_row__"):
            summary_comment = "See per-row comments"

        common = {
            "timestamp": ts,
            "analyst": user,
            "detection_rule": detection_rule,
            "csv_file": csv_file,
            "app_context": app_context,
            "comment": summary_comment,
        }
        # When executed via approval, include the request_id in every audit event.
        # Only trust _approval_request_id when _from_approval is True to
        # prevent non-approval saves from injecting fake request IDs.
        if _from_approval:
            approval_request_id = payload.get("_approval_request_id", "")
            if approval_request_id:
                common["request_id"] = approval_request_id

        # ── Helper: strip internal _ columns from a row ────────────────
        def _clean_entry(row):
            return {k: v for k, v in row.items() if not k.startswith("_")}

        # ── Helper: build numbered fields + "value" summary string ────
        # Returns (numbered_dict, value_string) where:
        #   numbered_dict = {"user_row_3": "jsmith", "src_ip_row_3": "10.0.0.1"}
        #   value_list    = ["user_row_3: jsmith", "src_ip_row_3: 10.0.0.1", ...]
        def _build_row_fields(entries, row_num_map):
            lines = []
            for entry in entries:
                row_num = row_num_map.get(id(entry), 0)
                cleaned = _clean_entry(entry)
                for col_name, col_val in sorted(cleaned.items()):
                    field_name = "{}_row_{}".format(col_name, row_num)
                    lines.append("{}: {}".format(field_name, col_val))
            return lines

        # ── Map added rows to row numbers in the NEW csv ─────────────
        # Row number = position in new_rows (1-based)
        # diff["added"] entries are the same Python objects as in new_rows
        # (from the list comprehension in _compute_diff), so we can match
        # by identity (id()) — no key-based scanning needed.
        new_row_id_to_pos = {id(row): i + 1 for i, row in enumerate(new_rows)}
        added_row_map = {}
        for entry in diff["added"]:
            pos = new_row_id_to_pos.get(id(entry))
            if pos is not None:
                added_row_map[id(entry)] = pos

        # ── "added" audit event (single event for all added rows) ────
        if diff["added_count"] > 0:
            added_values = _build_row_fields(
                diff["added"], added_row_map
            )
            evt = dict(common, **{
                "action": "row_added",
                "added_row_count": diff["added_count"],
                "value": added_values,
                "row_add_reason": explicit_row_add_reason or summary_comment,
                "added_by": user,
                "added_at": ts,
            })
            self._index_audit(request, evt)

        # ── Removal audit events ─────────────────────────────────────
        # Map removed rows to their 1-based position in old_rows.
        # diff["removed"] entries are the same Python objects as in old_rows,
        # so we match by identity (id()) for correct duplicate handling.
        old_row_id_to_pos = {id(row): i + 1 for i, row in enumerate(old_rows)}
        def _removed_row_map(removed_entries):
            rmap = {}
            for entry in removed_entries:
                pos = old_row_id_to_pos.get(id(entry))
                if pos is not None:
                    rmap[id(entry)] = pos
            return rmap

        if bulk_removal and diff["removed_count"] > 0:
            # Bulk removal via "Remove Selected" button
            bulk_reason = bulk_removal[0].get("reason", "") if bulk_removal else ""

            removed_values = _build_row_fields(
                diff["removed"], _removed_row_map(diff["removed"])
            )
            evt = dict(common, **{
                "action": "row_removed_multiple" if diff["removed_count"] > 1 else "row_removed",
                "removed_row_count": diff["removed_count"],
                "value": removed_values,
                "remove_reason": bulk_reason,
                "removed_by": user,
                "removed_at": ts,
            })
            self._index_audit(request, evt)
        elif diff["removed_count"] > 0:
            # Single row removal via "Remove" button
            single_reason = ""
            for rr in removal_reasons:
                single_reason = rr.get("reason", "")

            removed_values = _build_row_fields(
                diff["removed"], _removed_row_map(diff["removed"])
            )
            evt = dict(common, **{
                "action": "row_removed",
                "removed_row_count": diff["removed_count"],
                "value": removed_values,
                "remove_reason": single_reason,
                "removed_by": user,
                "removed_at": ts,
            })
            self._index_audit(request, evt)

        # ── "edited" audit event (cell-level changes) ────────────
        if diff["edited_count"] > 0:
            edit_value_lines = []
            edit_details = {}
            for edit_entry in diff["edited"]:
                rn = edit_entry["row_num"]
                for change in edit_entry["changed_fields"]:
                    field = change["field"]
                    before_key = "{}_row_{}_before".format(field, rn)
                    after_key = "{}_row_{}_after".format(field, rn)
                    edit_details[before_key] = change["before"]
                    edit_details[after_key] = change["after"]
                    edit_value_lines.append("{}: {}".format(before_key, change["before"]))
                    edit_value_lines.append("{}: {}".format(after_key, change["after"]))

            # When edits accompany a removal, use a distinct comment
            edit_comment = summary_comment
            if (bulk_removal or removal_reasons) and diff["removed_count"] > 0:
                edit_comment = "Edited alongside removal"

            evt = dict(common, **{
                "action": "row_edited",
                "edited_row_count": diff["edited_count"],
                "value": edit_value_lines,
                "comment": edit_comment,
                "edited_by": user,
                "edited_at": ts,
            })
            self._index_audit(request, evt)

        # ── Column change audit events ─────────────────────────────
        if diff.get("removed_columns"):
            col_reason = ""
            for cr in column_removal_reasons:
                if cr.get("column") in diff["removed_columns"]:
                    col_reason = cr.get("reason", "")
                    break

            value_lines = []
            for col in diff["removed_columns"]:
                for i, row in enumerate(old_rows):
                    cell = row.get(col, "")
                    if cell:
                        value_lines.append("{}_row_{}: {}".format(col, i + 1, cell))

            evt = dict(common, **{
                "action": "column_removed",
                "column_count": len(diff["removed_columns"]),
                "columns": diff["removed_columns"],
                "value": value_lines,
                "remove_reason": col_reason,
                "changed_by": user,
                "changed_at": ts,
            })
            self._index_audit(request, evt)

        if diff.get("added_columns"):
            evt = dict(common, **{
                "action": "column_added",
                "column_count": len(diff["added_columns"]),
                "columns": diff["added_columns"],
                "value": ["column: " + c for c in diff["added_columns"]],
                "changed_by": user,
                "changed_at": ts,
            })
            self._index_audit(request, evt)

        # ── Column rename audit events ───────────────────────────
        if column_renames:
            for cr in column_renames:
                evt = dict(common, **{
                    "action": "column_renamed",
                    "column_renamed_before": cr["old_name"],
                    "column_renamed_after": cr["new_name"],
                    "column_count": 1,
                    "value": [cr["old_name"] + " -> " + cr["new_name"]],
                    "changed_by": user,
                    "changed_at": ts,
                })
                self._index_audit(request, evt)

        # ── Row reorder audit event ────────────────────────────────
        if row_reorder and isinstance(row_reorder, dict):
            evt = dict(common, **{
                "action": "row_reordered",
                "row_number_before": row_reorder.get("from_position"),
                "row_number_after": row_reorder.get("to_position"),
                "reordered_by": user,
                "reordered_at": ts,
            })
            self._index_audit(request, evt)

        # ── Column reorder audit event ─────────────────────────────
        if column_reorder and isinstance(column_reorder, dict):
            evt = dict(common, **{
                "action": "column_reordered",
                "column_name": column_reorder.get("column"),
                "column_number_before": column_reorder.get("from_position"),
                "column_number_after": column_reorder.get("to_position"),
                "reordered_by": user,
                "reordered_at": ts,
            })
            self._index_audit(request, evt)

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

    # ------------------------------------------------------------------
    # Revert CSV to a previous version
    # ------------------------------------------------------------------
    def _revert_csv(self, request, payload, user, _from_approval=False):
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
        if len(revert_reason) > 500:
            revert_reason = revert_reason[:500]

        if not _safe_filename(csv_file):
            return self._resp(400, {"error": "Invalid CSV file name"})

        if not detection_rule:
            return self._resp(400, {"error": "detection_rule is required"})

        # ── Resolve current CSV path ─────────────────────────────────
        path = _resolve_csv_path(csv_file, app_context)
        if path is None:
            fallback = os.path.join(OWN_LOOKUPS, csv_file)
            if os.path.isfile(fallback) and _safe_realpath(fallback, APPS_DIR):
                path = _safe_realpath(fallback, APPS_DIR)
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
                current_mtime = int(os.path.getmtime(path))
                if current_mtime != int(expected_mtime):
                    return self._resp(409, {
                        "error": "Conflict: the CSV file was modified by another "
                                 "user or process since you loaded it. Please "
                                 "reload the file and try again.",
                        "current_mtime": current_mtime,
                    })
            except (ValueError, TypeError, OSError):
                pass

        # ── Locate the version file ──────────────────────────────────
        if not version_filename or os.path.basename(version_filename) != version_filename:
            return self._resp(400, {"error": "Invalid version filename"})

        versions_dir = _get_versions_dir(path)
        version_path = os.path.join(versions_dir, version_filename)
        if not os.path.isfile(version_path):
            return self._resp(404, {"error": "Version file not found"})

        # ── Read BEFORE state (current CSV) ──────────────────────────
        old_headers, old_rows = _read_csv(path)

        # ── Read the version to revert to ────────────────────────────
        new_headers, new_rows = _read_csv(version_path)

        # ── Compute diff between current state and reverted version ──
        diff = _compute_diff(old_headers, old_rows, new_headers, new_rows)

        # ── Daily limit enforcement for reverts ──────────────────────
        # Skip when replaying from approval — already checked at
        # submission time in _submit_approval().
        if not _from_approval:
            allowed, current, maximum = _check_daily_limit(user, "revert")
            if not allowed:
                return self._resp(429, {
                    "error": "Daily revert limit reached. "
                             "You have used {}/{} today. "
                             "Contact your administrator.".format(current, maximum),
                    "limit_type": "revert",
                    "current": current,
                    "maximum": maximum,
                })

        # ── Approval gate for large reverts ──────────────────────────
        # Skip when replaying from approval — the admin already approved.
        if not _from_approval:
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

        # ── Overwrite CSV with the version content ───────────────────
        _write_csv(path, new_headers, new_rows)

        # ── Get the current (latest) version label before modifying ────
        current_version_display = ""
        try:
            manifest = _read_version_manifest(path)
            if manifest:
                current_version_display = manifest[-1].get("display", "")
        except OSError:
            pass

        # ── Remove the source version first (it will be replaced by
        #    the revert snapshot, so removing it avoids duplicates and
        #    keeps the count correct before pruning) ───────────────────
        try:
            manifest = _read_version_manifest(path)
            updated = []
            for entry in manifest:
                if entry.get("filename") == version_filename:
                    old_path = os.path.join(versions_dir, entry["filename"])
                    try:
                        os.remove(old_path)
                    except OSError:
                        pass
                else:
                    updated.append(entry)
            _write_version_manifest(path, updated)
        except OSError as exc:
            _logger.warning("Failed to clean source version for %s: %s",
                            csv_file, exc)

        # ── Snapshot the revert (becomes a new version entry) ────────
        new_record_display = ""
        try:
            _, new_record_display = _snapshot_version(
                path, user, action_label="revert"
            )
        except OSError as exc:
            _logger.warning("Failed to snapshot after revert for %s: %s",
                            csv_file, exc)

        # ── Audit event ──────────────────────────────────────────────
        now = datetime.now(timezone.utc)
        ts = int(now.timestamp())
        ts_display_now = now.strftime("%d-%m-%Y %H:%M:%S")

        summary = (
            "User {} revert {} {} version to {} "
            "(which became the latest in the record {}) at {} GMT+00"
            .format(user, csv_file, current_version_display,
                    version_display, new_record_display, ts_display_now)
        )

        # Build value lines showing what changed (with row numbers)
        value_lines = []

        # Helper: build a visible-key for row matching
        vis_hdrs = [h for h in (new_headers or old_headers) if not h.startswith("_")]
        def _vis_key(row):
            return tuple(row.get(h, "") for h in vis_hdrs)

        # Map restored (added) rows to their position in new_rows.
        # diff entries are same objects as in new_rows/old_rows, so use id().
        rev_new_id_to_pos = {id(r): i + 1 for i, r in enumerate(new_rows)}
        for entry in diff.get("added", []):
            row_num = rev_new_id_to_pos.get(id(entry), 0)
            cleaned = {k: v for k, v in entry.items() if not k.startswith("_")}
            for col, val in sorted(cleaned.items()):
                value_lines.append("restoredback_{}_row_{}: {}".format(col, row_num, val))

        # Map reverted-away (removed) rows to their position in old_rows
        rev_old_id_to_pos = {id(r): i + 1 for i, r in enumerate(old_rows)}
        for entry in diff.get("removed", []):
            row_num = rev_old_id_to_pos.get(id(entry), 0)
            cleaned = {k: v for k, v in entry.items() if not k.startswith("_")}
            for col, val in sorted(cleaned.items()):
                value_lines.append("removedback_{}_row_{}: {}".format(col, row_num, val))

        # Edited rows: show old_row_num → new_row_num
        for entry in diff.get("edited", []):
            old_rn = entry.get("old_row_num", 0)
            new_rn = entry.get("row_num", 0)
            row_label = "{}_{}".format(old_rn, new_rn) if old_rn != new_rn else str(new_rn)
            for chg in entry.get("changed_fields", []):
                value_lines.append("changedback_{}_row_{}: {} -> {}".format(
                    chg["field"], row_label, chg["before"], chg["after"]))

        # ── Detect row position changes ────────────────────────────
        # Build maps: visible_key → list of 1-based positions
        old_key_positions = {}
        for idx, r in enumerate(old_rows):
            k = _vis_key(r)
            old_key_positions.setdefault(k, []).append(idx + 1)

        new_key_positions = {}
        for idx, r in enumerate(new_rows):
            k = _vis_key(r)
            new_key_positions.setdefault(k, []).append(idx + 1)

        moveback_rows = []
        used_old = {}  # track which position index we've consumed per key
        used_new = {}
        for k in old_key_positions:
            if k not in new_key_positions:
                continue
            old_pos_list = old_key_positions[k]
            new_pos_list = new_key_positions[k]
            for i in range(min(len(old_pos_list), len(new_pos_list))):
                if old_pos_list[i] != new_pos_list[i]:
                    # First visible field as row identifier
                    row_id = ", ".join("{}={}".format(vis_hdrs[j], k[j])
                                       for j in range(min(2, len(vis_hdrs)))
                                       if k[j])
                    moveback_rows.append({
                        "row_id": row_id,
                        "before": old_pos_list[i],
                        "after": new_pos_list[i],
                    })

        for mr in moveback_rows:
            rn = mr["before"]  # use actual row number as field identifier
            value_lines.append("moveback_row_{}_number_before: {}".format(rn, rn))
            value_lines.append("moveback_row_{}_number_after: {}".format(rn, mr["after"]))
            if mr["row_id"]:
                value_lines.append("moveback_row_{}_id: {}".format(rn, mr["row_id"]))

        # ── Detect column position changes ─────────────────────────
        old_vis_cols = [h for h in old_headers if not h.startswith("_")]
        new_vis_cols = [h for h in new_headers if not h.startswith("_")]
        common_cols = set(old_vis_cols) & set(new_vis_cols)

        moveback_cols = []
        for col in common_cols:
            old_pos = old_vis_cols.index(col) + 1
            new_pos = new_vis_cols.index(col) + 1
            if old_pos != new_pos:
                moveback_cols.append({
                    "column": col,
                    "before": old_pos,
                    "after": new_pos,
                })

        moveback_cols.sort(key=lambda x: x["before"])
        for mc in moveback_cols:
            cn = mc["before"]  # use actual column number as field identifier
            value_lines.append("moveback_column_{}_name: {}".format(cn, mc["column"]))
            value_lines.append("moveback_column_{}_number_before: {}".format(cn, cn))
            value_lines.append("moveback_column_{}_number_after: {}".format(cn, mc["after"]))

        evt = {
            "timestamp": ts,
            "analyst": user,
            "detection_rule": detection_rule,
            "csv_file": csv_file,
            "app_context": app_context,
            "comment": revert_reason,
            "revert_reason": revert_reason,
            "action": "revert",
            "reverted_from_version": current_version_display,
            "reverted_to_version": version_display,
            "new_record_version": new_record_display,
            "row_count_before": len(old_rows),
            "row_count_after": len(new_rows),
            "restoredback_row_count": diff["added_count"],
            "removedback_row_count": diff["removed_count"],
            "editedback_row_count": diff["edited_count"],
            "restoredback_column_count": len(diff.get("added_columns", [])),
            "restoredback_column_name": diff.get("added_columns", []),
            "removedback_column_count": len(diff.get("removed_columns", [])),
            "removedback_column_name": diff.get("removed_columns", []),
            "moveback_row_count": len(moveback_rows),
            "moveback_column_count": len(moveback_cols),
            "value": value_lines,
            "reverted_by": user,
            "reverted_at": ts,
        }
        self._index_audit(request, evt)

        # ── Increment daily revert counter ─────────────────────────────
        _increment_daily_limit(user, "revert")

        old_vis_hdrs = [h for h in old_headers if not h.startswith("_")]
        new_vis_hdrs = [h for h in new_headers if not h.startswith("_")]

        return self._resp(200, {
            "message": "CSV reverted successfully",
            "diff": diff,
            "rows_before": len(old_rows),
            "rows_after": len(new_rows),
            "cols_before": len(old_vis_hdrs),
            "cols_after": len(new_vis_hdrs),
            "summary": summary,
            "file_mtime": int(os.path.getmtime(path)),
        })

    # ------------------------------------------------------------------
    # Approval workflow handlers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_request_reasons(action_type, stored_payload):
        """Extract user-provided reason fields from a stored approval payload.

        Returns a dict with the appropriate reason fields based on action type:
          bulk_row_removal / column_removal → remove_reason
          bulk_row_addition                 → row_add_reason
          revert                            → revert_reason
        """
        reasons = {}
        if not stored_payload:
            return reasons
        if action_type == "bulk_row_removal":
            br = stored_payload.get("bulk_removal", [])
            if br and isinstance(br, list) and len(br) > 0:
                reasons["remove_reason"] = br[0].get("reason", "")[:500]
        elif action_type == "bulk_row_addition":
            reasons["row_add_reason"] = stored_payload.get(
                "row_add_reason", "")[:500]
        elif action_type == "column_removal":
            cr = stored_payload.get("column_removal_reasons", [])
            if cr and isinstance(cr, list) and len(cr) > 0:
                reasons["remove_reason"] = cr[0].get("reason", "")[:500]
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
        reason = _sanitize_text(
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
        elif not _safe_filename(csv_file):
            return self._resp(400, {"error": "Invalid CSV file name"})

        # Check for existing pending request by same user for same target + action
        detection_rule = payload.get("detection_rule", "")
        queue = _expire_pending_approvals()
        _rule_only = {"create_rule", "remove_rule"}
        for item in queue:
            if item["status"] != "pending" or item["analyst"] != user:
                continue
            if item["action_type"] != action_type:
                continue
            # For rule operations, match on detection_rule (csv_file is always __rule_operation__)
            if action_type in _rule_only:
                if item.get("detection_rule", "") == detection_rule:
                    return self._resp(409, {
                        "error": "You already have a pending {} request "
                                 "for detection rule '{}'. "
                                 "Wait for it to be processed.".format(
                                     action_type.replace("_", " "),
                                     detection_rule)
                    })
            else:
                if item["csv_file"] == csv_file:
                    return self._resp(409, {
                        "error": "You already have a pending {} request "
                                 "for this CSV. "
                                 "Wait for it to be processed.".format(
                                     action_type.replace("_", " "))
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
                over = current + approval_count - maximum
                return self._resp(429, {
                    "error": "Daily limit exceeded for {}. "
                             "This action affects {} rows, exceeding "
                             "your daily limit by {} ({}/{} used). "
                             "Contact your administrator.".format(
                                 limit_key.replace("_", " "),
                                 approval_count, over, current, maximum),
                    "limit_type": limit_key,
                    "current": current,
                    "maximum": maximum,
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
        description = _sanitize_text(payload.get("description", ""))

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

        entry = {
            "request_id": request_id,
            "timestamp": int(time.time()),
            "analyst": user,
            "csv_file": csv_file,
            "app_context": payload.get("app_context", ""),
            "detection_rule": payload.get("detection_rule", ""),
            "action_type": action_type,
            "description": description,
            "status": "pending",
            "payload": original_payload,
            "expected_mtime": payload.get("expected_mtime"),
            "pending_highlight": pending_highlight,
            "resolved_by": None,
            "resolved_at": None,
            "rejection_reason": None,
        }

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
                user, action_type.replace("_", " "), description[:100]),
            request_id, extra=_notif_extra, session_key=sys_key)

        return self._resp(200, {
            "message": "Your request has been submitted for approval.",
            "request_id": request_id,
        })

    def _cancel_request(self, request, payload, user):
        """Cancel a pending approval request — only the original requester."""
        request_id = payload.get("request_id", "")
        cancellation_reason = _sanitize_text(
            payload.get("cancellation_reason", ""))

        if not cancellation_reason.strip():
            return self._resp(400, {"error": "Cancellation reason is required"})

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

    def _process_approval(self, request, payload, admin_user):
        """Approve, reject, or cancel a pending approval request."""
        request_id = payload.get("request_id", "")
        decision = payload.get("decision", "")
        rejection_reason = _sanitize_text(
            payload.get("rejection_reason", ""))
        cancellation_reason = _sanitize_text(
            payload.get("cancellation_reason", ""))
        admin_comment = _sanitize_text(
            payload.get("admin_comment", ""))

        if decision not in ("approve", "reject", "cancel"):
            return self._resp(400, {"error": "Decision must be approve, reject, or cancel"})
        if decision == "cancel" and not cancellation_reason.strip():
            return self._resp(400, {"error": "Cancellation reason is required"})
        if decision == "reject" and not rejection_reason.strip():
            return self._resp(400, {"error": "Rejection reason is required"})

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
            admin_roles = self._get_roles(request)
            if target["analyst"] != admin_user and \
                    not admin_roles.intersection(ADMIN_ROLES):
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
                    admin_user, rejection_reason[:100]),
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
            path = _resolve_csv_path(csv_file, app_context)
            if path is None:
                fallback = os.path.join(OWN_LOOKUPS, csv_file)
                if os.path.isfile(fallback) and _safe_realpath(fallback, APPS_DIR):
                    path = _safe_realpath(fallback, APPS_DIR)
            if path is None:
                target["status"] = "failed"
                target["resolved_by"] = admin_user
                target["resolved_at"] = now
                target["rejection_reason"] = "CSV file no longer exists"
                _write_approval_queue(queue)
                _failed_evt = {
                    "timestamp": now, "analyst": admin_user,
                    "action": "request_failed", "status": "failed",
                    "detection_rule": target["detection_rule"],
                    "csv_file": csv_file, "app_context": app_context,
                    "request_id": request_id,
                    "requester": target["analyst"],
                    "approval_action_type": action_type,
                    "failure_reason": "CSV file no longer exists",
                    "comment": "{} failed to approve {} request created by {}".format(
                        admin_user, action_type.replace("_", " "),
                        target["analyst"]),
                }
                _failed_evt.update(self._extract_request_reasons(
                    action_type, target.get("payload", {})))
                self._index_audit(request, _failed_evt)
                return self._resp(404, {"error": "CSV file not found"})

            # Read current CSV state and build a fresh payload
            cur_headers, cur_rows = _read_csv(path)
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

            if not removed_entries:
                target["status"] = "failed"
                target["resolved_by"] = admin_user
                target["resolved_at"] = now
                target["rejection_reason"] = "Locked rows no longer found in CSV"
                _write_approval_queue(queue)
                _failed_evt = {
                    "timestamp": now, "analyst": admin_user,
                    "action": "request_failed", "status": "failed",
                    "detection_rule": target["detection_rule"],
                    "csv_file": csv_file, "app_context": app_context,
                    "request_id": request_id,
                    "requester": target["analyst"],
                    "approval_action_type": action_type,
                    "failure_reason": "Locked rows no longer found in CSV",
                    "comment": "{} failed to approve {} request created by {}".format(
                        admin_user, action_type.replace("_", " "),
                        target["analyst"]),
                }
                _failed_evt.update(self._extract_request_reasons(
                    action_type, stored_payload))
                self._index_audit(request, _failed_evt)
                return self._resp(409, {
                    "error": "The rows from this request no longer exist "
                             "in the CSV. Request has been marked as failed.",
                    "request_id": request_id,
                })

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
                target["status"] = "failed"
                target["resolved_by"] = admin_user
                target["resolved_at"] = now
                target["rejection_reason"] = (
                    "Column '{}' no longer exists".format(col_name))
                _write_approval_queue(queue)
                _failed_evt = {
                    "timestamp": now, "analyst": admin_user,
                    "action": "request_failed", "status": "failed",
                    "detection_rule": target["detection_rule"],
                    "csv_file": csv_file, "app_context": app_context,
                    "request_id": request_id,
                    "requester": target["analyst"],
                    "approval_action_type": action_type,
                    "failure_reason": "Column '{}' no longer exists".format(
                        col_name),
                    "comment": "{} failed to approve {} request created by {}".format(
                        admin_user, action_type.replace("_", " "),
                        target["analyst"]),
                }
                _failed_evt.update(self._extract_request_reasons(
                    action_type, stored_payload))
                self._index_audit(request, _failed_evt)
                return self._resp(409, {
                    "error": "Column '{}' no longer exists in the CSV."
                             .format(col_name),
                    "request_id": request_id,
                })
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
                target["status"] = "failed"
                target["resolved_by"] = admin_user
                target["resolved_at"] = now
                target["rejection_reason"] = (
                    "New rows could not be identified from stored payload")
                _write_approval_queue(queue)
                _failed_evt = {
                    "timestamp": now, "analyst": admin_user,
                    "action": "request_failed", "status": "failed",
                    "detection_rule": target["detection_rule"],
                    "csv_file": csv_file, "app_context": app_context,
                    "request_id": request_id,
                    "requester": target["analyst"],
                    "approval_action_type": action_type,
                    "failure_reason": (
                        "New rows could not be identified from stored payload"),
                    "comment": "{} failed to approve {} request created by {}".format(
                        admin_user, action_type.replace("_", " "),
                        target["analyst"]),
                }
                _failed_evt.update(self._extract_request_reasons(
                    action_type, stored_payload))
                self._index_audit(request, _failed_evt)
                return self._resp(409, {
                    "error": "The rows from this request could not be "
                             "identified. Request has been marked as failed.",
                    "request_id": request_id,
                })

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
            lock_h = hl.get("headers") or [
                h for h in cur_headers if not h.startswith("_")
            ]
            row_keys = hl.get("row_keys", [])
            # Use Counter (not set) so duplicate identical rows are all matched
            locked_counts = Counter(json.dumps(rk) for rk in row_keys)

            if edit_col not in cur_headers:
                target["status"] = "failed"
                target["resolved_by"] = admin_user
                target["resolved_at"] = now
                target["rejection_reason"] = (
                    "Column '{}' no longer exists".format(edit_col))
                _write_approval_queue(queue)
                _failed_evt = {
                    "timestamp": now, "analyst": admin_user,
                    "action": "request_failed", "status": "failed",
                    "detection_rule": target["detection_rule"],
                    "csv_file": csv_file, "app_context": app_context,
                    "request_id": request_id,
                    "requester": target["analyst"],
                    "approval_action_type": action_type,
                    "failure_reason": "Column '{}' no longer exists".format(
                        edit_col),
                    "comment": "{} failed to approve {} request created by {}".format(
                        admin_user, action_type.replace("_", " "),
                        target["analyst"]),
                }
                _failed_evt.update(self._extract_request_reasons(
                    action_type, stored_payload))
                self._index_audit(request, _failed_evt)
                return self._resp(409, {
                    "error": "Column '{}' no longer exists in the CSV."
                             .format(edit_col),
                    "request_id": request_id,
                })

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

            if not edited_count:
                target["status"] = "failed"
                target["resolved_by"] = admin_user
                target["resolved_at"] = now
                target["rejection_reason"] = "Target rows no longer found in CSV"
                _write_approval_queue(queue)
                _failed_evt = {
                    "timestamp": now, "analyst": admin_user,
                    "action": "request_failed", "status": "failed",
                    "detection_rule": target["detection_rule"],
                    "csv_file": csv_file, "app_context": app_context,
                    "request_id": request_id,
                    "requester": target["analyst"],
                    "approval_action_type": action_type,
                    "failure_reason": "Target rows no longer found in CSV",
                    "comment": "{} failed to approve {} request created by {}".format(
                        admin_user, action_type.replace("_", " "),
                        target["analyst"]),
                }
                _failed_evt.update(self._extract_request_reasons(
                    action_type, stored_payload))
                self._index_audit(request, _failed_evt)
                return self._resp(409, {
                    "error": "The rows from this request no longer exist "
                             "in the CSV. Request has been marked as failed.",
                    "request_id": request_id,
                })

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
            # Create/delete actions: replay the original action directly.
            # These don't go through _save_csv — they use their own methods.
            _method_map = {
                "create_csv": self._create_csv,
                "create_rule": self._create_rule,
                "remove_csv": self._remove_csv,
                "remove_rule": self._remove_rule,
            }
            method = _method_map[action_type]

            replay_payload = dict(stored_payload)
            replay_payload["_from_approval"] = True
            # Ensure key fields are present even if original_payload was
            # not stored (e.g., direct submit_approval call)
            if not replay_payload.get("detection_rule"):
                replay_payload["detection_rule"] = target.get(
                    "detection_rule", "")
            if not replay_payload.get("csv_file"):
                replay_payload["csv_file"] = csv_file
            if not replay_payload.get("app_context"):
                replay_payload["app_context"] = app_context

            result = method(request, replay_payload, original_analyst)

            result_body = json.loads(result.get("payload", "{}"))
            if result.get("status", 500) >= 400:
                fail_reason = result_body.get("error", "Unknown error")
                target["status"] = "failed"
                target["resolved_by"] = admin_user
                target["resolved_at"] = now
                target["rejection_reason"] = "Execution failed: " + fail_reason
                _write_approval_queue(queue)
                self._index_audit(request, {
                    "timestamp": now, "analyst": admin_user,
                    "action": "request_failed", "status": "failed",
                    "detection_rule": target["detection_rule"],
                    "csv_file": csv_file, "app_context": app_context,
                    "request_id": request_id,
                    "requester": target["analyst"],
                    "approval_action_type": action_type,
                    "failure_reason": "Execution failed: " + fail_reason,
                    "comment": "{} failed to execute {} request by {}".format(
                        admin_user, action_type.replace("_", " "),
                        target["analyst"]),
                })
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
            path = _resolve_csv_path(csv_file, app_context)
            if path is None:
                fallback = os.path.join(OWN_LOOKUPS, csv_file)
                if os.path.isfile(fallback) and _safe_realpath(fallback, APPS_DIR):
                    path = _safe_realpath(fallback, APPS_DIR)
            if path is None:
                return self._resp(404, {"error": "CSV file not found"})
            headers, rows = _read_csv(path)
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
                if isinstance(val, int) and 0 <= val <= 1000:
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
        """Reset daily usage counters for a specific analyst or all analysts."""
        analyst = payload.get("analyst", "")
        counters = _read_daily_limits()
        today = _get_counter_period_key()

        if today not in counters:
            return self._resp(200, {"message": "No usage to reset."})

        if analyst:
            if analyst in counters[today]:
                del counters[today][analyst]
                _write_daily_limits(counters)
                return self._resp(200, {
                    "message": "Daily usage reset for " + analyst
                })
            return self._resp(200, {
                "message": "No usage found for " + analyst
            })

        # Reset all analysts
        counters[today] = {}
        _write_daily_limits(counters)
        return self._resp(200, {"message": "Daily usage reset for all analysts"})

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

        user = self._get_user(request)
        ts = int(time.time())

        evt = {
            "timestamp":      ts,
            "analyst":        user,
            "action":         event_action,
            "detection_rule": _sanitize_text(
                payload.get("detection_rule", "")),
            "csv_file":       _sanitize_text(
                payload.get("csv_file", "")),
            "app_context":    _sanitize_text(
                payload.get("app_context", "")),
            "status":         _sanitize_text(
                payload.get("status", "success")),
            "export_file":    _sanitize_text(
                payload.get("export_file", "")),
            "comment":        _sanitize_text(
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

        Uses a direct HTTPS POST to Splunk's receivers/simple endpoint.
        No external SDK required — only Python's built-in urllib.
        """
        try:
            import urllib.request
            import urllib.parse
            import ssl

            # Use system auth token (from passSystemAuth in restmap.conf)
            # so non-admin users can still write audit events
            session_key = request.get("system_authtoken", "") or \
                request.get("session", {}).get("authtoken", "")
            if not session_key:
                return

            # Truncate value arrays to prevent oversized audit events
            if "value" in event and isinstance(event["value"], list):
                if len(event["value"]) > MAX_AUDIT_VALUE_LINES:
                    truncated_count = len(event["value"]) - MAX_AUDIT_VALUE_LINES
                    event["value"] = event["value"][:MAX_AUDIT_VALUE_LINES]
                    event["value"].append(
                        "... truncated {} more entries".format(truncated_count)
                    )

            qs = urllib.parse.urlencode({
                "index": AUDIT_INDEX,
                "sourcetype": AUDIT_SOURCETYPE,
                "source": AUDIT_SOURCE,
            })
            url = "https://127.0.0.1:8089/services/receivers/simple?%s" % qs
            event_data = json.dumps(event, default=str).encode("utf-8")

            req = urllib.request.Request(url, data=event_data, method="POST")
            req.add_header("Authorization", "Splunk %s" % session_key)
            req.add_header("Content-Type", "application/json")

            # SSL verification disabled intentionally: this request targets
            # localhost (127.0.0.1:8089) where Splunk uses a self-signed cert.
            # No data leaves the machine, so MITM risk is negligible.
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE

            urllib.request.urlopen(req, context=ctx, timeout=10)
        except Exception as exc:
            _logger.error("_index_audit error: %s", exc)

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
    def _get_user(request):
        return request.get("session", {}).get("user", "unknown")

    @staticmethod
    def _get_roles(request):
        """
        Look up the current user's roles via Splunk's REST API.

        The PersistentServerConnectionApplication session object only
        contains 'user' and 'authtoken' — roles must be fetched
        separately from /services/authentication/current-context.
        """
        try:
            import splunk.rest as rest
            session_key = request.get("session", {}).get("authtoken", "")
            if not session_key:
                return set()

            response, content = rest.simpleRequest(
                "/services/authentication/current-context",
                sessionKey=session_key,
                getargs={"output_mode": "json"},
            )
            data = json.loads(content)
            roles = data.get("entry", [{}])[0].get("content", {}).get("roles", [])
            return set(roles)
        except Exception as exc:
            _logger.error("Failed to fetch user roles: %s", exc)
            return set()

    @staticmethod
    def _resp(status, body):
        return {
            "status": status,
            "headers": {"Content-Type": "application/json"},
            "payload": json.dumps(body, default=str),
        }
