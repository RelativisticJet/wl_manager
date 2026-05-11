"""
Chaos-fixture smoke test — Ring 4 Day 4.

Verifies the chaos infrastructure itself works end-to-end:
- ``_splunkd_pid()`` finds the supervisor
- ``kill_splunkd()`` actually kills it
- ``restart_and_wait()`` brings REST back up
- ``kill_after_delay()`` runs an operation, kills, recovers,
  and returns a sensible ChaosResult

This is NOT a chaos test of any specific feature — that's
Day 5-6's job (``test_chaos_recovery.py``). Day 4 only
proves the fixture is reliable, so Day 5-6 doesn't waste
time debugging chaos-of-the-chaos-harness.

Marked ``slow`` so the default suite doesn't run it on
every pytest invocation. To run:

    python -m pytest tests/integration/test_chaos_smoke.py -m slow

Run time: ~60-90s per test (Splunk restart is ~30-60s).
"""

import time
import pytest

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
from lib_chaos import (
    kill_after_delay,
    kill_splunkd,
    restart_and_wait,
    splunkd_uptime_seconds,
    _splunkd_pid,
)


pytestmark = [
    pytest.mark.docker,
    pytest.mark.slow,
]


def test_chaos_fixture_smoke(container_curl):
    """End-to-end smoke test of the chaos fixture.

    Issues a read-only request, kills splunkd ~100ms later,
    waits for recovery, and asserts the cycle completed
    cleanly. Read-only because we don't want to leave
    half-written state for subsequent tests.
    """
    # Confirm splunkd is up before chaos and capture its
    # uptime. We can't rely on PID-changed because
    # ``docker restart`` often gives the new splunkd the
    # same PID (deterministic startup order in the
    # container). Uptime, however, MUST be smaller
    # post-restart than pre-test if a kill actually
    # happened.
    pre_pid = _splunkd_pid()
    assert pre_pid is not None, "splunkd not running pre-chaos"
    pre_uptime = splunkd_uptime_seconds() or 0

    def op():
        return container_curl(
            "/services/custom/wl_manager?action=get_mapping",
            check=False, user="admin")

    result = kill_after_delay(op, kill_delay_ms=100)

    # Kill should have succeeded
    assert result.kill_succeeded, (
        f"kill_splunkd returned False; errors: {result.errors}")
    # Recovery should have completed within the default
    # timeout (no entries in errors means restart_and_wait
    # didn't throw)
    assert not result.errors, (
        f"unexpected errors: {result.errors}")
    # Recovery time is non-zero (we did restart something)
    assert result.recovery_seconds > 0
    # Splunk is back up — verify by hitting an endpoint
    post_pid = _splunkd_pid()
    assert post_pid is not None, (
        "splunkd not running post-recovery")
    # Prove a restart actually happened via process
    # uptime: the post-restart splunkd must be younger
    # than 60s (fresh boot) AND younger than the pre-test
    # splunkd (which may have been running for minutes
    # or hours).
    post_uptime = splunkd_uptime_seconds()
    assert post_uptime is not None, (
        "could not read post-restart splunkd uptime")
    assert post_uptime < 60, (
        f"post-restart splunkd uptime {post_uptime}s "
        "exceeds 60s — was a restart actually performed?")
    assert post_uptime < pre_uptime or pre_uptime < 30, (
        f"pre_uptime={pre_uptime}s post_uptime={post_uptime}s "
        "— restart did not produce a younger process")


def test_kill_splunkd_then_restart(docker_available):
    """Lower-level: kill + restart without an operation in
    flight. Just verifies the kill primitive and the
    restart primitive work in isolation.
    """
    pre_pid = _splunkd_pid()
    assert pre_pid is not None
    pre_uptime = splunkd_uptime_seconds() or 0

    assert kill_splunkd(), "kill returned False"

    # Restart and assert REST comes back
    recovery_s = restart_and_wait(timeout=180)
    assert recovery_s > 0
    assert recovery_s < 180

    post_pid = _splunkd_pid()
    assert post_pid is not None
    # See test_chaos_fixture_smoke for why we use uptime
    # rather than PID — PIDs can collide after docker
    # restart due to deterministic process startup.
    post_uptime = splunkd_uptime_seconds()
    assert post_uptime is not None
    assert post_uptime < 60
    assert post_uptime < pre_uptime or pre_uptime < 30
