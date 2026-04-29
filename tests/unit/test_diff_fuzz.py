"""
Hypothesis-based fuzz tests for ``wl_csv.compute_diff``.

The diff engine is the most complex pure-Python in the handler:
similarity-based matching, Counter-based duplicate handling, and
the position-shift logic that took several rounds to get right
(see CLAUDE.md ``MEMORY.md`` notes — sets-vs-Counter bug, duplicate
row identity bug, position-iteration bug, etc.).

Fuzz invariants exercised here:

1. **Identity** — diff(headers, rows, headers, rows) is empty.
2. **Conservation** — ``len(new) == len(old) - len(removed_raw) + len(added_raw)``
   where ``removed_raw = removed + edited`` and ``added_raw = added + edited``.
3. **Append-only** — adding one row to the end produces exactly one
   ``added`` and nothing else.
4. **Delete-only** — removing one row produces exactly one ``removed``
   and nothing else.
5. **No-op reorder** — permuting rows produces 0 added / 0 removed / 0
   edited (since the diff is Counter-based, position is irrelevant).
6. **Determinism** — same input → same output.
7. **No double-classification** — no row dict appears in BOTH ``added``
   and ``removed`` (would be an internal bug).
8. **Edit pairs are well-formed** — every edit has non-None
   ``old_row``/``new_row`` and at least one ``changed_fields``.
9. **Header subsetting safety** — diff still functions when headers
   differ (some columns added, some removed) without raising.

Origin: round 6 audit, 2026-04-29. The diff engine had multiple
historical bugs that line-by-line review missed; property-based
testing is well-suited to its combinatorial input space.
"""

import os
import string
import sys

import pytest
from hypothesis import given, settings, strategies as st, assume, HealthCheck

_BIN = os.path.join(os.path.dirname(__file__), "..", "..", "bin")
sys.path.insert(0, os.path.abspath(_BIN))

from wl_csv import compute_diff  # noqa: E402


# ─────────────────────────────────────────────────────────────────
# Strategies
# ─────────────────────────────────────────────────────────────────

# Cell text — keep ASCII to focus the fuzz on diff logic, not on
# Unicode handling (which test_validator_fuzz.py covers).
_cell = st.text(
    alphabet=string.ascii_letters + string.digits + " _-.",
    min_size=0, max_size=8)


@st.composite
def header_set(draw):
    """Generate a small unique-header list (1-4 columns).

    Excludes headers starting with ``_`` because compute_diff filters
    those as metadata columns and would skip them from the row-match
    logic — making the test confusing rather than catching real bugs.
    """
    return draw(st.lists(
        st.text(
            alphabet=string.ascii_letters + string.digits,
            min_size=1, max_size=6),
        min_size=1, max_size=4, unique=True))


@st.composite
def csv_pair_random(draw):
    """A pair of (old_rows, new_rows) over a shared header set,
    generated independently. Tests robustness on uncorrelated
    inputs."""
    headers = draw(header_set())
    n_old = draw(st.integers(min_value=0, max_value=12))
    n_new = draw(st.integers(min_value=0, max_value=12))

    def _gen_row():
        return {h: draw(_cell) for h in headers}

    old = [_gen_row() for _ in range(n_old)]
    new = [_gen_row() for _ in range(n_new)]
    return headers, old, new


@st.composite
def csv_pair_mutated(draw):
    """A more realistic pair: start from a base CSV, then apply
    random mutations. This exercises the diff logic in a way that
    matches actual user behavior (most rows kept, some added/
    removed/edited)."""
    headers = draw(header_set())
    n = draw(st.integers(min_value=0, max_value=10))

    def _gen_row():
        return {h: draw(_cell) for h in headers}

    base = [_gen_row() for _ in range(n)]
    new = [dict(r) for r in base]  # copy

    # 0..3 random mutations.
    n_muts = draw(st.integers(min_value=0, max_value=3))
    for _ in range(n_muts):
        op = draw(st.sampled_from(["add", "remove", "edit"]))
        if op == "add":
            new.append(_gen_row())
        elif op == "remove" and new:
            i = draw(st.integers(min_value=0, max_value=len(new) - 1))
            new.pop(i)
        elif op == "edit" and new:
            i = draw(st.integers(min_value=0, max_value=len(new) - 1))
            target = new[i]
            if headers:
                col = draw(st.sampled_from(headers))
                target[col] = draw(_cell)
    return headers, base, new


