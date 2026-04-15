# Systematic Bug-Hunt — 2026-04-15

## Why this document exists

After landing Build 562 (dual-superadmin E2E, CSV-integrity monitoring,
Show Requested Data UI), we executed a deliberate coverage-gap hunt
using the 10-category strategy from
`~/.claude/memory/feedback_systematic_bug_hunting.md`. The goal: find
latent bugs before the next production window by testing paths the
regular suite doesn't exercise.

This file records **what was tested, what was found, what was NOT
tested, and what a future session should tackle next**. It is intended
to be picked up cold by the next engineer.

## Motivating incident

Writing the FIM deploy-window dual-superadmin E2E uncovered two latent
bugs that had survived every prior run:

- `VERSIONS_DIR` used as a relative path in five places — every REST
  `open_deploy_window` call failed with `PermissionError`.
- `hashlib` and `hmac` were never imported in `wl_handler.py` — every
  call crashed with `NameError`.

Both paths were "verified" only through `fim_deploy_window.sh` (shell
script), which uses absolute paths and has its own imports. The REST
path had never been end-to-end tested. Classic two-entry-point trap.

That incident seeded the two cross-project feedback rules committed to
`~/.claude/memory/` and pushed to
`relativisticjet-dev-knowledge-base` (commit `2fd76d9`):

- `multi-entrypoint-coverage` — every feature with >1 entry point must
  be tested through each path.
- `systematic-bug-hunting` — after every feature lands, propose tests
  from the 10 categories; always name at least three specific gaps.

## Test suites added today

Three new E2E suites under `tests/e2e/`, all gated by
`WL_TEST_HARNESS=1` and `docker container == wl_manager_test`:

| Suite | File | Count | Result |
|-------|------|-------|--------|
| Role × Action matrix | `test_role_matrix.cjs` | 84 | 84/84 PASS |
| Approval state machine | `test_state_machine.cjs` | 15 | 15/15 PASS |
| Concurrency / races | `test_concurrency.cjs` | 4 | 3/4 PASS (C02 reveals a real bug) |

Total: 103 new assertions, 102 passing, 1 failing by design (documents
a reproducible race condition — see "Bugs found" below).

### Suite 1: Role × Action matrix (`test_role_matrix.cjs`)

**What it does.** Enumerates every GET action and a safe subset of POST
actions across three role tiers (analyst, admin, superadmin) — 28
actions × 3 users = 84 combinations. For each combination asserts:

- The handler returns **well-formed JSON**, not an HTML error page.
- The response never contains `"internal server error"`, `"Traceback"`,
  `"NameError"`, `"KeyError"`, `"TypeError"`, `"AttributeError"`, or
  `"unbound"`.
- Sufficient role → success or domain error (never a permission error).
- Insufficient role → no tier-specific response shape leaks through.

**Result.** 84/84 PASS. Zero crashes, zero RBAC leaks. This validates
that the dispatch layer has no latent import/typo/missing-field bugs —
a direct descendant of the deploy-window discovery.

**Known gap.** The "insufficient role → must be denied" assertion is
loose: it only flags tier-specific **shape** leaks (`resp.queue`,
`resp.admin_limits`, etc.). A handler that silently returned `{}`
instead of a permission error would pass. A future-session test
should verify that denial returns a permission-style error with
HTTP 403 semantics for every insufficient-role combination.

### Suite 2: Approval state machine (`test_state_machine.cjs`)

**What it does.** Walks the approval queue through every valid and
invalid transition:

- Pure negatives: unknown request_id → 404, invalid decision → 400,
  missing rejection/cancellation reason → 400, invalid action_type →
  400.
- Lifecycle: `pending → approved`, then re-approve / reject / cancel
  all return 409 "already processed".
- `pending → rejected`, then re-approve returns 409.
- Self-approval (submitter == admin) blocked with 403.
- Unrelated analyst attempting to cancel another analyst's request →
  403.
- Duplicate submission for the same CSV → second is blocked with a
  "locked" error.

**Result.** 15/15 PASS. The approval state machine holds its invariants
under every tested scenario. Lock/rejection semantics are correct in
the non-concurrent case.

**Known gap.** These are single-threaded tests. Two admins processing
the same request simultaneously is covered by suite 3.

### Suite 3: Concurrency / races (`test_concurrency.cjs`)

**What it does.** Fires simultaneous requests via `Promise.all` and
asserts the system either serializes them correctly or fails one
cleanly.

| Test | Scenario | Result |
|------|----------|--------|
| C01 | Two admins approve the same request simultaneously | PASS — one succeeds / errors, the other gets "already processed" |
| C02 | Two analysts submit for the same CSV simultaneously | **FAIL** — both submits succeed, CSV lock bypassed |
| C03 | Two superadmins activate_lockdown simultaneously | PASS — one wins, lockdown state correct |
| C04 | Concurrent save_csv with the same stale mtime | PASS — no crash (no-op payload) |

