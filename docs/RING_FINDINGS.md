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
