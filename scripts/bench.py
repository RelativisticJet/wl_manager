#!/usr/bin/env python3
"""
Performance benchmark harness — Ring 3 Day 5.

Goes deeper than ``tests/integration/test_performance_smoke.py``,
which only checks that single calls finish under a generous
order-of-magnitude budget. The smoke is a regression detector;
this harness is for exploratory benchmarking and trend
tracking. Three subcommands:

    cold-start    Time the first N requests after a Splunk
                  restart. Captures cold-cache effects that the
                  smoke specifically median-of-3-eliminates.

    concurrency   Spawn W workers issuing R sequential read
                  requests each, distributed across multiple
                  user accounts to avoid per-user rate limits.
                  Report p50/p95/p99 and error rate.

    memory        Issue K requests serially; sample the
                  container's RSS via ``docker stats`` every
                  S requests; report trend (slope + max delta).
                  Detects memory leaks accumulating over many
                  calls.

Why a separate script (not pytest)
-----------------------------------

Each subcommand takes 1-10 minutes, doesn't fit the smoke-budget
assertion model, and shouldn't gate CI. Pytest assertions are
pass/fail; benchmarks are continuous values that need percentile
reasoning. Output goes to console + JSON under ``bench_results/``
(gitignored except for committed reference runs).

This is NOT meant to be run on every developer's machine on
every change. Use cases:

- Before/after a hot-path refactor (e.g., "did extracting
  ``wl_csv.py`` from the handler change dispatch cost?")
- Quarterly trend baseline (compare this quarter's cold-start
  p95 to last quarter's)
- Investigation when ``test_performance_smoke.py`` fails (the
  smoke catches the regression; this harness localizes it)

What this DOES catch that the smoke doesn't
--------------------------------------------

- Subtle 20-50% latency regressions (visible only in p95/p99
  over many samples, not single-call max)
- Cold-start latency (smoke explicitly medians-out cold-cache)
- Concurrency bottlenecks under high parallel request rate
  (smoke is single-threaded)
- Memory leaks accumulating across many calls (smoke runs
  three calls)

Usage
-----

    python scripts/bench.py cold-start --calls 10
    python scripts/bench.py concurrency --workers 6 --requests 30
    python scripts/bench.py memory --calls 500 --sample-every 50

Container is ``wl_manager_test`` by default; override with
``--container``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = REPO_ROOT / "bench_results"
RESULTS_DIR.mkdir(exist_ok=True)

DEFAULT_CONTAINER = "wl_manager_test"
# Password resolution mirrors scripts/reset_cooldowns.sh and the
# integration suite: env var first, dev-container default as
# fallback. The default is the well-known docker-compose dev
# password (also documented in INSTALLATION.md and used by
# tests/integration/conftest.py); production deployments don't
# run this harness.
DEFAULT_PASSWORD = os.environ.get(
    "SPLUNK_PASSWORD", "Chang3d!")

# User roster for concurrency distribution. Each user gets its
# own per-user rate-limit window (120 reads / 60s) so spreading
# workers across them gives ~720 reads/min sustainable capacity.
# Built-in admin is excluded because its panel RBAC and quota
# behaviour differ from app-specific roles (see
# feedback_use_role_specific_accounts.md).
WORKER_USERS = [
    "superadmin1",
    "superadmin2",
    "wladmin1",
    "wladmin2",
    "analyst1",
    "analyst2",
]


def _run_in_container(container: str, *args: str,
                      timeout: int = 60) -> subprocess.CompletedProcess:
    """Run a command inside the container.

    MSYS_NO_PATHCONV=1 prevents Git Bash from mangling
    /opt/splunk paths into Windows-style paths. Passed via the
    environment so the docker invocation itself is platform-
    neutral. Uses subprocess.run with a list of args (never
    shell=True) so command-injection through user-controlled
    arguments is not a concern.
    """
    env = os.environ.copy()
    env["MSYS_NO_PATHCONV"] = "1"
    return subprocess.run(
        ["docker", "exec", container, *args],
        capture_output=True, text=True, env=env,
        timeout=timeout, check=False,
    )


def _curl_get(container: str, action: str, user: str = "admin",
              password: str = DEFAULT_PASSWORD,
              timeout: int = 30) -> tuple[float, str, int]:
    """Issue a GET to the handler. Returns
    (elapsed_seconds, response_body, exit_code).

    Wall-clock time INCLUDES the docker-exec overhead (~140 ms
    on Windows). That's intentional — it's the cost a real
    in-container caller would pay too. We only optimize for
    relative comparisons; absolute numbers are dominated by the
    user's host config.
    """
    start = time.monotonic()
    proc = _run_in_container(
        container,
        "curl", "-sk", "-u", f"{user}:{password}",
        "-X", "GET",
        f"https://localhost:8089/services/custom/wl_manager?action={action}",
        timeout=timeout,
    )
    elapsed = time.monotonic() - start
    return elapsed, (proc.stdout or "").strip(), proc.returncode


def _splunk_restart(container: str) -> float:
    """Stop + start Splunk inside the container. Returns total
    elapsed seconds (including the post-start /services/server/info
    poll). Used by cold-start to establish the canonical
    "first request after warm-up" point.
    """
    print("  [splunk] stopping...", flush=True)
    _run_in_container(container, "su", "-c",
                      "/opt/splunk/bin/splunk stop", "splunk",
                      timeout=120)
    print("  [splunk] starting...", flush=True)
    start = time.monotonic()
    _run_in_container(container, "su", "-c",
                      "/opt/splunk/bin/splunk start --answer-yes",
                      "splunk", timeout=240)
    # splunkd reports "started" before REST is fully accepting
    # requests. Poll /services/server/info as the canonical
    # readiness signal — same probe ``setup_test_env.sh`` uses.
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        proc = _run_in_container(
            container,
            "curl", "-sk", "-o", "/dev/null",
            "-w", "%{http_code}",
            "-u", f"admin:{DEFAULT_PASSWORD}",
            "https://localhost:8089/services/server/info",
            timeout=10,
        )
        if (proc.stdout or "").strip() == "200":
            elapsed = time.monotonic() - start
            print(f"  [splunk] REST up after {elapsed:.1f}s",
                  flush=True)
            return elapsed
        time.sleep(2)
    raise RuntimeError(
        "Splunk did not become ready within 120s after restart")


def _percentile(values: list[float], p: float) -> float:
    """Approximate percentile via sorted-index lookup. ``p`` in
    [0, 100]. Returns 0 for empty input.
    """
    if not values:
        return 0.0
    s = sorted(values)
    if p <= 0:
        return s[0]
    if p >= 100:
        return s[-1]
    idx = int(round((p / 100.0) * (len(s) - 1)))
    return s[idx]


def _summarize(samples: list[float]) -> dict[str, float]:
    if not samples:
        return {"count": 0}
    return {
        "count": len(samples),
        "min_ms": round(min(samples) * 1000, 1),
        "p50_ms": round(_percentile(samples, 50) * 1000, 1),
        "p95_ms": round(_percentile(samples, 95) * 1000, 1),
        "p99_ms": round(_percentile(samples, 99) * 1000, 1),
        "max_ms": round(max(samples) * 1000, 1),
        "mean_ms": round(statistics.mean(samples) * 1000, 1),
        "stdev_ms": (round(statistics.stdev(samples) * 1000, 1)
                     if len(samples) > 1 else 0.0),
    }


def _save_result(name: str, payload: dict[str, Any]) -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = RESULTS_DIR / f"{name}_{ts}.json"
    out.write_text(json.dumps(payload, indent=2))
    print(f"\nResults saved to {out}", flush=True)
    return out


def cmd_cold_start(args: argparse.Namespace) -> int:
    print(f"[cold-start] container={args.container} "
          f"calls={args.calls}", flush=True)
    restart_seconds = _splunk_restart(args.container)

    samples: list[float] = []
    errors: list[dict[str, Any]] = []
    print(f"  [requests] firing {args.calls} sequential reads "
          f"as 'admin'...", flush=True)
    for i in range(args.calls):
        elapsed, body, rc = _curl_get(
            args.container, "get_mapping")
        samples.append(elapsed)
        marker = "OK" if rc == 0 and body else f"rc={rc}"
        print(f"    call {i + 1:3d}: {elapsed * 1000:8.1f}ms "
              f"[{marker}]", flush=True)
        if rc != 0 or not body:
            errors.append({"call": i + 1, "rc": rc,
                           "body_preview": (body or "")[:120]})

    payload = {
        "subcommand": "cold-start",
        "container": args.container,
        "restart_seconds": round(restart_seconds, 2),
        "summary": _summarize(samples),
        "samples_ms": [round(s * 1000, 1) for s in samples],
        "errors": errors,
        "first_call_ms": (round(samples[0] * 1000, 1)
                          if samples else None),
        # The "warmth-recovery" delta — how much faster did the
        # 3rd call become vs the 1st? Big delta = significant
        # cold-cache effect; small delta = warm path is fast.
        "first_vs_third_ms_delta": (
            round((samples[0] - samples[2]) * 1000, 1)
            if len(samples) >= 3 else None),
    }
    _save_result("cold_start", payload)
    print(f"\nFirst call:    {payload['first_call_ms']} ms")
    print(f"p50:           {payload['summary']['p50_ms']} ms")
    print(f"p95:           {payload['summary']['p95_ms']} ms")
    print(f"max:           {payload['summary']['max_ms']} ms")
    return 0 if not errors else 2


def cmd_concurrency(args: argparse.Namespace) -> int:
    print(f"[concurrency] container={args.container} "
          f"workers={args.workers} requests={args.requests}",
          flush=True)
    if args.workers > len(WORKER_USERS):
        print(f"WARNING: workers ({args.workers}) > available "
              f"users ({len(WORKER_USERS)}). Reusing users will "
              f"hit per-user rate limits — results unreliable.",
              flush=True)

    results: list[list[float]] = [
        [] for _ in range(args.workers)]
    errors: list[dict[str, Any]] = []
    err_lock = threading.Lock()

    def worker(worker_idx: int) -> None:
        user = WORKER_USERS[worker_idx % len(WORKER_USERS)]
        for j in range(args.requests):
            elapsed, body, rc = _curl_get(
                args.container, "get_mapping",
                user=user, password=DEFAULT_PASSWORD)
            results[worker_idx].append(elapsed)
            if rc != 0 or not body:
                with err_lock:
                    errors.append({
                        "worker": worker_idx, "user": user,
                        "request": j + 1, "rc": rc,
                        "body_preview": (body or "")[:120]})

    start = time.monotonic()
    threads = [threading.Thread(target=worker, args=(i,))
               for i in range(args.workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    wall = time.monotonic() - start

    flat = [s for w in results for s in w]
    total_calls = len(flat)
    throughput = total_calls / wall if wall > 0 else 0

    payload = {
        "subcommand": "concurrency",
        "container": args.container,
        "workers": args.workers,
        "requests_per_worker": args.requests,
        "total_calls": total_calls,
        "wall_seconds": round(wall, 2),
        "throughput_rps": round(throughput, 2),
        "summary": _summarize(flat),
        "per_worker_summary": [
            _summarize(w) for w in results],
        "errors": errors,
    }
    _save_result("concurrency", payload)
    print(f"\nTotal calls:   {total_calls} in {wall:.1f}s")
    print(f"Throughput:    {throughput:.2f} req/s")
    print(f"p50:           {payload['summary']['p50_ms']} ms")
    print(f"p95:           {payload['summary']['p95_ms']} ms")
    print(f"p99:           {payload['summary']['p99_ms']} ms")
    print(f"errors:        {len(errors)}/{total_calls}")
    return 0 if not errors else 2


_MEM_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*([KMG]i?B)", re.IGNORECASE)


def _parse_mem(s: str) -> float:
    """Parse 'docker stats' memory string like '125MiB' or
    '1.2GiB' into MiB float. Returns -1 on parse failure.
    """
    m = _MEM_RE.search(s or "")
    if not m:
        return -1.0
    value = float(m.group(1))
    unit = m.group(2).upper()
    if unit.startswith("G"):
        return value * 1024
    if unit.startswith("K"):
        return value / 1024
    return value


def _container_rss_mib(container: str) -> float:
    """Sample container RSS via 'docker stats --no-stream'.
    Returns MiB or -1 on failure.
    """
    proc = subprocess.run(
        ["docker", "stats", "--no-stream", "--format",
         "{{.MemUsage}}", container],
        capture_output=True, text=True, timeout=30, check=False,
    )
    return _parse_mem(proc.stdout or "")


def cmd_memory(args: argparse.Namespace) -> int:
    print(f"[memory] container={args.container} "
          f"calls={args.calls} sample_every={args.sample_every}",
          flush=True)

    baseline_rss = _container_rss_mib(args.container)
    print(f"  [baseline] RSS = {baseline_rss:.1f} MiB",
          flush=True)
    samples: list[dict[str, float]] = [
        {"call": 0, "rss_mib": baseline_rss}]

    timings: list[float] = []
    errors: list[dict[str, Any]] = []
    for i in range(args.calls):
        elapsed, body, rc = _curl_get(
            args.container, "get_mapping")
        timings.append(elapsed)
        if rc != 0 or not body:
            errors.append({"call": i + 1, "rc": rc,
                           "body_preview": (body or "")[:120]})
        if (i + 1) % args.sample_every == 0:
            rss = _container_rss_mib(args.container)
            samples.append({"call": i + 1, "rss_mib": rss})
            delta = rss - baseline_rss
            print(f"  [{i + 1:4d}/{args.calls}] RSS = "
                  f"{rss:.1f} MiB ({delta:+.1f} MiB)",
                  flush=True)

    final_rss = _container_rss_mib(args.container)
    samples.append({"call": args.calls, "rss_mib": final_rss})

    rss_values = [s["rss_mib"] for s in samples]
    rss_max = max(rss_values)
    rss_max_delta = rss_max - baseline_rss
    # Crude linear trend: (last - first) / N. Doesn't model
    # plateau-then-grow, but good enough to flag "RSS is climbing
    # ~1MB per 100 calls" type leaks.
    rss_slope_per_call = (
        (final_rss - baseline_rss) / args.calls
        if args.calls > 0 else 0.0)

    payload = {
        "subcommand": "memory",
        "container": args.container,
        "calls": args.calls,
        "sample_every": args.sample_every,
        "baseline_rss_mib": round(baseline_rss, 1),
        "final_rss_mib": round(final_rss, 1),
        "max_rss_mib": round(rss_max, 1),
        "max_rss_delta_mib": round(rss_max_delta, 1),
        "slope_mib_per_call": round(rss_slope_per_call, 4),
        "samples": samples,
        "timing_summary": _summarize(timings),
        "errors": errors,
    }
    _save_result("memory", payload)
    print(f"\nBaseline RSS:    {baseline_rss:.1f} MiB")
    print(f"Final RSS:       {final_rss:.1f} MiB "
          f"({final_rss - baseline_rss:+.1f} MiB)")
    print(f"Max RSS:         {rss_max:.1f} MiB "
          f"({rss_max_delta:+.1f} MiB)")
    print(f"Slope:           {rss_slope_per_call:+.4f} MiB/call")
    return 0 if not errors else 2


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="bench.py",
        description="Performance benchmark harness — Ring 3 "
                    "Day 5. Three subcommands: cold-start, "
                    "concurrency, memory.")
    ap.add_argument(
        "--container", default=DEFAULT_CONTAINER,
        help=f"Docker container name (default: "
             f"{DEFAULT_CONTAINER})")

    sub = ap.add_subparsers(dest="cmd", required=True)

    cs = sub.add_parser("cold-start",
                        help="Time first N requests after restart")
    cs.add_argument("--calls", type=int, default=10,
                    help="Number of read requests after restart")
    cs.set_defaults(func=cmd_cold_start)

    cc = sub.add_parser("concurrency",
                        help="W workers x R requests each")
    cc.add_argument("--workers", type=int, default=6,
                    help=f"Worker count (max {len(WORKER_USERS)} "
                         f"without rate-limit collisions)")
    cc.add_argument("--requests", type=int, default=30,
                    help="Read requests per worker")
    cc.set_defaults(func=cmd_concurrency)

    mm = sub.add_parser("memory",
                        help="Sustained call sequence with RSS "
                             "trend")
    mm.add_argument("--calls", type=int, default=500,
                    help="Total sequential read requests")
    mm.add_argument("--sample-every", type=int, default=50,
                    help="Sample container RSS every N calls")
    mm.set_defaults(func=cmd_memory)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
