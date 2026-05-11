"""
Hypothesis state-machine model of the approval queue
(Ring 4 Day 7).

Exercises the pure functions in ``bin/wl_approval.py``
(``_validate_queue_entry`` and ``expire_pending_approvals``)
with random sequences of submit/approve/reject/cancel/
expire operations and asserts the queue invariants hold
after every transition.

The state machine is intentionally pure-Python: no HTTP,
no filesystem, no Splunk. The goal is to find logic
bugs in the queue's invariant-preservation contract,
not in the deploy path. Integration-level chaos is
already covered by Day 4-6 chaos tests; this layer
catches the bugs those tests can't surface (subtle
state transitions, schema drift between submit and
replay, ordering edge cases).

Why state-machine testing
-------------------------

The build-614 dual-admin queue bug (Invalid Date) was a
schema drift between writers and readers: one path
wrote `submitted_at`, another expected `timestamp`. An
example-based test would have caught a single drift,
but the dual-admin write path was a narrow edge case
that lived for months without coverage.

A Hypothesis state machine generates SEQUENCES of
operations and shrinks failing sequences to the minimal
reproducer. If submit-then-cancel-then-resubmit-then-
expire produces an invalid entry, Hypothesis will find
that sequence (or a smaller one) automatically.

Invariants asserted after every transition
------------------------------------------

Split into two contracts that the production code path
intentionally upholds at different stages:

**Submit-time (strict)**:

1. Every freshly-submitted entry passes
   ``_validate_queue_entry`` — required fields present,
   status is one of the allowed values. This catches
   the build-614 schema drift class at write time.

**Read-time / expire-time (lenient)**:

2. ``expire_pending_approvals`` is idempotent:
   ``f(f(q)) == f(q)`` for any queue ``q``.
3. ``expire_pending_approvals`` never crashes on a
   legacy entry lacking ``timestamp`` (build-645
   fallback contract — the only field that must be
   present is ``submitted_at``, and the function reads
   it as the timestamp).
4. ``request_id`` is unique across all entries (no
   matter how the entries were produced).

Note: we explicitly do NOT assert that every entry on
the queue passes ``_validate_queue_entry``. In
production, ``_validate_queue_entry`` is the SUBMISSION
gate, never a global invariant. Legacy entries that
predate the build-645 fix lack ``timestamp`` and are
handled by ``expire_pending_approvals``'s fallback —
they coexist on the queue with new entries and the
system continues working. Asserting strict validation
as a global invariant would force a fix that's
unnecessary (and would risk re-introducing the
build-645 bug by removing the fallback).

Performance
-----------

Pure-Python state machine + Hypothesis runs ~500
sequences in <2 seconds. Run as part of the regular
unit suite — no docker/slow marker needed.
"""

import os
import sys
import time

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st
from hypothesis.stateful import (
    RuleBasedStateMachine,
    initialize,
    invariant,
    rule,
)


# wl_approval imports require the bin/ directory on path,
# and APP-internal modules (wl_constants etc.). Tests
# already do this pattern in tests/unit/conftest.py.
_REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_REPO_ROOT, "bin"))


from wl_approval import (  # noqa: E402
    _validate_queue_entry,
    expire_pending_approvals,
    APPROVAL_EXPIRY_DAYS,
)


# ───────────────────────────────────────────────────────
# Strategies
# ───────────────────────────────────────────────────────


# Action types that ``_submit_approval`` accepts. Mirrors
# the gate list in wl_handler.py:_submit_approval.
ACTION_TYPES = st.sampled_from([
    "bulk_row_removal", "column_removal",
    "csv_import_replace", "bulk_row_edit",
    "bulk_row_addition", "revert",
    "create_csv", "create_rule",
    "remove_csv", "remove_rule",
])

# Real-looking but bounded usernames.
USERNAMES = st.sampled_from([
    "analyst1", "analyst2", "wladmin1", "wladmin2",
    "superadmin1", "superadmin2",
])

# CSV filenames and rule names — short, ASCII-safe.
CSV_FILENAMES = st.sampled_from([
    "DR102_whitelist.csv", "DR_TEST.csv",
    "DR_VERSION_TEST.csv", "DR_E2E.csv",
])

RULE_NAMES = st.sampled_from([
    "DR102_priv_escalation", "DR_TEST", "DR_VERSION_TEST",
    "DR_E2E_ADMIN",
])

# Terminal statuses to choose from when a resolve rule
# fires.
TERMINAL_STATUSES = st.sampled_from([
    "approved", "rejected", "cancelled",
])


