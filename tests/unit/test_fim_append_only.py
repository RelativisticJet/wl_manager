"""
Unit tests for the append-only watch helpers in wl_fim.py.

Verifies that legitimate appends to `_recovery_log.jsonl` do NOT
alert, while truncation, mid-file rewrite, and full removal DO
alert. Covers:

- `_append_only_state(path)` — snapshot helper
- `_hash_file_prefix(path, length)` — prefix-hash helper
- The detection logic itself, exercised via the helper functions
  (the full FIM main() loop is integration-tested via E2E)

Origin: round 7 audit, 2026-04-29.
"""

import hashlib
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "bin"))

# Importing wl_fim runs module-level Splunk imports — guard with
# pytest.importorskip in case the test environment lacks them.
wl_fim = pytest.importorskip(
    "wl_fim",
    reason="wl_fim requires Splunk-bundled imports unavailable in some envs")


@pytest.fixture
def tmp_log(tmp_path):
    """Create an empty recovery-log-style file we can append to."""
    path = tmp_path / "_recovery_log.jsonl"
    path.write_bytes(b"")
    return str(path)


class TestHashFilePrefix:
    """Sanity checks on the prefix-hash helper itself."""

    def test_zero_length_is_empty_sha(self, tmp_log):
        # Edge case: length=0 should always return SHA-256 of empty
        # bytes regardless of file contents.
        with open(tmp_log, "wb") as fh:
            fh.write(b"abc")
        empty_sha = hashlib.sha256(b"").hexdigest()
        assert wl_fim._hash_file_prefix(tmp_log, 0) == empty_sha

    def test_full_file_prefix_matches_full_hash(self, tmp_log):
        with open(tmp_log, "wb") as fh:
            fh.write(b"hello world")
        full_sha = hashlib.sha256(b"hello world").hexdigest()
        assert wl_fim._hash_file_prefix(tmp_log, 11) == full_sha

    def test_partial_prefix(self, tmp_log):
        with open(tmp_log, "wb") as fh:
            fh.write(b"hello world")
        prefix_sha = hashlib.sha256(b"hello").hexdigest()
        assert wl_fim._hash_file_prefix(tmp_log, 5) == prefix_sha

    def test_length_exceeds_file_returns_none(self, tmp_log):
        with open(tmp_log, "wb") as fh:
            fh.write(b"abc")
        # File is only 3 bytes; asking for 100 means truncation
        # was observed — return None to signal that.
        assert wl_fim._hash_file_prefix(tmp_log, 100) is None

    def test_missing_file_returns_none(self, tmp_path):
        ghost = str(tmp_path / "ghost.jsonl")
        assert wl_fim._hash_file_prefix(ghost, 10) is None


class TestAppendOnlyState:
    """Verify the snapshot dict shape."""

    def test_missing_file_state(self, tmp_path):
        ghost = str(tmp_path / "ghost.jsonl")
        state = wl_fim._append_only_state(ghost)
        assert state == {"exists": False, "size": 0, "prefix_hash": None}

    def test_empty_file_state(self, tmp_log):
        state = wl_fim._append_only_state(tmp_log)
        assert state["exists"] is True
        assert state["size"] == 0
        # SHA-256 of zero bytes is deterministic
        assert state["prefix_hash"] == hashlib.sha256(b"").hexdigest()

    def test_file_with_content(self, tmp_log):
        with open(tmp_log, "wb") as fh:
            fh.write(b"line one\n")
        state = wl_fim._append_only_state(tmp_log)
        assert state["exists"] is True
        assert state["size"] == 9
        assert state["prefix_hash"] == hashlib.sha256(b"line one\n").hexdigest()


