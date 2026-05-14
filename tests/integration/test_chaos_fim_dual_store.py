"""
Chaos test — FIM dual-store baseline divergence detection.

Ring 6.2 Day 1 (deterministic asymmetric-state tests).

The FIM baseline lives in TWO independent stores:

  - ``lookups/_versions/.fim_baseline.json`` (filesystem, HMAC-signed)
  - ``wl_fim_baseline`` KV collection ``state`` record (also HMAC-signed)

[bin/wl_fim.py:716-867] reads both each cycle and decides which to
trust. The security claim is:

  1. If only the FS baseline is missing, fall back to KV silently
     (this is the rebuild-from-KV recovery path).
  2. If only the KV record is missing, fall back to FS silently
     (this is the rebuild-from-FS recovery path).
  3. If BOTH are intact but DISAGREE, emit
     ``fim_baseline_kv_fs_divergence`` at CRITICAL severity and
     treat the union as the baseline going forward.

Property #3 is the centerpiece of the dual-store design — it's how
the system detects an attacker who tampered with ONE side after the
last legitimate write (or a splunkd that died mid-write between
``_write_fs_baseline`` and ``_write_kv_baseline``, leaving the
stores asymmetric).

This test class drives the system into each of those three states
and asserts the documented detection behavior fires on the next
15-second FIM cycle.

How this is consistent with the "no synthetic fixtures" rule
============================================================

The synthetic-fixtures rule (CLAUDE.md) bans direct writes to FIM
baseline state when verifying that a FEATURE works (because the
synthetic state masks schema drift). This module's purpose is the
opposite: we're testing that a SECURITY CONTROL fires correctly
under the EXACT trigger condition it was designed to detect. The
trigger (asymmetric state) is normally caused by a mid-write
splunkd crash; we reproduce it deterministically so the detection
can be exercised in CI/test runs rather than waiting for a real
crash. See lib_fim_chaos.py module docstring for the full
rationale.

Run cost: each test waits up to two FIM cycles (15s each + buffer).
Expect ~30-90s per test, ~3-5 min total for the class.
Marked ``-m slow`` so the default suite doesn't run them.
"""

from __future__ import annotations

import os
import sys
import time
import pytest

sys.path.insert(0, os.path.dirname(__file__))
from lib_fim_chaos import (  # noqa: E402
    BASELINE_PATH,
    FIM_CYCLE_WAIT_SECONDS,
    clear_stateful_alert_dedup,
    read_fs_baseline_bytes,
    delete_fs_baseline,
    save_fs_baseline_copy,
    restore_fs_baseline_from,
    read_kv_baseline,
    delete_kv_baseline,
    query_fim_events,
    wait_for_next_fim_cycle,
)


pytestmark = [
    pytest.mark.docker,
    pytest.mark.slow,
]


@pytest.fixture(autouse=True)
def _reset_fim_alert_dedup(container_curl):
    """Clear ``.fim_alert_state.json`` AND ensure both baseline
    stores are present before every test in this module.

    bin/wl_fim.py:487 keeps a 1-hour dedup cache for the
    CRITICAL/HIGH actions this module asserts against
    (``fim_fs_baseline_missing_or_tampered``,
    ``fim_baseline_kv_fs_divergence``, etc). Without clearing it,
    a prior test run (or a real operator action) within the last
    hour leaves dedup state populated and the new emit is silently
    suppressed.

    Tests in this module also delete one store as part of setup.
    The next FIM cycle rebuilds it, but if a follow-up test starts
    before that rebuild completes it sees an unstable pre-condition.
    The store-wait below makes the tests order-independent.
    """
    clear_stateful_alert_dedup()
    # Wait for both stores to be present (max 30s = 2 FIM cycles)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        fs_present = bool(read_fs_baseline_bytes())
        kv_present = read_kv_baseline(container_curl) is not None
        if fs_present and kv_present:
            break
        time.sleep(2)
    # Re-clear after the wait — the FIM cycle that rebuilt may have
    # emitted a deduped action that we want to fire fresh in the
    # upcoming test.
    clear_stateful_alert_dedup()
    time.sleep(0.5)
    yield


