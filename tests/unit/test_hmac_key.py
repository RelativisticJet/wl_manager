"""Unit tests for the shared HMAC helper module (``bin/wl_hmac_key.py``).

The helpers in this module are the single source of truth for the CSV
expected-hash registry's cryptographic operations. Two independent modules
depend on them producing byte-identical output:

- ``wl_csv.py`` (handler path) — writes the registry after every CSV save.
- ``wl_fim_watch.py`` (scripted-input path) — reads and verifies the
  registry, raising CRITICAL alerts on HMAC mismatch.

If these two ever produce different keys or checksums, every legitimate
CSV write would look like tampering to the FIM watcher. These tests lock
the invariant in place.

Origin: graphify audit 2026-04-19 (Findings B). See CLAUDE.md Decision Log.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Dict, List, Optional
from unittest import mock

# Make ``bin/`` importable when tests are run from the repo root.
_BIN_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "bin")
if _BIN_DIR not in sys.path:
    sys.path.insert(0, _BIN_DIR)


# ─────────────────────────────────────────────────────────────────────────
# Key derivation
# ─────────────────────────────────────────────────────────────────────────


class TestKeyDerivation(unittest.TestCase):
    """``derive_hash_registry_key`` reads the Splunk GUID and salts it."""

    def _write_instance_cfg(self, tmp: Path, guid: str) -> str:
        cfg = tmp / "instance.cfg"
        cfg.write_text(f"[general]\nguid = {guid}\n")
        return str(cfg)

    def test_key_is_32_bytes_sha256_output(self) -> None:
        from wl_hmac_key import derive_hash_registry_key
        key = derive_hash_registry_key()
        self.assertEqual(len(key), 32)

    def test_same_guid_produces_same_key(self) -> None:
        from wl_hmac_key import INSTANCE_CFG_PATH  # noqa: F401
        import wl_hmac_key
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_instance_cfg(Path(tmp), "DEADBEEF-CAFE")
            with mock.patch.object(wl_hmac_key, "INSTANCE_CFG_PATH", path):
                k1 = wl_hmac_key.derive_hash_registry_key()
                k2 = wl_hmac_key.derive_hash_registry_key()
        self.assertEqual(k1, k2)

    def test_different_guids_produce_different_keys(self) -> None:
        import wl_hmac_key
        with tempfile.TemporaryDirectory() as tmp:
            p1 = self._write_instance_cfg(Path(tmp) / "a", "ID-AAAA")
            p2 = self._write_instance_cfg(Path(tmp) / "b", "ID-BBBB")
            with mock.patch.object(wl_hmac_key, "INSTANCE_CFG_PATH", p1):
                k1 = wl_hmac_key.derive_hash_registry_key()
            with mock.patch.object(wl_hmac_key, "INSTANCE_CFG_PATH", p2):
                k2 = wl_hmac_key.derive_hash_registry_key()
        self.assertNotEqual(k1, k2)

    def test_missing_instance_cfg_falls_back_to_salt_only(self) -> None:
        """If instance.cfg is unreadable, the key is derived from salt alone.
        The watcher still verifies; the key is just weaker (global, not
        per-instance). Must not crash."""
        import wl_hmac_key
        with mock.patch.object(
            wl_hmac_key, "INSTANCE_CFG_PATH", "/nonexistent/path.cfg"
        ):
            key = wl_hmac_key.derive_hash_registry_key()
        self.assertEqual(len(key), 32)

    def _write_instance_cfg(self, tmp: Path, guid: str) -> str:  # noqa: F811
        tmp.mkdir(parents=True, exist_ok=True)
        cfg = tmp / "instance.cfg"
        cfg.write_text(f"[general]\nguid = {guid}\n")
        return str(cfg)


# ─────────────────────────────────────────────────────────────────────────
# Checksum
# ─────────────────────────────────────────────────────────────────────────


class TestChecksum(unittest.TestCase):
    def test_checksum_is_deterministic_for_same_input(self) -> None:
        from wl_hmac_key import compute_registry_checksum
        key = b"0" * 32
        data = {"csv_a": "aaa", "csv_b": "bbb"}
        c1 = compute_registry_checksum(data, key)
        c2 = compute_registry_checksum(data, key)
        self.assertEqual(c1, c2)

    def test_checksum_is_order_independent(self) -> None:
        """sort_keys=True makes dict insertion order irrelevant."""
        from wl_hmac_key import compute_registry_checksum
        key = b"0" * 32
        c1 = compute_registry_checksum({"a": "1", "b": "2"}, key)
        c2 = compute_registry_checksum({"b": "2", "a": "1"}, key)
        self.assertEqual(c1, c2)

    def test_checksum_excludes_existing_checksum_field(self) -> None:
        """If the input already has _checksum, it's stripped before signing —
        otherwise re-reading a signed registry would produce a new checksum."""
        from wl_hmac_key import compute_registry_checksum
        key = b"0" * 32
        c_without = compute_registry_checksum({"a": "1"}, key)
        c_with    = compute_registry_checksum({"a": "1", "_checksum": "stale"}, key)
        self.assertEqual(c_without, c_with)

    def test_checksum_changes_when_data_changes(self) -> None:
        from wl_hmac_key import compute_registry_checksum
        key = b"0" * 32
        c1 = compute_registry_checksum({"a": "1"}, key)
        c2 = compute_registry_checksum({"a": "2"}, key)
        self.assertNotEqual(c1, c2)

    def test_checksum_changes_when_key_changes(self) -> None:
        from wl_hmac_key import compute_registry_checksum
        data = {"a": "1"}
        c1 = compute_registry_checksum(data, b"0" * 32)
        c2 = compute_registry_checksum(data, b"1" * 32)
        self.assertNotEqual(c1, c2)


# ─────────────────────────────────────────────────────────────────────────
# Regression lock
# ─────────────────────────────────────────────────────────────────────────


class TestRegressionLock(unittest.TestCase):
    """Hardcoded inputs → hardcoded outputs. If this fails, the HMAC
    algorithm or salt has changed and existing registries are invalidated
    — that is a conscious breaking change that must update this test
    AND include a migration plan. Do NOT silently bump the expected
    value."""

    def test_known_key_for_known_guid(self) -> None:
        import wl_hmac_key
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "instance.cfg"
            cfg.write_text("[general]\nguid = 11111111-2222-3333-4444-555555555555\n")
            with mock.patch.object(wl_hmac_key, "INSTANCE_CFG_PATH", str(cfg)):
                key = wl_hmac_key.derive_hash_registry_key()
        # sha256(FIM_HMAC_SALT + b"11111111-2222-3333-4444-555555555555").hex()
        # Computed once, locked in. Regenerating requires explicit migration plan.
        self.assertEqual(
            key.hex(),
            "c97d2f6278bd9b110c693050e2a35a1b7d02febd6d475b881892a0bbadb7d73e",
        )

    def test_known_checksum_for_known_input(self) -> None:
        from wl_hmac_key import compute_registry_checksum
        key = bytes.fromhex(
            "c97d2f6278bd9b110c693050e2a35a1b7d02febd6d475b881892a0bbadb7d73e"
        )
        data = {"csv_a.csv": "hashA", "csv_b.csv": "hashB"}
        checksum = compute_registry_checksum(data, key)
        # hmac.new(key, json.dumps({"csv_a.csv":"hashA","csv_b.csv":"hashB"},
        #                          sort_keys=True).encode()).hexdigest()
        self.assertEqual(
            checksum,
            "6dbd54024d923882d3ba3d1effa830b3b074cf817099607ba8a45e8470cf6a63",
        )


# ─────────────────────────────────────────────────────────────────────────
# Read / verify
# ─────────────────────────────────────────────────────────────────────────


class TestReadExpectedHashes(unittest.TestCase):
    def _write_signed(
        self, tmp: Path, data: Dict[str, str], key: bytes
    ) -> str:
        """Helper: write a signed registry file the same way the
        production writer would."""
        from wl_hmac_key import compute_registry_checksum
        body: Dict[str, str] = {k: v for k, v in data.items()}
        body["_checksum"] = compute_registry_checksum(body, key)
        path = str(tmp / "registry.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(body, fh)
        return path

    def test_missing_file_returns_empty(self) -> None:
        from wl_hmac_key import read_expected_hashes
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "nonexistent.json")
            self.assertEqual(read_expected_hashes(path), {})

    def test_corrupt_json_returns_empty(self) -> None:
        from wl_hmac_key import read_expected_hashes
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "r.json"
            path.write_text("{not valid json")
            self.assertEqual(read_expected_hashes(str(path)), {})

    def test_legacy_file_without_checksum_is_accepted(self) -> None:
        """Pre-HMAC registry files have no ``_checksum`` key. These must
        be accepted (returned as-is) so deployments that predate the
        HMAC rollout don't break. Next write will re-sign them."""
        from wl_hmac_key import read_expected_hashes
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "legacy.json"
            path.write_text(json.dumps({"csv_a": "hash_a"}))
            result = read_expected_hashes(str(path))
        self.assertEqual(result, {"csv_a": "hash_a"})

    def test_valid_signature_returns_data(self) -> None:
        import wl_hmac_key
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(
                wl_hmac_key, "INSTANCE_CFG_PATH", "/nonexistent"
            ):
                key = wl_hmac_key.derive_hash_registry_key()
                path = self._write_signed(
                    Path(tmp), {"csv_a": "A", "csv_b": "B"}, key
                )
                result = wl_hmac_key.read_expected_hashes(path)
        self.assertEqual(result, {"csv_a": "A", "csv_b": "B"})

    def test_tampered_signature_returns_empty(self) -> None:
        """Someone mutated the data without re-signing → fail-closed."""
        import wl_hmac_key
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(
                wl_hmac_key, "INSTANCE_CFG_PATH", "/nonexistent"
            ):
                key = wl_hmac_key.derive_hash_registry_key()
                path = self._write_signed(Path(tmp), {"csv_a": "A"}, key)
                # Tamper: replace hash without re-signing
                with open(path, "r", encoding="utf-8") as fh:
                    body = json.load(fh)
                body["csv_a"] = "TAMPERED"
                with open(path, "w", encoding="utf-8") as fh:
                    json.dump(body, fh)
                result = wl_hmac_key.read_expected_hashes(path)
        self.assertEqual(result, {})

    def test_tampered_signature_triggers_on_tamper_callback(self) -> None:
        """FIM watcher passes ``on_tamper`` to emit a CRITICAL event.
        Handler passes None. Behavior must differ per caller."""
        import wl_hmac_key
        called: List[bool] = []

        def on_tamper() -> None:
            called.append(True)

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(
                wl_hmac_key, "INSTANCE_CFG_PATH", "/nonexistent"
            ):
                key = wl_hmac_key.derive_hash_registry_key()
                path = self._write_signed(Path(tmp), {"csv_a": "A"}, key)
                with open(path, "r", encoding="utf-8") as fh:
                    body = json.load(fh)
                body["csv_a"] = "TAMPERED"
                with open(path, "w", encoding="utf-8") as fh:
                    json.dump(body, fh)
                wl_hmac_key.read_expected_hashes(path, on_tamper=on_tamper)

        self.assertEqual(called, [True])

    def test_valid_signature_does_not_trigger_on_tamper(self) -> None:
        """Callback must not fire on happy path — guards against
        alert-on-every-read regressions."""
        import wl_hmac_key
        called: List[bool] = []

        def on_tamper() -> None:
            called.append(True)

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(
                wl_hmac_key, "INSTANCE_CFG_PATH", "/nonexistent"
            ):
                key = wl_hmac_key.derive_hash_registry_key()
                path = self._write_signed(Path(tmp), {"csv_a": "A"}, key)
                wl_hmac_key.read_expected_hashes(path, on_tamper=on_tamper)

        self.assertEqual(called, [])


