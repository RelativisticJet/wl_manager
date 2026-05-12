"""
Rate limiting for Whitelist Manager REST API.

Provides sliding-window rate limiting per user and action type.

Ring 6.1 Day 6.1.9b — R6-F8 sibling fix:
    Previously stored ``_rate_limits`` as a module-level dict.
    Splunk's PersistentScriptHandler runs N worker processes, each
    with its own copy of the dict — so one user's writes routed
    across workers bypassed RATE_MAX_WRITES=30/60s independently
    per worker. Effective cap was ~30*N writes/60s, a 4-8x silent
    over-allowance on the defense-in-depth API-abuse control in
    typical production deployments.

    Migrated to a Splunk KV collection (``wl_ratelimit_state``)
    keyed by ``"<user>::<action_type>"`` with a JSON list of
    recent request timestamps. KV writes serialize across workers
    by design, so the cap is now enforced once across the entire
    handler pool.

Layer 2: imports only from wl_constants. KV access via
splunk.rest is loaded lazily.

Dual-mode (intentional): when ``session_key=None`` the functions
fall back to the module-level ``_rate_limits`` dict so unit tests
can exercise the math without a live Splunk container.
"""

import json
import os
import tempfile
import time
from typing import Dict, Tuple, List, Optional

__all__ = ["check_rate_limit", "reset_rate_limits"]

# Module-level state — UNIT TEST FALLBACK ONLY. Production paths
# pass session_key and hit the KV-backed code path below.
_rate_limits: Dict[Tuple[str, str], List[float]] = {}

_KV_COLLECTION = "wl_ratelimit_state"


def _kv_url(key: str = "") -> str:
    from wl_constants import APP_NAME
    base = ("/servicesNS/nobody/{}/storage/collections/data/{}"
            .format(APP_NAME, _KV_COLLECTION))
    return base + ("/" + key) if key else base


def _rmw_lock_path(user: str, action_type: str) -> str:
    """Per-(user, action_type) lock file path.

    Ring 6.1 Day 6.1.9b: KV alone doesn't fix the RMW race —
    60 parallel requests all read the empty bucket, all see
    "0 < cap", all pass, all write back their own single
    timestamp (last write wins). The cap is bypassed by the
    full parallelism degree. The cross-process file lock
    serializes the check+execute+write sequence within a
    single user/action bucket so the cap is enforced exactly.
    Different users / different action_types do NOT serialize
    against each other (per-key lock granularity).
    """
    safe = "".join(
        c if (c.isalnum() or c in "_.-") else "_"
        for c in (user + "_" + action_type))
    if not safe:
        safe = "_anon"
    return os.path.join(
        tempfile.gettempdir(),
        "wl_ratelimit_{}.rmw.lock".format(safe))


def _kv_key(user: str, action_type: str) -> str:
    """Compose the KV record key. Reversible by callers if needed."""
    # ASCII delimiter unlikely to occur in usernames; if it does,
    # the worst case is collision with another user/action pair —
    # rate limiting is approximate by design, so collision-induced
    # coupling between two users is acceptable as a known
    # trade-off.
    return "{}::{}".format(user, action_type)


def _kv_read_timestamps(session_key: str, user: str,
                        action_type: str) -> List[float]:
    """Read timestamp list for (user, action_type). [] on miss/error."""
    import splunk
    import splunk.rest
    try:
        status, content = splunk.rest.simpleRequest(
            _kv_url(_kv_key(user, action_type)),
            sessionKey=session_key,
            getargs={"output_mode": "json"},
            raiseAllErrors=False,
        )
    except splunk.ResourceNotFound:
        return []
    except Exception:  # noqa: BLE001
        return []  # fail-open: degraded enforcement, not security
    code = getattr(status, "status", 0)
    if code != 200:
        return []
    try:
        rec = json.loads(content)
    except (ValueError, TypeError):
        return []
    raw = rec.get("payload", "[]") if isinstance(rec, dict) else "[]"
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except (ValueError, TypeError):
        return []
    if not isinstance(parsed, list):
        return []
    # Filter to numeric timestamps only — defensive against
    # malformed records.
    return [float(t) for t in parsed
            if isinstance(t, (int, float))]


