#!/usr/bin/env python3
"""
wl_fim.py — File Integrity Monitor for Whitelist Manager.

Splunk scripted input that periodically hashes a curated list of
critical files and compares against a stored baseline. Any
unexpected change emits a JSON event to stdout which Splunk indexes
into ``wl_audit`` under ``sourcetype=wl_fim``.

Design changes in build 554:

1. **Dual-stored baseline** — the canonical baseline lives in BOTH
   ``lookups/_versions/.fim_baseline.json`` (filesystem, HMAC signed)
   AND the ``wl_fim_baseline`` KV store collection (authenticated,
   HMAC signed). On every run the two are cross-validated. If they
   diverge an alert fires and the more-conservative (higher file
   count) side wins. Attackers who delete only the filesystem copy
   are still caught because the KV row survives.

2. **Deploy-window suppression** — if
   ``lookups/_versions/_fim_deploy_window.json`` exists AND has a
   valid HMAC AND hasn't expired, file modifications are downgraded
   to ``severity: INFO`` and tagged ``action: fim_file_modified_during_deploy``.
   The deploy-window file itself cannot be forged without the
   runtime key. Window is capped at 1 hour to prevent permanent
   suppression.

3. **Session key from Splunk** — ``passAuth = splunk-system-user``
   in inputs.conf causes splunkd to pass a session token on stdin.
   The script reads the first line of stdin to get the token and
   uses it for KV store REST calls.

First run on any box: baseline is established in both stores
simultaneously, a single ``fim_baseline_initialized`` event is
emitted, and no alerts fire for existing files.
"""
import hashlib
import hmac
import json
import os
import sys
import time
from datetime import datetime, timezone

# Make ``bin/`` importable when launched by splunkd (scripted-input
# context may omit it from sys.path).
_BIN_DIR = os.path.dirname(os.path.abspath(__file__))
if _BIN_DIR not in sys.path:
    sys.path.insert(0, _BIN_DIR)

# Shared helpers (Phase 3b consolidation — see CLAUDE.md 2026-04-19).
# Exposed under the historical underscore-prefixed names so call sites
# stay unchanged.
from wl_fim_common import (  # noqa: E402
    file_hash_sha256 as _file_hash,
    kv_collection_url,
    queue_fim_notification,
    read_splunk_guid,
)

# ssl + urllib are imported lazily inside _kv_request so that a
# misconfigured Python environment (e.g. Splunk bundled Python
# without LD_LIBRARY_PATH pointing to /opt/splunk/lib when invoked
# outside splunkd) does NOT crash the whole script. KV store calls
# simply fall back to "KV unavailable" in that case and the
# filesystem baseline continues to work.

APP_NAME = "wl_manager"
APP_DIR = "/opt/splunk/etc/apps/wl_manager"
VERSIONS_DIR = os.path.join(APP_DIR, "lookups", "_versions")
BASELINE_PATH = os.path.join(VERSIONS_DIR, ".fim_baseline.json")
DEPLOY_WINDOW_PATH = os.path.join(VERSIONS_DIR, "_fim_deploy_window.json")
FIM_ALERT_QUEUE_PATH = os.path.join(VERSIONS_DIR, "_fim_alert_queue.jsonl")
INSTANCE_CFG = "/opt/splunk/etc/instance.cfg"
# Severities that trigger an in-app notification for superadmins.
FIM_NOTIFY_SEVERITIES = {"HIGH", "CRITICAL"}

# HMAC salt — imported from wl_constants (single source of truth).
# Fallback to local copy only if wl_constants is unavailable (e.g.
# running outside the app directory for diagnostics).
try:
    sys.path.insert(0, os.path.join(APP_DIR, "bin"))
    from wl_constants import FIM_HMAC_SALT
    HMAC_SALT = FIM_HMAC_SALT
    _HMAC_SALT_SOURCE = "wl_constants"
except ImportError:
    HMAC_SALT = b"wl_manager_fim_integrity_v1"
    _HMAC_SALT_SOURCE = "hardcoded_fallback"
    sys.stderr.write(
        "wl_fim WARNING: using hardcoded HMAC salt "
        "(wl_constants import failed). If the salt in "
        "wl_constants.py was rotated, FIM will derive a "
        "different key and flag all baselines as tampered.\n"
    )
KV_COLLECTION = "wl_fim_baseline"
KV_KEY = "state"
DEPLOY_WINDOW_MAX_SECONDS = 3600  # 1 hour hard cap

