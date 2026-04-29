"""
Frontend ↔ backend ASCII regex parity tests.

Goal: detect drift between the JavaScript validators in
appserver/static/modules/wl_constants.js (and inline regexes in
wl_modals.js / wl_table.js) and the Python validators in bin/wl_validation.py.

Why this matters: if the frontend accepts a character the backend rejects,
the user gets a confusing 400 error after a working-looking submission.
If the backend accepts a character the frontend rejects, the user can't
submit it via UI but a curl call still works — usually a non-issue, but
worth surfacing.

These tests load the JS source as TEXT, extract the regex literals,
and compare match behavior against representative inputs. We don't
parse JS; we just regex-extract the regex source and run it through
Python's `re` module (PCRE-compatible enough for these character
classes).

Origin: round 4 audit, 2026-04-29.
"""

import os
import re
import sys

import pytest

_BIN = os.path.join(os.path.dirname(__file__), "..", "..", "bin")
sys.path.insert(0, os.path.abspath(_BIN))

from wl_validation import (  # noqa: E402
    is_ascii_name,
    is_safe_filename,
    validate_ascii_text,
)
from wl_constants import _SAFE_COLNAME_RE  # noqa: E402


_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_JS_CONSTANTS = os.path.join(
    _REPO_ROOT, "appserver", "static", "modules", "wl_constants.js")
_JS_MODALS = os.path.join(
    _REPO_ROOT, "appserver", "static", "modules", "wl_modals.js")


def _read_file(path):
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def _extract_js_regex(source, var_name):
    """Pull a regex literal out of a `KEY: /pattern/flags` or
    `var KEY = /pattern/flags;` form. Returns the raw pattern string
    (without the slashes). Returns None if not found.

    We only need the pattern body — flags don't matter for these
    character-class checks.
    """
    # Match either `VAR_NAME: /.../flags` (object literal) or
    # `var VAR_NAME = /.../flags;` (top-level)
    patterns = [
        r"%s\s*:\s*/(.+?)/[gimsuy]*\s*[,}]" % re.escape(var_name),
        r"var\s+%s\s*=\s*/(.+?)/[gimsuy]*\s*[;]" % re.escape(var_name),
    ]
    for p in patterns:
        m = re.search(p, source)
        if m:
            return m.group(1)
    return None


# ─────────────────────────────────────────────────────────────────────────
# NON_ASCII_RE parity (used on reason / comment text fields)
# ─────────────────────────────────────────────────────────────────────────

class TestNonAsciiReParity:
    """Frontend NON_ASCII_RE in wl_constants.js must match Python's
    validate_ascii_text behavior for character-rejection."""

    @pytest.fixture(scope="class")
    def js_pattern(self):
        src = _read_file(_JS_CONSTANTS)
        return _extract_js_regex(src, "NON_ASCII_RE")

    def test_js_pattern_extracted(self, js_pattern):
        assert js_pattern is not None, \
            "Could not find NON_ASCII_RE in wl_constants.js — has the " \
            "constant been renamed or moved?"

    def test_js_pattern_matches_python(self, js_pattern):
        # Both sides should use the same pattern: [^\x00-\x7F]
        # (Python: r'[^\x00-\x7F]', JS: /[^\x00-\x7F]/)
        # We compare the literal pattern body.
        expected = r"[^\x00-\x7F]"
        assert js_pattern == expected, (
            "Frontend NON_ASCII_RE pattern '{}' diverged from backend "
            "expected '{}'. If the backend pattern in wl_validation.py "
            "_NON_ASCII_RE has changed, update this test AND verify the "
            "JS-side regex matches.".format(js_pattern, expected))

    @pytest.mark.parametrize("text", [
        "Plain ASCII",
        "理由：测试",
        "Rejected 🚫",
        "hidden​zwsp",
        "rule_правило",
        "",
    ])
    def test_behavior_parity(self, js_pattern, text):
        """For every test input, the JS pattern (as Python re) and the
        Python validate_ascii_text should agree on accept/reject."""
        py_re = re.compile(js_pattern)
        # JS .test() === Python re.search() != None
        js_says_non_ascii = py_re.search(text) is not None
        py_err = validate_ascii_text(text)
        py_says_non_ascii = py_err is not None
        assert js_says_non_ascii == py_says_non_ascii, (
            "JS regex says non-ASCII={}, Python says non-ASCII={}, "
            "for input {!r}".format(
                js_says_non_ascii, py_says_non_ascii, text))


# ─────────────────────────────────────────────────────────────────────────
# Detection rule name regex parity (wl_modals.js inline)
# ─────────────────────────────────────────────────────────────────────────

