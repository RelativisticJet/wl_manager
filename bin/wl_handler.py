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

# Column names treated as expiration dates (case-insensitive matching).
EXPIRE_COLUMN_NAMES = {
    "expires", "expire", "expiration", "expiration_date",
    "expiry", "termination", "termination_date",
}

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


def _remove_expired_rows(headers, rows, tz_offset_minutes=0):
    """
    Filter out rows where an expiration column contains a past date/time.

    Returns (kept_rows, expired_rows) where:
        kept_rows    — rows that are still valid (empty = permanent)
        expired_rows — rows that were removed due to expiration

    Date format expected: YYYY-MM-DD HH:MM  (also tolerates YYYY-MM-DD).

    Expiration values are treated as the user's local time.
    *tz_offset_minutes* is the value of JavaScript's
    ``Date.getTimezoneOffset()`` — minutes the user's timezone is
    **behind** UTC (e.g. UTC+2 → -120).  We convert the current UTC time
    to the user's local time before comparing.
    """
    expire_col = _find_expire_column(headers)
    if not expire_col:
        return rows, []

    # Convert UTC "now" to the user's local time so comparisons
    # match what the user sees in their browser.
    now_utc = datetime.now(timezone.utc)
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
        parsed = False
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                exp_date = datetime.strptime(exp_val, fmt)   # naive — user's local
                parsed = True
                break
            except ValueError:
                continue
        if not parsed:
            kept.append(row)
            continue
        if exp_date < now_local:
            expired.append(row)
        else:
            kept.append(row)

    return kept, expired