# ─────────────────────────────────────────────────────────────────────────
# Write / round-trip
# ─────────────────────────────────────────────────────────────────────────


class TestWriteExpectedHashes(unittest.TestCase):
    def test_write_read_roundtrip(self) -> None:
        import wl_hmac_key
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "sub", "registry.json")
            with mock.patch.object(
                wl_hmac_key, "INSTANCE_CFG_PATH", "/nonexistent"
            ):
                wl_hmac_key.write_expected_hashes(
                    path, {"csv_a": "A", "csv_b": "B"}
                )
                result = wl_hmac_key.read_expected_hashes(path)
        self.assertEqual(result, {"csv_a": "A", "csv_b": "B"})

    def test_write_is_atomic_no_tmp_left_on_success(self) -> None:
        """Write goes through .tmp + rename; on success no .tmp lingers."""
        import wl_hmac_key
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "r.json")
            with mock.patch.object(
                wl_hmac_key, "INSTANCE_CFG_PATH", "/nonexistent"
            ):
                wl_hmac_key.write_expected_hashes(path, {"csv_a": "A"})
            self.assertTrue(os.path.isfile(path))
            self.assertFalse(os.path.isfile(path + ".tmp"))

    def test_write_creates_parent_dirs(self) -> None:
        import wl_hmac_key
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "deep", "nested", "r.json")
            with mock.patch.object(
                wl_hmac_key, "INSTANCE_CFG_PATH", "/nonexistent"
            ):
                wl_hmac_key.write_expected_hashes(path, {"csv_a": "A"})
            self.assertTrue(os.path.isfile(path))


