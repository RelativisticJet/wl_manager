"""
User presence tracking for Whitelist Manager.

Tracks which users are actively editing which CSV files (for
collaborative awareness).

Ring 6.1 Day 6.1.9a — R6-F8 fix:
    Previously stored presence in a module-level ``_presence`` dict.
    Splunk's PersistentScriptHandler runs N worker processes, each
    with its own copy of the dict, so the "X is also viewing this
    CSV" indicator was unreliable — analysts whose requests hit
    different workers missed each other's presence.

    Migrated to a Splunk KV collection (``wl_presence_state``)
    keyed by csv_file with a JSON envelope of
    ``{user: {last_activity, idle_minutes}}``. KV writes serialize
    across workers by design, so every worker now sees the same
    presence state. The module-level ``_presence`` dict is kept
    as a fallback for unit tests (which run without Splunk
    available) — production paths always pass session_key.

Returns (data_dict, error_string) tuples (handler wraps in HTTP
responses).

Layer 2: imports from wl_constants. KV access via splunk.rest is
loaded lazily to avoid breaking unit-test imports.
"""

import json
import time
from datetime import datetime, timezone
from typing import Dict, Tuple, Optional, List

__all__ = ["report_presence", "get_presence", "cleanup_presence",
           "reset_presence"]

# Module-level state — UNIT TEST FALLBACK ONLY. Production paths
# pass session_key and hit the KV-backed code path below.
_presence: Dict[str, Dict] = {}

# KV collection name (must match default/collections.conf).
_KV_COLLECTION = "wl_presence_state"


def _kv_url(key: str = "") -> str:
    """Return KV REST endpoint for the presence collection."""
    from wl_constants import APP_NAME
    base = ("/servicesNS/nobody/{}/storage/collections/data/{}"
            .format(APP_NAME, _KV_COLLECTION))
    return base + ("/" + key) if key else base


def _kv_read_csv(session_key: str, csv_file: str) -> Optional[Dict]:
    """Read presence record for one CSV. Returns dict or None."""
    import splunk
    import splunk.rest
    try:
        status, content = splunk.rest.simpleRequest(
            _kv_url(csv_file),
            sessionKey=session_key,
            getargs={"output_mode": "json"},
            raiseAllErrors=False,
        )
    except splunk.ResourceNotFound:
        return None
    except Exception:  # noqa: BLE001
        return None  # fail-open: degraded UX, not a security gap
    code = getattr(status, "status", 0)
    if code != 200:
        return None
    try:
        rec = json.loads(content)
    except (ValueError, TypeError):
        return None
    raw = rec.get("payload", "{}") if isinstance(rec, dict) else "{}"
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        return parsed if isinstance(parsed, dict) else {}
    except (ValueError, TypeError):
        return {}


def _kv_write_csv(session_key: str, csv_file: str,
                  users: Dict) -> bool:
    """Insert-or-update presence record for one CSV.

    KV semantics: PUT to /<collection>/<key> updates if exists,
    POST to /<collection> with _key creates. We try update first
    then fall back to insert on 404 — same idiom as
    _kv_put_cooldown_record in wl_handler.py.
    """
    import splunk
    import splunk.rest
    body = {
        "_key": csv_file,
        "payload": json.dumps(users, default=str),
        "updated_at": int(time.time()),
    }
    update_url = _kv_url(csv_file)
    insert_url = _kv_url()

    def _do_insert() -> bool:
        try:
            status, _ = splunk.rest.simpleRequest(
                insert_url,
                sessionKey=session_key,
                method="POST",
                jsonargs=json.dumps(body),
                raiseAllErrors=False,
            )
            return getattr(status, "status", 0) in (200, 201)
        except Exception:  # noqa: BLE001
            return False

    try:
        # Update existing record. POST against the keyed URL is
        # the KV update verb (idiomatic per the cooldown helper).
        status, _ = splunk.rest.simpleRequest(
            update_url,
            sessionKey=session_key,
            method="POST",
            jsonargs=json.dumps({"payload": body["payload"],
                                 "updated_at": body["updated_at"]}),
            raiseAllErrors=False,
        )
        code = getattr(status, "status", 0)
        if code in (200, 201):
            return True
        if code == 404:
            return _do_insert()
        return False
    except splunk.ResourceNotFound:
        return _do_insert()
    except Exception:  # noqa: BLE001
        return False


def _kv_delete_csv(session_key: str, csv_file: str) -> bool:
    """Delete the presence record for one CSV. Best-effort."""
    import splunk
    import splunk.rest
    try:
        splunk.rest.simpleRequest(
            _kv_url(csv_file),
            sessionKey=session_key,
            method="DELETE",
            raiseAllErrors=False,
        )
        return True
    except Exception:  # noqa: BLE001
        return False


def _kv_list_all(session_key: str) -> Dict[str, Dict]:
    """List all presence records as {csv_file: users_dict}.

    Used by cleanup_presence to scan and age out stale entries.
    Returns empty dict on KV unreachable (fail-open).
    """
    import splunk.rest
    try:
        status, content = splunk.rest.simpleRequest(
            _kv_url(),
            sessionKey=session_key,
            getargs={"output_mode": "json"},
            raiseAllErrors=False,
        )
    except Exception:  # noqa: BLE001
        return {}
    code = getattr(status, "status", 0)
    if code != 200:
        return {}
    try:
        records = json.loads(content)
    except (ValueError, TypeError):
        return {}
    if not isinstance(records, list):
        return {}
    out: Dict[str, Dict] = {}
    for rec in records:
        if not isinstance(rec, dict):
            continue
        key = rec.get("_key")
        if not key:
            continue
        raw = rec.get("payload", "{}")
        try:
            parsed = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(parsed, dict):
                out[key] = parsed
        except (ValueError, TypeError):
            continue
    return out