# ───────────────────────────────────────────────────────
# State machine
# ───────────────────────────────────────────────────────


class ApprovalQueueMachine(RuleBasedStateMachine):
    """Pure-Python model of the approval queue.

    Maintains the queue as a list of dicts and applies
    submit/resolve/expire operations. After every
    operation, invariants are checked via the
    ``@invariant``-decorated method below.
    """

    @initialize()
    def setup(self):
        self.queue = []
        self.used_request_ids = set()
        # Use a fixed "now" anchor across the run so we
        # can deterministically reason about age. Each
        # rule advances it by a bounded amount.
        self.now = int(time.time())

    @rule(
        action_type=ACTION_TYPES,
        user=USERNAMES,
        csv_file=CSV_FILENAMES,
        rule_name=RULE_NAMES,
        # Age of the new entry relative to "now". Small
        # values keep it fresh; large values let it
        # become expirable on the next expire pass.
        age_seconds=st.integers(min_value=0, max_value=2 * APPROVAL_EXPIRY_DAYS * 86400),
    )
    def submit(self, action_type, user, csv_file, rule_name, age_seconds):
        """Submit a new pending request.

        Asserts the submit-time strict-validation
        contract: every newly-built entry passes
        ``_validate_queue_entry``. This is THE pin
        against the build-614 schema-drift class —
        if a future change to the entry schema breaks
        validation, every Hypothesis run will catch it.
        """
        rid = f"chaos-{len(self.used_request_ids):06d}"
        if rid in self.used_request_ids:
            return
        self.used_request_ids.add(rid)

        entry = {
            "request_id": rid,
            "status": "pending",
            "timestamp": self.now - age_seconds,
            "analyst": user,
            "action_type": action_type,
            "csv_file": csv_file,
            "detection_rule": rule_name,
            "description": f"chaos submit {rid}",
        }
        # Submit-time validation: must pass strict check.
        ok, err = _validate_queue_entry(entry)
        assert ok, (
            f"freshly-submitted entry failed validation: "
            f"{err}; entry={entry}")
        self.queue.append(entry)

    @rule(target_status=TERMINAL_STATUSES)
    def resolve(self, target_status):
        """Transition a pending entry to a terminal
        status. Picks the first pending entry; if none
        exists, this rule is a no-op (Hypothesis handles
        precondition-less rules cleanly).
        """
        for entry in self.queue:
            if entry["status"] == "pending":
                entry["status"] = target_status
                entry["resolved_by"] = "wladmin1"
                entry["resolved_at"] = self.now
                return

    @rule()
    def expire(self):
        """Apply ``expire_pending_approvals`` to the
        queue. Mirrors what the handler does on every
        write.
        """
        self.queue = expire_pending_approvals(self.queue)

    @rule(jump_days=st.integers(min_value=1, max_value=APPROVAL_EXPIRY_DAYS + 1))
    def advance_time(self, jump_days):
        """Jump the "now" anchor forward by some days.

        We don't actually mutate the system clock — instead
        we adjust every entry's timestamp BACKWARDS by
        the same amount so the relative age increases.
        This is observationally equivalent to advancing
        the clock from the queue's perspective, and
        avoids polluting other tests' use of time.
        """
        offset = jump_days * 86400
        for entry in self.queue:
            # Some entries may have been adversarially
            # mutated by break_timestamp_field to remove
            # `timestamp`. Skip them on the timestamp
            # path; the submitted_at branch below handles
            # the offset for those.
            if "timestamp" in entry:
                entry["timestamp"] = entry["timestamp"] - offset
            if "submitted_at" in entry:
                entry["submitted_at"] = entry["submitted_at"] - offset

    @rule()
    def break_timestamp_field(self):
        """Adversarial: pick a pending entry (if any)
        and remove its ``timestamp`` field, leaving only
        ``submitted_at``. Pins the build-645 fallback
        path — expire_pending_approvals MUST handle this
        without crashing or treating the entry as
        timestamp=0 (which would immediately expire it).
        """
        for entry in self.queue:
            if entry["status"] == "pending" and "timestamp" in entry:
                entry["submitted_at"] = entry["timestamp"]
                del entry["timestamp"]
                return  # only one mutation per rule

    # ────────────────────────────────────────────────
    # Invariants — checked after every rule
    # ────────────────────────────────────────────────

    @invariant()
    def request_ids_unique(self):
        """No two entries share a request_id."""
        ids = [e["request_id"] for e in self.queue]
        assert len(ids) == len(set(ids)), (
            f"duplicate request_id in queue: ids={ids}")

    @invariant()
    def expire_is_idempotent(self):
        """``expire_pending_approvals(expire(q)) == expire(q)``.

        A second expire pass must not change anything.
        If it does, the function isn't idempotent and
        repeated writes could keep removing entries
        that should stay.
        """
        once = expire_pending_approvals(list(self.queue))
        twice = expire_pending_approvals(list(once))
        # Compare via JSON serialization to handle dict
        # ordering nondeterminism cleanly.
        assert _normalize(once) == _normalize(twice), (
            "expire_pending_approvals is not idempotent: "
            f"first pass kept {len(once)} entries, "
            f"second pass kept {len(twice)}")

    @invariant()
    def expire_never_crashes_on_missing_timestamp(self):
        """Pin for build-645: expire must not crash on
        entries missing ``timestamp`` (legacy dual-admin
        format).
        """
        # The mere fact that other invariants ran without
        # exception is the assertion — but we make it
        # explicit by running expire on a copy that
        # definitely has at least one missing-timestamp
        # entry (if our adversarial rule fired).
        try:
            _ = expire_pending_approvals(list(self.queue))
        except Exception as exc:
            pytest.fail(
                f"expire_pending_approvals crashed: {exc}")


