#!/usr/bin/env python3
"""
wl_fim_watch.py — Near-real-time stat-based file change detector.

Persistent Splunk scripted input (``interval = 0``) that polls
``os.stat()`` on all watched files every 2 seconds. When a file's
mtime or size changes, it hashes the file and emits an immediate
alert to stdout (indexed by Splunk into ``wl_audit``).

This is the "fast path" complement to ``wl_fim.py`` (the "slow path"
that does full cryptographic verification every 15 seconds). Together
they provide:

    - Regular modifications (editor/cp/sed): detected in ~2 seconds
    - mtime-preserving writes (cp -p / touch -r): detected in ~15 seconds
    - File deletions/creations: detected in ~2 seconds

Additionally, this script monitors all CSV files registered in
``rule_csv_map.csv`` against expected hashes written by the handler.
When a CSV is modified outside the handler (SPL ``outputlookup``,
direct filesystem edit, Splunk REST lookup API), the hash won't
match the expected value and a CRITICAL alert fires.

Design:
    - Imports ``WATCH_CODE`` and ``WATCH_SENTINELS`` from ``wl_fim``
      so the file list is a single source of truth.
    - Reads ``rule_csv_map.csv`` periodically to discover managed CSVs.
    - Compares CSV hashes against ``.csv_expected_hashes.json`` to
      distinguish legitimate handler writes from external modifications.
    - Emits heartbeat events every 5 minutes.
    - Handles SIGTERM gracefully for clean Splunk shutdown.
"""

import csv
import hashlib
import json
import os
import signal
import sys
import time
from datetime import datetime, timezone

APP_DIR = "/opt/splunk/etc/apps/wl_manager"
LOOKUPS_DIR = os.path.join(APP_DIR, "lookups")
VERSIONS_DIR = os.path.join(LOOKUPS_DIR, "_versions")
MAPPING_FILE = os.path.join(LOOKUPS_DIR, "rule_csv_map.csv")
EXPECTED_HASHES_FILE = os.path.join(VERSIONS_DIR, ".csv_expected_hashes.json")
INSTANCE_CFG = "/opt/splunk/etc/instance.cfg"

FAST_INTERVAL = 2           # seconds between stat() sweeps
CSV_HASH_INTERVAL = 15      # seconds between full CSV hash checks (catches cp -p)
CSV_MAPPING_REFRESH = 15    # seconds between rule_csv_map.csv re-reads (was 60)
HEARTBEAT_INTERVAL = 300    # seconds between heartbeat events

# Import watch lists from wl_fim (single source of truth for code/sentinel files)
try:
    sys.path.insert(0, os.path.join(APP_DIR, "bin"))
    from wl_fim import WATCH_CODE, WATCH_SENTINELS
except ImportError:
    sys.stderr.write(
        "wl_fim_watch WARNING: cannot import from wl_fim, "
        "using hardcoded fallback file list.\n"
    )
    WATCH_CODE = [
        os.path.join(APP_DIR, "bin", "wl_handler.py"),
        os.path.join(APP_DIR, "bin", "wl_constants.py"),
        os.path.join(APP_DIR, "bin", "wl_fim.py"),
        os.path.join(APP_DIR, "default", "app.conf"),
    ]
    WATCH_SENTINELS = [
        os.path.join(VERSIONS_DIR, ".cooldown_initialized"),
        os.path.join(VERSIONS_DIR, ".cooldown_tamper"),
        os.path.join(VERSIONS_DIR, "_emergency_lockdown.json"),
        INSTANCE_CFG,
    ]

STATIC_PATHS = WATCH_CODE + WATCH_SENTINELS

# Graceful shutdown
_running = True


def _handle_signal(signum, frame):
    global _running
    _running = False


signal.signal(signal.SIGTERM, _handle_signal)
signal.signal(signal.SIGINT, _handle_signal)


_LOCKDOWN_STATE_PATH = os.path.join(
    VERSIONS_DIR, "_emergency_lockdown.json")
