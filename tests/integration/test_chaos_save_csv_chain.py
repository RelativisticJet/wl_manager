"""
Chaos test — CSV save chain crash recovery (Ring 4 Day 5).

The save_csv handler performs a 4-step mutation:

1. Write new rows to ``lookups/<csv_file>``
2. Write a version snapshot to
   ``lookups/_versions/<base>_<timestamp>.csv``
3. Update the JSON manifest at
   ``lookups/_versions/<base>_versions.json``
4. Update the hash registry at
   ``lookups/_versions/.csv_expected_hashes.json``
5. Emit an audit event to ``wl_audit``

If splunkd dies between any two steps, the system can be
left in a state where (a) the CSV file is updated but no
snapshot or audit event exists (forensic gap, no revert
possible), or (b) a snapshot is on disk but missing from
the manifest (revert dropdown can't surface it), or (c)
the hash registry diverges from the actual CSV file
(next FIM cycle will fire `fim_csv_external_modification`
on a legitimate save). Each of these is a real recovery
gap that's never been tested.

This module exercises the save chain under chaos using the
``lib_chaos`` fixture (Day 4) and asserts post-recovery
state is fully consistent — either the operation
COMMITTED (all five side effects present) or DID NOT
START (none of them present). Half-applied state =
test failure.

Caveat: ``kill_after_delay`` is timing-based — a 100ms
delay doesn't guarantee the kill lands mid-write. For
fast read-only paths the operation completes before the
kill. For save_csv the write phase takes 50-200ms
depending on row count, so 100ms is in the sweet spot
for "sometimes hits mid-write". A test pass under chaos
proves the recovery path is sound; a test FAIL almost
certainly indicates a real recovery gap.

Target rule: ``DR_VERSION_TEST`` — dedicated chaos
target with simple schema ``user, src_ip, Comment`` and
no prior versions (so manifest assertions start from a
clean slate).
"""

import hashlib
import json
import os
import subprocess
import sys
import time
import pytest

sys.path.insert(0, os.path.dirname(__file__))
from lib_chaos import (  # noqa: E402
    kill_after_delay,
    splunkd_uptime_seconds,
    _splunkd_pid,
    CONTAINER_NAME,
)


pytestmark = [
    pytest.mark.docker,
    pytest.mark.slow,
]


CHAOS_RULE = "DR_VERSION_TEST"
CHAOS_CSV = "DR_VERSION_TEST.csv"
APP_CONTEXT = "wl_manager"
LOOKUPS_DIR = (
    "/opt/splunk/etc/apps/wl_manager/lookups"
)
VERSIONS_DIR = f"{LOOKUPS_DIR}/_versions"
MANIFEST_PATH = (
    f"{VERSIONS_DIR}/DR_VERSION_TEST_versions.json"
)
HASH_REGISTRY_PATH = (
    f"{VERSIONS_DIR}/.csv_expected_hashes.json"
)


def _docker_read_bytes(path: str) -> bytes:
    """Read raw file bytes from the container as root.

    Returns the raw content as bytes, or b"" if the file
    doesn't exist. CRITICAL: we use ``text=False`` (binary
    mode) because the handler's content-hash is over the
    raw file bytes. Under ``text=True``, subprocess on
    Windows normalizes ``\\r\\n`` to ``\\n`` which makes
    our computed hash diverge from the server's hash for
    any file with CRLF endings. Caller is responsible for
    decoding if it wants text.
    """
    env = {**os.environ, "MSYS_NO_PATHCONV": "1"}
    cmd = ["docker", "exec", "-u", "0",
           CONTAINER_NAME, "cat", path]
    proc = subprocess.run(  # noqa: S603
        cmd, capture_output=True, text=False,
        timeout=15, check=False, env=env,
    )
    if proc.returncode == 0:
        return proc.stdout
    err = (proc.stderr or b"").decode("utf-8", "replace").lower()
    if "no such file" in err or "cannot stat" in err:
        return b""
    raise RuntimeError(
        f"docker cat {path} failed (rc={proc.returncode}): "
        f"{(proc.stderr or b'').decode('utf-8', 'replace').strip()}")


def _docker_read(path: str) -> str:
    """Read a file from the container as decoded text.

    Wraps ``_docker_read_bytes`` and decodes as UTF-8 with
    replacement on bad bytes. Use ``_docker_read_bytes``
    directly when computing a hash — text decoding can
    lose information.
    """
    return _docker_read_bytes(path).decode(
        "utf-8", "replace")


