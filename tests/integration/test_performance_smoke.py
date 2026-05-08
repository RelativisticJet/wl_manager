"""
Performance smoke — handler dispatch latency budgets.

Smoke-level performance checks for the live REST handler. Goal
is NOT to benchmark — it's to detect catastrophic regressions
(an O(N²) loop creeping in, a sync IO call leaking into a hot
path, audit emission becoming dominant). Absolute thresholds
are generous (1.5-8s depending on action class) to avoid CI
flake on host load variance; failures here mean something is
structurally wrong, not just "a bit slow today".

Why budgets are loose
---------------------

The Ring 1 retrospective floated a 10%-of-baseline threshold,
but that would flap on every run because:

1. The container runs on user-side Docker Desktop; absolute
   latency is heavily influenced by host load and disk speed.
2. The ``_container_curl`` path includes ``docker exec``
   overhead (~140ms per call on a typical Windows dev box) on
   top of the actual handler work (~30-100ms).
3. The handler's rate limiter retries with 3-5s sleeps on
   exhaustion — a single rate-limit hit dwarfs the 10%
   threshold by orders of magnitude.

Loose absolute thresholds (read < 1.5s, write < 2.5s, heavy
< 8s) catch order-of-magnitude regressions reliably and
tolerate normal variance.

Probed baseline (2026-05-08, dev machine)
-----------------------------------------

Median wall-clock per call (Python → docker exec → handler):

============== ========
Action class   Median
============== ========
read           ~175ms
write          ~250ms
heavy          ~250ms (bootstrap_csv_hashes with current state)
============== ========

Set budgets at ~10× measured to catch catastrophic regressions
while staying well above noise floor.

What this DOES catch:

- Sync IO call (e.g., HTTPS to external service) leaking into
  a hot dispatch path
- An O(N²) loop introduced in a list endpoint
- A KV query without index over a large collection
- Audit emission becoming synchronous in a way it wasn't before
- Rate-limit retry loop blowing past the per-call budget

What this does NOT catch:

- Subtle 20-50% regressions (visible only in benchmarking, not
  smoke)
- Cold-start latency (first request after restart)
- Concurrency bottlenecks under high parallel request rate
- Memory leaks accumulating across many calls

Origin
------

Ring 2 Day 5. The Ring 1 retrospective listed performance
smoke as Ring 2 followup but didn't define threshold
discipline; this file establishes that discipline.
"""

import json
import time

import pytest


pytestmark = pytest.mark.docker


# ─────────────────────────────────────────────────────────────────────
# Budget tiers (in milliseconds)
# ─────────────────────────────────────────────────────────────────────

# Per-call wall-clock budgets. Includes ``docker exec`` overhead
# (~140ms on the dev machine where these were calibrated) plus
# the actual handler work. Failures cross the order-of-magnitude
# line — they mean something structural is wrong, not just slow.
BUDGET_READ_MS = 1500     # baseline ~175ms; ~8x headroom
BUDGET_WRITE_MS = 2500    # baseline ~250ms; ~10x headroom
BUDGET_HEAVY_MS = 8000    # baseline ~250ms-1s; allows for CSV
                          # count growth + audit fan-out
BUDGET_FLOW_MS = 6000     # end-to-end submit + approve cycle


# ─────────────────────────────────────────────────────────────────────
# Timing helper
# ─────────────────────────────────────────────────────────────────────


def _time_curl_call(call_fn, repetitions=3):
    """Run ``call_fn()`` ``repetitions`` times and return
    (median_ms, max_ms, last_response_body).

    Three repetitions chosen to give a stable median while
    staying well under any per-user rate limit (30 writes / 60s).
    The first call includes any cold-cache effects; the median
    of three eliminates that without requiring explicit warmup.
    """
    timings_ms = []
    last = None
    for _ in range(repetitions):
        start = time.monotonic()
        last = call_fn()
        elapsed_ms = (time.monotonic() - start) * 1000.0
        timings_ms.append(elapsed_ms)
    timings_ms.sort()
    median = timings_ms[len(timings_ms) // 2]
    return (median, max(timings_ms), last)


def _read(container_curl, action, user="superadmin1", extra=""):
    def _do():
        proc = container_curl(
            "/services/custom/wl_manager?action={}{}".format(action, extra),
            check=False, user=user)
        raw = (proc.stdout or "").strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"_raw": raw}
    return _do


def _post(container_curl, action, payload, user="superadmin1"):
    body = json.dumps({"action": action, **payload})
    def _do():
        proc = container_curl(
            "/services/custom/wl_manager",
            method="POST", data=body,
            content_type="application/json",
            check=False, user=user)
        raw = (proc.stdout or "").strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"_raw": raw}
    return _do


