# Ring Findings — Test Coverage Audit Track

This file is the running log of findings from the test-coverage
hardening rings (0 → 3) that began on 2026-05-07 in response to the
build-641 latent bug discovery.

The structure is one section per ring. Findings are appended in
discovery order; nothing is rewritten retroactively. Each finding has
a stable id (`R<ring>-F<n>`) so subsequent rings can reference back.

---

## Ring 0 — Baseline Trust Calibration (in progress)

**Goal**: before adding new tests, calibrate how much we should trust
the existing 594-test baseline. If the existing suite has gaps, fix
them first; otherwise build Ring 1 on a foundation we know is solid.

**Method**: inspect the suite, run it, attempt to mutation-test
critical functions to see what tests catch.

**Status**: paused after surfacing significant baseline issues. See
"Stop-and-reassess summary" at the end of this section.

### R0-F1 — Splunk stub package missing `persistconn`

**Severity**: HIGH — blocks an entire test category from running.

`bin/wl_handler.py:49` imports
`from splunk.persistconn.application import PersistentServerConnectionApplication`.
The Splunk stub at `tests/stubs/splunk/` provides only `rest.py`, not
`persistconn`. Result: any test that imports `wl_handler` outside
the live container fails at collection time with
`ModuleNotFoundError: No module named 'splunk.persistconn'`.

The 3 test files that try to import `wl_handler` —
`test_handler_dispatch.py`, `test_handler_simple_post.py`,
`test_handler_complex_post.py` — wrap the import in a `try/except
ImportError` that silently sets the module to `None` and skips every
test in the file at runtime.

**Fix shipped**: added minimal stub at
`tests/stubs/splunk/persistconn/__init__.py` +
`tests/stubs/splunk/persistconn/application.py` exposing
`PersistentServerConnectionApplication` as a no-op base class.

**How long it was broken**: at least since 2026-04-01 (the commit
that introduced these test files). Possibly longer if the same import
was present in earlier handler revisions.

### R0-F2 — Three test files reference a class that does not exist

**Severity**: CRITICAL — 94 tests have been silently passing-by-skipping
for 5+ weeks, providing zero coverage despite being in the suite.

After fixing the stub gap (R0-F1), running the previously-skipped
tests revealed that all three files import `WlHandler`:

```python
try:
    from wl_handler import WlHandler
except ImportError:
    WlHandler = None
```

The actual class in `bin/wl_handler.py:1232` is
`class WhitelistHandler(PersistentServerConnectionApplication)`. There
is no `WlHandler` symbol in the module, never has been. The
`try/except ImportError` swallowed the missing-name failure and set
`WlHandler = None`, then every test method's `setUp` did
`if WlHandler is None: self.skipTest("wl_handler module not available")`
— every test silently no-op'd.

**What this means in practice**:

- `test_handler_dispatch.py` — 32 tests for the GET/POST dispatch
  table integrity. None ever ran.
- `test_handler_simple_post.py` — 38 tests for simple POST actions
  (save_col_widths, mark_notifications_read, cancel_request,
  log_event, save_as_default, reset_factory_defaults,
  set_trash_retention, purge_trash, restore_from_trash, create_csv,
  create_rule, error response shapes). None ever ran.
- `test_handler_complex_post.py` — 24 tests for complex POST actions
  (save_csv with approval, revert_csv with approval, remove_rule,
  remove_csv with approvals, dispatch table completeness). None ever
  ran.

**Total dormant test count**: 94 tests across these three files.