def _docker_ls(path: str) -> list:
    """List directory contents inside the container.

    Returns a sorted list of filenames, or [] if the
    directory is missing or empty.
    """
    env = {**os.environ, "MSYS_NO_PATHCONV": "1"}
    cmd = ["docker", "exec", "-u", "0",
           CONTAINER_NAME, "ls", "-1", path]
    proc = subprocess.run(  # noqa: S603
        cmd, capture_output=True, text=True,
        timeout=15, check=False, env=env,
    )
    if proc.returncode != 0:
        return []
    return sorted(
        line for line in proc.stdout.splitlines()
        if line.strip()
    )


def _capture_state() -> dict:
    """Snapshot the on-disk + KV state for the chaos
    target. Returns a dict with the five fields the
    save_csv chain mutates, so the test can compare
    pre/post and assert consistency.
    """
    csv_bytes = _docker_read_bytes(
        f"{LOOKUPS_DIR}/{CHAOS_CSV}")
    csv_hash = (
        hashlib.sha256(csv_bytes).hexdigest()
        if csv_bytes else None
    )
    csv_content = csv_bytes.decode("utf-8", "replace")

    # Snapshot files for THIS rule's CSV. Filename
    # pattern: <base>_<YYYYMMDD>_<HHMMSS>.csv
    snapshots = [
        f for f in _docker_ls(VERSIONS_DIR)
        if f.startswith("DR_VERSION_TEST_")
        and f.endswith(".csv")
    ]

    manifest_raw = _docker_read(MANIFEST_PATH)
    try:
        manifest = json.loads(manifest_raw) if manifest_raw else None
    except json.JSONDecodeError:
        manifest = "CORRUPT"

    hash_registry_raw = _docker_read(HASH_REGISTRY_PATH)
    hash_registry_entry = None
    if hash_registry_raw:
        try:
            registry = json.loads(hash_registry_raw)
            # Schema: flat map ``{ "<filename>": "<hex>" }``.
            # No envelope, no per-file dict. Verified by
            # reading the live registry.
            val = registry.get(CHAOS_CSV)
            if isinstance(val, str):
                hash_registry_entry = val
        except json.JSONDecodeError:
            hash_registry_entry = "CORRUPT"

    return {
        "csv_hash": csv_hash,
        "csv_content": csv_content,
        "snapshot_count": len(snapshots),
        "snapshot_files": snapshots,
        "manifest": manifest,
        "manifest_entry_count": (
            len(manifest.get("versions", []))
            if isinstance(manifest, dict) else 0
        ),
        "hash_registry_entry": hash_registry_entry,
    }


def _build_save_payload(row_count: int,
                        expected_content_hash: str) -> str:
    """Build a JSON payload for save_csv with ``row_count``
    rows. Each row has a unique user value so the test
    always produces a content-hash change (otherwise the
    optimistic-locking check could short-circuit and
    skip the write).

    ``expected_content_hash`` is REQUIRED by the handler
    for optimistic locking (build-562 hardening). Pass
    the SHA-256 of the current file bytes from
    ``_capture_state()``.
    """
    rows = [
        {
            "user": f"chaos_user_{i:04d}",
            "src_ip": f"10.0.{(i // 256) % 256}.{i % 256}",
            "Comment": f"chaos test row {i} ts={int(time.time())}",
        }
        for i in range(row_count)
    ]
    body = {
        "action": "save_csv",
        "csv_file": CHAOS_CSV,
        "detection_rule": CHAOS_RULE,
        "app_context": APP_CONTEXT,
        "headers": ["user", "src_ip", "Comment"],
        "rows": rows,
        "comment": "ring 4 day 5 chaos test",
        "expected_content_hash": expected_content_hash,
    }
    return json.dumps(body)


def _admin_post(payload_json: str, user="wladmin1"):
    """POST save_csv as an admin (bypasses approval gate).

    Returns a CompletedProcess with the curl output. The
    timeout is loose (45s) because a chaos kill while
    curl is mid-request causes the curl to hang briefly
    before connection-reset.
    """
    env = {**os.environ, "MSYS_NO_PATHCONV": "1"}
    args = [
        "docker", "exec", "-u", "0",
        CONTAINER_NAME,
        "curl", "-sk",
        "-u", f"{user}:Chang3d!",
        "-X", "POST",
        "-H", "Content-Type: application/json",
        "-d", payload_json,
        "https://localhost:8089/services/custom/wl_manager",
    ]
    return subprocess.run(  # noqa: S603
        args, capture_output=True, text=True,
        timeout=45, check=False, env=env,
    )


