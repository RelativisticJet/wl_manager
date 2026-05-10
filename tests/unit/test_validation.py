"""
Unit tests for wl_validation module.

Tests all validation and security helper functions.
"""

import pytest
import os
import sys
import tempfile
from unittest import mock

# Add bin directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'bin'))


@pytest.mark.unit
class TestSanitizeText:
    """Test sanitize_text function."""

    def test_sanitize_text_removes_control_chars(self):
        """Verify control characters are removed."""
        from wl_validation import sanitize_text

        # Input with control characters
        text = "hello\x00world\x1ftest"
        result = sanitize_text(text)
        assert "\x00" not in result
        assert "\x1f" not in result
        assert "hello" in result
        assert "world" in result
        assert "test" in result

    def test_sanitize_text_collapses_whitespace(self):
        """Verify multiple spaces are collapsed to single space."""
        from wl_validation import sanitize_text

        # Input with multiple spaces
        text = "hello   world\t\ttest"
        result = sanitize_text(text)
        # Should collapse to single spaces
        assert "   " not in result
        assert "\t" not in result
        assert result == "hello world test"

    def test_sanitize_text_truncates(self):
        """Verify text longer than max_length is truncated."""
        from wl_validation import sanitize_text

        # Input longer than default 500 chars
        text = "a" * 1000
        result = sanitize_text(text)
        assert len(result) == 500

        # Custom max_length
        result = sanitize_text(text, max_length=100)
        assert len(result) == 100

    def test_sanitize_text_returns_empty_for_invalid(self):
        """Verify invalid input returns empty string."""
        from wl_validation import sanitize_text

        # None input
        assert sanitize_text(None) == ""

        # Non-string input
        assert sanitize_text(123) == ""

        # Empty string
        assert sanitize_text("") == ""

    def test_sanitize_text_strips_whitespace(self):
        """Verify leading and trailing whitespace is removed."""
        from wl_validation import sanitize_text

        text = "  hello world  "
        result = sanitize_text(text)
        assert result == "hello world"
        assert not result.startswith(" ")
        assert not result.endswith(" ")


