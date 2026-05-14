"""
Chaos-test fixture — kill-mid-operation infrastructure.

Ring 4 Day 4. The integration test suite has good coverage of
happy-path multi-step state mutations (approval replay,
version snapshot + manifest update, FIM dual-store write,
cooldown KV update). What it has NEVER tested is: what
happens if splunkd dies BETWEEN those steps?

The non-atomic-operations feedback memo flags this category
but no test actually exercises it. This module provides the
infrastructure; ``test_chaos_recovery.py`` (Day 5-6) uses it
to exercise each multi-step mutation.

Architecture
------------

The fixture spawns the operation in a background thread,
sleeps for a configurable delay (long enough for the
operation to start writing, short enough to interrupt it),
sends SIGKILL to splunkd, waits for it to die, then restarts
Splunk and polls ``/services/server/info`` until 200.

The test then asserts on the post-restart state: is the
queue / version manifest / KV record / etc. in a sane state?
Or did the partial write leave orphan data that breaks the
next legitimate operation?

Why SIGKILL not SIGTERM
-----------------------

SIGTERM gives splunkd a chance to flush + clean up — exactly
what we DON'T want. We want to simulate "power cord pulled,"
"OOM kill," or "host crash." SIGKILL is the kernel-level
unavoidable terminate; no shutdown hook runs.

Why ``docker restart`` recovers and not ``splunk start``
--------------------------------------------------------

In the splunk/splunk:9.3.1 image, splunkd is effectively the
container's PID 1 (the ansible-playbook entrypoint waits on
it). SIGKILL'ing splunkd stops the container itself. Inside
a stopped container ``docker exec splunk start`` fails with
"container is not running". ``docker start`` brings the
container back but the playbook can leave splunkd in a
crash-loop if the post-SIGKILL index fsck partially fails.
``docker restart`` is uniform: it stops the container if
running, then starts cleanly, giving the entrypoint a fresh
run with consistent state. The polling loop then waits for
``/services/server/info`` to return 200.

Why this is slow
----------------

Each kill+restart cycle takes ~30-60s (Splunk's REST is
slow to come back). Tests using this fixture are
INTEGRATION tests, not unit tests, and a full chaos suite
of ~6 scenarios takes ~5-7 minutes. Don't run on every PR;
run before any release and after any change to a
multi-step mutation path.

Caveat: timing is best-effort
-----------------------------

A 100ms delay between "start the request" and "kill splunkd"
doesn't guarantee the kill lands MID-operation. Splunk may
finish the operation before the kill arrives (especially
if the operation is read-only or cached). When that happens
the chaos test degrades to a happy-path test, which is also
useful — it confirms the restart+resume path works for
non-disrupted operations too.

For deterministic mid-op chaos, you'd need to instrument the
handler with a debug-only sleep injection point. Out of
scope for Ring 4; chaos via timing is sufficient signal for
the multi-step mutations we care about.
"""

import json
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


CONTAINER_NAME = "wl_manager_test"
DEFAULT_PASSWORD = "Chang3d!"


@dataclass
class ChaosResult:
    """Outcome of a kill-and-restart cycle."""

    # Did the background operation complete? (True = response
    # came back before kill; False = thread was still running)
    operation_completed: bool = False
    # Response body if operation completed before kill.
    operation_response: Optional[str] = None
    # Did we successfully kill splunkd?
    kill_succeeded: bool = False
    # Wall-clock seconds from kill to REST-up.
    recovery_seconds: float = 0.0
    # Any errors during the chaos sequence (kill failure,
    # restart timeout, etc.).
    errors: list = field(default_factory=list)