def test_kv_missing_silent_rebuild_from_fs(container_curl):
    """KV record missing + FS baseline intact → silent rebuild,
    NO divergence alert (this is the documented happy-path
    recovery).

    [bin/wl_fim.py:760-776] handles this case: when the KV record
    is missing but the FS baseline is valid, the FS becomes
    authoritative and the KV is rewritten from it. The code path
    does NOT emit any audit event in this branch — silent rebuild
    is the contract.
    """
    # Confirm both stores are populated before we start
    pre_kv = read_kv_baseline(container_curl)
    assert pre_kv is not None, (
        "pre-test: KV baseline record must exist; FIM may have "
        "never run, OR the watcher is misconfigured. "
        "Check: docker exec wl_manager_test ls -la "
        f"{BASELINE_PATH}")

    pre_fs = read_fs_baseline_bytes()
    assert pre_fs, "pre-test: FS baseline file must exist"

    # Delete just the KV record
    deleted = delete_kv_baseline(container_curl)
    assert deleted, "delete_kv_baseline returned False"

    # Poll for the KV record to reappear. The silent-rebuild path
    # at bin/wl_fim.py:760-776 handles kv_status=="missing" +
    # fs_status=="ok" by rewriting KV from FS but DOES NOT call
    # _emit() — so wait_for_next_fim_cycle(check_for_action=None)
    # is the wrong signal here: it polls for any wl_fim event,
    # but the path under test is contractually event-less. The
    # actual observable signal IS the KV record reappearing.
    # (Previous attempt with timeout bumps 35→60 in commit ccb37fc
    # failed because it treated this as a timing issue when the
    # real cause is structural: polling for the wrong signal.)
    deadline = time.monotonic() + FIM_CYCLE_WAIT_SECONDS
    post_kv = None
    while time.monotonic() < deadline:
        post_kv = read_kv_baseline(container_curl)
        if post_kv is not None:
            break
        time.sleep(2)
    assert post_kv is not None, (
        "KV record was not rebuilt from FS within "
        f"{FIM_CYCLE_WAIT_SECONDS}s. Either the silent-rebuild "
        "path at bin/wl_fim.py:760-776 regressed, the scripted "
        "input is disabled, or splunkd is unhealthy.")

    # Assert: NO divergence alert fired (silent rebuild contract)
    divergence_events = query_fim_events(
        container_curl, "fim_baseline_kv_fs_divergence",
        since_seconds_ago=FIM_CYCLE_WAIT_SECONDS + 30,
    )
    # Filter to events from THIS test's window (after we deleted)
    recent = [e for e in divergence_events
              if _is_recent_enough(e)]
    assert not recent, (
        "Unexpected fim_baseline_kv_fs_divergence event during a "
        "KV-rebuild-from-FS scenario. The contract says this "
        "rebuild path is silent — divergence is only for the "
        "case where BOTH stores have valid signed but disagreeing "
        "content. Recent events: " + str(recent))