FIM_ALERT_QUEUE_PATH = os.path.join(
    VERSIONS_DIR, "_fim_alert_queue.jsonl")
FIM_NOTIFY_SEVERITIES = {"HIGH", "CRITICAL"}


def _queue_fim_notification(event):
    """Append HIGH/CRITICAL event to the alert queue for in-app bell.

    Matches wl_fim.py's helper so both scripts share the format. Handler
    drains lazily on next superadmin poll.

    Events use `monitored_path` (filesystem) and/or `csv_file` (CSVs).
    Prefer monitored_path > path > csv_file for the identifier.
    """
    try:
        path = (event.get("monitored_path", "")
                or event.get("path", "")
                or event.get("csv_file", ""))
        key_parts = [
            str(event.get("timestamp", "")),
            event.get("action", ""),
            path,
        ]
        event_id = "fim_" + "_".join(p.replace("/", "-") for p in key_parts)
        queued = {
            "id": event_id,
            "timestamp": event.get("timestamp"),
            "action": event.get("action"),
            "severity": event.get("severity"),
            "path": path,
            "lockdown_active": event.get("lockdown_active", False),
            "details": event.get("details", "")[:500],
            "source_script": event.get("source_script", "wl_fim_watch"),
        }
        os.makedirs(os.path.dirname(FIM_ALERT_QUEUE_PATH), exist_ok=True)
        with open(FIM_ALERT_QUEUE_PATH, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(queued) + "\n")
    except OSError:
        pass