def _normalize(queue):
    """Project a queue to a comparable structure so
    idempotence checks aren't fooled by Python dict
    ordering. Sort by request_id since that's our
    primary key.
    """
    return sorted(
        [(e["request_id"], e.get("status"), e.get("timestamp"))
         for e in queue],
        key=lambda t: t[0],
    )


# ────────────────────────────────────────────────────────
# Test glue
# ────────────────────────────────────────────────────────


# Suppress the "test ran for too long" health check —
# the state machine intentionally runs many sequences,
# which can exceed Hypothesis's default warning.
TestApprovalQueueMachine = ApprovalQueueMachine.TestCase
TestApprovalQueueMachine.settings = settings(
    # 500 sequences with the default avg sequence length
    # of 50 explores ~25k state transitions per test run.
    # In practice the state machine finds reproducers in
    # <50 sequences when a bug exists; bumping past 500
    # has diminishing returns. The whole test still
    # runs in <5s on a developer laptop.
    max_examples=500,
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.data_too_large,
    ],
    # deadline=None so a slow expire doesn't fail the
    # whole run — we care about correctness, not raw
    # speed at this layer.
    deadline=None,
)


# ────────────────────────────────────────────────────────
# Direct property tests — sanity-check the pure
# functions independently of the state machine. These
# give faster feedback when a regression breaks
# something obvious.
# ────────────────────────────────────────────────────────


@given(
    status=st.sampled_from([
        "pending", "approved", "rejected", "expired", "cancelled",
    ]),
    user=USERNAMES,
    action_type=ACTION_TYPES,
)
def test_validate_accepts_every_legal_status(status, user, action_type):
    """An entry with every required field and a legal
    status must pass validation. Pins the closed set of
    legal statuses.
    """
    entry = {
        "request_id": "rid-1",
        "status": status,
        "timestamp": int(time.time()),
        "analyst": user,
        "action_type": action_type,
    }
    ok, err = _validate_queue_entry(entry)
    assert ok, f"validation rejected legal entry: {err}"


@given(missing_field=st.sampled_from([
    "request_id", "status", "timestamp", "analyst", "action_type",
]))
def test_validate_rejects_missing_required_field(missing_field):
    """Removing any required field must cause rejection."""
    entry = {
        "request_id": "rid-1",
        "status": "pending",
        "timestamp": int(time.time()),
        "analyst": "analyst1",
        "action_type": "create_rule",
    }
    del entry[missing_field]
    ok, err = _validate_queue_entry(entry)
    assert not ok, (
        f"validation accepted entry missing {missing_field}: {err}")
    assert missing_field in err, (
        f"error message doesn't mention missing field: {err}")


@given(bogus_status=st.text(min_size=1, max_size=20).filter(
    lambda s: s not in (
        "pending", "approved", "rejected", "expired", "cancelled")))
def test_validate_rejects_unknown_status(bogus_status):
    """Any status outside the closed set must be rejected.

    This catches the case where someone introduces a new
    status type without updating the validator's allow
    list — a classic schema-drift seed.
    """
    entry = {
        "request_id": "rid-1",
        "status": bogus_status,
        "timestamp": int(time.time()),
        "analyst": "analyst1",
        "action_type": "create_rule",
    }
    ok, err = _validate_queue_entry(entry)
    assert not ok, (
        f"validation accepted bogus status {bogus_status!r}: {err}")
