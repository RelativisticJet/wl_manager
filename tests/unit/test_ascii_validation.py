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
    is_valid_app_context,
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


# ─────────────────────────────────────────────────────────────────────────
# is_valid_app_context — used at every site that joins app_context into
# etc/apps/<app_context>/lookups/... filesystem paths
# ─────────────────────────────────────────────────────────────────────────

class TestIsValidAppContext:
    """is_valid_app_context() — Splunk app names join into FS paths."""

    def test_accepts_typical_splunk_app_names(self):
        assert is_valid_app_context("wl_manager")
        assert is_valid_app_context("Splunk_TA_paloalto")
        assert is_valid_app_context("DA-ESS-CommonInterface")
        assert is_valid_app_context("search")
        assert is_valid_app_context("a")  # 1-char minimum

    def test_accepts_empty_means_default(self):
        # Empty → caller substitutes APP_NAME default; valid by contract
        assert is_valid_app_context("")
        # None is also empty-equivalent
        assert is_valid_app_context(None)

    def test_rejects_path_traversal(self):
        # The whole point — app_context joins into a filesystem path
        assert not is_valid_app_context("..")
        assert not is_valid_app_context("../etc")
        assert not is_valid_app_context("foo/bar")
        assert not is_valid_app_context("foo\\bar")
        assert not is_valid_app_context("./search")

    def test_rejects_dots_no_period_in_app_names(self):
        # Splunk does not allow dots in app names; this also blocks
        # ".hidden", "..", and "foo.bar" traversal-adjacent inputs
        assert not is_valid_app_context("foo.bar")
        assert not is_valid_app_context(".hidden_app")

    def test_rejects_spaces(self):
        # Splunk apps do not have spaces; rejecting is also defense
        # against "foo /etc/passwd" style payloads
        assert not is_valid_app_context("my app")
        assert not is_valid_app_context("search ")  # trailing
        assert not is_valid_app_context(" search")  # leading

    def test_rejects_non_ascii(self):
        # Same homoglyph defense as is_ascii_name
        assert not is_valid_app_context("应用")
        assert not is_valid_app_context("приложение")

    def test_rejects_special_chars(self):
        assert not is_valid_app_context("app$cmd")
        assert not is_valid_app_context("app|pipe")
        assert not is_valid_app_context("app;chain")
        assert not is_valid_app_context("app(paren)")
        assert not is_valid_app_context("app@host")

    def test_boundary_length_100(self):
        # 100 chars is the cap; 101 must reject
        assert is_valid_app_context("a" * 100)
        assert not is_valid_app_context("a" * 101)
        assert not is_valid_app_context("a" * 500)

    def test_rejects_non_string(self):
        assert not is_valid_app_context(123)
        assert not is_valid_app_context(["wl_manager"])
        assert not is_valid_app_context({"name": "wl_manager"})


# ─────────────────────────────────────────────────────────────────────────
# Adversarial / injection edge cases — these are the attacks an attacker
# would try AFTER reading our validator code looking for bypasses.
# ─────────────────────────────────────────────────────────────────────────

