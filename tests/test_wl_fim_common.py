"""Unit tests for the shared FIM helpers (``bin/wl_fim_common.py``).

Three modules (``wl_fim``, ``wl_fim_watch``, ``wl_migrate_cooldowns``)
depended on these helpers producing byte-identical output. Phase 3b of
the graphify audit consolidated them here; these tests lock the
behavior in place so the next extraction doesn't accidentally regress
one caller while fixing another.

Origin: CLAUDE.md Decision Log 2026-04-19.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

_BIN_DIR = os.path.join(os.path.dirname(__file__), "..", "bin")
if _BIN_DIR not in sys.path:
    sys.path.insert(0, _BIN_DIR)


class TestReadSplunkGuid(unittest.TestCase):

    def _write_cfg(self, tmp: Path, body: str) -> str:
        cfg = tmp / "instance.cfg"
        cfg.write_text(body, encoding="utf-8")
        return str(cfg)

    def test_returns_guid_from_wellformed_cfg(self):
        from wl_fim_common import read_splunk_guid
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_cfg(
                Path(tmp), "[general]\nguid = ABC-123\n")
            self.assertEqual(read_splunk_guid(path), "ABC-123")

    def test_returns_empty_on_missing_file_nonstrict(self):
        from wl_fim_common import read_splunk_guid
        self.assertEqual(
            read_splunk_guid("/nonexistent/instance.cfg"), "")

    def test_raises_on_missing_file_strict(self):
        from wl_fim_common import read_splunk_guid
        with self.assertRaises(RuntimeError):
            read_splunk_guid(
                "/nonexistent/instance.cfg", strict=True)

    def test_raises_on_no_guid_line_strict(self):
        from wl_fim_common import read_splunk_guid
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_cfg(Path(tmp), "[general]\n")
            with self.assertRaises(RuntimeError):
                read_splunk_guid(path, strict=True)


class TestFileHashSha256(unittest.TestCase):

    def test_known_content(self):
        from wl_fim_common import file_hash_sha256
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "f.txt")
            Path(path).write_bytes(b"hello")
            # sha256(b"hello") — known value
            self.assertEqual(
                file_hash_sha256(path),
                "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e"
                "73043362938b9824")

    def test_missing_file_returns_none(self):
        from wl_fim_common import file_hash_sha256
        self.assertIsNone(file_hash_sha256("/nonexistent/file"))


class TestKvCollectionUrl(unittest.TestCase):

    def test_basic_url(self):
        from wl_fim_common import kv_collection_url
        self.assertEqual(
            kv_collection_url("wl_manager", "wl_cooldowns"),
            "https://localhost:8089/servicesNS/nobody/wl_manager"
            "/storage/collections/data/wl_cooldowns")

    def test_with_suffix(self):
        from wl_fim_common import kv_collection_url
        self.assertEqual(
            kv_collection_url(
                "wl_manager", "wl_cooldowns", "/state"),
            "https://localhost:8089/servicesNS/nobody/wl_manager"
            "/storage/collections/data/wl_cooldowns/state")


class TestQueueFimNotification(unittest.TestCase):

    def test_appends_jsonl_with_stable_id(self):
        from wl_fim_common import queue_fim_notification
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "queue.jsonl")
            event = {
                "timestamp": 1000,
                "action": "fim_file_modified",
                "monitored_path": "/opt/splunk/etc/apps/wl/bin/x.py",
                "severity": "HIGH",
                "source_script": "wl_fim",
                "details": "something changed",
            }
            queue_fim_notification(event, path)
            queue_fim_notification(event, path)
            lines = Path(path).read_text(
                encoding="utf-8").strip().split("\n")
            self.assertEqual(len(lines), 2)
            first = json.loads(lines[0])
            self.assertTrue(first["id"].startswith("fim_"))
            self.assertEqual(first["severity"], "HIGH")
            # Same event → same id (dedupable by the handler)
            self.assertEqual(json.loads(lines[1])["id"], first["id"])

    def test_falls_back_to_csv_file_when_path_absent(self):
        from wl_fim_common import queue_fim_notification
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "queue.jsonl")
            event = {
                "timestamp": 2000,
                "action": "fim_csv_modified",
                "csv_file": "DR123.csv",
                "severity": "CRITICAL",
            }
            queue_fim_notification(event, path)
            entry = json.loads(Path(path).read_text(encoding="utf-8"))
            self.assertEqual(entry["path"], "DR123.csv")
            # Fallback source_script when caller omitted it
            self.assertEqual(entry["source_script"], "wl_fim")

    def test_writes_through_missing_parent_dir(self):
        from wl_fim_common import queue_fim_notification
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "a", "b", "queue.jsonl")
            queue_fim_notification({
                "timestamp": 1, "action": "x", "severity": "HIGH",
            }, path)
            self.assertTrue(os.path.isfile(path))


if __name__ == "__main__":
    unittest.main()