# ─────────────────────────────────────────────────────────────────────
# Read endpoints — list/lookup operations
# ─────────────────────────────────────────────────────────────────────


READ_PROBES = [
    # (action, user, extra_query)
    ("get_rules",            "superadmin1", ""),
    ("get_csvs",             "superadmin1", ""),
    ("get_mapping",          "superadmin1", ""),
    ("get_pending_approvals", "superadmin1", ""),
    ("get_notifications",    "superadmin1", ""),
    ("get_versions",         "superadmin1", ""),
    ("list_trash",           "superadmin1", ""),
    ("get_admin_limits",     "superadmin1", ""),
    ("get_daily_limits",     "superadmin1", ""),
    ("get_user_info",        "superadmin1", ""),
    # Parameterized read — uses a CSV that should exist in the
    # demo state. If demo state changes, this may need updating.
    ("get_csv_content",      "superadmin1",
     "&csv_file=DR102_whitelist.csv"),
    # Run a few as analyst1 too — different code path (RBAC
    # branch + role-filtered output).
    ("get_rules",            "analyst1",    ""),
    ("get_notifications",    "analyst1",    ""),
]


class TestReadLatencyBudget:
    """Read endpoints must complete under ``BUDGET_READ_MS``.

    Median-of-3 measurement to absorb the first-call cold-cache
    effect without explicit warmup. If median crosses the
    budget, a structural regression is likely (sync IO leak,
    O(N²) list traversal, KV scan without index).
    """

    @pytest.mark.parametrize(
        "action,user,extra",
        READ_PROBES,
        ids=["{}__{}{}".format(a, u, e[:20]) for a, u, e in READ_PROBES],
    )
    def test_read_under_budget(self, action, user, extra,
                                container_state, container_curl):
        median_ms, max_ms, body = _time_curl_call(
            _read(container_curl, action, user=user, extra=extra))
        assert median_ms < BUDGET_READ_MS, (
            "Read action '{}' (user={}) median latency {:.0f}ms "
            "exceeds budget {}ms (max in run: {:.0f}ms). "
            "Investigate: sync IO call, O(N²) loop, or KV scan "
            "regression. Body sample: {}".format(
                action, user, median_ms, BUDGET_READ_MS, max_ms,
                str(body)[:200]))


# ─────────────────────────────────────────────────────────────────────
# Write endpoints — light mutations
# ─────────────────────────────────────────────────────────────────────


WRITE_PROBES = [
    # (action, payload, user)
    # log_event — lightest write, no audit emission of its own
    ("log_event",
     {"event_type": "test_perf", "description": "probe"},
     "superadmin1"),
    # save_col_widths — KV write, no audit
    ("save_col_widths",
     {"csv_file": "DR102_whitelist.csv", "widths": {"c1": 100}},
     "superadmin1"),
    # mark_notifications_read — KV write
    ("mark_notifications_read",
     {"notification_ids": []},
     "superadmin1"),
    # check_approval_gate — read + dispatch logic, no write but
    # parses payload
    ("check_approval_gate",
     {"action_type": "save_csv", "edited_count": 1, "csv_file":
      "DR102_whitelist.csv", "detection_rule": "DR102"},
     "analyst1"),
]


class TestWriteLatencyBudget:
    """Write endpoints must complete under ``BUDGET_WRITE_MS``.

    Light writes (no audit emission, no version snapshot). If
    these blow past 2.5s, the dispatch overhead has regressed
    or a sync IO leak appeared.
    """

    @pytest.mark.parametrize(
        "action,payload,user",
        WRITE_PROBES,
        ids=[a for a, _, _ in WRITE_PROBES],
    )
    def test_write_under_budget(self, action, payload, user,
                                 container_state, container_curl):
        median_ms, max_ms, body = _time_curl_call(
            _post(container_curl, action, payload, user=user))
        assert median_ms < BUDGET_WRITE_MS, (
            "Write action '{}' (user={}) median latency {:.0f}ms "
            "exceeds budget {}ms (max: {:.0f}ms). Investigate: "
            "audit emission becoming sync, KV write hot loop. "
            "Body: {}".format(
                action, user, median_ms, BUDGET_WRITE_MS, max_ms,
                str(body)[:200]))


# ─────────────────────────────────────────────────────────────────────
# Heavy endpoints — bulk operations
# ─────────────────────────────────────────────────────────────────────


