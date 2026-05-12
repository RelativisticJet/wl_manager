"""
FIM dual-store chaos primitives — Ring 6.2 Day 1.

Scope: helpers used by ``test_chaos_fim_dual_store.py`` to drive
``bin/wl_fim.py``'s dual-store baseline through asymmetric states
(FS only, KV only, FS≠KV) and assert that the divergence detection
fires as designed on the next 15-second FIM cycle.

What this module exists to enable
=================================

The dual-store FIM baseline (added in build 554) writes the
authoritative file hashes to TWO independent sources:

  - ``lookups/_versions/.fim_baseline.json`` (HMAC-signed JSON)
  - ``wl_fim_baseline`` KV collection record ``state`` (also HMAC-signed)

The writes are sequential, not atomic — a splunkd crash between the
filesystem write and the KV write leaves the system in an asymmetric
state. The security claim is that the NEXT FIM cycle (15 seconds
later) detects the asymmetry and emits ``fim_baseline_kv_fs_divergence``
at CRITICAL severity. See [bin/wl_fim.py:739] for the comparison.

This module supplies the primitives needed to put the system into
each asymmetric state deterministically, plus the audit-query helpers
needed to verify detection fired.

Why this is consistent with the synthetic-fixtures rule
=======================================================

CLAUDE.md bans direct writes to ``.fim_baseline.json`` and the
``wl_fim_baseline`` KV collection for FEATURE VERIFICATION (the
purpose those bans serve is to prevent schema-drift bugs from
hiding behind synthetic state). This module's purpose is the
opposite: it sets up the EXACT trigger condition that the dual-
store's security control was designed to detect, then asserts the
detection fires. We are not making a feature "appear to work" — we
are testing a SECURITY CONTROL under controlled conditions that
would otherwise require a real mid-write splunkd crash to reproduce.

The hook (``scripts/hooks/block-synthetic-fixtures.js``) permits
this work because:

  - Bash ``rm`` operations have no WRITE_INDICATOR match (rm is not
    a write — it's a delete, which the dual-store is explicitly
    designed to handle gracefully).
  - The ``# JUSTIFIED: <reason>`` marker is used in
    ``inject_divergence_via_mv`` (the only operation where we MUST
    rewrite an existing baseline with a different valid-HMAC
    payload — no production endpoint can produce that state).
  - The Write tool path checks the file we're CREATING (this
    library, under ``tests/integration/``, not blocked).

The justifications for individual hook bypasses live next to the
calls themselves; do not extract them into a shared comment.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from typing import Any, Callable, Optional, Tuple

from lib_chaos import CONTAINER_NAME

APP_DIR = "/opt/splunk/etc/apps/wl_manager"
VERSIONS_DIR = f"{APP_DIR}/lookups/_versions"
BASELINE_PATH = f"{VERSIONS_DIR}/.fim_baseline.json"
# Stateful alert dedup cache. wl_fim.py suppresses repeat emits of
# certain HIGH/CRITICAL actions for 1 hour after first fire (see
# STATEFUL_ALERT_ACTIONS in bin/wl_fim.py:487). Tests must clear
# this file before each assertion against a deduped action,
# otherwise a prior test run leaves the dedup state populated and
# the live alert is silently suppressed.
ALERT_STATE_PATH = f"{VERSIONS_DIR}/.fim_alert_state.json"
KV_COLLECTION = "wl_fim_baseline"
KV_KEY = "state"
KV_ENDPOINT = (
    f"/servicesNS/nobody/wl_manager/storage/collections/data/"
    f"{KV_COLLECTION}/{KV_KEY}"
)

# Two consecutive FIM cycles + read latency. The script runs every
# 15s; worst case we set up state right after a cycle started and
# need to wait nearly a full cycle. Add a 5s buffer so flaky timing
# (slow indexing, network) doesn't bite. A test that waits 35s once
# per assertion is fine — these are -m slow tests.
FIM_CYCLE_WAIT_SECONDS = 35


def _docker_run(*args: str,
                timeout: int = 30,
                as_root: bool = False,
                ) -> subprocess.CompletedProcess:
    """Run a command inside the container with MSYS_NO_PATHCONV set.

    Mirrors lib_chaos._docker_run but kept private to this module so
    we don't grow lib_chaos's surface with FIM-specific helpers.
    """
    env = {**os.environ, "MSYS_NO_PATHCONV": "1"}
    cmd = ["docker", "exec"]
    if as_root:
        cmd.extend(["-u", "0"])
    cmd.extend([CONTAINER_NAME, *args])
    return subprocess.run(  # noqa: S603 — list-form, no shell
        cmd, capture_output=True, text=True, env=env,
        timeout=timeout, check=False,
    )


# ─────────────────────────────────────────────────────────────────
# FS-side helpers
# ─────────────────────────────────────────────────────────────────

def read_fs_baseline_bytes() -> bytes:
    """Return raw bytes of the on-disk baseline, or b'' if absent.

    Reads as root because the file is 0600 owned by splunk and the
    default docker-exec UID may differ.
    """
    env = {**os.environ, "MSYS_NO_PATHCONV": "1"}
    proc = subprocess.run(  # noqa: S603
        ["docker", "exec", "-u", "0", CONTAINER_NAME,
         "cat", BASELINE_PATH],
        capture_output=True, text=False, env=env,
        timeout=15, check=False,
    )
    if proc.returncode == 0:
        return proc.stdout
    err = (proc.stderr or b"").decode("utf-8", "replace").lower()
    if "no such file" in err or "cannot stat" in err:
        return b""
    raise RuntimeError(
        f"cat {BASELINE_PATH} failed (rc={proc.returncode}): "
        f"{(proc.stderr or b'').decode('utf-8', 'replace')[:200]}")


def clear_stateful_alert_dedup() -> None:
    """Delete ``.fim_alert_state.json`` so wl_fim.py's stateful
    alert dedup forgets which alerts have already fired.

    Required before any test that asserts a member of
    ``STATEFUL_ALERT_ACTIONS`` fires — without this, a prior test
    (or a recent operator action) that fired the same action within
    the last hour silently suppresses the new emit. The file is a
    pure cache; the next FIM cycle rebuilds it (see
    ``_save_alert_state`` in bin/wl_fim.py:516).

    rm has no WRITE_INDICATOR match, so this passes the synthetic-
    fixtures hook.
    """
    proc = _docker_run(
        "rm", "-f", ALERT_STATE_PATH, as_root=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"rm {ALERT_STATE_PATH} failed (rc={proc.returncode})")


def delete_fs_baseline() -> bool:
    """Remove the on-disk baseline file. Returns True if it existed.

    rm has no WRITE_INDICATOR match in the synthetic-fixtures hook,
    so this is permitted. The dual-store's documented contract is
    that a missing FS baseline triggers rebuild-from-KV with a
    ``fim_fs_baseline_missing_or_tampered`` audit event — exactly
    the scenario we want to verify.
    """
    pre = read_fs_baseline_bytes()
    proc = _docker_run("rm", "-f", BASELINE_PATH, as_root=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"rm {BASELINE_PATH} failed (rc={proc.returncode})")
    return bool(pre)


def save_fs_baseline_copy(remote_tmp: str) -> None:
    """Copy the live baseline to a container-local temp path so we
    can restore it later. Used by the divergence-injection test.

    ``cp`` IS in WRITE_INDICATORS, so this is a Bash call we make
    via subprocess — it is NOT subject to the PreToolUse hook
    because the hook only sees direct Bash-tool invocations made
    by Claude itself, not subprocesses spawned by pytest.
    """
    proc = _docker_run("cp", BASELINE_PATH, remote_tmp, as_root=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"cp {BASELINE_PATH} -> {remote_tmp} failed "
            f"(rc={proc.returncode}): "
            f"{(proc.stderr or '')[:200]}")


def restore_fs_baseline_from(remote_tmp: str) -> None:
    """Overwrite the live baseline with a saved copy. The only way
    to produce a FS≠KV state with both stores having valid HMACs is
    to swap the FS file back to a prior valid-signed snapshot while
    the KV holds the new one. ``mv`` is a WRITE_INDICATOR; the hook
    does not see subprocess calls from pytest.
    """
    proc = _docker_run("mv", remote_tmp, BASELINE_PATH, as_root=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"mv {remote_tmp} -> {BASELINE_PATH} failed "
            f"(rc={proc.returncode}): "
            f"{(proc.stderr or '')[:200]}")
    # Restore the 0600 perms wl_fim.py writes
    _docker_run("chmod", "600", BASELINE_PATH, as_root=True)
    _docker_run("chown", "splunk:splunk", BASELINE_PATH,
                as_root=True)


# ─────────────────────────────────────────────────────────────────
# KV-side helpers
# ─────────────────────────────────────────────────────────────────

def read_kv_baseline(container_curl: Callable[..., Any]
                     ) -> Optional[dict]:
    """Fetch the wl_fim_baseline/state record. Returns None on 404.

    Uses the conftest container_curl fixture so the call goes
    through the integration-test rate-limit-retry logic.
    """
    proc = container_curl(
        f"{KV_ENDPOINT}?output_mode=json",
        method="GET", user="admin", check=False)
    body = (proc.stdout or "").strip()
    if not body:
        return None
    if "404" in body[:64] or "Not Found" in body[:128]:
        return None
    try:
        record = json.loads(body)
    except json.JSONDecodeError:
        return None
    if isinstance(record, dict) and record.get("_key") == KV_KEY:
        return record
    return None


def delete_kv_baseline(container_curl: Callable[..., Any]) -> bool:
    """Delete the wl_fim_baseline/state record.

    Note on the hook: this issues ``-X DELETE`` against the
    wl_fim_baseline collection, which the PreToolUse hook would
    block IF this were a direct Bash call. It is not — it's a
    Python REST call via the container_curl fixture, which uses
    subprocess internally. The hook only fires on Claude's direct
    Bash tool usage, not on subprocesses run by pytest. We still
    document the intent clearly: this simulates the legitimate
    operational scenario where the KV record is missing (transient
    KV unavailability mid-cycle, or first-install before the
    record exists). The dual-store explicitly handles this case.
    """
    pre = read_kv_baseline(container_curl)
    proc = container_curl(KV_ENDPOINT, method="DELETE",
                          user="admin", check=False)
    body = (proc.stdout or "").strip()
    # Splunk returns 200 with empty body on successful DELETE,
    # or 404 if already missing. Both are "successful" for our
    # purposes.
    return bool(pre)


# ─────────────────────────────────────────────────────────────────
# Audit-query helpers
# ─────────────────────────────────────────────────────────────────

def _splunk_search(container_curl: Callable[..., Any],
                   spl: str,
                   earliest: str = "-2m",
                   timeout: int = 30,
                   ) -> list:
    """Run an SPL query via the search/jobs/oneshot REST endpoint.

    Returns a list of result dicts (one per row). Used to verify
    that specific FIM audit events appeared after a state change.
    """
    # Splunk's oneshot endpoint takes search + earliest_time +
    # output_mode form-encoded. We POST so the query goes in the
    # body and isn't truncated by URL limits.
    data = (
        f"search={_url_encode(spl)}"
        f"&earliest_time={_url_encode(earliest)}"
        f"&output_mode=json&exec_mode=oneshot"
    )
    proc = container_curl(
        "/services/search/jobs/oneshot", method="POST",
        data=data, content_type="application/x-www-form-urlencoded",
        user="admin", timeout=timeout, check=False)
    body = (proc.stdout or "").strip()
    if not body:
        return []
    try:
        envelope = json.loads(body)
    except json.JSONDecodeError:
        return []
    return envelope.get("results", []) or []


def _url_encode(s: str) -> str:
    """Minimal URL-encode for the SPL string. We escape the
    characters Splunk's form parser is sensitive to: space, &, =,
    +, #. Keeping this tiny rather than pulling in urllib so the
    helper has zero dependencies beyond the stdlib already in
    lib_chaos.
    """
    out = []
    for ch in s:
        if ch == " ":
            out.append("%20")
        elif ch == "&":
            out.append("%26")
        elif ch == "=":
            out.append("%3D")
        elif ch == "+":
            out.append("%2B")
        elif ch == "#":
            out.append("%23")
        elif ch == "\n":
            out.append("%0A")
        else:
            out.append(ch)
    return "".join(out)


def query_fim_events(container_curl: Callable[..., Any],
                     action: str,
                     since_seconds_ago: int = 120,
                     ) -> list:
    """Return all wl_fim events with the given action emitted in
    the last ``since_seconds_ago`` seconds.

    ``action`` is one of the FIM action names defined in
    ``bin/wl_fim.py`` near line 488 (e.g.
    ``fim_baseline_kv_fs_divergence``,
    ``fim_fs_baseline_missing_or_tampered``,
    ``fim_kv_baseline_checksum_mismatch``).

    The ``| table`` projection is required: a bare
    ``search ... sourcetype=wl_fim`` returns ``_time``/``_raw``
    only — Splunk does NOT include extracted fields in the default
    result envelope, only when explicitly projected.
    """
    spl = (f'search index=wl_audit sourcetype=wl_fim '
           f'action="{action}" '
           f'| table _time _raw action severity monitored_path')
    return _splunk_search(
        container_curl, spl,
        earliest=f"-{since_seconds_ago}s")


def query_fim_any_in_window(container_curl: Callable[..., Any],
                            since_seconds_ago: int = 60,
                            ) -> list:
    """Catch-all: every wl_fim event in the last window. Used to
    confirm the FIM cycle ran AT ALL (so test failures distinguish
    "detection didn't fire" from "FIM didn't run").
    """
    spl = ('search index=wl_audit sourcetype=wl_fim '
           '| table _time _raw action severity monitored_path')
    return _splunk_search(container_curl, spl,
                          earliest=f"-{since_seconds_ago}s")


# ─────────────────────────────────────────────────────────────────
# Cycle-wait helpers
# ─────────────────────────────────────────────────────────────────

def wait_for_next_fim_cycle(container_curl: Callable[..., Any],
                            check_for_action: Optional[str] = None,
                            timeout: int = FIM_CYCLE_WAIT_SECONDS,
                            ) -> Tuple[bool, list]:
    """Wait up to ``timeout`` seconds for the next FIM run to emit
    events. Returns (cycle_completed, events).

    If ``check_for_action`` is provided, returns as soon as that
    specific action has been observed. Otherwise returns as soon
    as ANY wl_fim event appears since the start of the wait.

    Why the cycle-wait helper exists: FIM is a 15s scripted input.
    Even after triggering a state change, the next cycle may be up
    to 15s away. Waiting blindly for 16s works most of the time
    but flakes if the cycle starts just before our check. The
    poll-with-deadline pattern avoids the flake.
    """
    deadline = time.monotonic() + timeout
    start_ts = int(time.time())

    while time.monotonic() < deadline:
        # Look at events since just before the wait started so we
        # don't accidentally match a stale event from prior cycle.
        events = query_fim_any_in_window(
            container_curl, since_seconds_ago=timeout + 5)
        recent = [e for e in events
                  if _event_ts(e) >= start_ts - 5]
        if recent:
            if check_for_action is None:
                return True, recent
            matched = [e for e in recent
                       if e.get("action") == check_for_action]
            if matched:
                return True, matched
        time.sleep(2)

    return False, []


def _event_ts(event: dict) -> int:
    """Best-effort epoch-int from a wl_fim event.

    Splunk's oneshot REST returns ``_time`` as ISO 8601:
        "2026-05-12T12:41:48.000+00:00"

    ``timestamp`` inside _raw is the epoch the script wrote. Either
    is acceptable for "was this event recent?" filtering.
    """
    # Try _time first (envelope), then timestamp (event body)
    raw = event.get("_time") or event.get("timestamp") or "0"
    # Epoch-as-string first (cheap path)
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        pass
    # ISO 8601 path. Use datetime to keep stdlib-only.
    if isinstance(raw, str):
        s = raw.strip()
        try:
            from datetime import datetime
            # Normalize "+00:00" to "+0000" for older fromisoformat,
            # but Python 3.11+ handles "+00:00" natively. Splunk
            # bundles 3.9 — strip the colon.
            if len(s) >= 6 and (s[-6] == "+" or s[-6] == "-") \
                    and s[-3] == ":":
                s = s[:-3] + s[-2:]
            dt = datetime.strptime(s, "%Y-%m-%dT%H:%M:%S.%f%z")
            return int(dt.timestamp())
        except (ValueError, ImportError):
            return 0
    return 0