class TestAdversarialEdgeCases:
    """Attacks that subvert ASCII checks via Unicode tricks or injection."""

    # ── Homoglyph / hidden-character defense ─────────────────────────

    def test_zero_width_chars_rejected_in_rule_name(self):
        # U+200B ZERO WIDTH SPACE, U+200C ZWNJ, U+200D ZWJ, U+FEFF BOM
        for ch in ["​", "‌", "‍", "﻿"]:
            assert not is_ascii_name("DR_test" + ch + "rule")
            assert not is_safe_filename("DR_test" + ch + "rule.csv")
            assert validate_ascii_text("reason " + ch + " text") is not None

    def test_bidi_override_rejected(self):
        # U+202E RLO / U+202D LRO are classic filename-spoofing chars
        for ch in ["‮", "‭", "‪", "‫", "‬"]:
            assert not is_ascii_name("DR_" + ch + "evil")
            assert not is_safe_filename("inv‮oice.csv")
            assert validate_ascii_text("reason " + ch) is not None

    def test_nbsp_and_other_unicode_spaces_rejected(self):
        # U+00A0 NBSP, U+2028 LSEP, U+2029 PSEP, U+3000 ideographic space
        for ch in [" ", " ", " ", "　"]:
            assert not is_ascii_name("rule" + ch + "name")
            assert validate_ascii_text("reason" + ch) is not None

    def test_fullwidth_ascii_lookalikes_rejected(self):
        # U+FF21 ('Ａ') looks like ASCII 'A' but is U+FF21 — reject
        assert not is_ascii_name("ＤＲ＿ｔｅｓｔ")
        assert validate_ascii_text("ｒｅａｓｏｎ") is not None

    def test_combining_marks_rejected(self):
        # ASCII letter + combining diacritic (U+0301) — visually 'á'
        # but byte-wise NOT ASCII. Must reject.
        assert not is_ascii_name("rule_á")
        assert validate_ascii_text("é") is not None

    # ── Control / injection chars ────────────────────────────────────

    def test_null_byte_rejected(self):
        # Null bytes in path strings are a classic C-string truncation attack
        assert not is_ascii_name("DR\x00evil")
        assert not is_safe_filename("DR\x00.csv")

    def test_newline_in_rule_name_rejected(self):
        # If a rule name landed in audit logs, embedded \n could forge
        # extra log lines (log injection)
        assert not is_ascii_name("DR_test\nrule")
        assert not is_ascii_name("DR_test\rrule")
        assert not is_ascii_name("DR_test\r\nrule")

    def test_tab_in_rule_name_rejected(self):
        # Tabs would mangle CSV / TSV downstream output
        assert not is_ascii_name("DR_test\trule")

    def test_newline_in_validate_ascii_text_allowed(self):
        # validate_ascii_text intentionally permits \n / \t — reason
        # fields are multi-line free text. Confirm that contract holds.
        assert validate_ascii_text("Line 1\nLine 2") is None
        assert validate_ascii_text("col1\tcol2") is None
        assert validate_ascii_text("trailing\r\n") is None

    # ── Boundary / degenerate inputs ─────────────────────────────────

    def test_numeric_only_name_accepted(self):
        # "1234" is a valid stem — common for ticket-id-named CSVs
        assert is_ascii_name("12345")
        assert is_safe_filename("12345.csv")

    def test_single_char_accepted(self):
        assert is_ascii_name("a")
        assert is_safe_filename("a.csv")

    def test_whitespace_only_rejected(self):
        # Spaces alone are not a name — would create blank-named rules
        assert not is_ascii_name("   ")
        # Frontend trims, but defense in depth: empty-after-trim should
        # not slip through. (Note: regex \s+ is multi-space; single space
        # alone — " " — also has no alphanumeric so safe path catches it)
        assert not is_safe_filename("   .csv")

    def test_long_inputs(self):
        # is_ascii_name has no length cap (caller enforces); just verify
        # the regex doesn't crash on big strings
        big = "a" * 10000
        assert is_ascii_name(big)
        # is_safe_filename also no internal cap; caller (resolve_csv_path)
        # is bounded by FS path length limits
        assert is_safe_filename(big + ".csv")

    def test_only_underscores_or_hyphens_rejected_in_filename(self):
        # is_safe_filename requires at least one alphanumeric in stem
        assert not is_safe_filename("___.csv")
        assert not is_safe_filename("---.csv")
        assert not is_safe_filename("_-_-_-_.csv")
        assert not is_safe_filename("...csv")  # treats as ".." stem + ".csv"

    # ── Mixed-content adversarial inputs ─────────────────────────────

    def test_ascii_prefix_with_cjk_suffix_rejected(self):
        # Real bug from 2026-04-26: name passed if Python only checked
        # the first chars. Must reject if ANY char is non-ASCII.
        assert not is_ascii_name("DR_legitimate_prefix_检测")
        assert not is_safe_filename("DR_legitimate_prefix_检测.csv")
        assert validate_ascii_text("Legitimate text 然后中文") is not None

    def test_cjk_prefix_with_ascii_suffix_rejected(self):
        assert not is_ascii_name("检测_DR")
        assert not is_safe_filename("检测_DR.csv")
        assert validate_ascii_text("中文 then English") is not None

    def test_ascii_with_single_cjk_char_rejected(self):
        # One bad char anywhere is enough
        assert not is_ascii_name("DR_test规")
        assert not is_safe_filename("DR_test规.csv")


