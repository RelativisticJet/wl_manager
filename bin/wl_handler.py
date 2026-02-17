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
"""

import os
import sys
import json
import csv
import difflib
import logging
import logging.handlers
from datetime import datetime, timezone

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

# Roles allowed to WRITE (POST). Everyone authenticated can READ (GET).
EDIT_ROLES = {"wl_editor", "admin", "sc_admin"}

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


# ═══════════════════════════════════════════════════════════════════════════
# Utility helpers
# ═══════════════════════════════════════════════════════════════════════════

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
    return True


def _resolve_csv_path(csv_file, app_context=""):
    """
    Build the absolute path to a lookup CSV.

    If *app_context* is provided (e.g. "SplunkEnterpriseSecuritySuite"),
    the CSV is looked up under that app's lookups/ folder.  Otherwise
    we fall back to the wl_manager app's own lookups/ folder.
    """
    if not _safe_filename(csv_file):
        return None

    if app_context:
        safe_app = os.path.basename(app_context)  # prevent traversal
        path = os.path.join(APPS_DIR, safe_app, "lookups", csv_file)
    else:
        path = os.path.join(OWN_LOOKUPS, csv_file)

    return path if os.path.isfile(path) else None


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


def _compute_diff(old_headers, old_rows, new_headers, new_rows):
    """
    Compare old vs new CSV content and return a structured diff.

    Returns dict with keys:
        added          — list of row dicts that are new
        removed        — list of row dicts that were deleted
        added_count    — int
        removed_count  — int
        text_diff      — list of unified-diff lines (Git-style)
    """
    all_headers = list(dict.fromkeys(old_headers + new_headers))

    def _row_key(row):
        return tuple(row.get(h, "") for h in all_headers)

    old_keys = {_row_key(r) for r in old_rows}
    new_keys = {_row_key(r) for r in new_rows}

    added = [r for r in new_rows if _row_key(r) not in old_keys]
    removed = [r for r in old_rows if _row_key(r) not in new_keys]

    # Text-based unified diff (like `git diff`)
    def _rows_to_lines(headers, rows):
        lines = [",".join(headers)]
        for r in rows:
            lines.append(",".join(r.get(h, "") for h in headers))
        return lines

    old_lines = _rows_to_lines(old_headers or all_headers, old_rows)
    new_lines = _rows_to_lines(new_headers or all_headers, new_rows)
    text_diff = list(
        difflib.unified_diff(
            old_lines, new_lines, fromfile="before", tofile="after", lineterm=""
        )
    )

    return {
        "added": added,
        "removed": removed,
        "added_count": len(added),
        "removed_count": len(removed),
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

            if method == "GET":
                return self._handle_get(request)
            elif method == "POST":
                return self._handle_post(request)
            else:
                return self._resp(405, {"error": "Method not allowed"})
        except Exception as exc:
            _logger.error("Unhandled exception: %s", exc)
            return self._resp(500, {"error": str(exc)})

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
                query.get("csv_file", ""), query.get("app", "")
            )

        if action == "get_mapping":
            return self._get_mapping()

        return self._resp(400, {
            "error": "Missing or unknown action",
            "valid_actions": [
                "get_rules", "get_csvs", "get_csv_content", "get_mapping"
            ],
        })

    def _get_rules(self):
        mapping = self._read_mapping()
        rules = sorted({row["rule_name"] for row in mapping})
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

    def _get_csv_content(self, csv_file, app_context):
        path = _resolve_csv_path(csv_file, app_context)
        if path is None:
            # Try own lookups as fallback
            if _safe_filename(csv_file):
                fallback = os.path.join(OWN_LOOKUPS, csv_file)
                if os.path.isfile(fallback):
                    path = fallback
        if path is None:
            return self._resp(404, {"error": f"CSV file not found: {csv_file}"})

        headers, rows = _read_csv(path)
        return self._resp(200, {
            "csv_file": csv_file,
            "headers": headers,
            "rows": rows,
            "row_count": len(rows),
        })

    def _get_mapping(self):
        mapping = self._read_mapping()
        return self._resp(200, {"mapping": mapping})

    # ==================================================================
    # POST
    # ==================================================================
    def _handle_post(self, request):
        user = self._get_user(request)
        roles = self._get_roles(request)

        # ── RBAC check ────────────────────────────────────────────────
        if not roles.intersection(EDIT_ROLES):
            return self._resp(403, {
                "error": (
                    "Permission denied. "
                    "Your account requires one of these roles: "
                    + ", ".join(sorted(EDIT_ROLES))
                )
            })

        payload = json.loads(request.get("payload", "{}"))
        action = payload.get("action", "")

        if action == "save_csv":
            return self._save_csv(request, payload, user)

        return self._resp(400, {"error": "Unknown POST action. Valid: save_csv"})

    def _save_csv(self, request, payload, user):
        csv_file = payload.get("csv_file", "")
        app_context = payload.get("app_context", "")
        detection_rule = payload.get("detection_rule", "")
        new_headers = payload.get("headers", [])
        new_rows = payload.get("rows", [])
        analyst_comment = payload.get("comment", "")

        # ── Validate filename ─────────────────────────────────────────
        if not _safe_filename(csv_file):
            return self._resp(400, {"error": "Invalid CSV file name"})

        # ── Resolve path ──────────────────────────────────────────────
        path = _resolve_csv_path(csv_file, app_context)
        if path is None:
            fallback = os.path.join(OWN_LOOKUPS, csv_file)
            if os.path.isfile(fallback):
                path = fallback
        if path is None:
            return self._resp(404, {"error": f"CSV file not found: {csv_file}"})

        # ── Read BEFORE state ─────────────────────────────────────────
        old_headers, old_rows = _read_csv(path)
        if not new_headers:
            new_headers = old_headers

        # ── Compute diff ──────────────────────────────────────────────
        diff = _compute_diff(old_headers, old_rows, new_headers, new_rows)

        if diff["added_count"] == 0 and diff["removed_count"] == 0:
            return self._resp(200, {"message": "No changes detected", "diff": diff})

        # ── Write AFTER state ─────────────────────────────────────────
        _write_csv(path, new_headers, new_rows)

        # ── Audit event ──────────────────────────────────────────────
        audit_event = {
            "timestamp": datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%S.%fZ"
            ),
            "analyst": user,
            "detection_rule": detection_rule,
            "csv_file": csv_file,
            "app_context": app_context,
            "comment": analyst_comment,
            "rows_before": len(old_rows),
            "rows_after": len(new_rows),
            "rows_added": diff["added_count"],
            "rows_removed": diff["removed_count"],
            "added_entries": diff["added"],
            "removed_entries": diff["removed"],
            "text_diff": diff["text_diff"],
        }

        # 1) Rotating log file
        _logger.info(json.dumps(audit_event, default=str))

        # 2) Splunk index
        self._index_audit(request, audit_event)

        return self._resp(200, {
            "message": "CSV saved successfully",
            "diff": diff,
            "rows_before": len(old_rows),
            "rows_after": len(new_rows),
        })

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

            session_key = request.get("session", {}).get("authtoken", "")
            if not session_key:
                return

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

            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE

            urllib.request.urlopen(req, context=ctx, timeout=10)
        except Exception as exc:
            sys.stderr.write("wl_manager _index_audit error: %s\n" % exc)

    # ==================================================================
    # Internal helpers
    # ==================================================================
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