import glob as _glob


def _expand_globs(patterns):
    """Expand glob patterns to a sorted unique list of existing files.

    Using glob-at-startup keeps the watch set authoritative w.r.t. what
    actually exists in OUR app directory. A foreign app's dashboards or
    JS files are NOT in this app's path and so cannot match. When we add
    a new dashboard or JS module, the next wl_fim.py run picks it up
    automatically — no manual WATCH_CODE update needed.
    """
    seen = set()
    for p in patterns:
        if "*" in p or "?" in p:
            for match in _glob.glob(p):
                seen.add(match)
        else:
            # Literal paths stay in the list even if missing — _snapshot
            # will record exists=False, and a sudden appearance is a
            # tamper signal.
            seen.add(p)
    return sorted(seen)


WATCH_CODE = _expand_globs([
    # Backend Python modules
    os.path.join(APP_DIR, "bin", "wl_handler.py"),
    os.path.join(APP_DIR, "bin", "wl_csv.py"),
    os.path.join(APP_DIR, "bin", "wl_rbac.py"),
    os.path.join(APP_DIR, "bin", "wl_constants.py"),
    os.path.join(APP_DIR, "bin", "wl_approval.py"),
    os.path.join(APP_DIR, "bin", "wl_rules.py"),
    os.path.join(APP_DIR, "bin", "wl_versions.py"),
    os.path.join(APP_DIR, "bin", "wl_trash.py"),
    os.path.join(APP_DIR, "bin", "wl_limits.py"),
    os.path.join(APP_DIR, "bin", "wl_audit.py"),
    os.path.join(APP_DIR, "bin", "wl_validation.py"),
    os.path.join(APP_DIR, "bin", "wl_replay.py"),
    os.path.join(APP_DIR, "bin", "wl_fim.py"),
    os.path.join(APP_DIR, "bin", "wl_fim_watch.py"),
    os.path.join(APP_DIR, "bin", "wl_migrate_cooldowns.py"),
    # Splunk conf files
    os.path.join(APP_DIR, "default", "restmap.conf"),
    os.path.join(APP_DIR, "default", "collections.conf"),
    os.path.join(APP_DIR, "default", "inputs.conf"),
    os.path.join(APP_DIR, "default", "authorize.conf"),
    os.path.join(APP_DIR, "default", "app.conf"),
    os.path.join(APP_DIR, "default", "savedsearches.conf"),
    # Our app's dashboards ONLY — the path constraint to APP_DIR prevents
    # matching other apps' dashboards. Even if the Splunk deployment hosts
    # dozens of apps with their own views, glob here returns only files
    # under /opt/splunk/etc/apps/wl_manager/.
    os.path.join(APP_DIR, "default", "data", "ui", "views", "*.xml"),
    os.path.join(APP_DIR, "default", "data", "ui", "nav", "*.xml"),
    # Our app's frontend JS — entry points + extracted modules.
    os.path.join(APP_DIR, "appserver", "static", "*.js"),
    os.path.join(APP_DIR, "appserver", "static", "modules", "*.js"),
    # Recovery scripts (round 6, 2026-04-29). These are unsigned bash
    # that perform privileged operations (clear tamper flags, delete
    # KV records, append to recovery log). An attacker with file
    # write could modify them to skip the audit log append or to
    # silently no-op. FIM coverage means tampering surfaces as a
    # `fim_code_modified` event within 15s.
    os.path.join(APP_DIR, "scripts", "emergency_unlock.sh"),
    os.path.join(APP_DIR, "scripts", "reset_cooldowns.sh"),
    os.path.join(APP_DIR, "scripts", "fim_deploy_window.sh"),
    os.path.join(APP_DIR, "scripts", "pre-commit-doc-drift.sh"),
])

WATCH_SENTINELS = [
    os.path.join(VERSIONS_DIR, ".cooldown_initialized"),
    os.path.join(VERSIONS_DIR, ".cooldown_tamper"),
    os.path.join(VERSIONS_DIR, "_emergency_lockdown.json"),
    INSTANCE_CFG,  # GUID rotation invalidates ALL HMAC-signed state
]


# ────────────────────────────────────────────────────────────────
# Key derivation (from Splunk server GUID)
# ────────────────────────────────────────────────────────────────