# ─────────────────────────────────────────────────────────────────
# Invariants
# ─────────────────────────────────────────────────────────────────

class TestComputeDiffStability:
    """The function must NEVER raise on any input."""

    @settings(
        max_examples=300,
        suppress_health_check=[HealthCheck.too_slow],
    )
    @given(csv_pair_random())
    def test_random_pairs_never_raise(self, fixture):
        headers, old, new = fixture
        compute_diff(headers, old, headers, new)

    @settings(max_examples=300)
    @given(csv_pair_mutated())
    def test_mutated_pairs_never_raise(self, fixture):
        headers, old, new = fixture
        compute_diff(headers, old, headers, new)

    @settings(max_examples=200)
    @given(header_set(), header_set(),
           st.lists(st.dictionaries(
               st.text(min_size=1, max_size=6),
               _cell, max_size=4),
               max_size=8),
           st.lists(st.dictionaries(
               st.text(min_size=1, max_size=6),
               _cell, max_size=4),
               max_size=8))
    def test_different_headers_never_raise(
            self, h_old, h_new, rows_old, rows_new):
        # Even when old and new have different schemas, the diff
        # must not raise. (Production handler code disallows this
        # case at the gate; the engine should still be robust.)
        compute_diff(h_old, rows_old, h_new, rows_new)


class TestComputeDiffIdentity:
    """diff(x, x) is the empty diff."""

    @settings(max_examples=200)
    @given(csv_pair_mutated())
    def test_self_diff_is_empty(self, fixture):
        headers, rows, _ = fixture
        result = compute_diff(headers, rows, headers, rows)
        assert result["added_count"] == 0, (
            "self-diff produced phantom added: " + repr(result))
        assert result["removed_count"] == 0
        assert result["edited_count"] == 0
        assert result["added"] == []
        assert result["removed"] == []
        assert result["edited"] == []

    @settings(max_examples=100)
    @given(csv_pair_mutated())
    def test_self_diff_no_column_changes(self, fixture):
        headers, rows, _ = fixture
        result = compute_diff(headers, rows, headers, rows)
        assert result["added_columns"] == []
        assert result["removed_columns"] == []


class TestComputeDiffConservation:
    """Row count math must balance.

    ``len(new) == len(old) - removed_raw + added_raw``
    where ``removed_raw = removed + edited`` (each edit consumed an
    old row) and ``added_raw = added + edited`` (each edit produced
    a new row).
    """

    @settings(max_examples=300)
    @given(csv_pair_mutated())
    def test_row_count_balances(self, fixture):
        headers, old, new = fixture
        result = compute_diff(headers, old, headers, new)
        added_raw = result["added_count"] + result["edited_count"]
        removed_raw = result["removed_count"] + result["edited_count"]
        # The diff folds same-keyed kept rows out before pairing,
        # so the equation only holds when no metadata columns
        # asymmetrically affect the visible-key set. Since our
        # strategy never emits ``_``-prefixed headers, this is a
        # clean assertion:
        assert len(new) - len(old) == added_raw - removed_raw, (
            "conservation failed: "
            "len(new)={} len(old)={} added_raw={} removed_raw={} "
            "result={}".format(
                len(new), len(old), added_raw, removed_raw, result))


class TestComputeDiffAppendOnly:
    """Adding a row at the END produces exactly 1 added + nothing
    else (provided the appended row's visible-key isn't already
    duplicated in the base — in which case Counter-based matching
    would correctly see no net new row, but the test would be
    misleading)."""

    @settings(max_examples=200)
    @given(csv_pair_mutated(), _cell)
    def test_append_one_row(self, fixture, junk):
        headers, base, _ = fixture
        if not headers:
            return
        # Build a new row that is GUARANTEED unique against base —
        # use the junk text in EVERY column so no chance of
        # accidental match.
        unique_row = {h: junk + "@" + h for h in headers}
        new = list(base) + [unique_row]
        result = compute_diff(headers, base, headers, new)
        assert result["added_count"] == 1, (
            "expected 1 added, got: " + repr(result))
        assert result["removed_count"] == 0
        assert result["edited_count"] == 0