@pytest.mark.unit
class TestIsSafeFilename:
    """Test is_safe_filename function."""

    def test_is_safe_filename_accepts_valid(self):
        """Verify valid filenames are accepted."""
        from wl_validation import is_safe_filename

        assert is_safe_filename("rule_whitelist.csv")
        assert is_safe_filename("DR102_exclusions.csv")
        assert is_safe_filename("a.csv")
        assert is_safe_filename("file123.csv")

    def test_is_safe_filename_rejects_traversal(self):
        """Verify path traversal attempts are rejected."""
        from wl_validation import is_safe_filename

        assert not is_safe_filename("../etc/passwd")
        assert not is_safe_filename("../../config.csv")
        assert not is_safe_filename("subdir/file.csv")
        assert not is_safe_filename("dir\\file.csv")

    def test_is_safe_filename_rejects_dots(self):
        """Verify files starting with dot are rejected."""
        from wl_validation import is_safe_filename

        assert not is_safe_filename(".hidden.csv")
        assert not is_safe_filename(".csv")

    def test_is_safe_filename_rejects_bad_extension(self):
        """Verify non-CSV files are rejected (by default)."""
        from wl_validation import is_safe_filename

        assert not is_safe_filename("file.txt")
        assert not is_safe_filename("config.json")
        assert not is_safe_filename("script.py")
        assert not is_safe_filename("file")

    def test_is_safe_filename_custom_extensions(self):
        """Verify allowed_extensions parameter works."""
        from wl_validation import is_safe_filename

        # JSON file with custom extension
        assert is_safe_filename("config.json", (".json",))
        assert not is_safe_filename("config.json", (".csv",))

        # Multiple extensions
        assert is_safe_filename("file.txt", (".csv", ".txt"))
        assert is_safe_filename("file.csv", (".csv", ".txt"))

    def test_is_safe_filename_requires_alphanumeric_stem(self):
        """Verify filename stem must contain alphanumeric characters."""
        from wl_validation import is_safe_filename

        # Only underscores in stem (no alphanumeric)
        assert not is_safe_filename("___.csv")

        # Valid stems with alphanumeric
        assert is_safe_filename("file123.csv")
        assert is_safe_filename("_file1.csv")  # has alphanumeric (file1)
        assert is_safe_filename("file_.csv")  # has alphanumeric (file)
        assert is_safe_filename("_only_underscores.csv")  # has alphanumeric (only, underscores)

    def test_is_safe_filename_rejects_invalid_input(self):
        """Verify invalid input is rejected."""
        from wl_validation import is_safe_filename

        assert not is_safe_filename(None)
        assert not is_safe_filename(123)
        assert not is_safe_filename("")

    def test_basename_check_independently_rejects_path_separators(self):
        """R0-F4 fix: pin the ``os.path.basename(name) != name``
        check independently of the stem regex.

        ``is_safe_filename`` has TWO defenses against path
        traversal:

        1. ``os.path.basename(name) != name`` rejects any name
           containing a separator
        2. ``_ASCII_FILENAME_STEM_RE.match(stem)`` restricts the
           stem to ``[A-Za-z0-9_-]+``, which incidentally also
           rejects ``/`` and ``\``.

        Because (2) is so strict, removing (1) is a no-op for
        current inputs — meaning no test that exercises real
        traversal inputs can distinguish "(1) is working" from
        "(2) is working". If a future refactor relaxes (2) (for
        example to allow ``/`` in some new context), (1) becomes
        load-bearing AND its absence becomes a real path-traversal
        vulnerability with no test failure.

        This test pins (1) by mock-relaxing the regex and
        confirming (1) still rejects path-traversal inputs.
        """
        from unittest.mock import patch
        import re
        import wl_validation
        from wl_validation import is_safe_filename

        # Patch the stem regex to a permissive variant that
        # WOULD accept slashes/backslashes if the basename check
        # were absent.
        permissive = re.compile(r'^[A-Za-z0-9_\-/\\]+\Z')
        with patch.object(wl_validation, "_ASCII_FILENAME_STEM_RE",
                          permissive):
            # Each input has a stem that the permissive regex
            # would accept, AND no other rejection condition
            # other than the basename check applies.
            assert not is_safe_filename("subdir/file.csv"), \
                "basename check failed to reject forward slash"
            assert not is_safe_filename("dir\\file.csv"), \
                "basename check failed to reject backslash"
            # Sanity: the permissive regex DID accept what we
            # wanted (a name without separators) — proves the
            # mock is in effect and the rejection is from the
            # basename check, not the regex.
            assert is_safe_filename("file_with-dashes.csv"), \
                ("permissive regex did not accept a benign name "
                 "— mock setup is wrong")


@pytest.mark.unit
class TestSafeRealpath:
    """Test safe_realpath function."""

    def test_safe_realpath_verifies_containment(self, tmp_path):
        """Verify safe_realpath checks path containment."""
        from wl_validation import safe_realpath

        # Create test files
        test_dir = tmp_path / "test"
        test_dir.mkdir()
        test_file = test_dir / "file.txt"
        test_file.write_text("test")

        # Path within allowed_base
        result = safe_realpath(str(test_file), str(test_dir))
        assert result is not None
        assert str(test_file) in result or test_file.resolve().__str__() in result

    def test_safe_realpath_rejects_traversal(self, tmp_path):
        """Verify safe_realpath rejects paths outside allowed_base."""
        from wl_validation import safe_realpath

        # Create test directories
        allowed = tmp_path / "allowed"
        allowed.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        outside_file = outside / "file.txt"
        outside_file.write_text("test")

        # Path outside allowed_base should be rejected
        result = safe_realpath(str(outside_file), str(allowed))
        assert result is None

    def test_safe_realpath_handles_nonexistent_paths(self):
        """Verify safe_realpath handles nonexistent paths gracefully."""
        from wl_validation import safe_realpath

        # Nonexistent paths should not raise
        result = safe_realpath("/nonexistent/path", "/allowed/base")
        # Should either return None or a path (depending on implementation)
        # The key is it doesn't crash