# ─────────────────────────────────────────────────────────────────────────
# Parity with existing modules (critical: catches extraction mistakes)
# ─────────────────────────────────────────────────────────────────────────


class TestParityWithExistingModules(unittest.TestCase):
    """After the extraction, ``wl_csv`` and ``wl_fim_watch`` must both
    derive identical keys to ``wl_hmac_key``. This test catches any
    accidental divergence introduced by the refactor."""

    def test_wl_csv_matches_wl_hmac_key(self) -> None:
        import wl_csv
        import wl_hmac_key
        # After Phase 2 refactor: wl_csv._derive_hash_registry_key (or
        # the new public import) must produce the same bytes as the
        # shared helper.
        shared_key = wl_hmac_key.derive_hash_registry_key()
        csv_key = wl_csv._derive_hash_registry_key()  # type: ignore[attr-defined]
        self.assertEqual(shared_key, csv_key)


class TestEdgeCases(unittest.TestCase):
    """Cover the last 3 missing branches (lines 128, 160-165)."""

    def test_read_returns_empty_dict_when_top_level_is_not_dict(self) -> None:
        """Top-level JSON list → fail-closed empty dict (line 128)."""
        from wl_hmac_key import read_expected_hashes
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "registry.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(["not", "a", "dict"], fh)
            self.assertEqual(read_expected_hashes(path), {})

    def test_write_cleans_up_tempfile_on_replace_failure(self) -> None:
        """write_expected_hashes deletes <path>.tmp when os.replace fails
        (covers lines 160-165 — the try/except/cleanup branch).
        """
        import wl_hmac_key
        from wl_hmac_key import write_expected_hashes
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "registry.json")
            # Patch os.replace inside the module to fail; the with-open
            # block has already created and closed <path>.tmp by then,
            # so the cleanup branch (lines 161-164) runs.
            with mock.patch.object(wl_hmac_key.os, "replace",
                                   side_effect=OSError("simulated EXDEV")):
                with self.assertRaises(OSError):
                    write_expected_hashes(path, {"x.csv": "deadbeef"})
            # Temp file must NOT be left behind
            self.assertFalse(os.path.isfile(path + ".tmp"),
                             "tempfile leaked after write failure")
            # Real file must not exist either (os.replace was patched to fail)
            self.assertFalse(os.path.isfile(path),
                             "registry file created despite replace failure")

    def test_write_handles_double_failure_in_cleanup(self) -> None:
        """If os.remove inside the cleanup branch ALSO fails, the original
        exception still propagates (covers the inner try/except at lines
        162-164 — the OSError-swallowing branch).
        """
        import wl_hmac_key
        from wl_hmac_key import write_expected_hashes
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "registry.json")
            with mock.patch.object(wl_hmac_key.os, "replace",
                                   side_effect=OSError("simulated EXDEV")), \
                 mock.patch.object(wl_hmac_key.os, "remove",
                                   side_effect=OSError("cleanup also failed")):
                with self.assertRaises(OSError) as cm:
                    write_expected_hashes(path, {"x.csv": "deadbeef"})
            # Original error propagates, cleanup OSError is swallowed
            self.assertIn("simulated EXDEV", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
