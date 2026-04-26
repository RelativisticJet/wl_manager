"""
Unit tests for ASCII-only validators in bin/wl_validation.py.

Origin: 2026-04-26 — stress test accidentally allowed `DR_压力测试_检...`
through both the create_rule and create_csv submission paths, plus the
approval reason field accepted Russian/Chinese/etc. The frontend was
correct (regex blocked non-ASCII at submit time) but the backend used
Python's c.isalnum() which is Unicode-aware and accepts CJK ideographs,
Cyrillic, Greek, etc. as "letters". An attacker (or anyone with curl)
could bypass the frontend.

These tests pin the new ASCII-strict behavior so future refactors
don't silently relax the policy.
"""

import os
import sys

import pytest

# Add bin/ to path so we can import wl_validation directly
_BIN = os.path.join(os.path.dirname(__file__), "..", "..", "bin")
sys.path.insert(0, os.path.abspath(_BIN))

from wl_validation import (  # noqa: E402
    is_ascii_name,
    is_safe_filename,
    validate_ascii_text,
)


# ─────────────────────────────────────────────────────────────────────────
# is_ascii_name
# ─────────────────────────────────────────────────────────────────────────

class TestIsAsciiName:
    """is_ascii_name() — used for detection rule names + CSV filename stems."""

    def test_accepts_pure_ascii_alphanumeric(self):
        assert is_ascii_name("DR102_powershell")
        assert is_ascii_name("rule_42")
        assert is_ascii_name("AaZz09")

    def test_accepts_allowed_punctuation(self):
        assert is_ascii_name("DR_BLOCKED-test.case")
        assert is_ascii_name("rule with spaces")  # spaces allowed by default
        assert is_ascii_name("DR_v1.2.3")

    def test_rejects_cjk_ideographs(self):
        # Origin bug 2026-04-26: c.isalnum() accepted these
        assert not is_ascii_name("DR_压力测试")
        assert not is_ascii_name("DR_检测")
        assert not is_ascii_name("規則名_DR")
        assert not is_ascii_name("ルール")

    def test_rejects_cyrillic(self):
        assert not is_ascii_name("DR_правило")  # Russian
        assert not is_ascii_name("Тест")

    def test_rejects_greek(self):
        assert not is_ascii_name("DR_κανόνας")
        assert not is_ascii_name("Δοκιμή")

    def test_rejects_arabic_rtl(self):
        assert not is_ascii_name("DR_قاعدة")

    def test_rejects_emoji_and_symbols(self):
        assert not is_ascii_name("DR_test_🔥")
        assert not is_ascii_name("rule​_zero_width_space")  # homoglyph attack
        assert not is_ascii_name("rule nbsp")  # non-breaking space

    def test_rejects_disallowed_ascii_punctuation(self):
        # ASCII but not in the allowed set
        assert not is_ascii_name("rule!exclaim")
        assert not is_ascii_name("rule@at")
        assert not is_ascii_name("rule/slash")
        assert not is_ascii_name("rule\\backslash")
        assert not is_ascii_name("rule;semicolon")

    def test_rejects_empty(self):
        assert not is_ascii_name("")
        assert not is_ascii_name(None)

    def test_rejects_non_string(self):
        assert not is_ascii_name(123)
        assert not is_ascii_name(["DR"])

    def test_allow_spaces_false(self):
        # CSV filename stem context — spaces not allowed
        assert is_ascii_name("DR_no_spaces", allow_spaces=False)
        assert not is_ascii_name("DR with spaces", allow_spaces=False)
        # But also: dots not in the no-spaces variant
        assert not is_ascii_name("DR.dotted", allow_spaces=False)


# ─────────────────────────────────────────────────────────────────────────
# is_safe_filename — tightened for ASCII at the same time
# ─────────────────────────────────────────────────────────────────────────

class TestIsSafeFilename:
    """is_safe_filename() — also tightened to reject non-ASCII filenames."""

    def test_accepts_normal_csv(self):
        assert is_safe_filename("DR102_powershell.csv")
        assert is_safe_filename("rule_42.csv")

    def test_rejects_cjk_in_filename(self):
        # Origin bug 2026-04-26: c.isalnum() in is_safe_filename accepted CJK
        assert not is_safe_filename("DR_压力测试.csv")
        assert not is_safe_filename("検出ルール.csv")

    def test_rejects_path_traversal(self):
        assert not is_safe_filename("../etc/passwd.csv")
        assert not is_safe_filename("foo/bar.csv")
        assert not is_safe_filename("foo\\bar.csv")

    def test_rejects_dotfile(self):
        assert not is_safe_filename(".hidden.csv")

    def test_rejects_wrong_extension(self):
        assert not is_safe_filename("rule.txt")
        assert not is_safe_filename("rule.json")
        assert not is_safe_filename("rule")

    def test_requires_ascii_alphanumeric_in_stem(self):
        # Stem must contain at least one ASCII a-z/A-Z/0-9
        assert not is_safe_filename("___.csv")  # all underscores, no alnum
        assert not is_safe_filename("---.csv")
        # But this is fine
        assert is_safe_filename("a.csv")
        assert is_safe_filename("DR1.csv")


# ─────────────────────────────────────────────────────────────────────────
# validate_ascii_text — used on reason/comment/description fields
# ─────────────────────────────────────────────────────────────────────────

class TestValidateAsciiText:
    """validate_ascii_text() — returns error string if non-ASCII present."""

    def test_returns_none_for_pure_ascii(self):
        assert validate_ascii_text("Plain ASCII reason text.") is None
        assert validate_ascii_text("Multi-line\nreason\nwith\ttabs.") is None

    def test_returns_error_for_cjk(self):
        # Origin bug 2026-04-26: this WAS NOT BEING CALLED on remove_csv
        # comment, remove_rule comment, or _submit_create_delete_approval
        # reason — analyst could submit "理由：测试" and it would store.
        err = validate_ascii_text("理由：测试")
        assert err is not None
        assert "ASCII" in err

    def test_returns_error_for_emoji(self):
        assert validate_ascii_text("Rejected 🚫") is not None

    def test_returns_error_for_zero_width_space(self):
        # Homoglyph / hidden-char defense
        assert validate_ascii_text("hidden​zwsp") is not None
        assert validate_ascii_text("hidden nbsp") is not None

    def test_returns_none_for_empty_or_none(self):
        # Empty input is valid (means user provided nothing — separate
        # check enforces required-ness; charset check is permissive here)
        assert validate_ascii_text("") is None
        assert validate_ascii_text(None) is None

    def test_returns_none_for_non_string(self):
        # Be tolerant of unexpected types — the calling site has its own
        # type check; this validator should not blow up
        assert validate_ascii_text(123) is None
        assert validate_ascii_text({"key": "value"}) is None