**Result.** 3/4 PASS. C02 is a real, deterministically-reproducible
race condition.

## Bugs found

### Bug 1 (HIGH) — TOCTOU race in `_submit_approval` CSV lock

**File.** `bin/wl_handler.py:4526-4699`, `bin/wl_approval.py:122-149`.

**Symptom.** Two analysts submitting an approval request for the same
CSV at the same millisecond can both succeed, creating two pending
entries for the same CSV. The documented invariant "Block if ANY
pending request exists for this CSV" is violated.

**Root cause.** The critical section is split:

1. `wl_handler._submit_approval` reads the queue via
   `_expire_pending_approvals()` (no lock).
2. Runs the block check against the in-memory queue (no lock).
3. Calls `_approval_queue_lock()` (a no-op context manager at
   `wl_handler.py:241` since the wl_approval migration).
4. Re-reads the queue, appends the entry, calls
   `_write_approval_queue()` — only this write is locked.

Two processes can both pass step 2, both enter step 3's no-op lock,
both re-read in step 4, and both write. The `file_lock` inside
`_write_approval_queue` serializes the two writes but does **not**
prevent both from appending — because by then both processes have
already decided the CSV is unlocked.

**Why the existing guards didn't catch it.** The commit `Re-read
inside lock to prevent TOCTOU race` was added, but only for the
`_expire_pending_approvals` reshuffle — not for the block-conflict
check. The context manager `_approval_queue_lock()` was turned into
a no-op during the wl_approval refactor with a comment claiming
"wl_approval handles locking internally", which is true only for the
write, not for the read-modify-write cycle.

**Reproduction.** 3/3 runs of `test_concurrency.cjs` show both submits
succeeding.

**Fix applied (Build 569).** Restored `_approval_queue_lock()` as a real
file lock (Option 1), and added an explicit authoritative conflict
re-check inside the lock in `_submit_approval`. Key design notes:

- The outer lock uses a **sibling `.rmw.lock` path**, NOT the queue
  JSON itself. fcntl.flock is not reentrant across file descriptors
  in the same process — nesting locks on the same path deadlocks with
  `wl_approval._write_approval_queue`'s inner write lock.
- A new `_approval_conflict_error()` helper is called in two places:
  once outside the lock as a UX fast-fail, once inside the lock as the
  authoritative TOCTOU guard.
- Inside the lock, uses `_read_approval_queue()` + in-memory
  `expire_pending_approvals(queue)` — **not** `_expire_pending_approvals()`
  (which performs its own unconditional write, widening the critical
  section and increasing interleaving risk).

**Effectiveness.** 30-run regression test: deterministic 100% failure
before the fix drops to ~13% flake rate after. The remaining flakes
are not the original TOCTOU race — when they occur, the queue contains
both entries (one spontaneously marked "failed") or one entry is lost
without either response seeing the other. These look like a secondary
race in `wl_approval._write_approval_queue`'s temp-file + os.replace
sequence where the flock is released BEFORE the rename ([wl_approval.py:138-142](bin/wl_approval.py#L138-L142)).

**Remaining work (next session):**

- Fix the inner write-lock to span the rename (currently `os.replace`
  happens after the `file_lock` context manager exits). This likely
  closes the remaining ~13% flake window.
- Add a regression test mode that runs C02 many times in a single
  process so the flake rate is quantifiable in CI.
- `_process_approval` has the same `_approval_queue_lock()` wrap
  pattern but its inner writes go through the locked
  `_write_approval_queue()` (which acquires flock on a DIFFERENT path
  than `.rmw.lock`, so no deadlock). Its state-transition check isn't
  wrapped in the outer lock the way submit's conflict check now is —
  worth auditing for the same class of TOCTOU.

**Severity rationale.** The double-submit doesn't leak privileges or
bypass an approval gate — both entries still need admin approval. But
it is confusing (analyst sees "you already have a pending request"
on their next visit, yet the queue has two), it can double-charge
daily limits if both are approved, and it undermines the stated
contract enforced by the UI. Downgrading from CRITICAL to HIGH.

### Bug 2 (LOW / observation) — `_approval_queue_lock()` is a silent no-op

**File.** `bin/wl_handler.py:241`.

**Symptom.** Every `with _approval_queue_lock():` call in the handler
provides zero serialization. This is documented in the docstring but
most callers appear to assume real locking (`# Re-read inside lock`
comments, etc.).

**Suggested fix.** Either rename it to make the no-op explicit
(`_approval_queue_noop_lock()`), or restore it to a real lock (which
also fixes Bug 1). Callers currently rely on a misleading name.

## What was NOT tested (and why)

A deliberate inventory — each item is a candidate for a future session:

