# E2E Tests — Test Harness Gate

## READ BEFORE WRITING A NEW E2E TEST — No Synthetic State Injection

E2E tests in this directory MUST drive the feature through the real
production code path — a real user (analyst1 / wladmin1 / superadmin1)
clicking the real UI, or an authenticated REST call to
`POST /custom/wl_manager` with the correct `action=`.

**Do NOT** start a test by writing directly to
`lookups/_versions/_approval_queue.json`, `.fim_baseline.json`,
`_daily_limits.json`, KV collections, or any other Splunk-internal
storage to "set up" queue entries, counter values, or baseline state.
Synthetic fixtures populate both sides of the handler/frontend
contract and hide schema drift — the exact failure mode that let the
build 614 dual-admin "Invalid Date" bug reach production. If the
state you need did not get there by a real user doing a real thing,
your test is not an E2E test.

The PreToolUse hook at `scripts/hooks/block-synthetic-fixtures.js`
blocks most such writes at the tool level. This banner is the
human-reader reminder that covers paths the hook cannot see (e.g. a
test that shells out through a subprocess, or a test added on another
machine without the hook wired up).

**Legitimate setup patterns:**

- `setup_test_env.sh` — stands up the container and seeds baseline
  state that exists for ALL E2E tests (not per-test fixtures).
- `lib_helpers.cjs :: assertTestHarness()` — the destructive-ops gate
  (see below). Destructive ops are allowed because they EMULATE
  real disaster-recovery scenarios, not because they bypass the
  handler during feature verification.
- `tests/unit/**` — pure-helper tests with synthetic inputs. Not E2E.

See `CLAUDE.md` → "Synthetic Fixtures — Banned for Feature
Verification (mechanically enforced)" for the full policy, and
`~/.claude/projects/c--Users-PC-wl-manager/memory/feedback_synthetic_fixtures_mask_schema_drift.md`
for the origin incident.

## STOP — READ THIS FIRST

Several tests in this directory run **destructive operations** against
the Splunk test container:

- Delete the `wl_cooldowns` KV store record
- Remove on-disk tamper / init markers
- Mutate `default/app.conf` and other watched files

These helpers bypass production security controls (HMAC tamper flags,
daily rate limits, FIM alerts) so the full test suite can run in under
a minute. **They must never run against a production-like environment.**

## The Gate

Every destructive helper calls `lib_helpers.cjs :: assertTestHarness()`
which enforces TWO independent checks:

1. **Environment variable** — `WL_TEST_HARNESS` must equal `"1"` (the
   exact string `"1"`, not `"true"` / `"yes"` / `"on"`).
2. **Container name** — the container running in docker must be
   named exactly `wl_manager_test`.

If either check fails, the helper throws an error and the test aborts
BEFORE any mutation happens. This is the safety floor.

## How to Run Tests

Always invoke with the env var explicitly, per command:

```bash
WL_TEST_HARNESS=1 node tests/e2e/test_admin_limits.cjs
WL_TEST_HARNESS=1 node tests/e2e/test_adversarial_hardening.cjs
WL_TEST_HARNESS=1 node tests/e2e/test_cooldown_tamper.cjs
WL_TEST_HARNESS=1 node tests/e2e/test_harness_gate.cjs
```

### DO NOT

- Export `WL_TEST_HARNESS=1` in `~/.bashrc`, `~/.zshrc`, or any shell
  profile file. That makes the gate useless because every shell in
  the session (including ones that accidentally open against a
  production container) will satisfy the env check.
- Put `WL_TEST_HARNESS=1` in a global `.env` file that other tooling
  reads.
- Remove the `WL_TEST_HARNESS=1` prefix from any CI command below.
- Rename your production container to `wl_manager_test` for any
  reason. The gate uses the name as a second factor; renaming
  breaks that factor.

### Run Order — Sequential is the reliable path

The destructive test suites (`test_cooldown_tamper`, `test_adversarial_hardening`,
`test_admin_limits`) share a global rate-limit counter for `set_admin_limits`
(5 changes/day). Running them in parallel can cause flaky failures when one
suite depletes the counter before another finishes.

**Recommended: run sequentially in this order:**

