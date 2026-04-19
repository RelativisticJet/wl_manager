#!/usr/bin/env python3
"""
wl_migrate_cooldowns.py — One-shot KV schema migration for wl_cooldowns.

This script exists so a schema version bump does NOT require a full
reset_cooldowns.sh run (which drops the counter state and forces a
fresh install bootstrap). Instead, an admin runs this tool to re-sign
existing records under the new format.

Usage (inside the Splunk container):

    # Prefer system python3 — it has a working ssl module:
    python3 /opt/splunk/etc/apps/wl_manager/bin/wl_migrate_cooldowns.py \\
        --from 0 --to 1 [--dry-run] [--auth admin:Chang3d!]

    # Or with Splunk bundled Python + env sourced:
    source /opt/splunk/bin/setSplunkEnv
    /opt/splunk/bin/python3 \\
        /opt/splunk/etc/apps/wl_manager/bin/wl_migrate_cooldowns.py \\
        --from 0 --to 1 [--dry-run] [--auth admin:Chang3d!]

Supported migrations (the dict ``MIGRATIONS`` below):

    (0 → 1)  pre-schema_version (build 552) records re-signed with
             the v1 HMAC format (checksum = HMAC(key, "v1:"+payload))
             and ``schema_version: 1`` added to the top-level record.

Future schema bumps: add a new entry like ``(1, 2): (verify_v1, sign_v2)``
and implement the pair of callables. The tool will refuse any
unsupported (from, to) combination so an accidental run cannot
corrupt state.

This tool NEVER writes unless the old-format HMAC verifies first
— if verification fails, the record is presumed tampered or
already-migrated and the tool bails with a non-zero exit code.
Append-only audit trail: every run (dry or not) appends a record to
lookups/_versions/_recovery_log.jsonl so the operation is visible
in the Audit dashboard exactly like emergency_unlock / reset_cooldowns.
"""
import argparse
import hashlib
import hmac
import json
import os
import sys
import time
from datetime import datetime, timezone
from urllib.parse import quote

import urllib.request
import ssl

APP_NAME = "wl_manager"
COLLECTION = "wl_cooldowns"
KEY = "state"
INSTANCE_CFG = "/opt/splunk/etc/instance.cfg"
VERSIONS_DIR = "/opt/splunk/etc/apps/wl_manager/lookups/_versions"
RECOVERY_LOG = os.path.join(VERSIONS_DIR, "_recovery_log.jsonl")

# HMAC salts — imported from wl_constants (single source of truth).
# The migration tool needs both V0 and V1 salts to verify old-format
# records and re-sign under the new format. V0 and V1 happen to use
# the same underlying salt today; if V2 changes it, add HMAC_SALT_V0
# as a separate constant in wl_constants.
try:
    # When run from the app's bin/ directory or via Splunk's python
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from wl_constants import COOLDOWN_HMAC_SALT
    HMAC_SALT_V1 = COOLDOWN_HMAC_SALT
    HMAC_SALT_V0 = COOLDOWN_HMAC_SALT  # same salt for v0 and v1
except ImportError:
    # Fallback for standalone execution outside the app directory
    HMAC_SALT_V1 = b"wl_manager_cooldown_integrity_v2"
    HMAC_SALT_V0 = b"wl_manager_cooldown_integrity_v2"
    print("WARNING: using hardcoded HMAC salt (wl_constants import "
          "failed). Ensure the salt matches wl_constants.py.",
          file=sys.stderr)

# Shared FIM/KV helpers (Phase 3b consolidation — CLAUDE.md 2026-04-19).
# This migration tool uses ``strict=True`` so a missing GUID fails loud
# instead of silently producing a zero-entropy key and re-signing every
# record under a predictable HMAC.
from wl_fim_common import (
    kv_collection_url as _kv_collection_url,
    read_splunk_guid,
)


def _read_guid():
    """Strict GUID read — migrations must fail loud on missing GUID."""
    return read_splunk_guid(INSTANCE_CFG, strict=True)


def _derive_key(salt):
    guid = _read_guid()
    return hashlib.sha256(salt + guid.encode("utf-8")).digest()


def _sign_v0(payload_json, key):
    """HMAC over the raw payload JSON (build 552 format)."""
    return hmac.new(key, payload_json.encode("utf-8"),
                    hashlib.sha256).hexdigest()


def _sign_v1(payload_json, key):
    """HMAC over 'v1:' + payload JSON (build 553+ format)."""
    signed = "v1:" + payload_json
    return hmac.new(key, signed.encode("utf-8"),
                    hashlib.sha256).hexdigest()


def verify_v0(record, key):
    payload_str = record.get("payload", "")
    stored = record.get("checksum", "")
    if not payload_str or not stored:
        return False, "missing payload or checksum"
    expected = _sign_v0(payload_str, key)
    if expected != stored:
        return False, "v0 HMAC mismatch"
    # v0 records MUST NOT have a schema_version field
    if "schema_version" in record:
        return False, ("record already has schema_version — probably "
                       "already migrated")
    return True, "ok"


def sign_v1(record, key):
    """Return a new record dict signed under the v1 format."""
    payload_str = record.get("payload", "")
    new = dict(record)
    new["schema_version"] = 1
    new["checksum"] = _sign_v1(payload_str, key)
    new["updated_at"] = int(time.time())
    new["updated_by"] = new.get("updated_by", "migration")
    return new


# (from_version, to_version) → (verifier, signer)
MIGRATIONS = {
    (0, 1): (verify_v0, sign_v1),
}


def _kv_url(suffix=""):
    """Build the KV-store REST URL for the wl_cooldowns collection."""
    return _kv_collection_url(APP_NAME, COLLECTION, suffix)