def _docker_run(*args: str,
                timeout: int = 60,
                as_root: bool = False
                ) -> subprocess.CompletedProcess:
    """Run a command inside the container.

    ``as_root=True`` adds ``-u 0`` so the command runs as
    root. Needed for signal operations like SIGKILL against
    the splunkd supervisor — even though the supervisor
    runs as the ``splunk`` user (same UID as the default
    docker-exec user), modern Linux ``kernel.yama.ptrace_scope``
    restrictions can block intra-UID signals to capability'd
    processes. Root sidesteps the issue.
    """
    import os
    env = {**os.environ, "MSYS_NO_PATHCONV": "1"}
    cmd = ["docker", "exec"]
    if as_root:
        cmd.extend(["-u", "0"])
    cmd.extend([CONTAINER_NAME, *args])
    return subprocess.run(  # noqa: S603 — list-form, no shell
        cmd,
        capture_output=True, text=True, env=env,
        timeout=timeout, check=False,
    )


def _splunkd_pid() -> Optional[int]:
    """Find the splunkd main process PID inside the container.

    Returns None if not found. Multiple splunkd processes
    exist (main + helpers); we want the one with the lowest
    PID, which is the supervisor.
    """
    proc = _docker_run("pgrep", "-f", "splunkd",
                       timeout=10)
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    pids = [int(p) for p in proc.stdout.strip().split()
            if p.strip().isdigit()]
    return min(pids) if pids else None


def splunkd_uptime_seconds() -> Optional[int]:
    """Read the supervisor's elapsed-time-since-start in
    integer seconds. Returns None if splunkd isn't running.

    Useful for chaos-test assertions that need to prove a
    restart actually happened, since PIDs can collide after
    a clean ``docker restart`` (deterministic startup order
    in the container often gives splunkd the same PID).
    A fresh post-restart splunkd has an uptime in the low
    tens of seconds; a pre-test splunkd that's been running
    for minutes or hours has a far larger uptime.
    """
    pid = _splunkd_pid()
    if pid is None:
        return None
    proc = _docker_run("ps", "-o", "etimes=", "-p", str(pid),
                       timeout=10)
    if proc.returncode != 0:
        return None
    txt = (proc.stdout or "").strip()
    if not txt or not txt.isdigit():
        return None
    return int(txt)


def kill_splunkd() -> bool:
    """SIGKILL the splunkd supervisor inside the container.

    Returns True if a process was killed, False if no
    splunkd was running (e.g. already killed by a previous
    chaos cycle).
    """
    pid = _splunkd_pid()
    if pid is None:
        return False
    # Two non-obvious constraints learned in the Day 4 smoke run:
    # 1. ``kill`` is not a binary in the splunk/splunk:9.3.1
    #    container — only a shell builtin. Direct ``docker exec
    #    kill ...`` returns OCI exit 127. Wrap in ``sh -c`` so
    #    the builtin resolves.
    # 2. Need root (``-u 0``). Splunkd runs as the splunk user
    #    (same UID as the default docker-exec user) but Linux
    #    kernel.yama.ptrace_scope blocks intra-UID signals to
    #    capability'd processes (splunkd binds privileged ports
    #    so it holds capabilities). Root sidesteps it.
    proc = _docker_run("sh", "-c", f"kill -9 {pid}",
                       timeout=10, as_root=True)
    if proc.returncode != 0:
        # Don't silently lie. Docker writes OCI exec errors to
        # STDOUT (not stderr); shell-builtin errors land on
        # stderr. Combine both so any failure surfaces.
        out = (proc.stdout or "").strip()
        err = (proc.stderr or "").strip()
        detail = err or out or "no output"
        raise RuntimeError(
            f"kill -9 {pid} failed (rc={proc.returncode}): "
            f"{detail}")
    # Even on success, ``kill -9`` returns 0; check via
    # absence after a brief delay.
    time.sleep(1.0)
    after = _splunkd_pid()
    # SIGKILL kills the supervisor but child processes may
    # be re-spawned if there's a watchdog. For our chaos
    # tests we just need the main process gone.
    return after != pid