def _is_lockdown_active():
    """Read emergency lockdown state from disk (fresh per call).

    Unlike wl_fim.py which is a re-invoked scripted input, wl_fim_watch
    is a persistent daemon — so we can't cache lockdown state at startup.
    The file is small (~200 bytes) and reads are cheap; we read on every
    emit to ensure events are tagged with the current state, not a stale
    snapshot from when the watcher started.
    """
    try:
        if not os.path.isfile(_LOCKDOWN_STATE_PATH):
            return False
        with open(_LOCKDOWN_STATE_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return bool(data.get("locked"))
    except (OSError, json.JSONDecodeError):
        return False


def _emit(event):
    event.setdefault("timestamp", int(time.time()))
    event.setdefault("timestamp_human",
                     datetime.now(timezone.utc)
                     .strftime("%Y-%m-%d %H:%M:%S UTC"))
    event["source_script"] = "wl_fim_watch"
    # Tag events with lockdown state. Any CSV mutation during an active
    # lockdown is unauthorized by definition (handler writes are frozen)
    # and should be escalated to CRITICAL regardless of the caller's
    # default severity.
    lockdown_active = _is_lockdown_active()
    event["lockdown_active"] = lockdown_active
    if lockdown_active:
        prior = event.get("severity", "INFO")
        if prior != "CRITICAL":
            event["severity_before_lockdown_promotion"] = prior
            event["severity"] = "CRITICAL"
    # Push HIGH/CRITICAL into the notification queue after lockdown
    # promotion — so even INFO-level CSV writes get surfaced when the
    # app is locked down.
    if event.get("severity") in FIM_NOTIFY_SEVERITIES:
        _queue_fim_notification(event)
    sys.stdout.write(json.dumps(event) + "\n")
    sys.stdout.flush()


def _file_hash(path):
    if not os.path.isfile(path):
        return None
    try:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _stat_key(path):
    """Return (mtime, size, exists) for quick change detection."""
    try:
        st = os.stat(path)
        return (st.st_mtime, st.st_size, True)
    except OSError:
        return (0, 0, False)


# ────────────────────────────────────────────────────────────────
# CSV mapping and expected-hash management
# ────────────────────────────────────────────────────────────────

def _read_csv_mapping():
    """Read rule_csv_map.csv and return list of (csv_file, app_context) tuples."""
    if not os.path.isfile(MAPPING_FILE):
        return []
    try:
        result = []
        with open(MAPPING_FILE, "r", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                csv_file = row.get("csv_file", "").strip()
                app_ctx = row.get("app_context", "").strip()
                if csv_file:
                    result.append((csv_file, app_ctx))
        return result
    except (OSError, csv.Error):
        return []


def _resolve_csv_paths(mapping):
    """Convert (csv_file, app_context) tuples to absolute filesystem paths.

    Returns dict of {absolute_path: csv_filename} for existing files.
    """
    paths = {}
    for csv_file, app_ctx in mapping:
        if app_ctx and app_ctx != "wl_manager":
            # Cross-app lookups — resolve via Splunk's apps directory
            path = os.path.join(
                os.path.dirname(APP_DIR), app_ctx, "lookups", csv_file)
        else:
            path = os.path.join(LOOKUPS_DIR, csv_file)
        if os.path.isfile(path):
            paths[path] = csv_file
    return paths


def _derive_hash_registry_key():
    """Derive HMAC key for verifying the expected-hash registry."""
    # Same construction as wl_csv._derive_hash_registry_key()
    try:
        sys.path.insert(0, os.path.join(APP_DIR, "bin"))
        from wl_constants import FIM_HMAC_SALT
    except ImportError:
        FIM_HMAC_SALT = b"wl_manager_fim_integrity_v1"
    guid = ""
    try:
        with open(INSTANCE_CFG, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line.startswith("guid"):
                    parts = line.split("=", 1)
                    if len(parts) == 2:
                        guid = parts[1].strip()
                        break
    except OSError:
        pass
    if guid:
        return hashlib.sha256(FIM_HMAC_SALT + guid.encode("utf-8")).digest()
    return hashlib.sha256(FIM_HMAC_SALT).digest()


_hash_registry_key = None  # cached at first use


def _bootstrap_registry_if_empty():
    """Auto-create the expected-hash registry on first run.

    On a fresh install, no registry file exists and the watcher would
    emit ``fim_csv_unregistered`` alerts for every CSV.  This creates
    an initial registry by hashing all managed CSVs — safe because on
    first run there's no "previous expected" state to compare against.

    Only runs when the file does NOT exist (never overwrites an
    existing registry, even a tampered one — that's the watcher's job
    to detect).
    """
    if os.path.isfile(EXPECTED_HASHES_FILE):
        return  # Registry exists — do not overwrite

    mapping = _read_csv_mapping()
    if not mapping:
        return  # No mapping file yet

    import hmac as _hmac

    hashes = {}
    for csv_file, app_ctx in mapping:
        if app_ctx and app_ctx != "wl_manager":
            path = os.path.join(os.path.dirname(APP_DIR), app_ctx,
                                "lookups", csv_file)
        else:
            path = os.path.join(LOOKUPS_DIR, csv_file)
        if os.path.isfile(path):
            hashes[csv_file] = _file_hash(path)

    # Also include rule_csv_map.csv itself (sentinel)
    if os.path.isfile(MAPPING_FILE):
        hashes["rule_csv_map.csv"] = _file_hash(MAPPING_FILE)

    if not hashes:
        return

    # Write with HMAC signature
    global _hash_registry_key
    if _hash_registry_key is None:
        _hash_registry_key = _derive_hash_registry_key()
    payload = json.dumps(hashes, sort_keys=True)
    checksum = _hmac.new(_hash_registry_key, payload.encode("utf-8"),
                         hashlib.sha256).hexdigest()
    hashes["_checksum"] = checksum

    os.makedirs(os.path.dirname(EXPECTED_HASHES_FILE), exist_ok=True)
    temp = EXPECTED_HASHES_FILE + ".tmp"
    try:
        with open(temp, "w", encoding="utf-8") as fh:
            json.dump(hashes, fh, indent=2)
        os.replace(temp, EXPECTED_HASHES_FILE)
    except OSError:
        try:
            os.remove(temp)
        except OSError:
            pass
        return

    _emit({
        "action": "fim_csv_auto_bootstrap",
        "severity": "INFO",
        "hashed_count": len(hashes) - 1,  # exclude _checksum
        "details": "Auto-created expected-hash registry on first run "
                   "(no previous registry file found)",
    })


def _read_expected_hashes():
    """Read and HMAC-verify the expected-hashes registry.

    Returns hash entries if HMAC is valid, empty dict if tampered/missing.
    Fail-closed: if the HMAC doesn't match, ALL CSVs are treated as
    unregistered → any change triggers an alert.
    """
    global _hash_registry_key
    if _hash_registry_key is None:
        _hash_registry_key = _derive_hash_registry_key()

    try:
        with open(EXPECTED_HASHES_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}

    stored = data.pop("_checksum", None)
    if stored is None:
        # Legacy file without HMAC — accept but warn
        return data

    import hmac as _hmac
    filtered = {k: v for k, v in data.items() if k != "_checksum"}
    payload = json.dumps(filtered, sort_keys=True)
    expected = _hmac.new(_hash_registry_key, payload.encode("utf-8"),
                         hashlib.sha256).hexdigest()
    if stored != expected:
        _emit({
            "action": "fim_csv_hash_registry_tampered",
            "severity": "CRITICAL",
            "details": "Expected-hash registry HMAC verification failed — "
                       "an attacker may have modified both CSVs and the "
                       "hash registry to cover their tracks.",
        })
        return {}  # Fail closed: treat all CSVs as unregistered
    return data


# ────────────────────────────────────────────────────────────────
# Main loop
# ────────────────────────────────────────────────────────────────

def main():
    # Auto-bootstrap the expected-hash registry if this is a fresh install
    # (no registry file exists). Must run before CSV monitoring starts.
    _bootstrap_registry_if_empty()

    # Initial stat snapshot for static paths (code + sentinels)
    prev_stats = {}
    for path in STATIC_PATHS:
        prev_stats[path] = _stat_key(path)

    # Initial CSV discovery
    csv_mapping = _read_csv_mapping()
    csv_paths = _resolve_csv_paths(csv_mapping)  # {abs_path: csv_filename}

    # Sentinel CSVs: infrastructure files that get CRITICAL severity
    # (same as code-file sentinels). rule_csv_map.csv controls which
    # CSVs map to which detection rules — modifying it via SPL redirects
    # detection rule whitelists without touching any whitelist CSV.
    SENTINEL_CSVS = {MAPPING_FILE}
    if MAPPING_FILE not in csv_paths and os.path.isfile(MAPPING_FILE):
        csv_paths[MAPPING_FILE] = os.path.basename(MAPPING_FILE)

    csv_prev_stats = {}
    csv_prev_hashes = {}  # {abs_path: hash} — last known hash per CSV
    initial_expected = _read_expected_hashes()
    unregistered_count = 0
    for path in csv_paths:
        csv_prev_stats[path] = _stat_key(path)
        csv_prev_hashes[path] = _file_hash(path)
        # Alert on CSVs that exist but have no expected hash
        csv_name = csv_paths[path]
        if csv_name not in initial_expected and os.path.isfile(path):
            unregistered_count += 1
            _emit({
                "action": "fim_csv_unregistered",
                "csv_file": csv_name,
                "monitored_path": path,
                "severity": "HIGH",
                "details": "CSV exists in mapping but has no expected hash "
                           "— may have been created outside wl_manager handler",
            })

    total_watched = len(STATIC_PATHS) + len(csv_paths)
    _emit({
        "action": "fim_watch_started",
        "severity": "INFO",
        "watched_code_files": len(STATIC_PATHS),
        "watched_csv_files": len(csv_paths),
        "total_watched": total_watched,
        "fast_interval_seconds": FAST_INTERVAL,
        "csv_hash_interval_seconds": CSV_HASH_INTERVAL,
    })

    last_heartbeat = time.monotonic()
    last_csv_full_hash = time.monotonic()
    last_csv_mapping_refresh = time.monotonic()
    _force_mapping_refresh = False  # set when rule_csv_map.csv changes

    while _running:
        time.sleep(FAST_INTERVAL)
        now = time.monotonic()

        # ── Static file monitoring (code + sentinels) ──
        for path in STATIC_PATHS:
            current = _stat_key(path)
            prev = prev_stats.get(path, (0, 0, False))
            if current == prev:
                continue
            is_sentinel = path in WATCH_SENTINELS
            severity = "HIGH" if is_sentinel else "MEDIUM"
            if current[2] and not prev[2]:
                _emit({
                    "action": "fim_watch_file_appeared",
                    "monitored_path": path,
                    "new_hash": _file_hash(path),
                    "severity": severity,
                    "detection_method": "stat_watch",
                })
            elif not current[2] and prev[2]:
                _emit({
                    "action": "fim_watch_file_removed",
                    "monitored_path": path,
                    "severity": severity,
                    "detection_method": "stat_watch",
                })
            elif current[0] != prev[0] or current[1] != prev[1]:
                _emit({
                    "action": "fim_watch_file_modified",
                    "monitored_path": path,
                    "new_hash": _file_hash(path),
                    "severity": severity,
                    "detection_method": "stat_watch",
                })
            prev_stats[path] = current

        # ── CSV file monitoring (stat-based fast path) ──
        expected_hashes = _read_expected_hashes()

        for path, csv_name in list(csv_paths.items()):
            current = _stat_key(path)
            prev = csv_prev_stats.get(path, (0, 0, False))

            if current == prev:
                continue

            # Stat changed — hash the file to check legitimacy
            new_hash = _file_hash(path)
            csv_prev_stats[path] = current

            if not current[2] and prev[2]:
                # CSV deleted outside handler
                expected = expected_hashes.get(csv_name)
                if expected is not None:
                    # Handler didn't remove it from expected hashes →
                    # external deletion
                    _emit({
                        "action": "fim_csv_external_deletion",
                        "csv_file": csv_name,
                        "monitored_path": path,
                        "severity": "CRITICAL",
                        "detection_method": "stat_watch",
                        "details": "CSV file deleted outside wl_manager handler",
                    })
                csv_prev_hashes[path] = None
                continue

            if current[2] and not prev[2]:
                # CSV appeared — could be restore or external creation
                expected = expected_hashes.get(csv_name)
                if expected and new_hash == expected:
                    # Hash matches expected → legitimate (restore, create)
                    csv_prev_hashes[path] = new_hash
                    continue
                # No expected hash or mismatch → external creation
                _emit({
                    "action": "fim_csv_external_creation",
                    "csv_file": csv_name,
                    "monitored_path": path,
                    "new_hash": new_hash,
                    "severity": "HIGH",
                    "detection_method": "stat_watch",
                    "details": "CSV file created outside wl_manager handler",
                })
                csv_prev_hashes[path] = new_hash
                continue

            # File modified — the critical check
            expected = expected_hashes.get(csv_name)
            old_hash = csv_prev_hashes.get(path)

            if new_hash == expected:
                # Hash matches expected → legitimate handler write.
                # No alert. Update local cache silently.
                csv_prev_hashes[path] = new_hash
                # If rule_csv_map.csv was legitimately updated (handler
                # added/removed a CSV), refresh the watch list immediately
                if path == MAPPING_FILE:
                    _force_mapping_refresh = True
                continue

            if new_hash == old_hash:
                # Hash unchanged despite stat change (e.g., touch without
                # content change, or metadata-only update). Ignore.
                continue

            # MISMATCH: file hash differs from both the expected hash
            # AND the previous known hash → external modification.
            is_sentinel_csv = path in SENTINEL_CSVS
            evt = {
                "action": "fim_csv_external_modification",
                "csv_file": csv_name,
                "monitored_path": path,
                "expected_hash": expected or "(not registered)",
                "actual_hash": new_hash,
                "severity": "CRITICAL",
                "detection_method": "stat_watch",
                "details": "CSV modified outside wl_manager handler "
                           "(SPL outputlookup, REST API, or filesystem edit)",
            }
            if is_sentinel_csv:
                evt["sentinel_csv"] = True
                evt["details"] = ("SENTINEL: {} modified outside handler — "
                                  "detection rule mappings may be compromised"
                                  .format(csv_name))
                # Sentinel CSV changed → force immediate mapping refresh
                # so newly added/removed CSVs are picked up within seconds
                if path == MAPPING_FILE:
                    _force_mapping_refresh = True
            _emit(evt)
            csv_prev_hashes[path] = new_hash

        # ── Full CSV hash sweep (catches mtime-preserving attacks) ──
        if now - last_csv_full_hash >= CSV_HASH_INTERVAL:
            expected_hashes = _read_expected_hashes()
            for path, csv_name in csv_paths.items():
                if not os.path.isfile(path):
                    continue
                current_hash = _file_hash(path)
                expected = expected_hashes.get(csv_name)
                old_hash = csv_prev_hashes.get(path)

                if current_hash == expected:
                    # Matches expected — legitimate
                    csv_prev_hashes[path] = current_hash
                    continue

                if current_hash == old_hash:
                    # No actual content change since last check
                    continue

                # Content changed without stat trigger (mtime-preserving)
                is_sentinel_csv = path in SENTINEL_CSVS
                sweep_evt = {
                    "action": "fim_csv_external_modification",
                    "csv_file": csv_name,
                    "monitored_path": path,
                    "expected_hash": expected or "(not registered)",
                    "actual_hash": current_hash,
                    "severity": "CRITICAL",
                    "detection_method": "full_hash_sweep",
                    "details": "CSV content changed without mtime update "
                               "(mtime-preserving external write detected)",
                }
                if is_sentinel_csv:
                    sweep_evt["sentinel_csv"] = True
                _emit(sweep_evt)
                csv_prev_hashes[path] = current_hash
                csv_prev_stats[path] = _stat_key(path)

            last_csv_full_hash = now

        # ── Periodic CSV mapping refresh (CSVs can be added/removed) ──
        if _force_mapping_refresh or now - last_csv_mapping_refresh >= CSV_MAPPING_REFRESH:
            _force_mapping_refresh = False
            new_mapping = _read_csv_mapping()
            new_paths = _resolve_csv_paths(new_mapping)
            # Add newly discovered CSVs
            refresh_expected = _read_expected_hashes()
            for path, name in new_paths.items():
                if path not in csv_paths:
                    csv_paths[path] = name
                    csv_prev_stats[path] = _stat_key(path)
                    csv_prev_hashes[path] = _file_hash(path)
                    # Check if this CSV has an expected hash — if not,
                    # it was created outside the handler (SPL, filesystem).
                    if name not in refresh_expected:
                        _emit({
                            "action": "fim_csv_unregistered",
                            "csv_file": name,
                            "monitored_path": path,
                            "severity": "HIGH",
                            "details": "CSV exists in mapping but has no "
                                       "expected hash — may have been "
                                       "created outside wl_manager handler",
                        })
            # Remove CSVs no longer in mapping
            for path in list(csv_paths.keys()):
                if path not in new_paths:
                    del csv_paths[path]
                    csv_prev_stats.pop(path, None)
                    csv_prev_hashes.pop(path, None)
            csv_mapping = new_mapping
            last_csv_mapping_refresh = now

        # ── Heartbeat ──
        if now - last_heartbeat >= HEARTBEAT_INTERVAL:
            _emit({
                "action": "fim_watch_heartbeat",
                "severity": "INFO",
                "watched_code_files": len(STATIC_PATHS),
                "watched_csv_files": len(csv_paths),
                "total_watched": len(STATIC_PATHS) + len(csv_paths),
            })
            last_heartbeat = now

    _emit({
        "action": "fim_watch_stopped",
        "severity": "INFO",
    })


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write("wl_fim_watch error: {}\n".format(exc))
        sys.exit(1)
