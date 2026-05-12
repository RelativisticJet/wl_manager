"""
Chaos test — FIM dual-store mid-write splunkd kill.

Ring 6.2 Day 2 (statistical mid-write chaos).

Day 1's tests (test_chaos_fim_dual_store.py) verify that
``fim_baseline_kv_fs_divergence`` fires when both stores hold
different validly-signed baselines, using deterministic setup.
Day 2 closes the OTHER half of the property — that a real
splunkd crash mid-write actually PRODUCES the asymmetric state
that Day 1's tests deterministically inject.

The dual-store writes are sequential, not atomic
([bin/wl_fim.py:725-727, 850-852, 858-860, 1066-1068]):

    _write_fs_baseline(new_baseline, key)
    if session_key:
        _write_kv_baseline(session_key, new_baseline, key)

A splunkd SIGKILL between those two calls would leave FS written
but KV missing — which the next FIM cycle should detect as
asymmetric state via the rebuild-from-FS path (bin/wl_fim.py:760).

Honest framing
==============
The window between ``_write_fs_baseline`` and ``_write_kv_baseline``
is microseconds — one fsync + one HTTP POST to the KV store. A
SIGKILL timer with millisecond granularity (Python thread + Docker
exec overhead) is unlikely to land in that window reliably.

The existing chaos tests (``test_chaos_save_csv_chain``,
``test_chaos_approval_queue``) document the same limitation:
"small writes complete in <10ms typically. The 100ms delay
usually lands AFTER the entire write sequence finishes" — they
end up validating "normal commit + chaos kill survives" rather
than catching true mid-write windows.

This test runs the SIGKILL across varied delays so that some
iterations land BEFORE the FIM cycle starts (no asymmetry), some
during the cycle's snapshot loop (potential asymmetry), and some
AFTER the cycle finishes (no asymmetry). It records the observed
% across iterations as the empirical answer to "is mid-write
asymmetry catchable from outside?"

What the test asserts
=====================
Recovery contract — REGARDLESS of where the kill lands, after
splunkd restart the next FIM cycle either:

  - Sees both stores intact and matching (kill landed safely)
  - Sees one missing and rebuilds it (rebuild-from-survivor)
  - Sees both missing and rebuilds fresh
    (bin/wl_fim.py:722-733 "first-ever run" branch)

It must NEVER leave the system in a state where subsequent FIM
runs cannot recover. The test verifies this invariant per
iteration.

Run cost
========
Each iteration: ~30-60s for splunkd restart, ~15-30s for FIM
recovery cycle, ~5s setup. N=3 iterations × ~60s = ~3 minutes.

Marked ``-m slow``. Not run in CI by default — chaos tests
require a healthy docker container.
"""

from __future__ import annotations

import json
import os
import sys
import time
import pytest

sys.path.insert(0, os.path.dirname(__file__))
from lib_fim_chaos import (  # noqa: E402
    clear_stateful_alert_dedup,
    read_fs_baseline_bytes,
    read_kv_baseline,
    trigger_fim_rebuild_and_kill,
    wait_for_next_fim_cycle,
)


pytestmark = [
    pytest.mark.docker,
    pytest.mark.slow,
]


# Kill-delay sweep. The values bracket the 15s FIM cycle window
# such that, across iterations, at least some kills land during
# a wl_fim.py exec. Repeating delays helps surface statistical
# variance — Docker exec overhead, splunkd scheduling jitter.
# Total kills = sum of iterations across delays.
KILL_DELAYS = [3.0, 7.0, 11.0]


@pytest.fixture(autouse=True)
def _reset_fim_alert_dedup(container_curl):
    """Same as the Day-1 module's fixture — clears dedup +
    waits for both stores so iterations don't see stale state."""
    clear_stateful_alert_dedup()
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        fs_present = bool(read_fs_baseline_bytes())
        kv_present = read_kv_baseline(container_curl) is not None
        if fs_present and kv_present:
            break
        time.sleep(2)
    clear_stateful_alert_dedup()
    time.sleep(0.5)
    yield


