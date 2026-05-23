"""Shared helpers for Python E2E workflow tests.

Why this module exists: the legacy workflow tests created a unique CSV
per test via `rest_client.post_action("create_csv", {...})`, then tried
to load it via the UI dropdown. That never worked because:

  1. The real `create_csv` REST action requires a `detection_rule` to
     attach the CSV to, plus app_context, plus may go through approval.
  2. The UI dropdown is sourced from `rule_csv_map.csv`, which has
     only 3 mappings (DR55_brute_force_users.csv, DR55_brute_force_src.csv,
     DR130_priv_escalation.csv as of 2026-05-23). A dynamically-created
     CSV is never in this map, so it's never selectable from the UI.

The proven pattern (from `tests/e2e/test_wl_save.py`) is to operate on
an EXISTING mapped CSV, backing up its contents at test start and
restoring at test end. That's what the helpers below provide.

Reference rule + CSV defaults: DR55_brute_force_login +
DR55_brute_force_users.csv. The DR55 rule maps multiple CSVs
(brute_force_users + brute_force_src) — using the `_users` CSV by
default. For tests that need a different schema (different columns),
pass an explicit csv_name.
"""
import time
import urllib3
from typing import Any, Dict, Optional

DEFAULT_RULE = "DR55_brute_force_login"
DEFAULT_CSV = "DR55_brute_force_users.csv"
APP = "wl_manager"


def backup_csv(rest_client, csv_name: str = DEFAULT_CSV) -> Dict[str, Any]:
    """Read current CSV contents. Returns {headers, rows, content_hash, ...}
    or {} on failure (callers should treat as missing baseline)."""
    urllib3.disable_warnings()
    return rest_client.get_action("get_csv_content", {
        "csv_file": csv_name,
        "app": APP,
    })


def restore_csv(rest_client, bak: Dict[str, Any], csv_name: str = DEFAULT_CSV,
                rule_name: str = DEFAULT_RULE) -> None:
    """Write back the backed-up contents. Idempotent on the happy path."""
    if not bak or "headers" not in bak:
        return
    rest_client.post_action("save_csv", {
        "csv_file": csv_name,
        "app_context": APP,
        "detection_rule": rule_name,
        "headers": bak["headers"],
        "rows": bak["rows"],
        "comment": "E2E test restore",
        "removal_reasons": [],
    })
    time.sleep(0.3)


def clear_pending_for_csv(rest_client, csv_name: str = DEFAULT_CSV) -> None:
    """Reject all pending approval requests for csv_name. Necessary because
    a previous test that submitted-for-approval may leave queue entries
    that block subsequent save attempts on the same CSV."""
    q = rest_client.get_action("get_approval_queue", {})
    items = q.get("approval_queue") or q.get("items") or []
    for it in items:
        csv = (
            it.get("csv_file")
            or it.get("payload", {}).get("csv_file")
            or it.get("meta", {}).get("csv_file")
        )
        if csv == csv_name or csv is None:
            req_id = it.get("request_id") or it.get("id")
            if req_id:
                rest_client.post_action("process_approval", {
                    "request_id": req_id,
                    "decision": "reject",
                    "rejection_reason": "E2E cleanup",
                    "admin_comment": "auto",
                })


def setup_clean(rest_client, csv_name: str = DEFAULT_CSV) -> Dict[str, Any]:
    """Compose: clear pending + backup. Returns the backup for teardown."""
    clear_pending_for_csv(rest_client, csv_name)
    return backup_csv(rest_client, csv_name)


def teardown_clean(rest_client, bak: Dict[str, Any],
                   csv_name: str = DEFAULT_CSV,
                   rule_name: str = DEFAULT_RULE) -> None:
    """Compose: clear pending + restore. Best-effort; never raises."""
    try:
        clear_pending_for_csv(rest_client, csv_name)
        restore_csv(rest_client, bak, csv_name, rule_name)
    except Exception as e:
        print(f"teardown_clean: {e}")
