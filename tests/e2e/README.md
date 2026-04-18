# E2E Tests — Test Harness Gate

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