1. **Payload fuzzing** — no unicode (RTL, zero-width, emoji), null
   bytes, max-length ±1 on reason/comment/column fields. ROI: medium;
   the ASCII validator is already strict, but individual handlers may
   skip it.
2. **Data boundary tests** — no max-row or max-column tests beyond the
   existing stress fixture. Duplicate-heavy rows, path-traversal
   filenames, unicode CSV filenames not covered. ROI: medium.
3. **Frontend integration** — no test of modal-open-during-navigation,
   undo-window-during-auto-save, multi-tab edits, browser back during
   modal. ROI: medium; refactor-prone.
4. **DR runbook end-to-end** — `reset_cooldowns.sh`, `emergency_unlock.sh`,
   FIM baseline rebuild are tested individually but not as a full
   post-GUID-rotation sequence. ROI: high; runbook correctness is
   usually checked only during real incidents.
5. **Persistent-process resilience** — no SIGKILL test of
   `wl_fim_watch.py`, no container-pause, no file-descriptor
   exhaustion. ROI: medium; existing heartbeat alerts haven't been
   failure-exercised.
6. **Dashboard / SPL correctness** — no unit test for the Audit
   dashboard panels (timezone correctness, empty-data behavior,
   unicode analyst names, the bootstrap-laundering correlation).
   ROI: medium.
7. **Role matrix — mutating POSTs** — today's matrix skipped
   create/remove/activate_lockdown etc. to avoid corrupting test
   state. A future pass should run each mutating POST against each
   role, then clean up. ROI: high; this is where RBAC typos hide.
8. **Cross-CSV state drift** — two analysts editing different CSVs
   simultaneously (not covered because we tested same-CSV races).
9. **Queue entry schema drift** — dual-admin queue entries lack
   `csv_file` at top level; iterators that use `item["csv_file"]`
   instead of `item.get("csv_file")` crash. A schema-validation test
   that re-hydrates every queue item and asserts schema compliance
   would catch future drift.
10. **CSV content-hash race** — bootstrap during an in-flight save.
    Conceptually similar to Bug 1 but on the CSV registry side.

## Suggestions for the next session

**Immediate (do-first):**

1. **Confirm with the user whether to patch Bug 1.** If yes, the
   one-line fix is to make `_approval_queue_lock()` a real file lock
   using `wl_filelock.file_lock` against the queue-JSON path. Add a
   regression test in `test_concurrency.cjs` that runs the old race
   and asserts the new behavior.
2. **Tighten the role matrix "insufficient role" assertion.** Assert
   `resp.error` is present and matches a permission pattern for every
   denied combination — don't just look for shape leaks.
3. **Extend the role matrix to mutating POSTs.** Do it with per-test
   cleanup so repeated runs stay stable.

**Medium-term:**

4. Write payload-fuzz tests against `reason`, `comment`,
   `admin_comment`, `rejection_reason`, `cancellation_reason`,
   `description`. Focus: unicode, max-length ±1, null bytes,
   zero-width chars.
5. Write the full DR runbook E2E: mutate a CSV, open lockdown, rotate
   GUID, run `reset_cooldowns.sh`, rebuild FIM baseline, verify
   operations resume.
6. Write a queue-entry schema validator test: load the queue, hydrate
   each entry against a Pydantic/dataclass shape, fail if any entry
   is missing a required key.

**Long-term:**

7. Introduce a `WL_DETERMINISTIC_RACE_HARNESS` mode that uses a
   mock clock / semaphore to make the TOCTOU races 100% reproducible
   (today's test is 3/3 on my box but may flap on slower boxes).
8. Lighthouse-style performance assertions on the Control Panel
   (bundle size, time-to-interactive). Currently untested.

## Running the suites

```bash
# Pre-req: test container running, WL_TEST_HARNESS=1 set
export WL_TEST_HARNESS=1

node tests/e2e/test_role_matrix.cjs      # 84 tests, ~30s
node tests/e2e/test_state_machine.cjs    # 15 tests, ~15s
node tests/e2e/test_concurrency.cjs      # 4 tests, ~20s (C02 fails by design)
```

All three gate on `wl_manager_test` container name via `assertTestHarness()`
in `lib_helpers.cjs`. They will refuse to run against anything else.

## Closing observation

The matrix test (84/84) and state-machine test (15/15) passing on the
first try is a strong signal that the recent modularization (Wave 3)
and security hardening (builds 552-562) did not break the invariants
they were meant to preserve. The one real bug surfaced (C02 TOCTOU) is
a pre-existing condition that predates the hardening work — it was
introduced during the wl_approval refactor that made
`_approval_queue_lock()` a no-op.

The bugs that hit production are rarely in the paths the team writes
tests for. Today's hunt added 103 assertions in three previously-uncovered
categories and found exactly what that principle predicts: a concurrency
bug hiding behind a misleading no-op lock.
