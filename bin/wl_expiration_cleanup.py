#!/usr/bin/env python3
"""
Scheduled expiration cleanup for Whitelist Manager.

Splunk scripted input that runs on a schedule (see ``default/inputs.conf``).
Iterates all CSVs from rule_csv_map.csv, removes expired rows, writes cleaned
CSVs back, and indexes audit events to wl_audit.

Delegates expired-row detection to ``wl_csv.remove_expired_rows`` so there
is a single source of truth for expiration semantics (UTC format, legacy
format, timezone handling). See ``tests/test_wl_expiration_cleanup.py``.

Session key is read from stdin (standard Splunk scripted input pattern).
"""

from __future__ import annotations

import json
import os
import re
import ssl
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Dict, List, Tuple

# Make ``bin/`` importable when this script is launched by splunkd.
_BIN_DIR = os.path.dirname(os.path.abspath(__file__))
if _BIN_DIR not in sys.path:
    sys.path.insert(0, _BIN_DIR)

from wl_csv import (  # noqa: E402
    get_expire_column,
    read_csv,
    remove_expired_rows,
    write_csv,
)

APP_NAME = "wl_manager"
SPLUNK_HOME = os.environ.get("SPLUNK_HOME", "/opt/splunk")
APPS_DIR = os.path.join(SPLUNK_HOME, "etc", "apps")
OWN_LOOKUPS = os.path.join(APPS_DIR, APP_NAME, "lookups")
MAPPING_FILE = os.path.join(OWN_LOOKUPS, "rule_csv_map.csv")
AUDIT_INDEX = "wl_audit"
AUDIT_SOURCE = "wl_manager"
AUDIT_SOURCETYPE = "wl_audit"

# Server-side scheduled cleanup has no browser timezone context. Legacy
# (no-suffix) expiration values are therefore interpreted as UTC to match
# the handler's ``tz_offset_minutes=0`` contract. Analysts who need
# precise timezone behavior should use the new " UTC"-suffixed format.
# Decision: CLAUDE.md Decision Log entry dated 2026-04-19.
SCHEDULED_TZ_OFFSET_MINUTES = 0


def read_session_key() -> str:
    """Read the Splunk session key from stdin (passed by splunkd)."""
    raw = sys.stdin.read()
    match = re.search(r"<sessionKey>(.*?)</sessionKey>", raw)
    if match:
        return match.group(1)
    return raw.strip()


def partition_expired(
    headers: List[str],
    rows: List[Dict[str, str]],
) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
    """Partition ``rows`` into (kept, expired) using ``wl_csv`` semantics.

    ``wl_csv.remove_expired_rows`` only returns ``(kept, expired_count)`` so
    callers that do not need the row contents pay no memory cost. The
    scheduled cleanup DOES need the contents — to build ``value_lines``
    for the audit event — so it partitions via dict-identity: every row
    not in the kept set is expired.

    Row identity is preserved by ``wl_csv.remove_expired_rows`` (it does
    ``kept.append(row)``, not ``kept.append(dict(row))``), which makes the
    id-based set-difference reliable. See
    ``tests/test_wl_expiration_cleanup.py::test_returned_rows_are_original_objects``.
    """
    kept, _ = remove_expired_rows(
        headers, rows, tz_offset_minutes=SCHEDULED_TZ_OFFSET_MINUTES
    )
    kept_ids = {id(row) for row in kept}
    expired = [row for row in rows if id(row) not in kept_ids]
    return kept, expired


def index_audit(session_key: str, event: Dict) -> None:
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

        urllib.request.urlopen(req, context=ctx, timeout=10)  # nosec B310
    except Exception as exc:
        sys.stderr.write("wl_expiration_cleanup audit error: %s\n" % exc)


def main() -> None:
    session_key = read_session_key()

    if not os.path.isfile(MAPPING_FILE):
        sys.stderr.write(
            "wl_expiration_cleanup: mapping file not found: %s\n" % MAPPING_FILE
        )
        return

    # Local csv import only here — read() of the mapping file is a small,
    # cross-module concern; the per-CSV read/write is via wl_csv.
    import csv

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

        headers, rows = read_csv(path)

        if not get_expire_column(headers):
            continue

        kept, expired = partition_expired(headers, rows)

        if not expired:
            continue

        # wl_csv.write_csv writes atomically (temp + rename) and updates
        # the expected-hash registry — FIM will NOT flag this as tampering.
        write_csv(path, headers, kept)
        total_removed += len(expired)

        expired_clean = [
            {k: v for k, v in r.items() if not k.startswith("_")}
            for r in expired
        ]
        value_lines: List[str] = []
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