def test_chaos_fim_dual_store_mid_write_recovery(
    container_curl, tmp_path
):
    """SIGKILL splunkd during a FIM cycle that's writing both
    baseline stores; verify recovery always converges.

    Per-iteration outcomes are persisted to a JSON file under
    pytest's tmp_path so the empirical distribution is queryable
    after a CI run (the Day 3 retro will summarize these).

    Assertion: EVERY iteration must end with FS and KV both
    present after one post-recovery FIM cycle. Whether the kill
    produced asymmetric state mid-recovery is informational —
    the contract is that recovery converges, not that the kill
    ALWAYS or NEVER lands in the write window.
    """
    outcomes = []

    for i, delay in enumerate(KILL_DELAYS):
        # Before each iteration, make sure both stores are present
        # (the post-iteration recovery cycle restores them).
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if (bool(read_fs_baseline_bytes())
                    and read_kv_baseline(container_curl) is not None):
                break
            time.sleep(2)

        clear_stateful_alert_dedup()

        outcome = trigger_fim_rebuild_and_kill(
            container_curl, kill_delay_seconds=delay)
        outcome["iteration"] = i
        outcome["delay_seconds"] = delay
        outcomes.append(outcome)

        if outcome["error"]:
            # Recovery infrastructure itself failed — distinct
            # from "recovered with unexpected state". Surface
            # immediately rather than continuing in a degraded
            # container.
            pytest.fail(
                f"Iteration {i} (delay={delay}s) infrastructure "
                f"error: {outcome['error']}")

        # Wait for the post-recovery FIM cycles to fix any
        # asymmetry. We poll up to 90s — far longer than one
        # cycle — because:
        #   1. The first post-restart FIM cycle may run BEFORE
        #      splunkd has fully wired passAuth, leaving session_key
        #      empty and KV-rebuild skipped (bin/wl_fim.py:776
        #      requires `session_key and kv_status in ("missing",
        #      "checksum_mismatch")`). Subsequent cycles get the
        #      key once splunkd settles.
        #   2. We need to OBSERVE the recovery path completes for
        #      the test's contract: "regardless of mid-write kill
        #      timing, the system converges to both-present".
        recovery_deadline = time.monotonic() + 90
        post_fs = False
        post_kv = False
        while time.monotonic() < recovery_deadline:
            post_fs = bool(read_fs_baseline_bytes())
            post_kv = read_kv_baseline(container_curl) is not None
            if post_fs and post_kv:
                break
            time.sleep(5)

        outcome["post_cycle_fs_present"] = post_fs
        outcome["post_cycle_kv_present"] = post_kv
        outcome["recovery_wait_seconds"] = (
            90 - max(0, recovery_deadline - time.monotonic()))

        # Hard contract: after the recovery window, both stores
        # must exist. Failure means the recovery path is broken
        # for some kill timing — a real bug.
        assert post_fs and post_kv, (
            f"Iteration {i} (delay={delay}s) failed to recover "
            f"within 90s: FS={post_fs}, KV={post_kv}, "
            f"outcome={outcome}")

    # Persist outcomes for Day-3 retro analysis. Pytest's tmp_path
    # gives us a per-test temp dir that survives the test for
    # local inspection.
    output_file = tmp_path / "fim_chaos_outcomes.json"
    output_file.write_text(json.dumps(outcomes, indent=2))
    print(f"\nChaos outcomes written to: {output_file}")

    # Summary print (visible with pytest -s; not assertion).
    asymmetric = sum(1 for o in outcomes
                     if o.get("post_asymmetric"))
    print(f"\nStatistical chaos summary ({len(outcomes)} runs):")
    print(f"  Kill-immediate asymmetry observed: "
          f"{asymmetric}/{len(outcomes)}")
    print(f"  All recovered cleanly: yes (test asserted)")
    for o in outcomes:
        print(f"  delay={o['delay_seconds']}s: "
              f"kill_ok={o['kill_succeeded']}, "
              f"recovery={o['recovery_seconds']:.1f}s, "
              f"immediate_asymmetric={o['post_asymmetric']}, "
              f"post_cycle_recovered=both_present")
