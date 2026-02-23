#!/usr/bin/env python3
"""
Scheduled expiration cleanup for Whitelist Manager.

Splunk scripted input that runs hourly (configurable in inputs.conf).
Iterates all CSVs from rule_csv_map.csv, removes expired rows,
writes cleaned CSVs back, and indexes audit events to wl_audit.

Session key is read from stdin (standard Splunk scripted input pattern).
"""

import os
import sys
import csv
import json
import re
import urllib.request
import urllib.parse
import ssl
from datetime import datetime, timezone

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


def find_expire_column(headers):
    """Return the first header that matches an expiration column name, or None."""
    for h in headers:
        if h.lower() in EXPIRE_COLUMN_NAMES:
            return h
    return None


def read_session_key():
    """Read the Splunk session key from stdin (passed by splunkd)."""
    raw = sys.stdin.read()
    m = re.search(r"<sessionKey>(.*?)</sessionKey>", raw)
    if m:
        return m.group(1)
    return raw.strip()


def read_csv_file(filepath):
    with open(filepath, "r", newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        headers = list(reader.fieldnames or [])
        rows = [dict(r) for r in reader]
    return headers, rows


def write_csv_file(filepath, headers, rows):
    with open(filepath, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def remove_expired_rows(headers, rows):
    """Filter out rows where an expiration column contains a past date/time.

    Expiration values are treated as local time (matching the user's browser).
    The scheduled cleanup uses the server's local time for comparison.
    """
    expire_col = find_expire_column(headers)
    if not expire_col:
        return rows, []

    now = datetime.now()          # server local time (naive)
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
                exp_date = datetime.strptime(exp_val, fmt)   # naive — local time
                parsed = True
                break
            except ValueError:
                continue
        if not parsed:
            kept.append(row)
            continue
        if exp_date < now:
            expired.append(row)
        else:
            kept.append(row)

    return kept, expired


def index_audit(session_key, event):
    """Post audit event to Splunk's receivers/simple endpoint."""
    try:
        qs = urllib.parse.urlencode({
            "index": AUDIT_INDEX,
            "sourcetype": AUDIT_SOURCETYPE,
            "source": AUDIT_SOURCE,
        })
        url = "https://127.0.0.1:8089/services/receivers/simple?%s" % qs
        data = json.dumps(event, default=str).encode("utf-8")

        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Authorization", "Splunk %s" % session_key)
        req.add_header("Content-Type", "application/json")

        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        urllib.request.urlopen(req, context=ctx, timeout=10)
    except Exception as exc:
        sys.stderr.write("wl_expiration_cleanup audit error: %s\n" % exc)


def main():
    session_key = read_session_key()

    if not os.path.isfile(MAPPING_FILE):
        sys.stderr.write(
            "wl_expiration_cleanup: mapping file not found: %s\n" % MAPPING_FILE
        )
        return

    with open(MAPPING_FILE, "r", newline="", encoding="utf-8-sig") as fh:
        mapping = list(csv.DictReader(fh))

    total_removed = 0

    for entry in mapping:
        csv_file = entry.get("csv_file", "")
        app_context = entry.get("app_context", "")
        rule_name = entry.get("rule_name", "")

        if not csv_file:
            continue

        if app_context:
            path = os.path.join(
                APPS_DIR, os.path.basename(app_context), "lookups", csv_file
            )
        else:
            path = os.path.join(OWN_LOOKUPS, csv_file)

        if not os.path.isfile(path):
            continue

        headers, rows = read_csv_file(path)

        if not find_expire_column(headers):
            continue

        kept, expired = remove_expired_rows(headers, rows)

        if not expired:
            continue

        write_csv_file(path, headers, kept)
        total_removed += len(expired)

        expired_clean = [
            {k: v for k, v in r.items() if not k.startswith("_")}
            for r in expired
        ]
        value_lines = []
        for i, entry_row in enumerate(expired_clean, 1):
            for col, val in sorted(entry_row.items()):
                value_lines.append("{}_row_{}: {}".format(col, i, val))

        ts = int(datetime.now(timezone.utc).timestamp())
        evt = {
            "timestamp": ts,
            "analyst": "system",
            "detection_rule": rule_name,
            "csv_file": csv_file,
            "app_context": app_context,
            "comment": "Scheduled expiration cleanup",
            "action": "auto_removed",
            "removed_row_count": len(expired),
            "value": value_lines,
            "remove_reason": "Expired",
        }
        index_audit(session_key, evt)

        sys.stderr.write(
            "wl_expiration_cleanup: removed %d expired row(s) from %s\n"
            % (len(expired), csv_file)
        )

    sys.stderr.write(
        "wl_expiration_cleanup: complete. Total removed: %d\n" % total_removed
    )


if __name__ == "__main__":
    main()
