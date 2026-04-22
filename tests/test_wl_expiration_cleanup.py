"""Unit tests for the scheduled expiration-cleanup scripted input.

Targets the partition-expired logic used by ``bin/wl_expiration_cleanup.py``.

History:
- Pre-fix: the module had its own ``remove_expired_rows`` that could not
  parse the ``YYYY-MM-DD HH:MM UTC`` format and used server-local time.
  That silently left UTC-dated expired rows in every CSV forever.
- Post-fix: the module delegates to ``wl_csv.remove_expired_rows`` and
  exposes a small ``partition_expired`` helper so the scripted input
  still has the expired-row DICTS for building the audit event.

The tests below drive that refactor and lock in the behavior.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple
from unittest import mock

# Make bin/ importable so ``import wl_expiration_cleanup`` works.
BIN_DIR = os.path.join(os.path.dirname(__file__), "..", "bin")
if BIN_DIR not in sys.path:
    sys.path.insert(0, BIN_DIR)


# ──────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────


def _utc_stamp(delta: timedelta, suffix: str = " UTC") -> str:
    """Render a timestamp in the new UTC-suffixed format."""
    return (datetime.now(timezone.utc) + delta).strftime("%Y-%m-%d %H:%M") + suffix


def _legacy_stamp(delta: timedelta) -> str:
    """Render a timestamp in the legacy (no-suffix) format."""
    return (datetime.now(timezone.utc) + delta).strftime("%Y-%m-%d %H:%M")


HEADERS = ["user", "Expires"]


# ──────────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────────


class TestModuleImport(unittest.TestCase):
    """Sanity: the module imports cleanly and exposes the helper."""

    def test_module_imports(self) -> None:
        import wl_expiration_cleanup  # noqa: F401

    def test_partition_expired_helper_exists(self) -> None:
        import wl_expiration_cleanup
        self.assertTrue(
            hasattr(wl_expiration_cleanup, "partition_expired"),
            "partition_expired() helper missing — required for audit event "
            "building in main(), and for these unit tests.",
        )


class TestPartitionExpiredUTCFormat(unittest.TestCase):
    """UTC-suffixed dates must be parsed and compared against UTC now.

    This is the core regression — the pre-fix implementation could not
    parse the "YYYY-MM-DD HH:MM UTC" format at all and silently kept
    every such row.
    """

    def test_past_utc_row_is_expired(self) -> None:
        from wl_expiration_cleanup import partition_expired
        rows: List[Dict[str, str]] = [
            {"user": "alice", "Expires": _utc_stamp(timedelta(days=-1))},
        ]
        kept, expired = partition_expired(HEADERS, rows)
        self.assertEqual(kept, [])
        self.assertEqual(len(expired), 1)
        self.assertEqual(expired[0]["user"], "alice")

    def test_future_utc_row_is_kept(self) -> None:
        from wl_expiration_cleanup import partition_expired
        rows: List[Dict[str, str]] = [
            {"user": "bob", "Expires": _utc_stamp(timedelta(days=1))},
        ]
        kept, expired = partition_expired(HEADERS, rows)
        self.assertEqual(len(kept), 1)
        self.assertEqual(expired, [])


class TestPartitionExpiredLegacyFormat(unittest.TestCase):
    """Legacy (no-suffix) dates are interpreted as UTC per 2026-04-19 policy.

    Before: compared against server-local time — non-deterministic across
    deployments. After: compared against UTC, matching the handler's
    ``tz_offset_minutes=0`` contract.
    """

    def test_past_legacy_row_is_expired(self) -> None:
        from wl_expiration_cleanup import partition_expired
        rows: List[Dict[str, str]] = [
            {"user": "carol", "Expires": _legacy_stamp(timedelta(days=-1))},
        ]
        kept, expired = partition_expired(HEADERS, rows)
        self.assertEqual(len(expired), 1)
        self.assertEqual(expired[0]["user"], "carol")

    def test_future_legacy_row_is_kept(self) -> None:
        from wl_expiration_cleanup import partition_expired
        rows: List[Dict[str, str]] = [
            {"user": "dave", "Expires": _legacy_stamp(timedelta(days=1))},
        ]
        kept, expired = partition_expired(HEADERS, rows)
        self.assertEqual(len(kept), 1)
        self.assertEqual(expired, [])


class TestPartitionExpiredEdgeCases(unittest.TestCase):
    def test_no_expire_column_keeps_all(self) -> None:
        from wl_expiration_cleanup import partition_expired
        rows: List[Dict[str, str]] = [
            {"user": "eve"},
            {"user": "frank"},
        ]
        kept, expired = partition_expired(["user"], rows)
        self.assertEqual(kept, rows)
        self.assertEqual(expired, [])

    def test_blank_expire_value_keeps_row(self) -> None:
        from wl_expiration_cleanup import partition_expired
        rows: List[Dict[str, str]] = [{"user": "grace", "Expires": ""}]
        kept, expired = partition_expired(HEADERS, rows)
        self.assertEqual(len(kept), 1)
        self.assertEqual(expired, [])

    def test_unparseable_date_keeps_row(self) -> None:
        from wl_expiration_cleanup import partition_expired
        rows: List[Dict[str, str]] = [
            {"user": "heidi", "Expires": "not a date"},
        ]
        kept, expired = partition_expired(HEADERS, rows)
        self.assertEqual(len(kept), 1)
        self.assertEqual(expired, [])

    def test_mixed_formats_both_handled(self) -> None:
        """CSV with UTC + legacy format rows: both expire if past."""
        from wl_expiration_cleanup import partition_expired
        rows: List[Dict[str, str]] = [
            {"user": "utc_past",    "Expires": _utc_stamp(timedelta(days=-1))},
            {"user": "utc_future",  "Expires": _utc_stamp(timedelta(days=1))},
            {"user": "legacy_past", "Expires": _legacy_stamp(timedelta(days=-1))},
            {"user": "legacy_future","Expires": _legacy_stamp(timedelta(days=1))},
            {"user": "no_date",     "Expires": ""},
        ]
        kept, expired = partition_expired(HEADERS, rows)
        kept_users = sorted(r["user"] for r in kept)
        expired_users = sorted(r["user"] for r in expired)
        self.assertEqual(
            kept_users, ["legacy_future", "no_date", "utc_future"]
        )
        self.assertEqual(expired_users, ["legacy_past", "utc_past"])


class TestPartitionExpiredIdentityAndCounts(unittest.TestCase):
    """Audit events iterate ``expired`` to build value_lines. The helper
    MUST return the same row objects (identity preserved) and its count
    MUST match the internal count from ``remove_expired_rows``.
    """

    def test_returned_rows_are_original_objects(self) -> None:
        from wl_expiration_cleanup import partition_expired
        r1 = {"user": "x", "Expires": _utc_stamp(timedelta(days=-1))}
        r2 = {"user": "y", "Expires": _utc_stamp(timedelta(days=1))}
        rows = [r1, r2]
        kept, expired = partition_expired(HEADERS, rows)
        self.assertIs(kept[0], r2, "kept rows must be same dict objects")
        self.assertIs(expired[0], r1, "expired rows must be same dict objects")

    def test_counts_are_consistent_with_wl_csv(self) -> None:
        """len(expired) from partition_expired must equal expired_count
        returned by the underlying ``wl_csv.remove_expired_rows``."""
        from wl_csv import remove_expired_rows as wl_csv_remove
        from wl_expiration_cleanup import partition_expired

        rows: List[Dict[str, str]] = [
            {"user": f"u{i}", "Expires": _utc_stamp(timedelta(days=-1))}
            for i in range(7)
        ] + [
            {"user": f"u{i}", "Expires": _utc_stamp(timedelta(days=1))}
            for i in range(7, 10)
        ]
        _, wl_csv_count = wl_csv_remove(HEADERS, list(rows), tz_offset_minutes=0)
        _, expired = partition_expired(HEADERS, list(rows))
        self.assertEqual(wl_csv_count, len(expired))
        self.assertEqual(wl_csv_count, 7)


class TestIndexAuditRetryAndFallback(unittest.TestCase):
    """index_audit() must never lose a record. CSV mutation has already
    happened by the time we get here; a silent 401 means a whitelist row
    vanished without a trail — exactly the compliance failure that drove
    this fix. The contract:

    * Successful POST on first try            → no recovery-log write
    * POST succeeds on retry                  → no recovery-log write
    * All POST attempts fail                  → fall back to recovery log
    * Empty session key                       → straight to recovery log
      (skip the REST call that's doomed to 401)
    * Recovery log itself fails to write      → splunkd.log CRITICAL msg
    """

    def setUp(self) -> None:
        # Re-import fresh each test so module-level patches don't leak.
        import importlib

        import wl_expiration_cleanup as module
        importlib.reload(module)
        self.module = module

        self.tmpdir = tempfile.mkdtemp(prefix="wl_exp_test_")
        self.recovery_path = os.path.join(self.tmpdir, "_recovery_log.jsonl")

        # Point RECOVERY_LOG at a tempdir so tests don't touch anything real.
        self._patcher = mock.patch.object(
            self.module, "RECOVERY_LOG", self.recovery_path
        )
        self._patcher.start()
        # Kill the retry sleep so tests are fast.
        self._sleep_patcher = mock.patch.object(
            self.module, "AUDIT_POST_RETRY_SLEEP", 0
        )
        self._sleep_patcher.start()

    def tearDown(self) -> None:
        self._patcher.stop()
        self._sleep_patcher.stop()
        # Best-effort cleanup
        try:
            if os.path.isfile(self.recovery_path):
                os.unlink(self.recovery_path)
            os.rmdir(self.tmpdir)
        except OSError:
            pass

    def _event(self) -> Dict:
        return {"action": "auto_removed", "csv_file": "DRxxx.csv",
                "removed_row_count": 1}

    def test_success_on_first_attempt_no_recovery_log(self) -> None:
        with mock.patch.object(
            self.module, "_post_audit_once", return_value=(True, "")
        ) as post:
            self.module.index_audit("abc", self._event())
        self.assertEqual(post.call_count, 1,
                         "should stop calling POST after first success")
        self.assertFalse(os.path.exists(self.recovery_path),
                         "no fallback write when POST succeeded")

    def test_retries_then_succeeds_no_recovery_log(self) -> None:
        # Fail once, then succeed.
        results = [(False, "HTTP 401"), (True, "")]
        with mock.patch.object(
            self.module, "_post_audit_once", side_effect=results
        ) as post:
            self.module.index_audit("abc", self._event())
        self.assertEqual(post.call_count, 2)
        self.assertFalse(os.path.exists(self.recovery_path),
                         "retry success must not write to recovery log")

    def test_persistent_401_falls_back_to_recovery_log(self) -> None:
        with mock.patch.object(
            self.module, "_post_audit_once",
            return_value=(False, "HTTP 401")
        ) as post:
            self.module.index_audit("abc", self._event())
        # 1 initial + AUDIT_POST_RETRIES attempts = 3 total
        self.assertEqual(post.call_count,
                         1 + self.module.AUDIT_POST_RETRIES)
        self.assertTrue(os.path.isfile(self.recovery_path))
        with open(self.recovery_path, encoding="utf-8") as fh:
            lines = [json.loads(line) for line in fh if line.strip()]
        self.assertEqual(len(lines), 1)
        rec = lines[0]
        self.assertEqual(rec["action"], "auto_removed")
        self.assertEqual(rec["source_script"], "wl_expiration_cleanup")
        self.assertTrue(rec["audit_post_failed"])
        self.assertEqual(rec["audit_post_error"], "HTTP 401")

    def test_empty_session_key_goes_straight_to_recovery_log(self) -> None:
        """When stdin delivered no session key (observed during splunkd
        restart races), skip the guaranteed-401 REST call and write the
        event directly to the fallback."""
        with mock.patch.object(
            self.module, "_post_audit_once"
        ) as post:
            self.module.index_audit("", self._event())
        self.assertEqual(post.call_count, 0,
                         "must not attempt authenticated POST with empty key")
        self.assertTrue(os.path.isfile(self.recovery_path))
        with open(self.recovery_path, encoding="utf-8") as fh:
            rec = json.loads(fh.readline())
        self.assertEqual(rec["audit_post_error"], "empty_session_key")

    def test_fallback_failure_logs_critical_to_stderr(self) -> None:
        # Point RECOVERY_LOG at a path we can't write to.
        unwritable = os.path.join(self.tmpdir, "nonexistent_dir",
                                  "cannot_create_here", "log.jsonl")
        with mock.patch.object(self.module, "RECOVERY_LOG", unwritable):
            with mock.patch.object(
                self.module, "_post_audit_once",
                return_value=(False, "HTTP 401")
            ):
                with mock.patch("os.makedirs",
                                side_effect=OSError("no perms")):
                    with mock.patch("sys.stderr") as fake_err:
                        self.module.index_audit("abc", self._event())
        # Expect at least one stderr write that contains CRITICAL.
        joined = "".join(
            call.args[0] for call in fake_err.write.call_args_list
            if call.args
        )
        self.assertIn("CRITICAL", joined)
        self.assertIn("LOST", joined)


if __name__ == "__main__":
    unittest.main()