class TestComputeDiffDeleteOnly:
    """Removing one existing row produces exactly 1 removed +
    nothing else (subject to the same uniqueness caveat as append)."""

    @settings(max_examples=200)
    @given(csv_pair_mutated())
    def test_remove_one_unique_row(self, fixture):
        headers, base, _ = fixture
        if len(base) < 2:
            return
        # Find a row whose visible-key is unique in base — only
        # then is its removal unambiguously a single deletion.
        from collections import Counter
        keys = Counter(
            tuple(r.get(h, "") for h in headers) for r in base)
        unique_idx = None
        for i, r in enumerate(base):
            k = tuple(r.get(h, "") for h in headers)
            if keys[k] == 1:
                unique_idx = i
                break
        if unique_idx is None:
            return
        new = base[:unique_idx] + base[unique_idx + 1:]
        result = compute_diff(headers, base, headers, new)
        assert result["removed_count"] == 1
        assert result["added_count"] == 0
        assert result["edited_count"] == 0


class TestComputeDiffNoOpReorder:
    """compute_diff is Counter-based, so a pure permutation of rows
    must produce zero diffs."""

    @settings(max_examples=200)
    @given(csv_pair_mutated(), st.randoms())
    def test_reordered_rows_produce_no_diff(self, fixture, rng):
        headers, base, _ = fixture
        if len(base) < 2:
            return
        permuted = list(base)
        rng.shuffle(permuted)
        if permuted == base:
            return  # not a real permutation
        result = compute_diff(headers, base, headers, permuted)
        assert result["added_count"] == 0, (
            "phantom add on pure reorder: " + repr(result))
        assert result["removed_count"] == 0
        assert result["edited_count"] == 0


class TestComputeDiffDeterminism:
    """Same input → same output every time."""

    @settings(max_examples=200)
    @given(csv_pair_mutated())
    def test_determinism(self, fixture):
        headers, old, new = fixture
        a = compute_diff(headers, old, headers, new)
        b = compute_diff(headers, old, headers, new)
        assert a["added_count"] == b["added_count"]
        assert a["removed_count"] == b["removed_count"]
        assert a["edited_count"] == b["edited_count"]
        # Spot-check structural fields too (lists may have been
        # built in different orders — accept either by sorting)
        assert sorted(repr(r) for r in a["added"]) == \
               sorted(repr(r) for r in b["added"])
        assert sorted(repr(r) for r in a["removed"]) == \
               sorted(repr(r) for r in b["removed"])


class TestComputeDiffNoDoubleClassification:
    """No single row should appear in BOTH ``added`` and
    ``removed`` outputs — that would be a logic error."""

    @settings(max_examples=200)
    @given(csv_pair_mutated())
    def test_added_and_removed_are_disjoint(self, fixture):
        headers, old, new = fixture
        result = compute_diff(headers, old, headers, new)
        # Compare by serialized content (rows are dicts so they
        # need a stable serialization for set ops).
        added_keys = [
            tuple(sorted(r.items())) for r in result["added"]]
        removed_keys = [
            tuple(sorted(r.items())) for r in result["removed"]]
        # Even if added==removed by value, they should not be the
        # SAME row dict instance — and since we already moved
        # all kept rows out, ANY overlap in serialized content
        # indicates the diff failed to recognize an edit.
        # (NB: this is strict — the diff engine is supposed to
        # collapse "row removed and the same row re-added" into
        # neither side, since the key counts cancel.)
        added_set = set(added_keys)
        removed_set = set(removed_keys)
        overlap = added_set & removed_set
        assert not overlap, (
            "row appears in both added and removed: " + repr(overlap))


class TestComputeDiffEditPairsWellFormed:
    """Every edit must have non-empty old_row, new_row, and at
    least one changed field."""

    @settings(max_examples=200)
    @given(csv_pair_mutated())
    def test_edit_pairs_have_both_sides(self, fixture):
        headers, old, new = fixture
        result = compute_diff(headers, old, headers, new)
        for edit in result["edited"]:
            assert edit.get("old_row") is not None, repr(edit)
            assert edit.get("new_row") is not None, repr(edit)
            # An edit by definition has at least one differing
            # visible field (otherwise it's a kept row).
            assert edit.get("changed_fields"), (
                "edit with no changed_fields: " + repr(edit))
