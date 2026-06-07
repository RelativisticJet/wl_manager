"""
Hypothesis-based fuzz tests for the ASCII validators.

Goal: throw thousands of random inputs at the validators and confirm:
- They never crash on weird input (stability)
- They obey their documented contracts (no surprising acceptances)
- They're deterministic (same input → same output)

Hypothesis is a property-based testing library that generates inputs
based on strategies (text, integers, lists, etc.) with built-in
shrinking — when a failure is found, hypothesis reduces it to the
minimal failing case.

Origin: round 5 audit, 2026-04-29.
"""

import os
import string
import sys

import pytest
from hypothesis import given, settings, strategies as st, assume

_BIN = os.path.join(os.path.dirname(__file__), "..", "..", "bin")
sys.path.insert(0, os.path.abspath(_BIN))

from wl_validation import (  # noqa: E402
    is_ascii_name,
    is_safe_filename,
    is_valid_app_context,
    sanitize_text,
    validate_ascii_text,
    build_csv_path,
)


# ─────────────────────────────────────────────────────────────────────────
# Stability — none of the validators should ever raise on any input
# ─────────────────────────────────────────────────────────────────────────

class TestStability:
    """Validators must be total functions: no input should make them raise.
    The test fails if hypothesis finds ANY input that crashes the validator.
    """

    @settings(max_examples=1000)
    @given(st.text())
    def test_is_ascii_name_never_raises(self, text):
        is_ascii_name(text)
        is_ascii_name(text, allow_spaces=False)

    @settings(max_examples=1000)
    @given(st.text())
    def test_is_safe_filename_never_raises(self, text):
        is_safe_filename(text)

    @settings(max_examples=1000)
    @given(st.text())
    def test_is_valid_app_context_never_raises(self, text):
        is_valid_app_context(text)

    @settings(max_examples=1000)
    @given(st.text())
    def test_validate_ascii_text_never_raises(self, text):
        validate_ascii_text(text)

    @settings(max_examples=1000)
    @given(st.text())
    def test_sanitize_text_never_raises(self, text):
        sanitize_text(text)

    @settings(max_examples=1000)
    @given(st.text())
    def test_build_csv_path_never_raises(self, text):
        # build_csv_path may return None (invalid filename) — but never raise
        build_csv_path(text)
        build_csv_path(text, app_context="wl_manager")

    @settings(max_examples=400)
    @given(st.one_of(
        st.none(),
        st.integers(),
        st.lists(st.text()),
        st.dictionaries(st.text(), st.text()),
        st.binary(),
    ))
    def test_validators_handle_non_string_types(self, value):
        # Should return False / None / "" without raising — the type
        # mismatch is a legitimate input from REST clients sending JSON
        # arrays/objects/numbers where strings are expected.
        is_ascii_name(value)
        is_safe_filename(value)
        is_valid_app_context(value)
        # validate_ascii_text and sanitize_text return None / "" for
        # non-strings (verified by existing tests; just confirm no raise)
        validate_ascii_text(value)
        sanitize_text(value)


# ─────────────────────────────────────────────────────────────────────────
# Contract — accepted strings always re-validate the same way
# ─────────────────────────────────────────────────────────────────────────

class TestDeterminism:
    """Same input → same output, every time. Catches accidental
    statefulness or use of `random` etc."""

    @settings(max_examples=600)
    @given(st.text())
    def test_is_ascii_name_deterministic(self, text):
        first = is_ascii_name(text)
        second = is_ascii_name(text)
        assert first == second, "is_ascii_name returned different results for same input!"

    @settings(max_examples=600)
    @given(st.text())
    def test_is_safe_filename_deterministic(self, text):
        first = is_safe_filename(text)
        second = is_safe_filename(text)
        assert first == second


# ─────────────────────────────────────────────────────────────────────────
# Contract — accepted ASCII names are pure ASCII
# ─────────────────────────────────────────────────────────────────────────

