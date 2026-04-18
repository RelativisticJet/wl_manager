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

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple

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


if __name__ == "__main__":
    unittest.main()