def _kv_write_timestamps(session_key: str, user: str,
                         action_type: str,
                         timestamps: List[float]) -> bool:
    """Upsert the timestamp list for (user, action_type)."""
    import splunk
    import splunk.rest
    key = _kv_key(user, action_type)
    body = {
        "_key": key,
        "payload": json.dumps(timestamps),
        "updated_at": int(time.time()),
    }
    update_url = _kv_url(key)
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


def _kv_list_all(session_key: str) -> List[Dict]:
    """List all records. Used by reset_rate_limits."""
    import splunk.rest
    try:
        status, content = splunk.rest.simpleRequest(
            _kv_url(),
            sessionKey=session_key,
            getargs={"output_mode": "json"},
            raiseAllErrors=False,
        )
    except Exception:  # noqa: BLE001
        return []
    if getattr(status, "status", 0) != 200:
        return []
    try:
        parsed = json.loads(content)
        return parsed if isinstance(parsed, list) else []
    except (ValueError, TypeError):
        return []


def _kv_delete_key(session_key: str, key: str) -> None:
    import splunk.rest
    try:
        splunk.rest.simpleRequest(
            _kv_url(key),
            sessionKey=session_key,
            method="DELETE",
            raiseAllErrors=False,
        )
    except Exception:  # noqa: BLE001
        pass


def check_rate_limit(user: str, action_type: str = "write",
                     session_key: Optional[str] = None) -> bool:
    """
    Check if a user action is within rate limits using sliding window.

    Args:
        user: Username
        action_type: "read" or "write"
        session_key: When provided, state lives in KV (cross-worker
            safe). When None (unit tests), uses module-level dict.

    Returns:
        True if request allowed, False if rate limit exceeded.
    """
    from wl_constants import (
        RATE_WINDOW, RATE_MAX_WRITES, RATE_MAX_READS)

    now = time.time()
    max_req = (RATE_MAX_WRITES if action_type == "write"
               else RATE_MAX_READS)
    use_kv = bool(session_key)

    if use_kv:
        # Read existing timestamps; prune; check cap; append +
        # write back. The RMW MUST be serialized within a single
        # (user, action_type) bucket — Day 6.1.9b verified that
        # without the lock 60 parallel requests all read the
        # empty bucket, all see "0 < cap", all pass, all write
        # their own [now] (last-write-wins), and the cap is
        # bypassed by the full parallelism degree.
        #
        # Lock granularity is per-(user, action_type) so two
        # different users / two different action_types don't
        # block each other. Lock acquisition is fast
        # (microseconds when uncontended); the only serialization
        # cost falls on a user spamming the same endpoint —
        # exactly the case rate limiting is designed to
        # constrain.
        from wl_filelock import file_lock
        with file_lock(_rmw_lock_path(user, action_type),
                       timeout=5):
            timestamps = _kv_read_timestamps(
                session_key, user, action_type)
            # Prune outside the window
            timestamps = [t for t in timestamps
                          if now - t < RATE_WINDOW]
            if len(timestamps) >= max_req:
                # Write back the pruned list so the bucket
                # doesn't carry stale entries forever.
                _kv_write_timestamps(
                    session_key, user, action_type, timestamps)
                return False
            timestamps.append(now)
            _kv_write_timestamps(
                session_key, user, action_type, timestamps)
        return True

    # In-memory path (unit tests only).
    global _rate_limits
    key = (user, action_type)
    if key not in _rate_limits:
        _rate_limits[key] = []
    _rate_limits[key] = [t for t in _rate_limits[key]
                         if now - t < RATE_WINDOW]
    # Auto-cleanup stale keys to prevent unbounded growth
    if len(_rate_limits) > 10000:
        stale = [k for k, v in _rate_limits.items()
                 if not v or now - v[-1] > RATE_WINDOW * 2]
        for k in stale:
            del _rate_limits[k]
    if len(_rate_limits[key]) >= max_req:
        return False
    _rate_limits[key].append(now)
    return True


def reset_rate_limits(session_key: Optional[str] = None) -> None:
    """Reset all rate limit counters. Used for testing."""
    if session_key:
        records = _kv_list_all(session_key)
        for rec in records:
            if isinstance(rec, dict):
                key = rec.get("_key")
                if key:
                    _kv_delete_key(session_key, key)
    global _rate_limits
    _rate_limits.clear()