def _read_guid():
    """Best-effort GUID read (wraps wl_fim_common.read_splunk_guid).

    Scheduled input must not crash on missing/unreadable instance.cfg;
    fall back to empty string so key derivation uses the unkeyed path.
    """
    return read_splunk_guid(INSTANCE_CFG, strict=False)


def _derive_hmac_key():
    guid = _read_guid()
    if not guid:
        return hashlib.sha256(HMAC_SALT).digest()
    return hashlib.sha256(HMAC_SALT + guid.encode("utf-8")).digest()


def _compute_baseline_checksum(baseline_body, key):
    filtered = {k: v for k, v in baseline_body.items() if k != "_checksum"}
    payload = json.dumps(filtered, sort_keys=True, default=str)
    return hmac.new(key, payload.encode("utf-8"), hashlib.sha256).hexdigest()


def _compute_window_checksum(body, key):
    filtered = {k: v for k, v in body.items() if k != "_checksum"}
    payload = json.dumps(filtered, sort_keys=True, default=str)
    return hmac.new(key, payload.encode("utf-8"), hashlib.sha256).hexdigest()


# ────────────────────────────────────────────────────────────────
# Filesystem baseline
# ────────────────────────────────────────────────────────────────

# ``_file_hash`` is imported from wl_fim_common as the canonical helper.