# ─────────────────────────────────────────────────────────────────────────
# build_csv_path — gateway used by replay (legacy queue entries)
# ─────────────────────────────────────────────────────────────────────────

class TestBuildCsvPathRejectsLegacyCjk:
    """build_csv_path returns None for legacy CJK names — replay then
    surfaces a clear "Invalid CSV file name" error rather than crashing
    on `write_csv(None, ...)` further down the pipeline.

    Origin: 2026-04-26 — added a None check in
    bin/wl_replay.py::_execute_replay_create_csv after tracing the
    legacy-queue replay path (the validators were tightened mid-session
    and pre-tightening queue entries needed a graceful fallback)."""

    def test_returns_none_for_cjk_filename(self):
        from wl_validation import build_csv_path
        assert build_csv_path("DR_压力测试.csv") is None
        assert build_csv_path("検出ルール.csv") is None

    def test_returns_none_for_traversal(self):
        from wl_validation import build_csv_path
        assert build_csv_path("../etc/passwd.csv") is None
        assert build_csv_path("foo/bar.csv") is None

    def test_returns_none_for_null_byte(self):
        from wl_validation import build_csv_path
        assert build_csv_path("DR_evil\x00.csv") is None

    def test_returns_path_for_clean_name(self):
        from wl_validation import build_csv_path
        result = build_csv_path("DR_clean.csv")
        assert result is not None
        assert result.endswith("DR_clean.csv")


# ─────────────────────────────────────────────────────────────────────────
# _SAFE_COLNAME_RE — pin the column-header ASCII contract
# ─────────────────────────────────────────────────────────────────────────

class TestSafeColnameRegex:
    """_SAFE_COLNAME_RE governs every column header in this app.

    The regex requires ≥1 ASCII alphanumeric and rejects any non-ASCII
    character. This test pins that contract — if anyone widens the
    regex to accept Unicode "letters" (e.g. via re.UNICODE flag drift),
    these tests will fail and surface the regression."""

    def test_accepts_typical_csv_columns(self):
        from wl_constants import _SAFE_COLNAME_RE
        assert _SAFE_COLNAME_RE.match("src_ip")
        assert _SAFE_COLNAME_RE.match("dest_port")
        assert _SAFE_COLNAME_RE.match("user_agent")
        assert _SAFE_COLNAME_RE.match("event-id-1")
        assert _SAFE_COLNAME_RE.match("col1")

    def test_accepts_allowed_punctuation(self):
        from wl_constants import _SAFE_COLNAME_RE
        # Punctuation set: _-.()/:#@&+
        for ch in "_-.()/:#@&+":
            assert _SAFE_COLNAME_RE.match("a" + ch + "b"), \
                f"should accept 'a{ch}b'"

    def test_rejects_cjk_column_name(self):
        from wl_constants import _SAFE_COLNAME_RE
        assert not _SAFE_COLNAME_RE.match("源IP")
        assert not _SAFE_COLNAME_RE.match("规则_id")
        assert not _SAFE_COLNAME_RE.match("col_检测")

    def test_rejects_cyrillic_column_name(self):
        from wl_constants import _SAFE_COLNAME_RE
        assert not _SAFE_COLNAME_RE.match("источник")
        assert not _SAFE_COLNAME_RE.match("col_правило")

    def test_rejects_emoji(self):
        from wl_constants import _SAFE_COLNAME_RE
        assert not _SAFE_COLNAME_RE.match("col_🔥")

    def test_rejects_spaces(self):
        from wl_constants import _SAFE_COLNAME_RE
        # Handler enforces no-spaces separately; regex itself rejects too
        assert not _SAFE_COLNAME_RE.match("col with space")
        assert not _SAFE_COLNAME_RE.match(" leading_space")
        assert not _SAFE_COLNAME_RE.match("trailing_space ")

    def test_rejects_purely_punctuation(self):
        # Lookahead requires ≥1 alphanumeric — "___" or "()()" alone
        # would create headers that look like data corruption
        from wl_constants import _SAFE_COLNAME_RE
        assert not _SAFE_COLNAME_RE.match("___")
        assert not _SAFE_COLNAME_RE.match("---")
        assert not _SAFE_COLNAME_RE.match("()/")
        assert not _SAFE_COLNAME_RE.match(".")

    def test_rejects_empty(self):
        from wl_constants import _SAFE_COLNAME_RE
        assert not _SAFE_COLNAME_RE.match("")

    def test_rejects_zero_width_chars(self):
        from wl_constants import _SAFE_COLNAME_RE
        assert not _SAFE_COLNAME_RE.match("col​")
        assert not _SAFE_COLNAME_RE.match("col﻿")

    def test_rejects_null_byte(self):
        from wl_constants import _SAFE_COLNAME_RE
        assert not _SAFE_COLNAME_RE.match("col\x00evil")