class TestAcceptedInputsAreASCII:
    """Any string accepted by is_ascii_name must contain only the
    documented allowed characters. If hypothesis can find an
    accepted string with disallowed chars, the regex is broken."""

    ALLOWED_RULE_CHARS = set(string.ascii_letters + string.digits + "_-. ")
    ALLOWED_FILENAME_STEM_CHARS = set(string.ascii_letters + string.digits + "_-")

    @settings(max_examples=1000)
    @given(st.text())
    def test_accepted_rule_names_only_allowed_chars(self, text):
        if is_ascii_name(text, allow_spaces=True):
            for c in text:
                assert c in self.ALLOWED_RULE_CHARS, (
                    "is_ascii_name accepted {!r} containing disallowed "
                    "char {!r} (codepoint U+{:04X})".format(
                        text, c, ord(c)))

    @settings(max_examples=1000)
    @given(st.text())
    def test_accepted_filename_stems_only_allowed_chars(self, text):
        if is_ascii_name(text, allow_spaces=False):
            for c in text:
                assert c in self.ALLOWED_FILENAME_STEM_CHARS, (
                    "is_ascii_name(allow_spaces=False) accepted {!r} "
                    "containing disallowed char {!r}".format(text, c))

    @settings(max_examples=1000)
    @given(st.text())
    def test_accepted_app_contexts_only_allowed_chars(self, text):
        if is_valid_app_context(text) and text:
            # Empty is also valid (caller substitutes default)
            allowed = set(string.ascii_letters + string.digits + "_-")
            assert len(text) <= 100
            for c in text:
                assert c in allowed, (
                    "is_valid_app_context accepted {!r} containing "
                    "disallowed char {!r}".format(text, c))


# ─────────────────────────────────────────────────────────────────────────
# Contract — sanitize_text invariants
# ─────────────────────────────────────────────────────────────────────────

class TestSanitizeTextInvariants:
    """sanitize_text contract:
    1. Returns a string (never None for string input)
    2. Length ≤ max_length
    3. No leading/trailing whitespace (collapsed + stripped)
    4. No internal whitespace runs longer than 1 char
    5. No control characters (\\n, \\r, \\t etc. become single space)
    """

    @settings(max_examples=1000)
    @given(st.text())
    def test_returns_string(self, text):
        result = sanitize_text(text)
        assert isinstance(result, str)

    @settings(max_examples=1000)
    @given(st.text(), st.integers(min_value=1, max_value=10000))
    def test_respects_max_length(self, text, max_length):
        result = sanitize_text(text, max_length=max_length)
        assert len(result) <= max_length

    @settings(max_examples=1000)
    @given(st.text())
    def test_no_leading_trailing_whitespace(self, text):
        result = sanitize_text(text)
        if result:  # empty string trivially satisfies
            assert result == result.strip(), (
                "sanitize_text returned untrimmed: {!r}".format(result))

    @settings(max_examples=1000)
    @given(st.text())
    def test_no_doubled_whitespace(self, text):
        result = sanitize_text(text)
        assert "  " not in result, (
            "sanitize_text left double-space in: {!r}".format(result))

    @settings(max_examples=1000)
    @given(st.text())
    def test_no_newlines_or_tabs(self, text):
        # Defense: sanitize is the last layer before audit emission.
        # If \n or \t survive, log injection becomes possible.
        result = sanitize_text(text)
        assert "\n" not in result, "sanitize_text left newline in: {!r}".format(result)
        assert "\r" not in result
        assert "\t" not in result


# ─────────────────────────────────────────────────────────────────────────
# Cross-validator consistency
# ─────────────────────────────────────────────────────────────────────────

class TestCrossValidatorConsistency:
    """Where validators overlap, they must agree."""

    @settings(max_examples=600)
    @given(st.text(min_size=1))
    def test_safe_filename_implies_ascii_stem(self, stem):
        # Build a .csv filename and check the cross-validator invariant.
        # We prepend the stem to ".csv" rather than filtering random
        # text for ".csv" endings (hypothesis dislikes high filter rates).
        name = stem + ".csv"
        if is_safe_filename(name):
            # is_ascii_name(allow_spaces=False) is the equivalent
            # check at the stem level.
            assert is_ascii_name(stem, allow_spaces=False), (
                "is_safe_filename accepted {!r} but stem {!r} fails "
                "is_ascii_name(allow_spaces=False)".format(name, stem))

    @settings(max_examples=600)
    @given(st.text())
    def test_ascii_text_consistent_with_ascii_name(self, text):
        # If is_ascii_name accepts a string, validate_ascii_text must
        # also return None (they both reject non-ASCII).
        if is_ascii_name(text):
            err = validate_ascii_text(text)
            assert err is None, (
                "is_ascii_name accepted {!r} but validate_ascii_text "
                "rejected with {!r}".format(text, err))