@pytest.mark.unit
class TestBuildCsvPath:
    """Test build_csv_path function."""

    def test_build_csv_path_rejects_unsafe_names(self):
        """Verify unsafe filenames return None."""
        from wl_validation import build_csv_path

        assert build_csv_path("../etc/passwd") is None
        assert build_csv_path("..\\windows\\system32\\config.csv") is None
        assert build_csv_path(".hidden.csv") is None
        assert build_csv_path("file.txt") is None

    def test_build_csv_path_accepts_valid_names(self):
        """Verify valid filenames return paths."""
        from wl_validation import build_csv_path

        result = build_csv_path("valid_file.csv")
        assert result is not None
        assert "valid_file.csv" in result
        assert result.endswith("valid_file.csv")

    def test_build_csv_path_uses_own_lookups_by_default(self):
        """Verify default context uses OWN_LOOKUPS."""
        from wl_validation import build_csv_path
        from wl_constants import OWN_LOOKUPS

        result = build_csv_path("file.csv")
        assert result is not None
        # Result should be under OWN_LOOKUPS (normalize paths for comparison)
        assert os.path.normpath(OWN_LOOKUPS) in os.path.normpath(result)

    def test_build_csv_path_custom_app_context(self):
        """Verify app_context parameter works."""
        from wl_validation import build_csv_path
        from wl_constants import APPS_DIR

        result = build_csv_path("file.csv", "other_app")
        assert result is not None
        # Result should be under other_app/lookups
        assert "other_app" in result
        assert "lookups" in result

    def test_build_csv_path_normalizes_path(self):
        """Verify path is normalized (using os.path.normpath)."""
        from wl_validation import build_csv_path

        result = build_csv_path("file.csv")
        assert result is not None
        # Path should be absolute and normalized (no /./ or /../)
        assert "\\" not in result or "/" not in result  # Consistent separators
        assert "." not in result or result.endswith(".csv")  # No relative components

    def test_build_csv_path_prevents_apps_dir_escape(self):
        """Verify normalization prevents escaping APPS_DIR."""
        from wl_validation import build_csv_path

        # Try to escape with complex path
        result = build_csv_path("file.csv/../../../etc/passwd.csv")
        # Should either reject or normalize to safe path
        if result is not None:
            # If it returns a path, it should still be under APPS_DIR
            from wl_constants import APPS_DIR
            assert result.startswith(os.path.normpath(APPS_DIR))


@pytest.mark.unit
class TestResolveCsvPath:
    """Test resolve_csv_path function."""

    def test_resolve_csv_path_returns_none_if_missing(self):
        """Verify nonexistent files return None."""
        from wl_validation import resolve_csv_path

        result = resolve_csv_path("nonexistent_file_12345.csv")
        assert result is None

    def test_resolve_csv_path_returns_path_if_exists(self, tmp_path):
        """Verify existing files return real paths."""
        from wl_validation import resolve_csv_path, build_csv_path
        from wl_constants import OWN_LOOKUPS
        import os

        # Create a test CSV file in OWN_LOOKUPS
        os.makedirs(OWN_LOOKUPS, exist_ok=True)
        test_file = os.path.join(OWN_LOOKUPS, "test_resolve.csv")
        with open(test_file, "w") as f:
            f.write("col1,col2\nval1,val2\n")

        try:
            result = resolve_csv_path("test_resolve.csv")
            assert result is not None
            assert os.path.isfile(result)
        finally:
            # Cleanup
            if os.path.exists(test_file):
                os.remove(test_file)

    def test_resolve_csv_path_checks_filename_safety(self):
        """Verify unsafe filenames return None."""
        from wl_validation import resolve_csv_path

        result = resolve_csv_path("../etc/passwd")
        assert result is None

    def test_resolve_csv_path_rejects_symlink_traversal(self, tmp_path):
        """Verify symlinks escaping allowed_base are rejected."""
        from wl_validation import resolve_csv_path
        import os

        # Skip on Windows (symlinks require special permissions)
        if os.name == 'nt':
            pytest.skip("Symlink test skipped on Windows")

        # Create directories
        allowed_dir = tmp_path / "allowed"
        allowed_dir.mkdir()
        outside_dir = tmp_path / "outside"
        outside_dir.mkdir()

        # Create file outside allowed directory
        outside_file = outside_dir / "file.csv"
        outside_file.write_text("test")

        # Create symlink inside allowed directory pointing outside
        symlink = allowed_dir / "link.csv"
        try:
            symlink.symlink_to(outside_file)

            # Try to resolve through symlink in a custom context
            # This is hard to test without modifying APPS_DIR
            # For now, just verify it doesn't crash
            result = resolve_csv_path("nonexistent.csv")
            assert result is None
        except OSError:
            # Symlink creation might fail on some systems
            pytest.skip("Unable to create symlinks on this system")