class TestRuleNameRegexParity:
    """The inline /[^a-zA-Z0-9_\\-. ]/ test in wl_modals.js (line ~293)
    must accept exactly the same names as is_ascii_name(allow_spaces=True).
    """

    # JS literal: /[^a-zA-Z0-9_\-. ]/.test(name) — true if any char NOT in set
    # Python equivalent: not re.match(r'^[A-Za-z0-9_\-. ]+$', name)
    JS_NEGATED_PATTERN = r"[^a-zA-Z0-9_\-. ]"

    @pytest.mark.parametrize("name,expected_valid", [
        ("DR102_powershell", True),
        ("DR_BLOCKED-test.case", True),
        ("rule with spaces", True),
        ("DR_压力测试", False),
        ("DR_правило", False),
        ("rule!exclaim", False),
        ("rule@at", False),
        ("rule\nwith\nnewlines", False),
        ("", False),
        ("   ", False),
    ])
    def test_parity(self, name, expected_valid):
        """JS-style negated test plus alphanumeric requirement should
        match is_ascii_name's result.

        Frontend wl_modals.js does TWO checks:
          1. /[^a-zA-Z0-9_\\-. ]/.test(name) — fails if any non-allowed
          2. /[a-zA-Z0-9]/.test(name) — fails if no alphanumeric
          (And `.trim()` + `if (!name)` for the empty case)
        """
        # Simulate frontend's full check
        trimmed = name.strip()
        if not trimmed:
            js_valid = False
        elif re.search(self.JS_NEGATED_PATTERN, trimmed):
            js_valid = False  # has disallowed char
        elif not re.search(r"[a-zA-Z0-9]", trimmed):
            js_valid = False  # no alphanumeric
        else:
            js_valid = True

        py_valid = is_ascii_name(name.strip())  # backend pre-trims at gate
        assert js_valid == expected_valid, (
            "JS frontend says valid={}, expected={}, for {!r}".format(
                js_valid, expected_valid, name))
        assert py_valid == expected_valid, (
            "Python is_ascii_name says valid={}, expected={}, for {!r}"
            .format(py_valid, expected_valid, name))


# ─────────────────────────────────────────────────────────────────────────
# SAFE_COLNAME_RE parity (wl_constants.js mirrors wl_constants.py)
# ─────────────────────────────────────────────────────────────────────────

class TestSafeColnameReParity:
    """SAFE_COLNAME_RE must match between Python and JS sources."""

    @pytest.fixture(scope="class")
    def js_pattern(self):
        src = _read_file(_JS_CONSTANTS)
        return _extract_js_regex(src, "SAFE_COLNAME_RE")

    def test_js_pattern_extracted(self, js_pattern):
        assert js_pattern is not None

    def test_character_set_matches(self, js_pattern):
        # JS: ^(?=.*[a-zA-Z0-9])[a-zA-Z0-9_\-.()\/:&#@+]+$
        # Py: ^(?=.*[a-zA-Z0-9])[a-zA-Z0-9_\-\.()/:#@&+]+$
        # Differences that DON'T matter:
        #   - Char order inside [...] class
        #   - / vs \/ (JS escapes literal /; Python doesn't need to)
        #   - . vs \. (Python may escape; both work the same INSIDE [...])
        # Compare by extracting the second-class character set ([...]+$
        # at the end) and confirming the sets are equal.
        py_pattern = _SAFE_COLNAME_RE.pattern

        def extract_main_class(p):
            # Pull the second [...] block (the one quantified with +)
            m = re.search(r"\[([^\]]+)\]\+\$", p)
            assert m, "could not find main char class in: " + p
            chars = m.group(1)
            # Drop escape backslashes (\/, \., \-) — they're cosmetic
            # in a character class.
            chars = chars.replace("\\/", "/").replace("\\.", ".")
            chars = chars.replace("\\-", "-")
            return frozenset(chars)

        js_set = extract_main_class(js_pattern)
        py_set = extract_main_class(py_pattern)
        assert js_set == py_set, (
            "JS SAFE_COLNAME_RE chars {} diverged from Python {}"
            .format(sorted(js_set), sorted(py_set)))

    @pytest.mark.parametrize("colname,expected_valid", [
        ("src_ip", True),
        ("dest-port", True),
        ("col(1)", True),
        ("colWith#hash", True),
        ("源IP", False),
        ("col 空格", False),
        ("___", False),  # No alphanumeric
        ("col\x00", False),  # Null byte
        ("col\nnewline", False),
        ("", False),
    ])
    def test_behavior_parity(self, js_pattern, colname, expected_valid):
        # Bridge JS regex syntax to Python re
        py_eq = re.compile(js_pattern.replace("\\/", "/"))
        js_valid = bool(py_eq.match(colname))
        py_valid = bool(_SAFE_COLNAME_RE.match(colname))
        assert js_valid == expected_valid, \
            "JS regex valid={} expected={} for {!r}".format(
                js_valid, expected_valid, colname)
        assert py_valid == expected_valid, \
            "Python regex valid={} expected={} for {!r}".format(
                py_valid, expected_valid, colname)