def _compute_diff(old_headers, old_rows, new_headers, new_rows):
    """
    Compare old vs new CSV content and return a structured diff.

    Returns dict with keys:
        added          — list of row dicts that are new
        removed        — list of row dicts that were deleted
        edited         — list of dicts with keys: old_row, new_row, row_num,
                         changed_fields (list of {field, before, after})
        added_count    — int
        removed_count  — int
        edited_count   — int
        text_diff      — list of unified-diff lines (Git-style)
    """
    all_headers = list(dict.fromkeys(old_headers + new_headers))

    # Only compare visible (non-metadata) columns for diff detection.
    # Internal _ columns (_added_by, _added_at, _review_status) are
    # bookkeeping and should not trigger change events.
    visible_headers = [h for h in all_headers if not h.startswith("_")]

    def _row_key(row):
        return tuple(row.get(h, "") for h in visible_headers)

    old_keys = {_row_key(r) for r in old_rows}
    new_keys = {_row_key(r) for r in new_rows}

    added_raw = [r for r in new_rows if _row_key(r) not in old_keys]
    removed_raw = [r for r in old_rows if _row_key(r) not in new_keys]

    # ── Detect edits: match by row position ─────────────────────
    # When a user edits cells, the row stays at the same CSV index.
    # Compare old_rows[i] vs new_rows[i] — if they differ and the
    # old version is in removed_raw / new version in added_raw, it's
    # an edit, not a separate remove + add.
    edited = []

    # Build fast lookup sets for the raw added/removed keys
    removed_key_set = {_row_key(r) for r in removed_raw}
    added_key_set = {_row_key(r) for r in added_raw}

    # Track which raw added/removed entries are consumed by edits
    paired_old_keys = set()   # keys from removed_raw that became edits
    paired_new_keys = set()   # keys from added_raw   that became edits

    for i in range(min(len(old_rows), len(new_rows))):
        old_k = _row_key(old_rows[i])
        new_k = _row_key(new_rows[i])

        if old_k == new_k:
            continue  # unchanged row

        # Both sides must be in the raw diff lists (old was "removed",
        # new was "added") for this to be a genuine positional edit.
        if old_k not in removed_key_set or new_k not in added_key_set:
            continue

        changed_fields = []
        for h in visible_headers:
            old_val = old_rows[i].get(h, "")
            new_val = new_rows[i].get(h, "")
            if old_val != new_val:
                changed_fields.append({
                    "field": h, "before": old_val, "after": new_val
                })

        if changed_fields:
            edited.append({
                "old_row": old_rows[i],
                "new_row": new_rows[i],
                "row_num": i + 1,          # 1-based
                "changed_fields": changed_fields,
            })
            paired_old_keys.add(old_k)
            paired_new_keys.add(new_k)

    # Remove paired rows from added/removed lists
    added = [r for r in added_raw if _row_key(r) not in paired_new_keys]
    removed = [r for r in removed_raw if _row_key(r) not in paired_old_keys]

    # Text-based unified diff (like `git diff`)
    def _rows_to_lines(headers, rows):
        lines = [",".join(headers)]
        for r in rows:
            lines.append(",".join(r.get(h, "") for h in headers))
        return lines

    # Use only visible headers for the text diff so metadata columns
    # don't pollute the human-readable output.
    old_vis = [h for h in (old_headers or all_headers) if not h.startswith("_")]
    new_vis = [h for h in (new_headers or all_headers) if not h.startswith("_")]
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
                request, query.get("csv_file", ""), query.get("app", ""),
                query.get("tz_offset", "0"),
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

    def _get_csv_content(self, request, csv_file, app_context, tz_offset="0"):
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

        return self._resp(200, {
            "csv_file": csv_file,
            "headers": headers,
            "rows": rows,
            "row_count": len(rows),
            "auto_removed_count": auto_removed_count,
            "expire_column": _find_expire_column(headers) or "",
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

        return self._resp(400, {
            "error": "Unknown POST action. Valid: save_csv"
        })

    def _save_csv(self, request, payload, user):
        csv_file = payload.get("csv_file", "")
        app_context = payload.get("app_context", "")
        detection_rule = payload.get("detection_rule", "")
        new_headers = payload.get("headers", [])
        new_rows = payload.get("rows", [])
        analyst_comment = payload.get("comment", "")
        removal_reasons = payload.get("removal_reasons", [])
        bulk_removal = payload.get("bulk_removal", [])

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

        if diff["added_count"] == 0 and diff["removed_count"] == 0 and diff["edited_count"] == 0:
            return self._resp(200, {"message": "No changes detected", "diff": diff})

        # ── Stamp row-level history on newly added rows ──────────────
        ts_now = str(int(datetime.now(timezone.utc).timestamp()))

        added_set = set()
        visible_headers = [h for h in new_headers if not h.startswith("_")]
        for entry in diff["added"]:
            key = tuple(entry.get(h, "") for h in visible_headers)
            added_set.add(key)

        for row in new_rows:
            key = tuple(row.get(h, "") for h in visible_headers)
            if key in added_set:
                row["_added_by"] = user
                row["_added_at"] = ts_now

        # Ensure metadata columns are in the header list for CSV write
        write_headers = list(new_headers)
        for meta in ("_added_by", "_added_at"):
            if meta not in write_headers:
                write_headers.append(meta)

        # ── Write AFTER state ─────────────────────────────────────────
        _write_csv(path, write_headers, new_rows)

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

        # ── Helper: strip internal _ columns from a row ────────────────
        def _clean_entry(row):
            return {k: v for k, v in row.items() if not k.startswith("_")}

        # ── Helper: build numbered fields + "value" summary string ────
        # Returns (numbered_dict, value_string) where:
        #   numbered_dict = {"user_row_3": "jsmith", "src_ip_row_3": "10.0.0.1"}
        #   value_list    = ["user_row_3: jsmith", "src_ip_row_3: 10.0.0.1", ...]
        def _build_row_fields(entries, row_num_map):
            numbered = {}
            lines = []
            for entry in entries:
                row_num = row_num_map.get(_visible_key(entry), 0)
                cleaned = _clean_entry(entry)
                for col_name, col_val in sorted(cleaned.items()):
                    field_name = "{}_row_{}".format(col_name, row_num)
                    numbered[field_name] = col_val
                    lines.append("{}: {}".format(field_name, col_val))
            return numbered, lines

        # ── Map added rows to row numbers in the NEW csv ─────────────
        # Row number = position in new_rows (1-based)
        added_row_map = {}
        for entry in diff["added"]:
            ekey = _visible_key(entry)
            for i, row in enumerate(new_rows):
                if _visible_key(row) == ekey and ekey not in added_row_map:
                    added_row_map[ekey] = i + 1
                    break

        # ── "added" audit event (single event for all added rows) ────
        if diff["added_count"] > 0:
            added_numbered, added_values = _build_row_fields(
                diff["added"], added_row_map
            )
            evt = dict(common, **{
                "action": "added",
                "added_row_count": diff["added_count"],
                "added_values": added_numbered,
                "value": added_values,
                "added_by": user,
                "added_at": ts,
            })
            self._index_audit(request, evt)

        # ── Removal audit events ─────────────────────────────────────
        if bulk_removal and diff["removed_count"] > 0:
            # Bulk removal via "Remove Selected" button
            bulk_reason = bulk_removal[0].get("reason", "") if bulk_removal else ""

            bulk_row_map = {}
            for br in bulk_removal:
                br_row = br.get("row", {})
                bulk_row_map[_visible_key(br_row)] = br.get("row_number", 0)

            removed_numbered, removed_values = _build_row_fields(
                diff["removed"], bulk_row_map
            )
            evt = dict(common, **{
                "action": "removed_multiple" if diff["removed_count"] > 1 else "removed",
                "removed_row_count": diff["removed_count"],
                "removed_values": removed_numbered,
                "value": removed_values,
                "remove_reason": bulk_reason,
                "removed_by": user,
                "removed_at": ts,
            })
            self._index_audit(request, evt)
        elif diff["removed_count"] > 0:
            # Single row removal via "Remove" button
            single_row_map = {}
            single_reason = ""
            for rr in removal_reasons:
                rr_row = rr.get("row", {})
                single_row_map[_visible_key(rr_row)] = rr.get("row_number", 0)
                single_reason = rr.get("reason", "")

            removed_numbered, removed_values = _build_row_fields(
                diff["removed"], single_row_map
            )
            evt = dict(common, **{
                "action": "removed",
                "removed_row_count": diff["removed_count"],
                "removed_values": removed_numbered,
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

            evt = dict(common, **{
                "action": "edited",
                "edited_row_count": diff["edited_count"],
                "edited_values": edit_details,
                "value": edit_value_lines,
                "edited_by": user,
                "edited_at": ts,
            })
            self._index_audit(request, evt)

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
