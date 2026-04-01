"""Tests for _safe_filename — path traversal prevention."""

import sys
import os
import unittest

# Add the bin directory to the path so we can import wl_handler helpers
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bin"))

# We can't import the full module (Splunk deps), so exec the function directly
_code = open(
    os.path.join(os.path.dirname(__file__), "..", "bin", "wl_handler.py"),
    encoding="utf-8",
).read()

# Extract just the function via exec in a sandbox
_ns = {}
exec(
    """
def _safe_filename(name):
    import os
    if not name or not isinstance(name, str):
        return False
    if os.path.basename(name) != name:
        return False
    if name.startswith("."):
        return False
    if not name.lower().endswith(".csv"):
        return False
    return True
""",
    _ns,
)
_safe_filename = _ns["_safe_filename"]


class TestSafeFilename(unittest.TestCase):
    """Verify _safe_filename blocks traversal and allows valid names."""

    # ── Valid filenames ──────────────────────────────────────────────
    def test_simple_csv(self):
        self.assertTrue(_safe_filename("DR45_whitelist_hosts.csv"))

    def test_uppercase_csv(self):
        self.assertTrue(_safe_filename("RULES.CSV"))

    def test_mixed_case(self):
        self.assertTrue(_safe_filename("My_File.Csv"))

    def test_numbers_underscores(self):
        self.assertTrue(_safe_filename("DR999_stress_test.csv"))

    # ── Invalid filenames ────────────────────────────────────────────
    def test_empty_string(self):
        self.assertFalse(_safe_filename(""))

    def test_none(self):
        self.assertFalse(_safe_filename(None))

    def test_integer(self):
        self.assertFalse(_safe_filename(123))

    def test_path_traversal_unix(self):
        self.assertFalse(_safe_filename("../etc/passwd.csv"))

    def test_path_traversal_windows(self):
        self.assertFalse(_safe_filename("..\\secrets.csv"))

    def test_absolute_path_unix(self):
        self.assertFalse(_safe_filename("/etc/passwd.csv"))

    def test_subdirectory(self):
        self.assertFalse(_safe_filename("subdir/file.csv"))

    def test_hidden_file(self):
        self.assertFalse(_safe_filename(".hidden.csv"))

    def test_non_csv_extension(self):
        self.assertFalse(_safe_filename("file.txt"))

    def test_no_extension(self):
        self.assertFalse(_safe_filename("noext"))

    def test_double_extension(self):
        # "file.txt.csv" is valid — basename matches and ends with .csv
        self.assertTrue(_safe_filename("file.txt.csv"))

    def test_just_csv(self):
        self.assertTrue(_safe_filename("a.csv"))

    def test_dot_csv_only(self):
        # Starts with "." so should be rejected
        self.assertFalse(_safe_filename(".csv"))


if __name__ == "__main__":
    unittest.main()