def test_fs_missing_triggers_critical_alert(container_curl):
    """FS file deleted + KV intact → ``fim_fs_baseline_missing_or_tampered``
    CRITICAL alert + rebuild from KV.

    [bin/wl_fim.py:804-828] handles this case. Unlike the KV-missing
    case which is silent (KV is a soft store), a missing FS file
    is suspicious — it could mean an attacker deleted the on-disk
    record. The code emits a CRITICAL alert and rebuilds the FS
    from the KV record.
    """
    # Confirm starting state
    pre_fs_bytes = read_fs_baseline_bytes()
    assert pre_fs_bytes, "pre-test: FS baseline file must exist"
    pre_kv = read_kv_baseline(container_curl)
    assert pre_kv is not None, "pre-test: KV baseline must exist"

    # Delete the FS baseline
    existed = delete_fs_baseline()
    assert existed, (
        "delete_fs_baseline reported file did not exist pre-test")

    # Wait for next FIM cycle and the specific tamper alert
    cycle_ran, matched = wait_for_next_fim_cycle(
        container_curl,
        check_for_action="fim_fs_baseline_missing_or_tampered",
        timeout=FIM_CYCLE_WAIT_SECONDS,
    )
    assert cycle_ran, (
        f"fim_fs_baseline_missing_or_tampered event did not "
        f"appear within {FIM_CYCLE_WAIT_SECONDS}s. The dual-store "
        "is supposed to emit this CRITICAL alert when the FS "
        "baseline is missing but the KV is intact — see "
        "[bin/wl_fim.py:806-812].")

    # Sanity-check the event has the expected fields
    assert matched, "wait_for_next_fim_cycle returned True but matched is empty"
    # Pick the most recent matching event
    evt = matched[0]
    raw = evt.get("_raw") or ""
    assert "CRITICAL" in raw or evt.get("severity") == "CRITICAL", (
        "Event severity should be CRITICAL; raw=" + raw[:300])

    # Assert: FS was rebuilt from KV (documented recovery action)
    post_fs_bytes = read_fs_baseline_bytes()
    assert post_fs_bytes, (
        "FS baseline was not rebuilt from KV after the alert — "
        "this is a regression in [bin/wl_fim.py:814-828]")