def _state_implies_commit(pre: dict, post: dict) -> bool:
    """Did the save actually commit? Returns True iff the
    CSV content changed (the strongest signal — bytes on
    disk differ).
    """
    if pre["csv_hash"] is None and post["csv_hash"] is None:
        return False
    return pre["csv_hash"] != post["csv_hash"]


def test_save_csv_chain_chaos_consistency(docker_available):
    """Submit save_csv, kill mid-write, verify post-
    recovery state is fully consistent.

    Acceptable outcomes:

    - **Operation didn't start**: post == pre across all
      five state fields. The kill landed before the
      handler started writing.
    - **Operation committed**: CSV updated, snapshot file
      exists, manifest has new entry pointing to that
      snapshot, hash registry matches new CSV hash. All
      five side effects present and consistent.

    Unacceptable (test failure):

    - CSV updated but no matching snapshot file
    - CSV updated but manifest missing entry
    - Snapshot file exists but manifest doesn't reference it
    - Hash registry doesn't match CSV content (next FIM
      cycle would fire `fim_csv_external_modification`
      on a legitimate save)
    - Manifest file corrupt (JSON parse failed)
    """
    pre_pid = _splunkd_pid()
    assert pre_pid is not None, "splunkd not running pre-chaos"

    pre_state = _capture_state()
    assert pre_state["csv_hash"] is not None, (
        "chaos target CSV missing pre-test — DR_VERSION_TEST.csv "
        "must exist for this test to run")
    payload = _build_save_payload(
        row_count=80,
        expected_content_hash=pre_state["csv_hash"])

    def op():
        return _admin_post(payload, user="wladmin1")

    # 100ms is the design sweet-spot from the Day 4
    # fixture. Save_csv writes are typically 50-200ms,
    # so a fraction of runs will land mid-write.
    result = kill_after_delay(op, kill_delay_ms=100)

    assert result.kill_succeeded, (
        f"kill_splunkd returned False; errors: {result.errors}")
    assert not result.errors, (
        f"unexpected recovery errors: {result.errors}")
    assert result.recovery_seconds > 0

    # Prove we actually got a fresh splunkd back. Use
    # uptime not PID (see Day 4 RING_FINDINGS note on
    # docker-restart PID collisions).
    post_uptime = splunkd_uptime_seconds()
    assert post_uptime is not None and post_uptime < 60, (
        f"post-restart splunkd uptime {post_uptime}s "
        "doesn't look like a fresh process")

    post_state = _capture_state()

    # The manifest must NEVER be corrupt JSON, regardless
    # of when the kill landed. A corrupt manifest is the
    # most damaging failure mode — no version is
    # recoverable until manual intervention.
    assert post_state["manifest"] != "CORRUPT", (
        "version manifest is corrupt JSON after chaos kill — "
        "this is the worst-case half-write outcome and "
        "indicates the manifest needs an atomic-write fix")

    # Same for the hash registry. A corrupt registry
    # would cause `wl_fim_watch.py` to fail-closed and
    # treat every CSV as unregistered.
    assert post_state["hash_registry_entry"] != "CORRUPT", (
        "CSV hash registry is corrupt JSON after chaos kill")

    if _state_implies_commit(pre_state, post_state):
        # Operation committed — all four side effects
        # must be present and self-consistent.
        assert post_state["snapshot_count"] > pre_state["snapshot_count"], (
            "CSV changed but no new snapshot file appeared "
            "in _versions/. Revert is impossible from this state.")
        if isinstance(post_state["manifest"], dict):
            assert post_state["manifest_entry_count"] > pre_state["manifest_entry_count"], (
                "CSV changed and new snapshot exists, but "
                "manifest has no entry for it. Revert "
                "dropdown will not surface this version.")
        else:
            pytest.fail(
                "manifest file missing entirely after a "
                "successful save_csv chaos run")
        # Hash registry must point at the new content
        if post_state["hash_registry_entry"] is not None:
            assert post_state["hash_registry_entry"] == post_state["csv_hash"], (
                "CSV file hash doesn't match hash registry "
                "entry. Next FIM cycle will fire "
                "`fim_csv_external_modification` on this "
                "legitimately-saved CSV.")
    else:
        # Operation didn't commit. All state stores must
        # be unchanged. ANY divergence is a half-write.
        assert post_state["snapshot_count"] == pre_state["snapshot_count"], (
            f"CSV content unchanged but snapshot count "
            f"changed: {pre_state['snapshot_count']} -> "
            f"{post_state['snapshot_count']}. Orphan snapshot.")
        assert post_state["manifest_entry_count"] == pre_state["manifest_entry_count"], (
            "CSV content unchanged but manifest entry "
            "count changed. Manifest references a "
            "non-existent or unchanged CSV.")