**Origin**: commit `beea551` on 2026-04-01 ("test(04-01): add
integration and unit tests for dispatch and replay") introduced these
files with the wrong class name. The suite has been running with
this hidden gap for over five weeks.

**Why this wasn't noticed sooner**: pytest reports skipped tests in
the summary line ("XX skipped"), but skipped tests don't fail CI and
don't print details unless `-rs` is passed. Combined with the
test-internal `skipTest` call (which is more obscure than a
collection-time skip), the failure mode was effectively invisible.

**Fix shipped (partial)**: renamed `WlHandler` → `WhitelistHandler`
in all three files (78 references total). The tests now reach their
bodies — and **all 94 fail immediately** because the test bodies
themselves were written against API assumptions that don't match the
real handler. None of the 94 tests has ever been validated against
real handler behaviour.

### R0-F3 — Existing handler-smoke contract tests are shallow

**Severity**: MEDIUM — explains why build-641 slipped through despite
the suite hitting the affected endpoint.

`tests/integration/test_docker_handler_smoke.py` has tests at lines
176-189 that ARE running and DO hit the build-641 bug area:

```python
def test_get_pending_approvals_response_shape(self, docker_available):
    """get_pending_approvals must return {pending: [...]}."""
    code, body = _docker_curl("get_pending_approvals")
    assert code == 200
    assert "pending" in body or "pending_approvals" in body
```

The test asserts the response has a top-level array key — and stops
there. It never inspects the contents of the array. A projection that
strips `comment` (or any other field) from every entry passes this
test cleanly. This test exists in name only; it provides zero
protection against the bug class it should cover.

**Same shape problem in**:
- `test_get_csv_content_response_shape` (lines 176-183) — checks for
  `headers` and `rows` keys, doesn't inspect entries
- `test_get_mapping_response_shape` (line 167-174) — checks
  `mapping[0]` has `rule_name` and `csv_file`, but no other fields
- `test_all_get_actions_dont_crash` (lines 200-213) — only asserts
  non-500. A 200 response with empty body would pass.

**Pattern**: contract tests assert "the JSON has the right shape at
the top level" but never recurse into nested entries. Build-641's
`comment` was 2 levels deep (`pending_approvals[0].comment`); no
existing test would have surfaced its absence.

---

### Stop-and-reassess summary

Triggered the user's "every 5 bugs = pause" gate after finding:

1. R0-F1 — missing stub blocks an entire test category
2. R0-F2 — 94 zombie tests with broken imports, dead since
   2026-04-01
3. R0-F3 — shallow contract tests in the running suite

These add up to a much bigger Ring 0 finding than expected:
**roughly 13% of the test surface (94 / 700) has been providing zero
coverage for over a month, and another portion provides only
top-level shape coverage.** The 594-test "trusted baseline" we
started with is closer to ~570 real tests with notable shallow spots.

**Decision needed from user before proceeding**:

Three options for the 94 broken tests:

A. **Repair in place** — fix each test's API assumptions to match
   the real handler. Time: ~3-5 days because there are 94 tests and
   many will reveal further drift between test expectations and
   handler reality. Highest yield (94 working tests).

B. **Delete them all** — they've never worked, no contributor has
   relied on them, treat them as untrusted code. Time: 5 minutes.
   Lowest yield (lose 94 hypothetical tests, but they've never
   actually existed in any meaningful sense).

C. **Hybrid** — delete in this commit, rewrite the most important
   contracts (dispatch table integrity, simple-POST happy paths,
   complex-POST approval gating) as part of Ring 1's contract-test
   plan. Time: 0 to delete + Ring 1's existing budget for the new
   tests. Yields a smaller but actually-working test surface
   targeting the highest-value contracts.

**Recommendation**: option C. Delete the zombies now (they're worse
than nothing — they create false trust). Roll the high-value
contracts into Ring 1 where we'll write them properly with mutation
testing as part of the ring-completion gate. The remaining tests in
the deleted files (e.g., admin signature checks) are duplicates of
tests already covered by `test_rbac.py`.

**Decision (2026-05-07)**: user picked option C. Zombies deleted in
this commit. High-value contracts catalogued for Ring 1 in
`docs/RING1_INPUT_handler_contracts.md`.

### Clean baseline after R0-F1, R0-F2 fixes

**Test suite state after Ring 0 cleanup**:

- Unit tests: passing
- Integration tests (non-docker): passing
- Integration tests (docker, against `wl_manager_test`): 16 passing
- Total: **702 passing, 1 skipped (Windows symlink test)**

This is the trustworthy baseline Ring 0 mutation testing runs
against. The pre-Ring-0 number of "594 / 666 / 682" was inflated by
zombie tests that never executed.

### Mutation testing results

Sabotaged 5 functions across the codebase, ran the test suite
against each sabotage, recorded what caught (or didn't), then
restored.

| # | Function | Sabotage | Tests caught | Verdict |
|---|----------|----------|--------------|---------|
| 1 | `wl_approval.project_pending_info` | drop `comment` field (build-641 bug) | 14/15 in `test_pending_info_projection.py` | CAUGHT |
| 2 | `wl_validation.is_safe_filename` | remove path-separator (basename) check | 0/117 in `test_validation.py` etc. | NOT CAUGHT |
| 3 | `wl_approval._read_approval_queue` | skip HMAC fail-closed | 3/74 in `test_approval.py::TestApprovalQueueHmac` | CAUGHT |
| 4 | `wl_versions.snapshot_version` | skip manifest write | 5/27 in `test_versions.py` | CAUGHT |
| 5 | `wl_trash.move_to_trash` | drop `comment` field (build-641 class) | 0/23 in `test_trash.py` | NOT CAUGHT |

**Mutation kill rate: 3/5 = 60%.** Below the ≥80% gate I set as the
ring-completion criterion. The two misses are the same bug class:
**field-presence in stored/returned data**.

#### R0-F4 — `is_safe_filename` basename check is incidentally redundant

**Severity**: MEDIUM — latent vulnerability, not active.

`is_safe_filename` has two layered defenses against path traversal:

1. `os.path.basename(name) != name` — rejects `subdir/file.csv` etc.
2. `_ASCII_FILENAME_STEM_RE.match(stem)` — restricts stem to
   `[A-Za-z0-9_-]+`, which incidentally rejects `/`, `\`, `.`

Because (2) is so strict, removing (1) is a no-op for current
inputs. **No test pins (1) independently.** If a future refactor
relaxes (2) — e.g., to allow underscores in directory components,
or accept arbitrary characters in some new context — (1) becomes
load-bearing and its absence becomes a real traversal vulnerability.

**Fix in Ring 1**: add a unit test that pins (1) directly. Test
candidate: a filename that would PASS the stem regex if (1) were
absent. Hard to construct given current regex strictness, so the
test should mock the stem regex to be permissive and verify (1)
still rejects path-separator inputs.

#### R0-F5 — `move_to_trash` has the same projection-drift bug class as build-641

**Severity**: HIGH — silent data loss waiting to happen.

When a CSV or rule is moved to trash, the `metadata` dict written
to `metadata.json` includes `"comment": sanitize_text(comment) if
comment else ""`. **No test asserts that field is present.** I
removed the line entirely; all 23 trash unit tests passed.

If a future refactor (or a careless edit) drops that line, every
trash entry from then on would have no comment in the audit trail
and on the trash dashboard. We'd find out only when an analyst
asked "why was this rule deleted?" and the audit had no answer.

**This is the build-641 bug class in a different module.**
Confirms the gap is systemic, not isolated.

**Fix in Ring 1**: add `test_trash.py::TestMoveToTrashMetadataShape`
that asserts the FULL set of expected fields is present in the
written metadata. Same pattern as `test_pending_info_projection.py`.

---

### Ring 0 conclusion

**Trust calibration**: the existing 702-test baseline catches some
classes of bug very well (HMAC tampering, manifest persistence) and
others not at all (field-presence in projections and stored
metadata). Mutation kill rate of 60% is below the ring gate.

**Total Ring 0 findings**: 5
- R0-F1: missing Splunk stub package — FIXED
- R0-F2: 94 zombie tests — DELETED (with high-value contracts
  catalogued for Ring 1 rewrite)
- R0-F3: shallow contract tests in handler smoke suite — to be
  addressed in Ring 1
- R0-F4: latent `is_safe_filename` traversal vulnerability —
  Ring 1 will add a pin test
- R0-F5: `move_to_trash` projection-drift bug class — Ring 1 will
  add metadata-shape test

**What this means for Ring 1**:

The Ring 1 plan was already to add endpoint contract tests + audit
event schema tests + recovery script tests + KV invariants. Ring 0
adds three specific items to that plan:

1. Rewrite the 70 high-value scenarios from
   `docs/RING1_INPUT_handler_contracts.md` as proper container
   contract tests
2. Add the basename-check pin test for `is_safe_filename`
3. Add the metadata-shape test for `move_to_trash`

Plus the original Ring 1 scope. Ring 1's effort estimate goes up
from ~3 days to ~5-7 days as a result, but the foundation is now
trustworthy — we know what the existing suite catches and what it
misses, so Ring 1's tests fill specific gaps rather than overlap
with existing coverage.

**Ring 0 status: ready for sign-off.** Awaiting user "go" to
proceed to Ring 1.

**Ring 0 closed**: user signed off 2026-05-07 with "Proceed" on
mutation kill rate, "full Ring 1" on scope.

---

## Ring 1 — Backend Contract Tests (in progress)

**Goal**: rewrite the high-value scenarios from the deleted zombie
tests (R0-F2) as proper container contract tests with deep response
shape inspection. Add audit-event schema tests, KV invariants,
recovery script smoke tests, and the R0-F4/R0-F5 fixes. Close with a
mutation gate at ≥80% kill rate.

### Day 1 — `docs/TESTING.md` + `container_state` fixture

**Status**: complete.

#### `docs/TESTING.md` (new)

Authoritative architecture document. Defines the three test layers
(unit / integration / e2e), when to use each, the
``container_state`` fixture contract, the markers, and the pattern
of "deep contract over shallow shape, container over mock,
mutation-gated over feeling-confident."

Written so the next contributor — or the next Claude session —
has a clear answer to "where does this test go?" and "what does
it need to assert?". Specifically calls out the build-641 / R0-F5
shallow-test anti-pattern with a concrete bad/good example pair.

#### `tests/integration/conftest.py` (new) — `container_state` fixture

Snapshots and restores wl_manager's state around each test that
requests the fixture. Two layers:

1. **Filesystem**: ``tar -czf`` over ``lookups/`` (atomic, captures
   approval queue, daily limits, FIM baseline, trash, version
   snapshots, all CSVs). Snapshot kept both inside the container
   and on the host (for survival across container restart).
2. **KV**: ``curl`` each wl_manager-owned collection
   (``wl_cooldowns``, ``wl_fim_baseline``) to a JSON dump,
   restore via DELETE-all + POST-each.

All subprocess calls use ``subprocess.run([list, of, args])`` —
never shell strings, no injection vectors. Container name and
credentials are baked-in module constants.

Cost: ~3-4 seconds per state-mutating test. Tests that don't
request the fixture pay zero cost (opt-in by parameter name).

#### `tests/integration/test_container_state_fixture.py` (new)

Eight smoke tests that pin the fixture's behaviour:

- **Handle shape**: snapshot_path exists, kv_dumps populated for
  each collection, dumps are lists
- **File restore**: sentinel file written inside the fixture is
  gone after teardown
- **KV restore**: sentinel record added to ``wl_cooldowns`` inside
  the fixture is gone after teardown
- **Opt-in**: test that doesn't request the fixture pays no cost

The file/KV restore tests use a clever pattern — write a sentinel
in `test_X_inside_fixture`, verify it's gone in
`test_X_is_gone_after_teardown`. This catches a class of fixture
bug that single-test verification cannot: any state that "leaks"
between tests.

All 8 tests pass. The fixture is the foundation Ring 1 builds on.

#### Day 1 baseline

**694 tests passing**, 1 Windows-skipped (symlink). Up from 686
after Ring 0 — net +8 from the new fixture smoke tests.

Container snapshot+restore cost confirmed at ~3 seconds per
fixture-using test (well within the 2-4 second budget). Total
suite runtime: 31.5 seconds.

### Day 2 (chunk 1) — dispatch integrity + simple POST happy paths

**Status**: in progress (chunk 1 done; chunks 2+ continue Day 2-3).

#### `tests/integration/test_dispatch_integrity.py` (new) — 16 tests

Pins the structural invariants of ``GET_ACTIONS`` and
``POST_ACTIONS``. Read-only, no fixture overhead. Covers:

- Tables exist + are non-empty dicts (2 tests)
- Every entry has the right shape (roles + method_name) (2 tests)
- Every method_name resolves to a callable on the handler (2 tests)
- Every method_name follows ``_action_<name>`` naming (2 tests)
- No action name in both tables, no duplicate method_names (3 tests)
- **RBAC tier hard-list** — known-superadmin/admin/edit actions
  pinned to the right tier; weakening a tier fails the test
  (3 tests)
- **Public actions allow-list** — every action with ``roles=None``
  must be on a hardcoded allow-list with a documented rationale
  (2 tests). Catches the regression where a destructive action
  silently loses its role tier.

Discovery during test development: my initial assumption was that
roles were tuples — they're actually ``Set[str]``. Test was
adjusted; this is exactly the kind of contract clarification
that test-writing surfaces.

#### `tests/integration/test_post_happy_paths.py` (new) — 10 tests

Each test issues a real POST against the test container and
asserts the FULL response shape, not just top-level keys. Uses
``container_state`` fixture for state-mutating tests.

Tier 1 (no preconditions) — 7 tests:
- ``mark_notifications_read`` — success flag
- ``save_col_widths`` — success flag + round-trip via GET (2 tests)
- ``log_event`` — csv_exported / csv_imported / audit_exported
  variants (3 tests)
- ``set_trash_retention`` — config file written with new value

Tier 2 (preconditions needed) — 3 tests:
- ``create_csv`` — full response shape (success, csv_file echo,
  message)
- ``create_rule`` — full response shape (success, detection_rule
  echo, message)
- ``save_csv`` (small edit, no approval) — including the
  ``pending_approvals`` deep contract that pins all 8 fields
  (build-641 fence). If the same projection drift recurs in
  ``save_csv``'s embedded pending_approvals, this test fails.

Field-name discoveries during test writing (good signal — pins
the actual API contract):
- ``create_csv`` and ``create_rule`` both take ``detection_rule``
  (not ``rule_name``). The mapping CSV stores ``rule_name`` as
  the column header but the API uses ``detection_rule``
  consistently. Documenting this in the test fence makes it
  self-pinning.
- ``save_csv`` requires ``detection_rule`` AND ``headers`` AND
  ``rows`` AND ``expected_mtime`` AND ``expected_content_hash``.
  Missing any returns 400. Test now follows the proper sequence:
  GET mapping → resolve rule → GET csv_content → POST save_csv.

#### Day 2 chunk 1 summary

26 new tests, all passing. Total suite: **720 tests** (was 694).
Total runtime: ~46 seconds (15 of those are the new docker tests).

Continuing Day 2-3 with: more POST happy paths (purge_trash,
restore_from_trash, save_as_default, submit_approval, etc.), then
POST error paths and approval workflow.

### Day 2 (chunk 2) — approval workflow contract tests

#### `tests/integration/test_approval_workflow.py` (new) — 14 tests

The highest-value Ring 1 file. Pins the response shapes and side
effects of the three approval-workflow endpoints. Build-641-class
projection drift in any of these would surface here.

Submit-side tests (6):
- ``test_submit_returns_request_id_and_message`` — pins minimum
  response shape (``message``, ``request_id``)
- ``test_submit_grows_the_queue_by_one`` — side-effect verification
  via ``get_approval_queue`` GET; catches "submit returns success
  but queue isn't actually updated"
- ``test_submitted_entry_has_full_contract`` — **pins the
  build-641 WRITE-SIDE contract.** Asserts the queue entry has
  all 12 documented fields including ``comment``. This complements
  ``test_pending_info_projection.py`` which pins the READ side.
- ``test_invalid_action_type_returns_400`` — error path
- ``test_missing_action_type_returns_400`` — error path
- ``test_non_ascii_description_returns_400`` — ASCII-only enforcement
  (the 2026-04-26 strict-ASCII policy decision)

Process-side tests (5):
- ``test_reject_response_shape`` — pins reject response (``message``,
  ``request_id``) and validates the message acknowledges rejection
- ``test_reject_transitions_status_in_queue`` — side-effect on the
  queue (``status=rejected``, ``resolved_by`` populated)
- ``test_unknown_request_id_returns_404``
- ``test_invalid_decision_returns_400`` (only approve/reject/cancel
  allowed)
- ``test_reject_without_reason_returns_400`` (rejection_reason
  required)

Cancel-side tests (3):
- ``test_cancel_response_shape``
- ``test_cancel_unknown_request_returns_404``
- ``test_cancel_without_reason_returns_400``

Test design choice: each test that needs a precondition submits
an approval request DIRECTLY via ``submit_approval`` (vs. via a
real ``save_csv`` + bulk-edit gate trigger). This keeps each
test focused on the contract under test, not the gate-detection
path. Setup is centralized in ``_submit_column_removal_request``
so future test additions reuse the same fixture pattern.

#### Day 2 chunk 2 summary

14 new tests, all passing. Suite: **734 tests** (was 720). Total
runtime: 74s (the approval tests are slower at ~2s each because
they each go through container_state snapshot + restore).

Day 2 progress: 40 / 70 tests complete. Continuing with POST
error paths and remaining happy paths.

### Day 2 (chunk 3) — POST error paths + first Ring 1 production bug fix

#### `tests/integration/test_post_error_paths.py` (new) — 16 tests

Pins the error contract for every POST endpoint. The test pattern:

1. Issue a POST with a deliberately-invalid payload
2. Assert ``error`` field present, type is string
3. Assert error message contains the documented substring (e.g.,
   ``"ASCII"`` for non-ASCII rejections, ``"100"`` for length-limit
   errors). This pins the substring the frontend toast displays.

Coverage by endpoint:

- create_csv (5): invalid filename, missing detection_rule,
  missing headers, non-ASCII rule name, internal-prefix column
- create_rule (3): missing detection_rule, too-long name (>100),
  non-ASCII name
- save_csv (3): missing detection_rule, non-ASCII comment, invalid
  app_context (path-traversal style)
- save_col_widths (2): missing csv_file, invalid app_context
- trash (2): retention below minimum, purge non-existent trash_id
- generic dispatch (1): unknown action name returns error not 500

#### Real production bug surfaced and fixed: `create_rule` UX (shipped build 643)

Two of the create_rule tests failed initially:
- ``test_too_long_rule_name_returns_error`` expected the error to
  mention "100" (the length limit)
- ``test_non_ascii_rule_name_returns_error`` expected "ASCII"

Both got the generic ``"Invalid request data."`` from the dispatch
wrapper's ``ValueError`` catch. **Inconsistent with create_csv**
which validates upfront and returns specific messages for the
same input classes.

Root cause: ``_action_create_rule`` had no upfront validation; it
delegated immediately to ``create_rule_pipeline`` which raised
``ValueError`` for bad inputs. The dispatch wrapper caught and
returned generic 400 — appropriate as a fallback for unexpected
errors, but the SPECIFIC validation messages aren't sensitive
(they describe the user's own input) and helping the analyst
understand what to fix is core UX.

Fix shipped in build 643: added upfront validation block to
``_action_create_rule`` mirroring the ``_action_create_csv``
pattern. Now both endpoints return:
- ``"Detection rule name is required"`` for empty input
- ``"Detection rule name too long: N chars (max 100)"`` for length
- ``"Detection rule name can only contain ASCII letters..."`` for
  non-ASCII

Same dispatch wrapper still catches truly unexpected ``ValueError``s.

This is the first Ring 1 test-driven production bug fix — exactly
the pattern Ring 1 was designed to surface. Test fails →
investigation reveals real bug → fix shipped → test now pins the
fix as a regression-prevention contract.

#### Day 2 chunk 3 summary

16 new tests (all passing after the create_rule fix).
**Suite: 750 tests passing** (was 734). Total runtime ~103 seconds.

Day 2 progress: 56 / 70 tests done. Continuing with remaining
happy paths (Day 3) — purge_trash, restore_from_trash,
save_as_default, reset_factory_defaults, and the bulk_edit
approval-gate trigger paths.

### Day 3 — Advanced happy paths + test infrastructure improvements

Five new tests, plus two significant fixture improvements.

#### New tests (5)

Added to ``tests/integration/test_post_happy_paths.py``:

1. ``test_approve_response_shape_for_column_removal`` — exercises
   the dual-user approval flow. Submits as ``analyst1``, approves
   as ``wladmin1``. Pins ``{message, request_id}`` minimum
   contract for approve responses.
2. ``test_revert_response_shape`` — pins the FULL 8-field shape
   of revert_csv responses (``message``, ``diff``, ``rows_before``,
   ``rows_after``, ``cols_before``, ``cols_after``, ``file_mtime``,
   ``content_hash``). Build-641 territory — drift in any of these
   would surface here.
3. ``test_bulk_row_removal_via_submit_approval`` — pins the
   approval-gate path response shape for bulk operations.
4. ``test_set_admin_limits_response_shape`` — pins the superadmin
   ``set_admin_limits`` contract; uses ``superadmin1`` user.
5. ``test_with_specific_ids_returns_success`` — completes the
   ``mark_notifications_read`` coverage with the IDs-passed variant.

#### Test infrastructure improvement 1 — multi-user curl

Two of the five new tests revealed that the conftest was hardcoded
to ``admin:Chang3d!`` and couldn't exercise role-specific paths:

- The approve test cannot use the same user that submitted —
  Splunk's ``"You cannot approve your own request"`` security
  block is correct behavior, but tests need TWO different users.
- ``set_admin_limits`` requires ``wl_superadmin`` role; the
  built-in ``admin`` user does NOT have it.

Updated ``_container_curl`` to accept ``user=`` and ``password=``
parameters defaulting to the WL_USERS table. Tests can now do:

```python
container_curl(path, method="POST", data=body,
               user="superadmin1")
```

WL_USERS table documents all four test users (admin, superadmin1,
wladmin1, analyst1) with shared password. Confirmed all are
configured in the test container.

#### Test infrastructure improvement 2 — rate-limit retry

After all 755 tests were written they passed individually but
**flaked intermittently in full-suite runs**, with different test
pairs failing each time. Investigation:

```
{'error': 'Rate limit exceeded. Please wait before retrying.'}
```

The handler's REST endpoint enforces a sliding-window rate limit
of 30 writes / 120 reads per user per 60 seconds (see
``bin/wl_ratelimit.py``). The test suite issues 100+ POSTs as
``admin`` in 100 seconds, exceeding the limit.

Updated ``_container_curl`` to detect ``"Rate limit exceeded"`` in
the response, sleep briefly (3-5 seconds with backoff), and
retry up to 2 times. After one retry the sliding window has
typically drained one slot.

This is the right fix because:
1. The rate limiter is a real production feature; tests should
   handle it gracefully, not bypass it
2. The retry preserves test semantics — tests still see the same
   contract the handler returns under normal load
3. Failure mode if retries exhaust: tests get the rate-limit
   response and can assert on it normally

#### Day 3 summary

5 new tests + 2 infrastructure improvements. **Suite: 755 tests
passing**, 1 Windows-skipped, ZERO flakes after retry handler.
Total runtime: ~120 seconds.

Day 1+2+3 cumulative: **69 / 70 tests** (close enough to call
Day 2-3 contract-test work complete). The audit-event schema
tests scheduled for Day 4 will push us over 70.

Ready to proceed to Day 4: audit event schema contract tests.

---

### Day 4 — Audit event schema contract tests

**Date**: 2026-05-07. Goal: pin the `wl_audit` write contract for
representative handler actions, and pin the schema invariant
("every handler-emitted event carries the 7 common fields") so a
future contributor cannot land a new action that silently breaks
SOC dashboards.

#### Tests added

`tests/integration/test_audit_emission.py` — 4 new tests, all
container-backed (real Splunk indexing, real `splunk search` CLI,
~1-15 second indexing-lag polling):

| Test class | What it pins |
| ---------- | ------------ |
| `TestRequestSubmittedAuditSchema` | `submit_approval` event has `action`, `analyst`, `detection_rule`, `csv_file`, `app_context`, `request_id`, `approval_action_type`, `description`, `status="pending"`, `comment` |
| `TestRequestRejectedAuditSchema` | `process_approval reject` event has all of the above plus `rejection_reason`, `status="rejected"` |
| `TestRuleCreatedAuditSchema` | `create_rule` event has `action="dr_created"`, `analyst`, `detection_rule`, `status="created"` |
| `TestCommonAuditFieldsInvariant` | Sample of 20 most recent `sourcetype=wl_audit` events all carry the 7 documented common fields |

The schema-pin tests use UUID4 markers embedded in `comment` /
`description` / rule-name so the test only matches its own event
(not someone else's parallel test run).

#### Finding R1-D4-F1 — config-only audit events bypass the common envelope

Surfaced by `TestCommonAuditFieldsInvariant`. The sample contained
an `admin_limit_change` event missing four of the seven common
fields (`detection_rule`, `csv_file`, `app_context`, `comment`).

A grep across `bin/wl_handler.py` turned up ~20 inline
`evt = {...}` constructions that bypass `wl_audit.build_audit_event()`:

- **Config-only events** that have no logical detection_rule /
  csv_file (admin_limit_change, limit_change, limit_reset,
  limit_factory_reset, limit_defaults_saved, emergency_lockdown_*,
  fim_deploy_window_*, bootstrap_csv_hashes,
  bootstrap_csv_hash_changed, dual_approval_*, trash_purged,
  factory_reset_executed, mass_usage_reset_executed,
  request_auto_cancelled, cross_app_csv_read, whitelist_view) ship
  various subsets of the common envelope and trip the invariant.

The invariant correctly caught the schema drift. CLAUDE.md
"Audit Event Structure" documents the 7 common fields as universal
for `sourcetype=wl_audit`, so the invariant is right; the inline
events are wrong.

**Fix (build 644)**: rather than refactor 20 callsites, backfill
the envelope at the chokepoint. `_index_audit` now applies
`dict.setdefault()` for all 7 common fields before delegating to
`post_audit_event()`. Defense-in-depth: even if a future
contributor adds another inline `evt = {...}` block, the schema
invariant holds.

`build_audit_event()` is still the documented helper; it just no
longer is the only line of defense.

#### Decision — chokepoint over callsites

Considered: refactor each of the 20 inline event constructions to
use `build_audit_event()`. Rejected: ~200-line diff with the same
observable behavior. The chokepoint pattern produces the same
guarantee with six lines of `setdefault` and protects against
future inline-event additions, which is the more important
property for a long-lived codebase.

#### Scope clarification — FIM events have a different sourcetype

The invariant initially failed against `fim_file_modified`,
`fim_watch_started`, `fim_baseline_kv_fs_divergence`, etc. These
are emitted by `wl_fim.py` and `wl_fim_watch.py` (separate
scripted-input processes) with `sourcetype=wl_fim` — they do NOT
go through `_index_audit`, they print JSON to stdout for Splunk's
scripted-input pipeline. CLAUDE.md "CSV Integrity Monitoring"
documents their schema separately, and they have their own
dashboard panel.

Resolution: the invariant test now scopes to
`sourcetype=wl_audit` (handler-emitted events). FIM events are a
distinct sourcetype with a distinct contract; if we want to pin
their schema too, that's a separate test class. Logged as a
follow-up for Ring 2 ("Coverage matrix").

#### Day 4 summary

4 new tests, 1 production fix (build 644 chokepoint envelope),
zero regressions in the integration suite.

| Suite scope | Pre-Day-4 | Post-Day-4 |
| ----------- | --------- | ---------- |
| Audit emission tests | 0 | 4 |
| Total integration tests | 161 | 165 |
| Pass rate | 100% | 100% |

Day 1+2+3+4 cumulative: **73 / 70 tests** (over the original
goal). Splunk indexing lag tolerated via 15s poll loop with 1.5s
intervals; no flakes observed in the 4 sample runs.

Ready to proceed to Day 5: KV schema invariants
(`wl_cooldowns`, `wl_fim_baseline`, `wl_presence`, `wl_lockdown`).
