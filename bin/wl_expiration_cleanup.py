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
import time
import urllib.error
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

# Recovery-log fallback path. When the authenticated audit POST fails
# (observed 401 Unauthorized when splunkd recycles the scripted-input
# session token, typically around restarts), we append the audit event
# here. The wl_audit_recovery monitor input tails this file and indexes
# each line into `index=wl_audit sourcetype=wl_audit_recovery`, so the
# event is still discoverable — it just lands under a different
# sourcetype. Far better than silently losing an auto-removed row after
# the CSV has already been mutated.
RECOVERY_LOG = os.path.join(OWN_LOOKUPS, "_versions", "_recovery_log.jsonl")

# Number of retries after an initial failure. A short retry catches the
# common transient case where the stdin-delivered session key is briefly
# not recognized by splunkd's auth subsystem (sub-second race on restart).
AUDIT_POST_RETRIES = 2
AUDIT_POST_RETRY_SLEEP = 1.0  # seconds

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


def _post_audit_once(session_key: str, event: Dict) -> Tuple[bool, str]:
    """Single audit POST attempt. Returns (success, short_error_description)."""
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

    try:
        urllib.request.urlopen(req, context=ctx, timeout=10)  # nosec B310
        return (True, "")
    except urllib.error.HTTPError as exc:
        return (False, "HTTP %s" % exc.code)
    except Exception as exc:
        return (False, type(exc).__name__)


def _append_recovery_log(event: Dict, last_error: str) -> bool:
    """Append a failed audit event to the recovery-log fallback.

    The file is monitored by the wl_audit_recovery input and indexed to
    wl_audit under a distinguishing sourcetype, so the event is visible
    in the Audit dashboard even though the authenticated REST path
    failed. Returns True on successful write.
    """
    try:
        os.makedirs(os.path.dirname(RECOVERY_LOG), exist_ok=True)
        record = dict(event)
        record["source_script"] = "wl_expiration_cleanup"
        record["audit_post_failed"] = True
        record["audit_post_error"] = last_error
        with open(RECOVERY_LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, default=str) + "\n")
        try:
            os.chmod(RECOVERY_LOG, 0o644)
        except OSError:
            pass  # not fatal if we can't chmod (e.g. non-owner)
        return True
    except Exception as exc:
        sys.stderr.write(
            "wl_expiration_cleanup recovery-log write failed: %s\n" % exc
        )
        return False


def index_audit(session_key: str, event: Dict) -> None:
    """Post audit event to Splunk, with retry + recovery-log fallback.

    CSV mutation has already happened by the time we get here, so a
    silent loss of the audit event would mean a whitelist entry
    vanished without a trail. The retry handles the common transient
    case; the fallback guarantees the event is not lost even when the
    authenticated REST path stays broken.
    """
    if not session_key:
        # Empty session key → no point calling /services/receivers/simple;
        # go straight to the fallback. This happens when stdin arrives
        # truncated (observed during splunkd restart races).
        _append_recovery_log(event, "empty_session_key")
        sys.stderr.write(
            "wl_expiration_cleanup: empty session key — "
            "wrote audit event to recovery log\n"
        )
        return

    last_error = ""
    for attempt in range(AUDIT_POST_RETRIES + 1):
        ok, err = _post_audit_once(session_key, event)
        if ok:
            if attempt > 0:
                sys.stderr.write(
                    "wl_expiration_cleanup: audit POST succeeded on "
                    "attempt %d\n" % (attempt + 1)
                )
            return
        last_error = err
        if attempt < AUDIT_POST_RETRIES:
            time.sleep(AUDIT_POST_RETRY_SLEEP)

    # All attempts failed — fall back to recovery log so the event is
    # not lost. The wl_audit_recovery monitor input will index it.
    if _append_recovery_log(event, last_error):
        sys.stderr.write(
            "wl_expiration_cleanup: audit POST failed after %d attempts "
            "(%s) — wrote to recovery log\n"
            % (AUDIT_POST_RETRIES + 1, last_error)
        )
    else:
        # Last resort: recovery log also failed. Log a LOUD error so
        # the failure is visible at least in splunkd.log even though we
        # have no other route left.
        sys.stderr.write(
            "wl_expiration_cleanup CRITICAL: audit POST and recovery-log "
            "write both failed. Audit event LOST. Last POST error: %s. "
            "Event payload: %s\n"
            % (last_error, json.dumps(event, default=str))
        )


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