def _http(method, url, auth, body=None):
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    req = urllib.request.Request(url, method=method)
    user, pw = auth.split(":", 1)
    import base64
    token = base64.b64encode((user + ":" + pw).encode()).decode()
    req.add_header("Authorization", "Basic " + token)
    req.add_header("Content-Type", "application/json")
    if body is not None:
        req_body = json.dumps(body).encode("utf-8")
    else:
        req_body = None
    try:
        resp = urllib.request.urlopen(req, data=req_body, context=ctx)
        return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")


def kv_read(auth):
    status, body = _http("GET", _kv_url("/" + KEY + "?output_mode=json"), auth)
    if status == 200:
        return json.loads(body)
    if status == 404:
        return None
    raise RuntimeError("KV GET failed status={} body={}".format(status, body[:200]))


def kv_write(auth, record):
    # Try update first
    status, body = _http("POST", _kv_url("/" + KEY), auth, record)
    if status in (200, 201):
        return True
    if status == 404:
        # Insert via collection endpoint
        body_with_key = dict(record)
        body_with_key["_key"] = KEY
        status, body = _http("POST", _kv_url(""), auth, body_with_key)
        if status in (200, 201):
            return True
    raise RuntimeError("KV PUT failed status={} body={}".format(status, body[:200]))


def _append_recovery_log(entry):
    os.makedirs(os.path.dirname(RECOVERY_LOG), exist_ok=True)
    with open(RECOVERY_LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")
    try:
        os.chmod(RECOVERY_LOG, 0o644)
    except OSError:
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="from_version", type=int, required=True,
                        help="Current schema version (e.g. 0 for build 552)")
    parser.add_argument("--to", dest="to_version", type=int, required=True,
                        help="Target schema version (e.g. 1 for build 553)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Verify old signature and PRINT the new record "
                             "without writing.")
    parser.add_argument("--auth", default="admin:changeme",
                        help="Splunk basic auth (user:password). Default "
                             "'admin:changeme' — must be overridden.")
    parser.add_argument("--reason", default="schema migration",
                        help="Reason for the operation — written to the "
                             "recovery log.")
    args = parser.parse_args()

    pair = (args.from_version, args.to_version)
    if pair not in MIGRATIONS:
        print("ERROR: unsupported migration {} → {}. Supported: {}".format(
            args.from_version, args.to_version,
            ", ".join("{}→{}".format(a, b) for (a, b) in MIGRATIONS)))
        sys.exit(2)

    verify, sign = MIGRATIONS[pair]

    # Both verify and sign need the HMAC key — in v0/v1 they share
    # the same underlying salt so a single derived key works. If a
    # future migration changes the salt, keep two derived keys here.
    key = _derive_key(HMAC_SALT_V1)

    print("Reading current wl_cooldowns/state record...")
    record = kv_read(args.auth)
    if record is None:
        print("No KV record found. Nothing to migrate.")
        _append_recovery_log({
            "timestamp": int(time.time()),
            "timestamp_human": datetime.now(timezone.utc)
                .strftime("%Y-%m-%d %H:%M:%S UTC"),
            "action": "migrate_cooldowns",
            "script": "wl_migrate_cooldowns.py",
            "from_version": args.from_version,
            "to_version": args.to_version,
            "status": "no_record",
            "dry_run": args.dry_run,
            "reason": args.reason[:500],
        })
        sys.exit(0)

    ok, why = verify(record, key)
    if not ok:
        print("ERROR: old-format verification failed: {}".format(why))
        print("  This can mean:")
        print("    - the record is already at the target version")
        print("    - the record was tampered with")
        print("    - the HMAC salt was rotated without migration path")
        print("  Run scripts/reset_cooldowns.sh as a last resort.")
        _append_recovery_log({
            "timestamp": int(time.time()),
            "timestamp_human": datetime.now(timezone.utc)
                .strftime("%Y-%m-%d %H:%M:%S UTC"),
            "action": "migrate_cooldowns",
            "script": "wl_migrate_cooldowns.py",
            "from_version": args.from_version,
            "to_version": args.to_version,
            "status": "verify_failed",
            "reason_text": why,
            "dry_run": args.dry_run,
        })
        sys.exit(3)

    new_record = sign(record, key)
    # Strip KV store internal metadata so the PUT body is clean
    for meta in ("_key", "_user"):
        new_record.pop(meta, None)

    print("Old record (verified):")
    print("  schema_version: {}".format(record.get("schema_version", "<absent>")))
    print("  checksum[:16]:  {}".format(record.get("checksum", "")[:16]))
    print("New record:")
    print("  schema_version: {}".format(new_record.get("schema_version")))
    print("  checksum[:16]:  {}".format(new_record.get("checksum", "")[:16]))

    if args.dry_run:
        print("\n--dry-run — not writing.")
        _append_recovery_log({
            "timestamp": int(time.time()),
            "timestamp_human": datetime.now(timezone.utc)
                .strftime("%Y-%m-%d %H:%M:%S UTC"),
            "action": "migrate_cooldowns",
            "script": "wl_migrate_cooldowns.py",
            "from_version": args.from_version,
            "to_version": args.to_version,
            "status": "dry_run_ok",
            "reason": args.reason[:500],
        })
        return

    kv_write(args.auth, new_record)
    print("\nMigration complete.")
    _append_recovery_log({
        "timestamp": int(time.time()),
        "timestamp_human": datetime.now(timezone.utc)
            .strftime("%Y-%m-%d %H:%M:%S UTC"),
        "action": "migrate_cooldowns",
        "script": "wl_migrate_cooldowns.py",
        "from_version": args.from_version,
        "to_version": args.to_version,
        "status": "applied",
        "reason": args.reason[:500],
    })


if __name__ == "__main__":
    main()