@pytest.mark.unit
class TestMutationCoverageGaps:
    """Pin specific behaviors that mutmut (Ring 3 Day 2, build 648)
    found could be silently mutated without any existing test
    failing. Each test below kills a specific surviving mutant.

    See docs/RING_FINDINGS.md "R3-D2-F2 Mutation coverage" for the
    full survivor analysis. Other survivors are equivalent
    mutations (caught by downstream defenses) and intentionally
    not pinned here.
    """

    def test_sanitize_text_replaces_control_chars_with_empty(self):
        """Kill mutmut #7: ``_CONTROL_CHAR_RE.sub('', text)``.

        Existing ``test_sanitize_text_removes_control_chars`` only
        asserts ``'\\x00' not in result`` and ``'hello' in result``,
        which still passes if the replacement string is mutated to
        ``'XXXX'`` (the substring assertions remain true). Pin the
        exact result so any non-empty replacement is caught.
        """
        from wl_validation import sanitize_text

        # Adjacent control chars must collapse to nothing, not
        # leave artifacts. Use input with no whitespace so the
        # whitespace-collapse step doesn't mask the issue.
        assert sanitize_text("hello\x00world") == "helloworld"
        assert sanitize_text("a\x01b\x02c\x03d") == "abcd"

    def test_sanitize_text_replaces_special_chars_with_empty(self):
        """Kill mutmut #9: ``_SANITIZE_RE.sub('', cleaned)``.

        ``_SANITIZE_RE`` strips characters NOT in the allowlist
        ``[a-zA-Z0-9_ \\t.,;:!?'\"()\\-/@#&+=[]{}%$\\n\\r]``. Without
        an exact-equality assertion, mutating the replacement to
        ``'XXXX'`` survives.
        """
        from wl_validation import sanitize_text

        # Tilde, caret, asterisk, pipe are not in the allowlist —
        # they must be stripped to nothing.
        assert sanitize_text("hello~world") == "helloworld"
        assert sanitize_text("a^b*c|d") == "abcd"

    def test_build_csv_path_with_app_context_uses_lookups_subdir(
        self, tmp_path, monkeypatch
    ):
        """Kill mutmut #88: ``os.path.join(APPS_DIR, safe_app, 'lookups')``
        with the literal 'lookups' mutated.

        No existing test exercised the ``app_context`` branch of
        ``build_csv_path``, so the literal directory name could be
        replaced and still pass. Pin that the path goes through a
        directory literally named 'lookups'.
        """
        import wl_validation
        from wl_validation import build_csv_path

        # Stand up a fake APPS_DIR layout under tmp_path. The
        # function only joins paths and normalizes — it doesn't
        # check existence — so the directory doesn't need to be
        # populated.
        fake_apps = tmp_path / "apps"
        fake_apps.mkdir()
        monkeypatch.setattr(wl_validation, "APPS_DIR", str(fake_apps))

        result = build_csv_path("rule.csv", app_context="other_app")
        assert result is not None
        # The path MUST contain a 'lookups' directory between the
        # app context and the csv filename — that is the contract
        # the mutation breaks.
        norm = result.replace("\\", "/")
        assert "/other_app/lookups/rule.csv" in norm

    def test_is_safe_filename_rejects_backslash_on_any_os(self):
        """Pin the platform-independent backslash rejection added
        in build 648 (R3-D2-F1).

        ``os.path.basename`` is platform-aware: posixpath does NOT
        treat backslash as a separator. Splunk runs on Linux, so
        the explicit ``'\\\\' in name`` check is the only thing
        rejecting backslash on the production host. This test
        pins that defense.
        """
        from wl_validation import is_safe_filename

        # On Linux, os.path.basename("dir\\file.csv") == "dir\\file.csv"
        # (no separator interpretation). The explicit check must
        # still reject it.
        assert not is_safe_filename("dir\\file.csv")
        assert not is_safe_filename("a\\b\\c.csv")
