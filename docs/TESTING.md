# Testing Architecture

This document describes the structure and conventions of the
Whitelist Manager test suite.

It exists because Ring 0 of the test-coverage hardening track
(2026-05-07) revealed that without an architecture document, the
test suite drifts: zombies accumulate (94 dead tests for 5+ weeks
in our case), shallow contract tests spread, and developers can't
tell which layer to add a new test to. This file is the
authoritative answer to "where does this test go?" and "what does
it need to assert?"

## Test layers

```
┌──────────────────────────────────────────────────────────────┐
│ tests/e2e/         — Playwright .cjs, full browser flows     │
│ tests/integration/ — Python, real Splunk container           │
│ tests/unit/        — Python, pure helpers + Splunk stubs     │
└──────────────────────────────────────────────────────────────┘
```

### `tests/unit/` — pure-helper tests

Tests for library code that has NO dependency on a running Splunk
instance. Imports from `bin/` go through `tests/conftest.py`,
which adds `tests/stubs/` to the path so `splunk.rest` and
`splunk.persistconn.application` resolve to the no-op stubs.

What lives here:

- Validators (`wl_validation.py`, `wl_rbac.py`)
- Pure transformations (`wl_csv.py` diff/parse, `wl_versions.py`
  manifest helpers, `wl_approval.project_pending_info`)
- HMAC primitives, file lock helpers, audit event builders
- Anything callable as a function with no side effects on Splunk
  state

What does NOT live here:

- Tests that need to call a REST endpoint
- Tests that need to verify KV collection state
- Tests that need to interact with a running handler instance

Speed: <1 second total. Run on every save (`pytest tests/unit/`).

### `tests/integration/` — handler-with-container tests

Tests that exercise the handler end-to-end against the real
`wl_manager_test` Docker container. These are the slow but
authoritative tests — they catch projection drift, dispatch
table bugs, RBAC mismatches, and audit emission gaps.

Two kinds:

1. **Container-state tests** (`@pytest.mark.docker`) — call REST
   endpoints via `_docker_curl()`, assert response shapes,
   inspect KV state, verify audit events. State-mutating tests
   MUST use the `container_state` fixture (see below).

2. **In-process handler tests** (no `@pytest.mark.docker`, default
   collection) — instantiate `WhitelistHandler()` directly,
   exercise method-level contracts. Faster than container tests,
   slower than unit tests. Useful when the goal is to verify the
   Python code path without the network round-trip.

Speed: ~10-30 seconds for a full integration run. Run on every
PR.

### `tests/e2e/` — Playwright browser flows

Full-stack tests that drive the Splunk Web UI via Playwright.
Used for user-flow validation (click X, see Y), cross-browser
checks, visual regression, and accessibility.

These complement the integration tests — integration covers the
backend contract, E2E covers the frontend wiring.

Speed: minutes per file. Run on every PR but in a separate CI
job from the Python suite so a flaky test in one doesn't block
the other.

## Container-state isolation (`container_state` fixture)

State-mutating integration tests use the `container_state` pytest
fixture defined in `tests/integration/conftest.py`. The fixture:

1. **Snapshots** the relevant container state before the test:
   - `lookups/` directory (all approval queues, version
     snapshots, FIM baselines, daily limits, notifications,
     trash, KV mirror files)
   - All KV collections that the handler maintains
     (`wl_cooldowns`, `wl_fim_baseline`, `wl_presence`,
     `wl_lockdown`)
2. **Yields** to the test
3. **Restores** the snapshot — replaces files, repopulates KV

Cost: ~2-4 seconds per test (snapshot + restore + tar I/O). This
is the price we pay for accuracy. The user's explicit decision
during Ring 0 was "container tests for accuracy" over speed.

Tests that DON'T mutate state can opt out by NOT requesting the
`container_state` fixture — they run faster and don't pay the
restore cost.

### When to use `container_state`

Required:

- Any test that issues a POST that writes to disk or KV
- Any test that triggers a notification or audit event
- Any test that creates/modifies/deletes a CSV, rule, or trash
  entry
- Any test that approves, rejects, or expires queue entries

Not required:

- Pure GET tests that only read state (`get_csv_content`,
  `get_pending_approvals`, `list_trash`)
- Tests that only verify dispatch table integrity
- Tests that only check method existence / signatures

### When `container_state` is NOT enough

The fixture restores the application's state (lookups + KV). It
does NOT restore:

- Splunk's internal indexes (`wl_audit`, `_internal`,
  `_introspection`). Audit events emitted by the test will
  remain in the index. Tests that need to verify audit emission
  should use the `audit_query` fixture (Ring 1 Day 4) which
  queries by a unique marker the test embeds in the event.
- Splunk's runtime in-memory state (RBAC cache, session keys).
  These survive across tests but are reset on container restart.
- Files outside `lookups/` (e.g., `default/`, `bin/`,
  `appserver/`). Tests should never mutate these.

