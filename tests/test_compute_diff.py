"""Tests for _compute_diff — similarity-based diff algorithm."""

import sys
import os
import unittest

# We extract the function without importing the full module (Splunk deps).
# The function only uses stdlib (difflib), so it runs standalone.

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bin"))

# Read source and exec just the _compute_diff function
_src = open(
    os.path.join(os.path.dirname(__file__), "..", "bin", "wl_handler.py"),
    encoding="utf-8",
).read()

# Build a minimal namespace with the required import
import difflib

_ns = {"difflib": difflib}

# Extract the function definition from source
import re

_match = re.search(
    r"(def _compute_diff\(.*?\n)(?=\ndef |\nclass |\n# ═)",
    _src,
    re.DOTALL,
)
if _match:
    exec(_match.group(0), _ns)

_compute_diff = _ns["_compute_diff"]


class TestComputeDiffNoChanges(unittest.TestCase):
    """No changes should produce empty diff."""

    def test_identical_data(self):
        headers = ["user", "ip"]
        rows = [{"user": "alice", "ip": "10.0.0.1"}]
        diff = _compute_diff(headers, rows, headers, rows)
        self.assertEqual(diff["added_count"], 0)
        self.assertEqual(diff["removed_count"], 0)
        self.assertEqual(diff["edited_count"], 0)


class TestComputeDiffAdded(unittest.TestCase):
    """Detect newly added rows."""

    def test_single_add(self):
        headers = ["user", "ip"]
        old = [{"user": "alice", "ip": "10.0.0.1"}]
        new = [
            {"user": "alice", "ip": "10.0.0.1"},
            {"user": "bob", "ip": "10.0.0.2"},
        ]
        diff = _compute_diff(headers, old, headers, new)
        self.assertEqual(diff["added_count"], 1)
        self.assertEqual(diff["removed_count"], 0)
        self.assertEqual(diff["added"][0]["user"], "bob")

    def test_multiple_adds(self):
        headers = ["name"]
        old = []
        new = [{"name": "a"}, {"name": "b"}, {"name": "c"}]
        diff = _compute_diff(headers, old, headers, new)
        self.assertEqual(diff["added_count"], 3)
        self.assertEqual(diff["removed_count"], 0)


class TestComputeDiffRemoved(unittest.TestCase):
    """Detect removed rows."""

    def test_single_remove(self):
        headers = ["user", "ip"]
        old = [
            {"user": "alice", "ip": "10.0.0.1"},
            {"user": "bob", "ip": "10.0.0.2"},
        ]
        new = [{"user": "alice", "ip": "10.0.0.1"}]
        diff = _compute_diff(headers, old, headers, new)
        self.assertEqual(diff["removed_count"], 1)
        self.assertEqual(diff["added_count"], 0)
        self.assertEqual(diff["removed"][0]["user"], "bob")