class TestDetectionLogic:
    """Integration-ish tests of the alert decisions, simulating
    the main loop's logic in isolation."""

    def _decide(self, prev, cur_state, cur_path):
        """Replica of the in-loop decision tree. Returns one of
        ('ok_no_change', 'ok_appended', 'first_baseline',
         'tampered_truncated', 'tampered_rewritten',
         'tampered_removed')."""
        prev_exists = bool(prev.get("exists"))
        prev_size = int(prev.get("size") or 0)
        prev_prefix_hash = prev.get("prefix_hash")
        cur_exists = cur_state["exists"]
        cur_size = cur_state["size"]
        cur_prefix_hash = cur_state["prefix_hash"]

        if not prev:
            return "first_baseline"
        if not cur_exists and prev_exists:
            return "tampered_removed"
        if cur_exists and not prev_exists:
            return "first_baseline"
        if cur_size < prev_size:
            return "tampered_truncated"
        if prev_size > 0 and prev_prefix_hash is not None:
            cur_prefix_at_prev = wl_fim._hash_file_prefix(
                cur_path, prev_size)
            if cur_prefix_at_prev != prev_prefix_hash:
                return "tampered_rewritten"
        if cur_size == prev_size and cur_prefix_hash == prev_prefix_hash:
            return "ok_no_change"
        return "ok_appended"

    def test_legitimate_append_does_not_alert(self, tmp_log):
        with open(tmp_log, "wb") as fh:
            fh.write(b'{"event": 1}\n')
        prev = wl_fim._append_only_state(tmp_log)
        # Append a new entry
        with open(tmp_log, "ab") as fh:
            fh.write(b'{"event": 2}\n')
        cur = wl_fim._append_only_state(tmp_log)
        assert self._decide(prev, cur, tmp_log) == "ok_appended"

    def test_no_change_is_silent(self, tmp_log):
        with open(tmp_log, "wb") as fh:
            fh.write(b'{"event": 1}\n')
        prev = wl_fim._append_only_state(tmp_log)
        cur = wl_fim._append_only_state(tmp_log)
        assert self._decide(prev, cur, tmp_log) == "ok_no_change"

    def test_truncation_in_place_alerts(self, tmp_log):
        with open(tmp_log, "wb") as fh:
            fh.write(b'{"event": 1}\n{"event": 2}\n')
        prev = wl_fim._append_only_state(tmp_log)
        # Attacker removes the second entry, leaving only the first
        with open(tmp_log, "wb") as fh:
            fh.write(b'{"event": 1}\n')
        cur = wl_fim._append_only_state(tmp_log)
        assert self._decide(prev, cur, tmp_log) == "tampered_truncated"

    def test_full_removal_alerts(self, tmp_log):
        with open(tmp_log, "wb") as fh:
            fh.write(b'{"event": 1}\n')
        prev = wl_fim._append_only_state(tmp_log)
        os.remove(tmp_log)
        cur = wl_fim._append_only_state(tmp_log)
        assert self._decide(prev, cur, tmp_log) == "tampered_removed"

    def test_in_place_rewrite_with_same_size_alerts(self, tmp_log):
        # Attacker changes a historical entry but keeps file size
        # the same to evade simple size monitoring.
        with open(tmp_log, "wb") as fh:
            fh.write(b'{"event": 1, "user": "alice"}\n')
        prev = wl_fim._append_only_state(tmp_log)
        same_len_payload = b'{"event": 1, "user": "BOBBB"}\n'
        # Sanity: same byte count
        assert len(same_len_payload) == prev["size"]
        with open(tmp_log, "wb") as fh:
            fh.write(same_len_payload)
        cur = wl_fim._append_only_state(tmp_log)
        assert self._decide(prev, cur, tmp_log) == "tampered_rewritten"

    def test_rewrite_then_append_alerts(self, tmp_log):
        # Attacker rewrites historical entries AND adds new ones,
        # producing a file with size > prev_size but mismatched
        # prefix.
        with open(tmp_log, "wb") as fh:
            fh.write(b'OLD-ENTRY-A\nOLD-ENTRY-B\n')
        prev = wl_fim._append_only_state(tmp_log)
        with open(tmp_log, "wb") as fh:
            fh.write(b'NEW-ENTRY-A\nOLD-ENTRY-B\nNEW-ENTRY-C\n')
        cur = wl_fim._append_only_state(tmp_log)
        assert self._decide(prev, cur, tmp_log) == "tampered_rewritten"

    def test_first_baseline_when_no_prev(self, tmp_log):
        with open(tmp_log, "wb") as fh:
            fh.write(b'{"event": 1}\n')
        prev = {}  # no baseline yet
        cur = wl_fim._append_only_state(tmp_log)
        assert self._decide(prev, cur, tmp_log) == "first_baseline"

    def test_first_creation_after_missing_baseline(self, tmp_log):
        # Recovery log doesn't exist yet; first time we see it,
        # don't alert — just baseline.
        os.remove(tmp_log)
        prev = {"exists": False, "size": 0, "prefix_hash": None}
        with open(tmp_log, "wb") as fh:
            fh.write(b'{"event": "first"}\n')
        cur = wl_fim._append_only_state(tmp_log)
        assert self._decide(prev, cur, tmp_log) == "first_baseline"