If a test needs broader state reset, use the
`@pytest.mark.docker_restart` marker which restarts Splunk
between tests. This is even slower (~30 seconds per test) and
should be used sparingly — only for tests of in-memory cached
state (e.g., HMAC key derivation, lockdown TTL).

## What "complete" coverage looks like (Ring 1 standards)

Every endpoint test must:

1. Run against the real container (per user's accuracy
   preference)
2. **Inspect the FULL response shape** — every documented field,
   not just top-level keys. This is the build-641 / R0-F5
   class. Shallow tests pass while real bugs ship.
3. Carry a corresponding mutation gate — sabotage the handler in
   1-2 ways the test should catch, confirm failure, restore.
   Mutation kill rate ≥80% per ring.
4. Use `container_state` if it mutates state.
5. Have a clear docstring stating: what it pins, what bug class
   it catches, what failure mode it would surface.

### Anti-pattern: shallow contract tests

```python
# BAD — what build-641 slipped past
def test_get_pending_approvals_response_shape(self, docker_available):
    code, body = _docker_curl("get_pending_approvals")
    assert code == 200
    assert "pending" in body or "pending_approvals" in body
```

This test asserts the response has a top-level array key and
stops. A projection that strips every field except `request_id`
from each entry passes. **It exists in name only.**

### Pattern: deep contract tests

```python
# GOOD — pins the full contract per entry
PENDING_INFO_FIELDS = {
    "request_id", "action_type", "description", "comment",
    "analyst", "timestamp", "pending_highlight", "payload",
}

def test_pending_approvals_entry_carries_full_shape(
        self, docker_available, container_state, seeded_pending_request):
    """get_pending_approvals must return entries with all 8 fields.

    Pins: build-641 projection contract.
    Catches: any projection that drops a field on the way to the
        frontend (the build-641 bug class). Both endpoints that
        return pending_info shapes (_get_csv_content and
        _action_get_pending_approvals) share this contract.
    """
    code, body = _docker_curl("get_pending_approvals")
    assert code == 200
    assert body["pending_approvals"], "fixture failed: no pending"
    for entry in body["pending_approvals"]:
        assert set(entry.keys()) == PENDING_INFO_FIELDS, \
            f"projection drift: {entry.keys() ^ PENDING_INFO_FIELDS}"
```

Every Ring 1 contract test follows the second pattern.

## Markers

Defined in `tests/pytest.ini`:

| Marker | Meaning |
|--------|---------|
| `unit` | Pure-helper test, no Splunk dependency |
| `integration` | Handler-level test, may use Splunk stubs |
| `docker` | Requires the `wl_manager_test` container to be running |
| `docker_restart` | Requires Splunk to be restarted between tests (use sparingly) |
| `slow` | Test takes >5 seconds — concurrent, fuzz, stress, E2E |
| `crud` | Core CRUD workflow (add/edit/remove/revert) |
| `approval` | Approval workflow (submit/approve/reject) |
| `revert` | Version revert |
| `admin` | Admin panel actions |
| `stress` | Wide CSV / large row count |
| `security` | Security/attack/injection |

When adding a new test, pick the most specific applicable marker.
Tests can have multiple markers (e.g., `@pytest.mark.docker
@pytest.mark.approval`).

## Running the suite

```bash
# Fastest — unit tests only, ~1 second
pytest tests/unit/

# Standard PR check — unit + non-docker integration, ~15 seconds
pytest tests/unit tests/integration -m "not docker and not slow"

# Full suite including docker, ~1 minute
pytest tests/unit tests/integration

# Just the docker-marked tests, ~15 seconds (after container is up)
pytest tests/integration -m docker

# Full suite + slow + E2E, ~10 minutes
pytest tests/

# Specific marker
pytest -m approval
pytest -m "docker and approval"
```

## Adding a new test

1. **Pick a layer** — unit if it's a pure function, integration
   if it needs the handler, e2e if it needs the browser
2. **Pick markers** — at minimum the layer marker, plus any
   workflow markers that apply
3. **Use the right isolation** — `container_state` for any
   integration test that mutates state
4. **Write a deep contract assertion** — full response shape, not
   just top-level
5. **Add a docstring** that names the bug class the test catches
6. **Run the mutation gate** — pick a way the production code
   could be broken that the test SHOULD catch, sabotage, run,
   confirm failure, restore

## Why Ring 0 happened

Five weeks of fictional safety net (94 zombie tests) shipped
because:

- The test files used `try/except ImportError` which silently
  set the handler to None and skipped every test
- pytest's "skipped" output was indistinguishable from
  legitimate "needs docker, ok skipped" cases
- No test architecture document existed to explain what each
  layer should look like

Ring 0 fixed the immediate damage. This document is the lesson
written down so the next contributor — or the next Claude
session — has the architecture in front of them before they add
a test that drifts the same way.

When in doubt: **deep contract over shallow shape, container over
mock, mutation-gated over feeling-confident.**