class TestComputeDiffEdited(unittest.TestCase):
    """Detect edited rows via similarity matching."""

    def test_single_field_edit(self):
        headers = ["user", "ip", "comment"]
        old = [{"user": "alice", "ip": "10.0.0.1", "comment": "old"}]
        new = [{"user": "alice", "ip": "10.0.0.1", "comment": "new"}]
        diff = _compute_diff(headers, old, headers, new)
        self.assertEqual(diff["edited_count"], 1)
        self.assertEqual(diff["added_count"], 0)
        self.assertEqual(diff["removed_count"], 0)
        changed = diff["edited"][0]["changed_fields"]
        self.assertEqual(len(changed), 1)
        self.assertEqual(changed[0]["field"], "comment")
        self.assertEqual(changed[0]["before"], "old")
        self.assertEqual(changed[0]["after"], "new")

    def test_edit_with_simultaneous_removal(self):
        """The key test: edits must be detected correctly when rows are also removed."""
        headers = ["user", "ip", "threshold"]
        old = [
            {"user": "alice", "ip": "10.0.0.1", "threshold": "100"},
            {"user": "bob", "ip": "10.0.0.2", "threshold": "200"},
            {"user": "charlie", "ip": "10.0.0.3", "threshold": "300"},
        ]
        # Remove bob, edit charlie's threshold
        new = [
            {"user": "alice", "ip": "10.0.0.1", "threshold": "100"},
            {"user": "charlie", "ip": "10.0.0.3", "threshold": "999"},
        ]
        diff = _compute_diff(headers, old, headers, new)
        self.assertEqual(diff["removed_count"], 1)
        self.assertEqual(diff["removed"][0]["user"], "bob")
        self.assertEqual(diff["edited_count"], 1)
        self.assertEqual(diff["edited"][0]["new_row"]["threshold"], "999")
        self.assertEqual(diff["added_count"], 0)

    def test_no_false_edit_when_all_fields_differ(self):
        """Completely different rows should NOT be paired as edits."""
        headers = ["a", "b", "c"]
        old = [{"a": "1", "b": "2", "c": "3"}]
        new = [{"a": "x", "b": "y", "c": "z"}]
        diff = _compute_diff(headers, old, headers, new)
        # All 3 fields differ → below 50% threshold → not an edit
        self.assertEqual(diff["edited_count"], 0)
        self.assertEqual(diff["added_count"], 1)
        self.assertEqual(diff["removed_count"], 1)


class TestComputeDiffColumns(unittest.TestCase):
    """Detect column additions and removals."""

    def test_column_added(self):
        old_h = ["user", "ip"]
        new_h = ["user", "ip", "region"]
        rows = [{"user": "alice", "ip": "10.0.0.1"}]
        new_rows = [{"user": "alice", "ip": "10.0.0.1", "region": "US"}]
        diff = _compute_diff(old_h, rows, new_h, new_rows)
        self.assertIn("region", diff["added_columns"])
        self.assertEqual(len(diff["removed_columns"]), 0)

    def test_column_removed(self):
        old_h = ["user", "ip", "region"]
        new_h = ["user", "ip"]
        rows = [{"user": "alice", "ip": "10.0.0.1", "region": "US"}]
        new_rows = [{"user": "alice", "ip": "10.0.0.1"}]
        diff = _compute_diff(old_h, rows, new_h, new_rows)
        self.assertIn("region", diff["removed_columns"])
        self.assertEqual(len(diff["added_columns"]), 0)

    def test_column_change_no_false_edits(self):
        """Adding/removing columns should NOT trigger false edit events."""
        old_h = ["user", "ip"]
        new_h = ["user", "ip", "tag"]
        old_rows = [{"user": "alice", "ip": "10.0.0.1"}]
        new_rows = [{"user": "alice", "ip": "10.0.0.1", "tag": ""}]
        diff = _compute_diff(old_h, old_rows, new_h, new_rows)
        self.assertEqual(diff["edited_count"], 0)
        self.assertIn("tag", diff["added_columns"])


class TestComputeDiffMetadata(unittest.TestCase):
    """Internal _ columns should be ignored in diff detection."""

    def test_metadata_columns_ignored(self):
        headers = ["user", "_added_by", "_added_at"]
        old = [{"user": "alice", "_added_by": "admin", "_added_at": "123"}]
        new = [{"user": "alice", "_added_by": "bob", "_added_at": "456"}]
        diff = _compute_diff(headers, old, headers, new)
        # Changes to _ columns should not appear as edits
        self.assertEqual(diff["edited_count"], 0)
        self.assertEqual(diff["added_count"], 0)
        self.assertEqual(diff["removed_count"], 0)


class TestComputeDiffTextDiff(unittest.TestCase):
    """Verify text_diff output is present."""

    def test_text_diff_present(self):
        headers = ["user"]
        old = [{"user": "alice"}]
        new = [{"user": "alice"}, {"user": "bob"}]
        diff = _compute_diff(headers, old, headers, new)
        self.assertIsInstance(diff["text_diff"], list)
        self.assertTrue(len(diff["text_diff"]) > 0)


if __name__ == "__main__":
    unittest.main()