# ─────────────────────────────────────────────────────────────────────────
# _safe_trash_item_dir — defense-in-depth path traversal guard
# ─────────────────────────────────────────────────────────────────────────

class TestSafeTrashItemDir:
    """_safe_trash_item_dir() must reject any trash_id that resolves
    outside trash_dir. Origin: 2026-04-29 audit found purge_trash_item
    fed user-supplied trash_id directly into shutil.rmtree — a
    malicious admin sending trash_id='../../tmp' would have silently
    deleted /opt/splunk/.../tmp."""

    def test_rejects_traversal_dotdot(self):
        from wl_trash import _safe_trash_item_dir
        assert _safe_trash_item_dir("..") is None
        assert _safe_trash_item_dir("../etc") is None
        assert _safe_trash_item_dir("../../tmp") is None

    def test_rejects_path_separators(self):
        from wl_trash import _safe_trash_item_dir
        assert _safe_trash_item_dir("foo/bar") is None
        assert _safe_trash_item_dir("foo\\bar") is None

    def test_rejects_dotfiles(self):
        from wl_trash import _safe_trash_item_dir
        assert _safe_trash_item_dir(".hidden") is None
        assert _safe_trash_item_dir(".") is None

    def test_rejects_empty_or_none(self):
        from wl_trash import _safe_trash_item_dir
        assert _safe_trash_item_dir("") is None
        assert _safe_trash_item_dir(None) is None

    def test_rejects_non_string(self):
        from wl_trash import _safe_trash_item_dir
        assert _safe_trash_item_dir(123) is None
        assert _safe_trash_item_dir(["x"]) is None

    def test_rejects_nonexistent(self):
        # Even a clean-looking trash_id should return None if the
        # directory doesn't exist (caller should treat as "not found")
        from wl_trash import _safe_trash_item_dir
        assert _safe_trash_item_dir("nonexistent_trash_id_12345") is None


# ─────────────────────────────────────────────────────────────────────────
# _from_dual_approval bypass — STRIDE round 2026-04-29 finding
# ─────────────────────────────────────────────────────────────────────────

class TestNoDualApprovalPayloadBypass:
    """The `_from_dual_approval` flag must NOT be readable from
    user-controlled `payload` in any handler action wrapper.

    Origin: STRIDE audit 2026-04-29. Same anti-pattern as the
    `_from_approval` bypass we fixed earlier — bypass flags from
    payload are user-controlled and let an attacker skip security
    gates by simply setting them to true.

    The legitimate dual-approval replay path calls
    `delete_rule_pipeline()` and `delete_csv_pipeline()` DIRECTLY,
    not through `_action_remove_rule` / `_action_remove_csv`, so
    no bypass flag is ever needed in the action wrappers.
    """

    def test_no_payload_read_of_flag_in_handler(self):
        import os
        repo = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        path = os.path.join(repo, "bin", "wl_handler.py")
        with open(path, "r", encoding="utf-8") as fh:
            source = fh.read()
        # The flag must NEVER be read from `payload` in this file.
        # Comments mentioning the flag are fine; only actual
        # `payload.get("_from_dual_approval"...)` is banned.
        bad_pattern = 'payload.get("_from_dual_approval"'
        assert bad_pattern not in source, (
            "SECURITY: _from_dual_approval is being read from payload "
            "in wl_handler.py. This is the same anti-pattern as the "
            "_from_approval bypass — payload is user-controlled, so "
            "any attacker can send the flag and skip the dual-admin "
            "gate. Remove the read; the legitimate replay path calls "
            "the pipeline directly, not the action wrapper.")