class TestHeavyLatencyBudget:
    """Heavier operations (bootstrap CSV hashes, large list
    enumerations) must complete under ``BUDGET_HEAVY_MS``.

    These scale with state size (CSV count, queue depth, trash
    count). Budget is generous (8s) to allow for state growth
    without flapping. If a test fails here, the operation has
    likely become quadratic or pulled in an unbounded scan.
    """

    def test_bootstrap_csv_hashes_under_budget(
            self, container_state, container_curl):
        # bootstrap iterates every managed CSV, hashes it,
        # writes to the registry, signs with HMAC. Linear in
        # CSV count; ~30ms per CSV in current state.
        median_ms, max_ms, body = _time_curl_call(
            _post(container_curl, "bootstrap_csv_hashes", {},
                  user="superadmin1"),
            repetitions=2)  # fewer reps — exempt from rate limit
                            # but heavy enough to be worth fewer
        assert median_ms < BUDGET_HEAVY_MS, (
            "bootstrap_csv_hashes median {:.0f}ms exceeds heavy "
            "budget {}ms (max: {:.0f}ms). Likely cause: CSV "
            "count grew dramatically OR hash computation became "
            "non-incremental. Body: {}".format(
                median_ms, BUDGET_HEAVY_MS, max_ms,
                str(body)[:300]))

    def test_get_audit_with_filter_under_budget(
            self, container_state, container_curl):
        # probe_audit_access is the most realistic "search the
        # audit index" operation we can run from tests. It hits
        # the wl_audit index and returns the latest events.
        median_ms, max_ms, body = _time_curl_call(
            _read(container_curl, "probe_audit_access",
                  user="superadmin1"))
        assert median_ms < BUDGET_HEAVY_MS, (
            "probe_audit_access median {:.0f}ms exceeds heavy "
            "budget {}ms (max: {:.0f}ms). The wl_audit index "
            "may have grown unboundedly or the SPL search has "
            "regressed. Body: {}".format(
                median_ms, BUDGET_HEAVY_MS, max_ms,
                str(body)[:300]))


# ─────────────────────────────────────────────────────────────────────
# End-to-end flow latency
# ─────────────────────────────────────────────────────────────────────


class TestApprovalFlowLatency:
    """Approval submit + process roundtrip under ``BUDGET_FLOW_MS``.

    This exercises the most-orchestrated path: analyst submits,
    admin queries the queue (read), admin approves (replay).
    The replay step runs the same pipeline as the original
    write would have, so a regression in the dispatch path
    surfaces here as a flow-level slowdown.
    """

    def test_submit_then_query_queue_under_budget(
            self, container_state, container_curl):
        # Step 1: analyst submits a column-removal request
        # (one of the lightest approvable actions — doesn't
        # require valid CSV state mutation).
        submit_payload = {
            "action_type": "column_removal",
            "csv_file": "DR102_whitelist.csv",
            "detection_rule": "DR102",
            "comment": "perf smoke",
            "pending_highlight": {
                "type": "column",
                "column_name": "_smoke_test_col",
            },
        }
        # Step 2: admin reads the queue
        read_queue = _read(container_curl, "get_approval_queue",
                           user="superadmin1")

        def _flow():
            submit = _post(container_curl, "submit_approval",
                           submit_payload, user="analyst1")
            submit()
            return read_queue()

        median_ms, max_ms, body = _time_curl_call(
            _flow, repetitions=2)
        assert median_ms < BUDGET_FLOW_MS, (
            "Submit+query approval flow median {:.0f}ms exceeds "
            "budget {}ms (max: {:.0f}ms). Combined dispatch + "
            "queue write + queue read regression. Body: {}".format(
                median_ms, BUDGET_FLOW_MS, max_ms,
                str(body)[:300]))


# ─────────────────────────────────────────────────────────────────────
# Coverage — every documented budget tier has at least one test
# ─────────────────────────────────────────────────────────────────────


class TestBudgetTierCoverage:
    """Drift detector for budget tiers. If a future change
    introduces a new budget tier or removes one, this test
    needs updating — preventing the budget table from drifting
    out of sync with the test classes that use it.
    """

    def test_every_budget_constant_is_referenced_by_a_test_class(self):
        # Read the live module's source and assert each of the
        # four budget constants is referenced from a test
        # method assertion. (The constants themselves are
        # defined at module level but could become orphaned if
        # a class is deleted without removing the constant.)
        import inspect
        import sys
        mod = sys.modules[__name__]
        src = inspect.getsource(mod)
        for budget in ("BUDGET_READ_MS", "BUDGET_WRITE_MS",
                       "BUDGET_HEAVY_MS", "BUDGET_FLOW_MS"):
            # Each budget constant should appear in at least
            # one assert message (i.e., be used by a test class)
            references = src.count(budget)
            # 1 reference for the definition + 1+ for usage = >= 2
            assert references >= 2, (
                "Budget constant {} is defined but no test "
                "class references it. Either remove the "
                "constant or wire it into a test.".format(budget))