```bash
# 1. Gate test first (fast sanity check)
WL_TEST_HARNESS=1 node tests/e2e/test_harness_gate.cjs

# 2. Cooldown tamper (resets KV state, fast)
WL_TEST_HARNESS=1 node tests/e2e/test_cooldown_tamper.cjs

# 3. Adversarial hardening (heaviest, depends on clean counter)
WL_TEST_HARNESS=1 node tests/e2e/test_adversarial_hardening.cjs

# 4. Admin limits (resets counter at start, safe to run last)
WL_TEST_HARNESS=1 node tests/e2e/test_admin_limits.cjs
```

**Parallel is supported** but may produce flaky results on rate-limit-sensitive
tests. Each suite clears its own counter at critical points, but interleaved
execution can still deplete the shared counter between clears.

### First run on a fresh container

If the container was recreated (e.g., `docker-compose down && up`), run the
setup script first to create test users and roles:

```bash
./tests/e2e/setup_test_env.sh
```

### CI Setup

Every CI job that runs these tests must set the env var **inline for
the single command**, not as a job-wide `env:` block, to minimize the
blast radius if a config error leaks the variable into other steps:

```yaml
# .github/workflows/ci.yml
- name: Run E2E tests
  run: |
    ./tests/e2e/setup_test_env.sh
    WL_TEST_HARNESS=1 node tests/e2e/test_harness_gate.cjs
    WL_TEST_HARNESS=1 node tests/e2e/test_cooldown_tamper.cjs
    WL_TEST_HARNESS=1 node tests/e2e/test_adversarial_hardening.cjs
    WL_TEST_HARNESS=1 node tests/e2e/test_admin_limits.cjs
```

## If the Gate Fires

If `assertTestHarness()` throws during a test run:

1. **Do not set the env var and retry.** The gate fired for a reason
   — probably because you are running against the wrong container or
   forgot to prefix the command. Fix the underlying cause first.
2. Check which container is running: `docker ps --format '{{.Names}}'`.
3. If you are certain you are in the test environment, prefix the
   command with `WL_TEST_HARNESS=1` and rerun.

## Test Files

| File | Purpose |
|---|---|
| `test_harness_gate.cjs` | Verifies the gate itself rejects missing / wrong env var |
| `test_cooldown_tamper.cjs` | KV store cooldown tamper detection |
| `test_adversarial_hardening.cjs` | Threat-model-driven checks across all 3 user tiers |
| `test_admin_limits.cjs` | Admin limit RBAC, enforcement, bypass resistance |
| `lib_helpers.cjs` | Shared helpers including `assertTestHarness` and `clearKvCooldownCounter` |

## Test-Run Cadence (Ring 6.1 Day 6.1.10)

Since the Day 6.1.9b fix landed (build 657), rate limiting is enforced
strictly cross-worker: each `(user, action_type)` bucket allows
**30 writes / 60 seconds** across the entire Splunk persistconn pool.
This is the correct production behavior, but it changes how the
test suite must be sequenced.

**Cadence rule for concurrency tests** that fire many POSTs as
the same user (e.g. `test_concurrent_save_csv.cjs`,
`test_concurrent_limit_other_counters.cjs`,
`test_concurrent_presence.cjs`,
`test_ratelimit_per_worker.cjs`):

- Wait **at least 75 seconds** between runs that share a user
  (default test users: `superadmin1`, `wladmin1`, `analyst1`).
- The 60-second sliding window plus a small margin ensures the
  prior bucket has fully aged out before setup writes hit the cap.
- Symptom of violating the cadence: setup-phase actions like
  `create_rule`, `save_csv`, or `report_presence` return
  `"Rate limit exceeded"` and the test fails in Phase A or B.

**Why this is correct behavior**: pre-fix the per-worker
`_rate_limits` dict bypassed this — each worker had its own
30/60s budget, so two workers gave you 60/60s, four workers
120/60s, etc. The R6-F8 fix at build 657 closed this and
restored the documented cap. Tests must now respect the cap
just like production callers do.

**Future work**: if the cadence cost becomes painful (e.g. the
full suite goes from 5 min to 25 min because of wait gates),
add a `wait_for_ratelimit_clear(page, user, action_type)`
helper to `lib_helpers.cjs` that polls a cheap GET endpoint
until the bucket has capacity. Out of scope for Ring 6.1.