def report_presence(csv_file: str, user: str,
                    last_activity: Optional[float] = None,
                    session_key: Optional[str] = None
                    ) -> Tuple[Dict, str]:
    """
    Report that a user is actively editing a CSV.

    Args:
        csv_file: CSV filename being edited
        user: Username
        last_activity: Timestamp of last activity (defaults to now)
        session_key: Splunk session key — when provided, state is
            read/written through KV (cross-worker safe). When None
            (unit tests), falls back to module-level dict.

    Returns:
        ({data}, "error message" or "")
    """
    from wl_constants import (
        MAX_PRESENCE_FILES,
        MAX_PRESENCE_USERS,
        PRESENCE_TIMEOUT,
    )

    if not csv_file or not user:
        return ({}, "csv_file and user are required")

    now = time.time()
    if last_activity is None:
        last_activity = now

    use_kv = bool(session_key)

    # ── Read current state ────────────────────────────────────
    if use_kv:
        # Fetch this CSV's record + a listing to enforce
        # MAX_PRESENCE_FILES.
        users = _kv_read_csv(session_key, csv_file) or {}
        all_records = _kv_list_all(session_key)
    else:
        users = dict(_presence.get(csv_file, {}))
        all_records = dict(_presence)

    # ── Cleanup stale users for this CSV ──────────────────────
    users = {u: d for u, d in users.items()
             if isinstance(d, dict)
             and now - d.get("last_activity", 0) <= PRESENCE_TIMEOUT}

    # ── Enforce MAX_PRESENCE_FILES (only if this CSV is new) ──
    if csv_file not in all_records and len(all_records) >= MAX_PRESENCE_FILES:
        return ({},
                "Presence tracking at limit ({} files)".format(
                    MAX_PRESENCE_FILES))

    # ── Enforce MAX_PRESENCE_USERS (only if user is new here) ─
    if user not in users and len(users) >= MAX_PRESENCE_USERS:
        return ({},
                "Too many users editing {} ({} limit)".format(
                    csv_file, MAX_PRESENCE_USERS))

    # ── Record presence ───────────────────────────────────────
    users[user] = {
        "last_activity": last_activity,
        "idle_minutes": int((now - last_activity) / 60)
                          if last_activity else 0,
    }

    # ── Persist ───────────────────────────────────────────────
    if use_kv:
        _kv_write_csv(session_key, csv_file, users)
    else:
        _presence[csv_file] = users

    # ── Build response ────────────────────────────────────────
    presence_list = []
    for u, data in users.items():
        idle_min = int((now - data.get("last_activity", now)) / 60)
        presence_list.append({"user": u, "idle_minutes": idle_min})
    active_users = [p["user"] for p in presence_list]

    return ({"presence": presence_list,
             "active_users": active_users}, "")


def get_presence(csv_file: str,
                 session_key: Optional[str] = None
                 ) -> Tuple[Dict, str]:
    """
    Get current presence data for a CSV file.

    Args:
        csv_file: CSV filename to query.
        session_key: When provided, read from KV. Otherwise read
            from in-memory dict (unit tests).
    """
    now = time.time()

    if session_key:
        users = _kv_read_csv(session_key, csv_file) or {}
    else:
        users = dict(_presence.get(csv_file, {}))

    if not users:
        return ({"presence": []}, "")

    presence_list = []
    for user, data in users.items():
        if not isinstance(data, dict):
            continue
        idle_min = int((now - data.get("last_activity", now)) / 60)
        presence_list.append({"user": user, "idle_minutes": idle_min})

    return ({"presence": presence_list}, "")


def cleanup_presence(max_idle_minutes: int = 30,
                     session_key: Optional[str] = None) -> int:
    """
    Remove users who haven't been active for max_idle_minutes.

    Returns the number of users removed.
    """
    now = time.time()
    cutoff = now - max_idle_minutes * 60
    removed = 0

    if session_key:
        all_records = _kv_list_all(session_key)
        for csv_file, users in all_records.items():
            kept = {u: d for u, d in users.items()
                    if isinstance(d, dict)
                    and d.get("last_activity", 0) > cutoff}
            removed += len(users) - len(kept)
            if not kept:
                _kv_delete_csv(session_key, csv_file)
            elif len(kept) != len(users):
                _kv_write_csv(session_key, csv_file, kept)
        return removed

    # In-memory path (unit tests)
    stale_csvs = []
    for csv_file, users in _presence.items():
        users_to_remove = [
            u for u, data in users.items()
            if isinstance(data, dict)
            and now - data.get("last_activity", 0) > max_idle_minutes * 60
        ]
        for u in users_to_remove:
            del users[u]
            removed += 1
        if not users:
            stale_csvs.append(csv_file)
    for csv in stale_csvs:
        del _presence[csv]
    return removed


def reset_presence(session_key: Optional[str] = None) -> None:
    """Reset all presence data. Used for testing."""
    if session_key:
        all_records = _kv_list_all(session_key)
        for csv_file in all_records:
            _kv_delete_csv(session_key, csv_file)
    _presence.clear()