def test_divergence_detected_when_fs_and_kv_disagree(container_curl):
    """Both stores intact but with DIFFERENT validly-signed
    contents → ``fim_baseline_kv_fs_divergence`` CRITICAL alert.

    This is the chaos-test centerpiece. To produce the asymmetric
    state without forging an HMAC (we don't have the runtime key),
    we let wl_fim.py legitimately produce two different signed
    baselines from two different filesystem states, then swap
    them so FS and KV hold DIFFERENT valid-signed snapshots.

    Sequence
    --------
      1. Save the current FS baseline (BL_v1) to a container-local
         temp file. Both stores currently hold BL_v1.
      2. Modify a watched file (append a harmless comment to
         scripts/package.sh — purely a release-time artifact,
         not loaded by Splunk runtime).
      3. Wait for the next FIM cycle. It detects the change,
         emits ``fim_file_modified``, and writes BL_v2 (with the
         new hash) to BOTH stores.
      4. Restore BL_v1 to the FS file (overwriting BL_v2). Now
         FS=BL_v1, KV=BL_v2. Both have valid HMACs because they
         were both produced by wl_fim.py at different times.
      5. Wait for the next FIM cycle. It reads both stores, sees
         ``fs_baseline != kv_baseline``, emits
         ``fim_baseline_kv_fs_divergence`` CRITICAL.

    Cleanup
    -------
    Revert the file edit and wait for one more cycle so both
    stores re-sync to the clean baseline before the next test.
    """
    # ── Step 1: save the current baseline ─────────────────────
    pre_fs = read_fs_baseline_bytes()
    assert pre_fs, "pre-test: FS baseline must exist"
    pre_kv = read_kv_baseline(container_curl)
    assert pre_kv is not None, "pre-test: KV baseline must exist"

    test_tag = f"chaos_fim_dual_store_{int(time.time())}"
    saved_baseline = f"/tmp/baseline_{test_tag}.json"
    save_fs_baseline_copy(saved_baseline)

    # ── Step 2: append a harmless comment to a watched file ──
    # wl_diff.js is a leaf frontend module — appending a comment
    # changes its hash (triggering a baseline rewrite) but cannot
    # break runtime: Splunk does not auto-reload static JS, so
    # users currently in the dashboard keep their loaded copy.
    # The next dashboard load picks up the new hash, but the
    # cleanup at the end of the test reverts it before that
    # matters in practice.
    target_file = (
        "/opt/splunk/etc/apps/wl_manager/appserver/static/"
        "modules/wl_diff.js")
    saved_target = f"/tmp/wl_diff_{test_tag}.bak.js"

    # Save original so cleanup can restore exactly.
    import subprocess
    env = {**os.environ, "MSYS_NO_PATHCONV": "1"}
    subprocess.run(  # noqa: S603
        ["docker", "exec", "-u", "0", "wl_manager_test",
         "cp", target_file, saved_target],
        capture_output=True, text=True, env=env,
        timeout=15, check=True,
    )

    # Append a marker comment so the hash changes deterministically.
    marker = f"# chaos-test-marker-{test_tag}"
    subprocess.run(  # noqa: S603
        ["docker", "exec", "-u", "0", "wl_manager_test",
         "sh", "-c",
         f"echo '{marker}' >> {target_file}"],
        capture_output=True, text=True, env=env,
        timeout=15, check=True,
    )

    try:
        # ── Step 3: wait for FIM to re-snapshot to BL_v2 ──────
        cycle_ran, _events = wait_for_next_fim_cycle(
            container_curl,
            check_for_action="fim_file_modified",
            timeout=FIM_CYCLE_WAIT_SECONDS,
        )
        assert cycle_ran, (
            "FIM did not detect the package.sh modification "
            f"within {FIM_CYCLE_WAIT_SECONDS}s — cannot proceed "
            "to divergence injection")

        # ── Step 4: restore BL_v1 to the FS file ──────────────
        # Now FS=BL_v1 (HMAC valid, hashes for state S1),
        # KV=BL_v2 (HMAC valid, hashes for state S2 with marker).
        restore_fs_baseline_from(saved_baseline)

        # ── Step 5: wait for divergence detection ─────────────
        cycle_ran, matched = wait_for_next_fim_cycle(
            container_curl,
            check_for_action="fim_baseline_kv_fs_divergence",
            timeout=FIM_CYCLE_WAIT_SECONDS,
        )
        assert cycle_ran, (
            "fim_baseline_kv_fs_divergence did NOT fire when FS "
            f"and KV held different validly-signed baselines. "
            "This means [bin/wl_fim.py:739 fs_baseline != "
            "kv_baseline] check failed to detect the asymmetry, "
            "which is a REGRESSION in the security control. "
            f"Searched the last {FIM_CYCLE_WAIT_SECONDS}s "
            "of wl_audit for the event.")

        # Sanity-check the divergence event severity
        evt = matched[0]
        raw = evt.get("_raw") or ""
        assert ("CRITICAL" in raw
                or evt.get("severity") == "CRITICAL"), (
            "Divergence event severity should be CRITICAL; "
            "raw=" + raw[:300])

    finally:
        # ── Cleanup: restore the file and let FIM resync ─────
        # Even if the assertions above failed, leave the system
        # in a clean state so subsequent tests have a sane baseline.
        try:
            subprocess.run(  # noqa: S603
                ["docker", "exec", "-u", "0", "wl_manager_test",
                 "mv", saved_target, target_file],
                capture_output=True, text=True, env=env,
                timeout=15, check=False,
            )
        except Exception:  # noqa: BLE001
            pass

        # Wait one more cycle so FIM re-snapshots both stores
        # to the post-cleanup state. Don't assert anything — this
        # is just to leave the system tidy.
        time.sleep(FIM_CYCLE_WAIT_SECONDS)


def _is_recent_enough(event: dict,
                      window_seconds: int = FIM_CYCLE_WAIT_SECONDS + 30,
                      ) -> bool:
    """Return True if the event was emitted within the last
    ``window_seconds`` seconds. Used to filter out stale audit
    events from prior test runs.
    """
    raw_ts = event.get("_time") or "0"
    try:
        evt_ts = int(float(raw_ts))
    except (TypeError, ValueError):
        return False
    return (int(time.time()) - evt_ts) <= window_seconds