def _read_fs_baseline(key):
    if not os.path.isfile(BASELINE_PATH):
        return None, "missing"
    try:
        with open(BASELINE_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except PermissionError:
        # Distinct from "corrupt": the file exists and may be intact,
        # but the running user cannot read it (e.g. file was created by
        # root during a manual test, and the scripted input runs as
        # splunk). Operators need a different remediation here — chown
        # the file, don't rebuild.
        return None, "permission_denied"
    except (OSError, json.JSONDecodeError):
        return None, "corrupt"
    stored = data.pop("_checksum", None)
    if stored is None:
        return None, "missing_checksum"
    expected = _compute_baseline_checksum(data, key)
    if stored != expected:
        return data, "checksum_mismatch"
    return data, "ok"


def _write_fs_baseline(baseline, key):
    """Write baseline to disk. Returns (True, "") on success, (False, reason)
    on failure. Callers must surface failures — silent write failures caused
    a 2840-event/day flood of fim_fs_baseline_missing_or_tampered when a
    root-owned baseline file made every write silently no-op."""
    try:
        os.makedirs(os.path.dirname(BASELINE_PATH), exist_ok=True)
        body = {k: v for k, v in baseline.items() if k != "_checksum"}
        body["_checksum"] = _compute_baseline_checksum(body, key)
        with open(BASELINE_PATH, "w", encoding="utf-8") as fh:
            json.dump(body, fh, indent=2)
        try:
            os.chmod(BASELINE_PATH, 0o600)
        except OSError:
            pass
        return True, ""
    except PermissionError as exc:
        return False, "permission_denied:{}".format(exc)
    except OSError as exc:
        return False, "os_error:{}".format(exc)


# ────────────────────────────────────────────────────────────────
# KV store baseline (requires session key via stdin)
# ────────────────────────────────────────────────────────────────

def _kv_url(suffix=""):
    """Build a KV-store REST URL under this script's collection."""
    return kv_collection_url(APP_NAME, KV_COLLECTION, suffix)


def _kv_request(method, url, session_key, body=None):
    try:
        import ssl
        import urllib.request
        import urllib.error
    except ImportError as exc:
        # Splunk bundled Python sometimes can't import ssl without
        # LD_LIBRARY_PATH=/opt/splunk/lib. When that happens we can't
        # reach the KV store — fall back to "KV unavailable".
        return 0, "import_error:{}".format(exc)
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(url, method=method)
    req.add_header("Authorization", "Splunk " + session_key)
    req.add_header("Content-Type", "application/json")
    data = json.dumps(body).encode("utf-8") if body is not None else None
    try:
        resp = urllib.request.urlopen(req, data=data, context=ctx)
        return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, exc.read().decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            return exc.code, ""
    except Exception as exc:  # noqa: BLE001
        return 0, str(exc)


def _read_kv_baseline(session_key, key):
    """Return (baseline_dict_or_None, status_string).

    Status values mirror the filesystem function:
        "missing" | "corrupt" | "missing_checksum" |
        "checksum_mismatch" | "ok"
    """
    if not session_key:
        return None, "no_session"
    status, body = _kv_request(
        "GET", _kv_url("/" + KV_KEY + "?output_mode=json"), session_key)
    if status == 404:
        return None, "missing"
    if status != 200:
        return None, "transient:status={}".format(status)
    try:
        record = json.loads(body)
    except (json.JSONDecodeError, TypeError):
        return None, "corrupt"
    payload_str = record.get("payload", "")
    stored = record.get("checksum", "")
    if not payload_str or not stored:
        return None, "missing_checksum"
    try:
        data = json.loads(payload_str)
    except (json.JSONDecodeError, TypeError):
        return None, "corrupt"
    expected = _compute_baseline_checksum(data, key)
    if expected != stored:
        return data, "checksum_mismatch"
    return data, "ok"


def _write_kv_baseline(session_key, baseline, key):
    if not session_key:
        return False
    body_body = {k: v for k, v in baseline.items() if k != "_checksum"}
    payload_str = json.dumps(body_body, sort_keys=True, default=str)
    checksum = _compute_baseline_checksum(body_body, key)
    record = {
        "payload": payload_str,
        "checksum": checksum,
        "updated_at": int(time.time()),
        "updated_by": "wl_fim",
    }
    # Try update first
    status, _body = _kv_request(
        "POST", _kv_url("/" + KV_KEY), session_key, record)
    if status in (200, 201):
        return True
    if status == 404:
        record_with_key = dict(record)
        record_with_key["_key"] = KV_KEY
        status, _body = _kv_request(
            "POST", _kv_url(""), session_key, record_with_key)
        if status in (200, 201):
            return True
    return False


# ────────────────────────────────────────────────────────────────
# Deploy-window check (HMAC-signed file, hard 1 hour cap)
# ────────────────────────────────────────────────────────────────

def _read_deploy_window(key):
    """Return (is_active_bool, details_dict).

    ``details_dict`` is a small dict shown in any alert emitted
    during the window so operators know which deploy the noise
    belongs to.
    """
    if not os.path.isfile(DEPLOY_WINDOW_PATH):
        return False, None
    try:
        with open(DEPLOY_WINDOW_PATH, "r", encoding="utf-8") as fh:
            body = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return False, {"error": "deploy_window_unreadable"}
    stored = body.pop("_checksum", None)
    if not stored:
        return False, {"error": "deploy_window_unsigned"}
    expected = _compute_window_checksum(body, key)
    if expected != stored:
        return False, {"error": "deploy_window_checksum_mismatch"}
    now = int(time.time())
    started = int(body.get("started_at", 0))
    expires = int(body.get("expires_at", 0))
    if expires <= 0 or now >= expires:
        return False, None
    if expires - started > DEPLOY_WINDOW_MAX_SECONDS:
        # Hard cap — refuse to honor oversized windows
        return False, {"error": "deploy_window_exceeds_cap"}
    return True, {
        "started_by": body.get("started_by"),
        "reason": body.get("reason"),
        "expires_at": expires,
    }


# ────────────────────────────────────────────────────────────────
# Event emission
# ────────────────────────────────────────────────────────────────

_LOCKDOWN_STATE_PATH = os.path.join(
    VERSIONS_DIR, "_emergency_lockdown.json")

# Process-level cache so _emit doesn't re-read the lockdown file
# on every event. Set once at the start of main() via _refresh_lockdown_state.
_LOCKDOWN_ACTIVE = False


def _refresh_lockdown_state():
    """Read lockdown state into the process-level cache.

    Called once per scripted-input run. Must NOT be called from inside
    the per-file comparison loop or we'll re-read the file on every emit
    and open a TOCTOU window where the lockdown file could be mutated
    mid-run.
    """
    global _LOCKDOWN_ACTIVE
    try:
        if os.path.isfile(_LOCKDOWN_STATE_PATH):
            with open(_LOCKDOWN_STATE_PATH, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            _LOCKDOWN_ACTIVE = bool(data.get("locked"))
        else:
            _LOCKDOWN_ACTIVE = False
    except (OSError, json.JSONDecodeError):
        # Fail-closed-ish: if we can't read the file, assume lockdown is
        # NOT active for severity-promotion purposes (we'd rather not
        # generate false-positive CRITICAL alerts). The HMAC-signed
        # sentinel watcher will alert if the file itself is tampered.
        _LOCKDOWN_ACTIVE = False


def _queue_fim_notification(event):
    """Push an event into the FIM bell-notification queue.

    Thin wrapper over ``wl_fim_common.queue_fim_notification`` that
    bakes in this script's queue path.
    """
    queue_fim_notification(event, FIM_ALERT_QUEUE_PATH)


# ────────────────────────────────────────────────────────────────
# Edge-triggered alert dedup for stateful conditions
# ────────────────────────────────────────────────────────────────
# Some FIM alerts describe conditions that PERSIST across runs (e.g.,
# the baseline file is root-owned and unreadable). Without dedup, the
# script would emit a CRITICAL alert every 60s for the same condition,
# flooding the audit index and the notification bell. We track per
# (action+key) the last-emitted timestamp and only re-emit if either
# (a) we haven't seen this key before, or (b) the reminder interval
# has elapsed (so persistent conditions still get periodic visibility,
# but at human-attentive cadence rather than per-cycle).
#
# Event-based alerts (file modifications, deletions, deploy windows
# opening/closing) are NOT in this set — each such event is a discrete
# occurrence that must be indexed individually.
FIM_ALERT_STATE_PATH = os.path.join(VERSIONS_DIR, ".fim_alert_state.json")
STATEFUL_ALERT_ACTIONS = frozenset({
    "fim_fs_baseline_permission_denied",
    "fim_fs_baseline_rebuild_failed",
    "fim_fs_baseline_missing_or_tampered",
    "fim_baseline_kv_fs_divergence",
    "fim_kv_baseline_checksum_mismatch",
    "fim_csv_hash_registry_tampered",
    "fim_lookups_dir_unreadable",
    "fim_scripted_input_no_session_key",
    "fim_baseline_tampered",
    "fim_baseline_hmac_mismatch",
    "fim_baseline_rebuilt_no_source",
})
STATEFUL_REMIND_INTERVAL_SECS = 3600  # 1 hour

_alert_state_cache = None  # lazy-loaded once per run


def _load_alert_state():
    try:
        with open(FIM_ALERT_STATE_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
            if isinstance(data, dict):
                return data
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        pass
    return {}


def _save_alert_state(state):
    try:
        os.makedirs(os.path.dirname(FIM_ALERT_STATE_PATH), exist_ok=True)
        with open(FIM_ALERT_STATE_PATH, "w", encoding="utf-8") as fh:
            json.dump(state, fh)
        try:
            os.chmod(FIM_ALERT_STATE_PATH, 0o600)
        except OSError:
            pass
    except OSError:
        # Best-effort. If we can't persist state, the next run will just
        # re-fire the alert — acceptable degradation.
        pass


def _should_emit_stateful(event, now_ts):
    """Return True if this stateful alert should fire now (edge or reminder)."""
    global _alert_state_cache
    action = event.get("action", "")
    if action not in STATEFUL_ALERT_ACTIONS:
        return True
    if _alert_state_cache is None:
        _alert_state_cache = _load_alert_state()
    # Dedup key: action + path/file identity + reason. This lets
    # different paths fire independently while suppressing repeat alerts
    # on the same path.
    path = (event.get("path", "")
            or event.get("monitored_path", "")
            or event.get("csv_file", ""))
    key = "{}|{}|{}".format(action, path, event.get("reason", ""))
    last_ts = _alert_state_cache.get(key)
    if last_ts is None or (now_ts - int(last_ts)) >= STATEFUL_REMIND_INTERVAL_SECS:
        _alert_state_cache[key] = now_ts
        _save_alert_state(_alert_state_cache)
        # Annotate the event so dashboards can distinguish "first fire"
        # from "1-hour reminder" when triaging.
        if last_ts is not None:
            event["alert_kind"] = "reminder"
            event["last_alert_ts"] = int(last_ts)
        else:
            event["alert_kind"] = "first_fire"
        return True
    return False


def _emit(event):
    event.setdefault("timestamp", int(time.time()))
    event.setdefault("timestamp_human",
                     datetime.now(timezone.utc)
                     .strftime("%Y-%m-%d %H:%M:%S UTC"))
    # Edge-triggered dedup for persistent-state alerts. Suppression
    # decision uses the event's timestamp (already set above).
    if not _should_emit_stateful(event, event["timestamp"]):
        return
    # Tag every event with the lockdown state. During an active lockdown,
    # ALL writes from the handler are blocked — so any FIM event is
    # definitionally unauthorized and should be treated as a high-signal
    # indicator of compromise. Promote severity to CRITICAL regardless
    # of the caller's default classification (including INFO-level
    # deploy-window-downgraded alerts on code files).
    event["lockdown_active"] = _LOCKDOWN_ACTIVE
    if _LOCKDOWN_ACTIVE:
        prior = event.get("severity", "INFO")
        if prior != "CRITICAL":
            event["severity_before_lockdown_promotion"] = prior
            event["severity"] = "CRITICAL"
    # Push HIGH/CRITICAL events into the in-app notification bell queue
    # AFTER severity promotion, so lockdown-promoted events are surfaced
    # even if their default severity was INFO.
    if event.get("severity") in FIM_NOTIFY_SEVERITIES:
        _queue_fim_notification(event)
    sys.stdout.write(json.dumps(event) + "\n")
    sys.stdout.flush()


def _snapshot():
    result = {}
    for path in WATCH_CODE + WATCH_SENTINELS:
        result[path] = {
            "hash": _file_hash(path),
            "exists": os.path.isfile(path),
        }
    return result


def _read_session_key():
    """Splunk passes the session key on stdin when passAuth is set."""
    try:
        line = sys.stdin.readline()
        return line.strip()
    except Exception:  # noqa: BLE001
        return ""


# ────────────────────────────────────────────────────────────────
# Main
# ────────────────────────────────────────────────────────────────

def main():
    # Allow direct CLI runs without passAuth — fall back to no
    # session key and skip KV operations.
    session_key = os.environ.get("WL_FIM_SESSION_KEY", "")
    if not session_key and not sys.stdin.isatty():
        session_key = _read_session_key()

    # Cache instance.cfg hash BEFORE deriving the HMAC key, so both
    # key derivation and the file-hash comparison in the loop below
    # see the same file content. Without this, an attacker who swaps
    # instance.cfg between _derive_hmac_key() and the comparison loop
    # could make the key derivation use the NEW GUID while the hash
    # comparison sees "no change" (because the file was already swapped).
    _instance_cfg_hash_cache = _file_hash(INSTANCE_CFG)

    # Snapshot lockdown state once per run so _emit can tag every event
    # with lockdown_active and promote severity to CRITICAL when true.
    _refresh_lockdown_state()

    # Detect missing passAuth: when run as a Splunk scripted input with
    # `passAuth = true` set in inputs.conf (the default we ship), splunkd
    # writes a session key to stdin. If we started non-interactively but
    # got no session key, someone has changed inputs.conf to drop
    # passAuth — which disables KV baseline sync. The watcher still
    # functions with filesystem-only state, but KV/FS divergence
    # detection is degraded. Emit one alert per run so operators can
    # see the misconfiguration in their dashboards.
    if not session_key and not sys.stdin.isatty():
        _emit({
            "action": "fim_scripted_input_no_session_key",
            "severity": "HIGH",
            "details": "Scripted input started without a session key. "
                       "Either passAuth was removed from inputs.conf or "
                       "splunkd failed to pass the token. KV-store "
                       "baseline sync is disabled in this mode — the "
                       "filesystem baseline remains the single source of "
                       "truth, which weakens the dual-store tamper "
                       "detection. Fix by restoring "
                       "'passAuth = true' in default/inputs.conf (or "
                       "local/inputs.conf override) for the "
                       "[script://$SPLUNK_HOME/etc/apps/wl_manager/bin/"
                       "wl_fim.py] stanza.",
        })

    key = _derive_hmac_key()

    deploy_active, deploy_details = _read_deploy_window(key)

    fs_baseline, fs_status = _read_fs_baseline(key)
    kv_baseline, kv_status = _read_kv_baseline(session_key, key)

    # ── Decide which baseline is authoritative ──
    _baseline_needs_resigning = False

    if fs_status == "missing" and kv_status == "missing":
        # First-ever run — establish both baselines simultaneously
        new_baseline = _snapshot()
        _write_fs_baseline(new_baseline, key)
        if session_key:
            _write_kv_baseline(session_key, new_baseline, key)
        _emit({
            "action": "fim_baseline_initialized",
            "file_count": len(new_baseline),
            "kv_store": bool(session_key),
        })
        return

    # KV-FS cross-validation. If both exist and disagree, alert and
    # use the side that flags MORE files as differing from current
    # (the more conservative, more-likely-to-catch-an-attack choice).
    if fs_status == "ok" and kv_status == "ok":
        if fs_baseline != kv_baseline:
            _emit({
                "action": "fim_baseline_kv_fs_divergence",
                "severity": "CRITICAL",
                "details": "Filesystem and KV store baselines disagree — "
                           "one source has been tampered with since the "
                           "last FIM run.",
                "fs_file_count": len(fs_baseline),
                "kv_file_count": len(kv_baseline),
            })
            # Use the union: treat any file as baselined if EITHER
            # source has it, which makes subsequent comparisons
            # maximally paranoid.
            merged = dict(kv_baseline)
            for p, v in fs_baseline.items():
                if p not in merged:
                    merged[p] = v
            baseline = merged
        else:
            baseline = fs_baseline

    elif fs_status == "ok" and kv_status in (
        "missing", "transient:status=0", "no_session", "checksum_mismatch",
    ):
        baseline = fs_baseline
        # Rebuild KV from the valid FS baseline when KV is missing,
        # unavailable, or has a bad HMAC (e.g. GUID rotation changed
        # the KV signing key but the FS copy was already re-signed).
        if session_key and kv_status in ("missing", "checksum_mismatch"):
            if kv_status == "checksum_mismatch":
                _emit({
                    "action": "fim_kv_baseline_checksum_mismatch",
                    "severity": "HIGH",
                    "details": "KV store baseline HMAC failed but "
                               "filesystem baseline is intact. "
                               "Rebuilding KV from filesystem.",
                })
            _write_kv_baseline(session_key, fs_baseline, key)

    elif fs_status == "permission_denied":
        # The filesystem baseline is intact on disk but the running user
        # can't read it (e.g. a previous manual run as root created a
        # root-owned file; scripted input now runs as splunk). Emit a
        # DIFFERENT, actionable alert once per run — do NOT try to
        # rebuild from KV because the write will also fail, producing
        # a flood. KV stays authoritative until an operator fixes chown.
        _emit({
            "action": "fim_fs_baseline_permission_denied",
            "severity": "CRITICAL",
            "fs_status": fs_status,
            "path": BASELINE_PATH,
            "details": "Running user cannot read the filesystem "
                       "baseline (likely ownership mismatch). Fix with: "
                       "docker exec -u 0 <container> chown splunk:splunk "
                       + BASELINE_PATH + " && chmod 600 " + BASELINE_PATH
                       + ". KV-store copy remains authoritative.",
        })
        if kv_status == "ok":
            baseline = kv_baseline
        else:
            # No usable baseline from either source — don't attempt
            # per-file comparison, just return and wait for an operator
            # to fix the permissions.
            return

    elif kv_status == "ok" and fs_status in ("missing", "corrupt", "missing_checksum", "checksum_mismatch"):
        # Filesystem was deleted or tampered — KV is the authority.
        _emit({
            "action": "fim_fs_baseline_missing_or_tampered",
            "severity": "CRITICAL",
            "fs_status": fs_status,
            "details": "Filesystem baseline is {} but KV store copy "
                       "is intact. Rebuilding filesystem from KV.".format(fs_status),
        })
        baseline = kv_baseline
        ok, reason = _write_fs_baseline(kv_baseline, key)
        if not ok:
            # Silent write failures produced the 2840-event/day flood.
            # Surface the failure with a distinct action so operators
            # see the root cause, not just the "tampered" symptom.
            _emit({
                "action": "fim_fs_baseline_rebuild_failed",
                "severity": "CRITICAL",
                "reason": reason,
                "path": BASELINE_PATH,
                "details": "Cannot rebuild filesystem baseline from KV. "
                           "Subsequent runs will keep emitting "
                           "fim_fs_baseline_missing_or_tampered until "
                           "the underlying cause is fixed.",
            })

    elif fs_status in ("corrupt", "missing_checksum", "checksum_mismatch"):
        _emit({
            "action": "fim_baseline_tampered",
            "severity": "CRITICAL",
            "reason": fs_status,
            "details": "Filesystem baseline HMAC failed; comparing "
                       "unverified data against current state before "
                       "re-establishing baseline.",
        })
        if fs_baseline and fs_status == "checksum_mismatch":
            # We have the old file hashes but can't trust the HMAC
            # (e.g. GUID rotation changed the key). Use the unverified
            # data to emit per-file diffs so the operator sees exactly
            # which files changed — including instance.cfg.
            baseline = fs_baseline
            _baseline_needs_resigning = True
            # Fall through to the per-file comparison loop below
        else:
            # Truly corrupt or missing checksum — no usable data.
            new_baseline = _snapshot()
            _write_fs_baseline(new_baseline, key)
            if session_key:
                _write_kv_baseline(session_key, new_baseline, key)
            return

    else:
        # Degenerate: no usable baseline from either source.
        new_baseline = _snapshot()
        _write_fs_baseline(new_baseline, key)
        if session_key:
            _write_kv_baseline(session_key, new_baseline, key)
        _emit({
            "action": "fim_baseline_rebuilt_no_source",
            "severity": "HIGH",
            "fs_status": fs_status,
            "kv_status": kv_status,
        })
        return

    # ── Compare each watched file against the baseline ──
    new_baseline = dict(baseline)
    changed = False

    def _is_sentinel(p):
        return p in WATCH_SENTINELS

    def _modify_alert_severity(default, path):
        # Sentinel files (cooldown markers, lockdown state, instance.cfg)
        # are NEVER touched by legitimate deploys — keep them at HIGH
        # even during a deploy window so attacker-timed mutations are
        # not buried in INFO-level noise.
        if deploy_active and not _is_sentinel(path):
            return "INFO"
        return default

    def _modify_alert_action(default, path):
        if deploy_active and not _is_sentinel(path):
            return "fim_file_modified_during_deploy"
        return default

    for path in WATCH_CODE + WATCH_SENTINELS:
        # Use cached hash for instance.cfg to close the TOCTOU gap
        # between key derivation and hash comparison.
        if path == INSTANCE_CFG:
            current_hash = _instance_cfg_hash_cache
        else:
            current_hash = _file_hash(path)
        current_exists = current_hash is not None
        prev = baseline.get(path) or {}
        prev_hash = prev.get("hash")
        prev_exists = bool(prev.get("exists"))

        if path not in baseline:
            new_baseline[path] = {
                "hash": current_hash, "exists": current_exists,
            }
            changed = True
            continue

        if current_exists and not prev_exists:
            evt = {
                "action": _modify_alert_action("fim_file_appeared", path),
                "monitored_path": path,
                "new_hash": current_hash,
                "severity": _modify_alert_severity(
                    "HIGH" if _is_sentinel(path) else "MEDIUM", path),
            }
            if deploy_active:
                evt["deploy_window"] = deploy_details
                if _is_sentinel(path):
                    evt["sentinel_alert"] = True
            _emit(evt)
            new_baseline[path] = {"hash": current_hash, "exists": True}
            changed = True
            continue

        if not current_exists and prev_exists:
            evt = {
                "action": _modify_alert_action("fim_file_removed", path),
                "monitored_path": path,
                "old_hash": prev_hash,
                "severity": _modify_alert_severity(
                    "HIGH" if path in WATCH_CODE else "MEDIUM", path),
            }
            if deploy_active:
                evt["deploy_window"] = deploy_details
                if _is_sentinel(path):
                    evt["sentinel_alert"] = True
            _emit(evt)
            new_baseline[path] = {"hash": None, "exists": False}
            changed = True
            continue

        if current_exists and current_hash != prev_hash:
            evt = {
                "action": _modify_alert_action("fim_file_modified", path),
                "monitored_path": path,
                "old_hash": prev_hash,
                "new_hash": current_hash,
                "severity": _modify_alert_severity(
                    "HIGH" if path in WATCH_CODE else "MEDIUM", path),
            }
            if deploy_active:
                evt["deploy_window"] = deploy_details
                if _is_sentinel(path):
                    evt["sentinel_alert"] = True
            _emit(evt)
            new_baseline[path] = {"hash": current_hash, "exists": True}
            changed = True

    # Force-rewrite when the baseline HMAC failed (checksum_mismatch)
    # even if no watched files changed. Without this, a clean GUID
    # rotation (e.g. DR restore with identical app files) would leave
    # the baseline signed with the OLD key, causing an infinite
    # CRITICAL alert loop every 60 seconds.
    if changed or _baseline_needs_resigning:
        _write_fs_baseline(new_baseline, key)
        if session_key:
            _write_kv_baseline(session_key, new_baseline, key)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write("wl_fim error: {}\n".format(exc))
        sys.exit(1)