def restart_and_wait(timeout: int = 180) -> float:
    """Bring Splunk back up and wait for
    /services/server/info to return 200. Returns the
    wall-clock recovery time in seconds.

    Raises TimeoutError if Splunk doesn't come up within
    ``timeout`` seconds.

    Why ``docker restart`` and not ``docker start`` or
    ``splunk start``: in the splunk/splunk:9.3.1 image,
    splunkd is effectively the container's PID 1 (via the
    ansible-playbook entrypoint that waits on it).
    SIGKILL'ing splunkd stops the container. After a kill,
    we may also see "container running but splunkd dead"
    if the entrypoint trapped the signal but a child
    crashed later (observed during Day 4 smoke testing
    when post-kill index fsck caused splunkd to crash
    seconds after re-boot). ``docker restart`` handles
    both states uniformly: it stops the container if
    running, then starts it. The entrypoint then runs
    its ansible playbook which restarts splunkd from a
    consistent state.
    """
    import subprocess
    import os

    start = time.monotonic()

    # Stop + start the container. Uniform behavior whether
    # the container was Exited (after SIGKILL took PID 1
    # down) or Running-but-unhealthy (splunkd died but
    # entrypoint script still alive). Smoke testing showed
    # ``docker start`` alone could leave splunkd in an
    # fsck-loop crash after repeated chaos kills;
    # ``restart`` resets that path.
    env = {**os.environ, "MSYS_NO_PATHCONV": "1"}
    subprocess.run(  # noqa: S603 — list-form, no shell
        ["docker", "restart", CONTAINER_NAME],
        capture_output=True, text=True, env=env,
        timeout=60, check=False,
    )

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        proc = _docker_run(
            "curl", "-sk", "-o", "/dev/null",
            "-w", "%{http_code}",
            "-u", f"admin:{DEFAULT_PASSWORD}",
            "https://localhost:8089/services/server/info",
            timeout=30,
        )
        if (proc.stdout or "").strip() == "200":
            return time.monotonic() - start
        time.sleep(2)

    raise TimeoutError(
        f"Splunk did not become ready within {timeout}s")


def kill_after_delay(operation: Callable[[], Any],
                     kill_delay_ms: int = 100,
                     restart_timeout: int = 180,
                     ) -> ChaosResult:
    """Run ``operation()`` in a background thread, kill
    splunkd after ``kill_delay_ms`` milliseconds, then
    restart and wait for recovery.

    ``operation`` should be a zero-arg callable that issues
    the request (e.g. ``lambda: container_curl("/...",
    method="POST", data=...)``). Its return value, if any,
    is captured into ``ChaosResult.operation_response``.

    The function does NOT raise if the operation was
    interrupted — the whole point is that mid-operation
    death is normal. Errors during kill or restart DO get
    captured into ``ChaosResult.errors``.
    """
    result = ChaosResult()
    op_holder: dict = {}

    def runner():
        try:
            op_holder["response"] = operation()
            op_holder["completed"] = True
        except Exception as e:
            op_holder["error"] = str(e)
            op_holder["completed"] = True

    t = threading.Thread(target=runner, daemon=True)
    t.start()
    time.sleep(kill_delay_ms / 1000.0)

    try:
        result.kill_succeeded = kill_splunkd()
    except Exception as e:
        result.errors.append(f"kill failed: {e}")

    # Give the background thread a moment to notice the
    # connection drop. If it finished BEFORE we killed, the
    # response is already captured.
    t.join(timeout=10)
    result.operation_completed = op_holder.get(
        "completed", False)
    if "response" in op_holder:
        # Response is typically a CompletedProcess; capture
        # stdout as the user-facing payload.
        resp = op_holder["response"]
        if hasattr(resp, "stdout"):
            result.operation_response = resp.stdout
        else:
            result.operation_response = str(resp)
    elif "error" in op_holder:
        result.errors.append(
            f"operation error: {op_holder['error']}")

    try:
        result.recovery_seconds = restart_and_wait(
            timeout=restart_timeout)
    except Exception as e:
        result.errors.append(f"restart failed: {e}")

    return result


def parse_json_response(raw: Optional[str]) -> Optional[dict]:
    """Helper for tests: parse a JSON response body, return
    None if not parseable. The chaos response might be a
    full success, a partial write, or empty (if the kill
    landed before the response was sent).
    """
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None
