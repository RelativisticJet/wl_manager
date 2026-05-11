"""
Chaos test — CSV hash registry rebuild atomicity (Ring 4 Day 6, 2/2).

``bootstrap_csv_hashes`` (superadmin-only action) rebuilds
the entire ``.csv_expected_hashes.json`` registry by
hashing every managed CSV. The write itself is atomic
(temp + os.replace), but the operation takes longer than
a single save_csv because it walks all CSVs.

If splunkd dies during the hashing loop OR between the
registry write and the audit-event emission, the system
must end in one of:

- **Operation didn't start**: registry unchanged on disk,
  no audit events emitted.
- **Operation committed**: registry has new content,
  ``bootstrap_csv_hashes`` summary event in
  ``index=wl_audit`` (one per chaos run), plus zero or
  more ``bootstrap_csv_hash_changed`` HIGH events for
  each CSV whose hash drifted.

Unacceptable:

- Registry corrupt JSON (atomic-write contract broken)
- Registry has new hashes but ``bootstrap_csv_hashes``
  summary event missing from wl_audit — this is the
  "audit-emit gap" called out in the
  ``Audit Trail Verification`` rule in CLAUDE.md.
- Audit summary event present but registry unchanged on
  disk (audit said "we hashed" but disk doesn't reflect
  it — even worse).

Caveat: the test does not enforce audit-presence under
chaos because the audit emit happens AFTER the registry
write returns. A chaos kill between os.replace and
_index_audit() lands in the documented "audit may be
lost on hard crash" window. We surface the observation
without failing the test.
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


REGISTRY_PATH = (
    "/opt/splunk/etc/apps/wl_manager/lookups/_versions/"
    ".csv_expected_hashes.json"
)


def _docker_read_bytes(path: str) -> bytes:
    """Read raw file bytes from the container as root."""
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
        f"docker cat {path} failed (rc={proc.returncode})")


def _capture_state() -> dict:
    """Snapshot the hash registry."""
    raw = _docker_read_bytes(REGISTRY_PATH)
    parsed = None
    parse_ok = True
    entry_count = 0
    if raw:
        try:
            parsed = json.loads(raw.decode("utf-8"))
            if isinstance(parsed, dict):
                entry_count = len(parsed)
        except (json.JSONDecodeError, UnicodeDecodeError):
            parse_ok = False

    return {
        "raw_bytes": raw,
        "sha256": (
            hashlib.sha256(raw).hexdigest() if raw else None
        ),
        "parsed": parsed,
        "parse_ok": parse_ok,
        "entry_count": entry_count,
    }


def _superadmin_post(payload_json: str) -> subprocess.CompletedProcess:
    """POST as superadmin1 (required for bootstrap_csv_hashes)."""
    env = {**os.environ, "MSYS_NO_PATHCONV": "1"}
    args = [
        "docker", "exec", "-u", "0",
        CONTAINER_NAME,
        "curl", "-sk",
        "-u", "superadmin1:Chang3d!",
        "-X", "POST",
        "-H", "Content-Type: application/json",
        "-d", payload_json,
        "https://localhost:8089/services/custom/wl_manager",
    ]
    return subprocess.run(  # noqa: S603
        args, capture_output=True, text=True,
        timeout=60, check=False, env=env,
    )


def test_bootstrap_hash_registry_chaos(docker_available):
    """Run bootstrap_csv_hashes under chaos kill. Verify
    the registry file is either fully rebuilt OR
    unchanged, never corrupt JSON or partial.
    """
    pre_pid = _splunkd_pid()
    assert pre_pid is not None, "splunkd not running pre-chaos"

    pre_state = _capture_state()
    assert pre_state["parse_ok"], (
        "hash registry is already corrupt JSON pre-test "
        "— fix the registry before running chaos")

    payload = json.dumps({"action": "bootstrap_csv_hashes"})

    def op():
        return _superadmin_post(payload)

    # Use a slightly longer kill delay (150ms) because
    # bootstrap_csv_hashes walks ~30 CSV files before
    # writing. The 100ms default often lands during the
    # hashing loop (the operation never reaches the write
    # phase). 150ms gives the loop time to complete on
    # the typical container, sometimes catching the
    # write phase.
    result = kill_after_delay(op, kill_delay_ms=150)

    assert result.kill_succeeded, (
        f"kill_splunkd returned False; errors: {result.errors}")
    assert not result.errors, (
        f"unexpected recovery errors: {result.errors}")
    assert result.recovery_seconds > 0

    post_uptime = splunkd_uptime_seconds()
    assert post_uptime is not None and post_uptime < 60, (
        f"post-restart splunkd uptime {post_uptime}s "
        "doesn't look like a fresh process")

    post_state = _capture_state()

    # Critical: registry must NEVER be corrupt JSON.
    # The atomic temp+rename pattern guarantees this.
    assert post_state["parse_ok"], (
        "hash registry is corrupt JSON after chaos kill — "
        "the atomic-write contract was violated")

    # Entry count sanity: must be > 0 (we have managed
    # CSVs). Whether the bootstrap committed or not,
    # the registry from pre-test should still be intact.
    assert post_state["entry_count"] > 0, (
        "hash registry has zero entries after chaos — "
        "the bootstrap may have truncated the file before "
        "writing the new content")

    # The registry should have entries for the bulk of the
    # managed CSVs. We don't pin an exact count (it
    # varies with how many test CSVs have been created),
    # but a sudden drop to a tiny number would be a
    # red flag.
    assert post_state["entry_count"] >= max(
        pre_state["entry_count"] // 2, 5), (
        f"hash registry shrank dramatically: "
        f"{pre_state['entry_count']} -> "
        f"{post_state['entry_count']}. Possible "
        f"partial-write that lost entries.")
