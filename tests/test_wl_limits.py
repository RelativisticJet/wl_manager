"""Unit tests for the consolidated rate-limit module (``bin/wl_limits.py``).

Before Phase 3a (2026-04-19), ``wl_limits.py`` and ``wl_handler.py`` each
shipped an independent implementation of the same rate-limit primitives
that read/wrote DIFFERENT physical files:

- ``wl_handler`` local funcs → ``lookups/_versions/_{limit_config,daily_limits}.json``
- ``wl_limits`` module funcs → ``lookups/_{limit_config,daily_limits}.json``

Net effect: ``wl_approval.check_approval_gate`` called
``wl_limits.check_analyst_limit`` which read a file that nothing ever
wrote to, so approval-path rate-limit checks always returned
``current=0`` — a silent limit bypass.

This test module locks in the canonical behavior after the merge:
- Both config AND counters live under ``lookups/_versions/``.
- ``get_counter_period_key`` supports all 5 reset frequencies.
- ``read_limit_config`` validates HMAC integrity + migrates legacy keys.
- ``check_admin_daily_limit`` reads ``admin_limits`` sub-config with
  ``admin_`` action-type prefix (matches handler's prior local semantics).

Origin: graphify audit Pair A, CLAUDE.md Decision Log 2026-04-19.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

# Make ``bin/`` importable when tests run from the repo root.
_BIN_DIR = os.path.join(os.path.dirname(__file__), "..", "bin")
if _BIN_DIR not in sys.path:
    sys.path.insert(0, _BIN_DIR)


def _fresh_tmp_lookups():
    """Return a TemporaryDirectory context for an isolated lookups root.

    Patches ``wl_limits.OWN_LOOKUPS`` so every function under test resolves
    paths into the fresh dir. The caller is responsible for exiting the
    context to clean up.
    """
    return tempfile.TemporaryDirectory()


def _patch_lookups(tmp: str):
    """Return an ``mock.patch`` for ``wl_limits.OWN_LOOKUPS``."""
    import wl_limits
    return mock.patch.object(wl_limits, "OWN_LOOKUPS", tmp)


# ─────────────────────────────────────────────────────────────────────────
# Canonical path resolution (regression lock)
# ─────────────────────────────────────────────────────────────────────────


class TestCanonicalPaths(unittest.TestCase):
    """Both files MUST live under ``_versions/`` after the merge.

    Regression lock: if anyone reverts to top-level ``lookups/``, the
    wl_approval path silently goes back to reading an empty file.
    """

    def test_limit_config_path_resolves_under_versions(self):
        import wl_limits
        with _fresh_tmp_lookups() as tmp, _patch_lookups(tmp):
            path = wl_limits._get_limit_config_path()
            self.assertTrue(path.endswith(
                os.path.join("_versions", "_limit_config.json")))
            self.assertTrue(os.path.isdir(
                os.path.join(tmp, "_versions")))

    def test_daily_limits_path_resolves_under_versions(self):
        import wl_limits
        with _fresh_tmp_lookups() as tmp, _patch_lookups(tmp):
            path = wl_limits._get_daily_limits_path()
            self.assertTrue(path.endswith(
                os.path.join("_versions", "_daily_limits.json")))


# ─────────────────────────────────────────────────────────────────────────
# Integrity checksum (regression lock — hardcoded known bytes)
# ─────────────────────────────────────────────────────────────────────────


class TestChecksumRegressionLock(unittest.TestCase):
    """``compute_config_checksum`` is the handler's anti-tamper signature.

    Hardcoded input → hardcoded output. Any change to the salt or the
    serialization invalidates every config file in production, so this
    is a breaking change guard.
    """

    def test_known_checksum_for_pinned_config(self):
        from wl_limits import compute_config_checksum
        # Minimal config subset — deliberately small so the test doesn't
        # need to evolve with DEFAULT_LIMITS.
        cfg = {"row_removal": 10, "revert": 3}
        # HMAC-SHA256(b"wl_manager_config_integrity_v1",
        #             json.dumps({"revert": 3, "row_removal": 10},
        #                        sort_keys=True, default=str))
        # Locking in handler's historical salt + serialization.
        expected = (
            "2ba63046be629935d770b645d0a728e9"
            "23109ade415ca3000ca3d4ee8547a5c4"
        )
        actual = compute_config_checksum(cfg)
        self.assertEqual(actual, expected,
                         "Checksum drifted. If this is intentional, "
                         "every existing deployment's config becomes "
                         "invalid. Requires a migration.")

    def test_checksum_excludes_existing_checksum_key(self):
        from wl_limits import compute_config_checksum
        cfg_without = {"row_removal": 10}
        cfg_with = {"row_removal": 10, "_checksum": "stale_value"}
        self.assertEqual(compute_config_checksum(cfg_without),
                         compute_config_checksum(cfg_with))

    def test_checksum_is_order_independent(self):
        from wl_limits import compute_config_checksum
        a = {"row_removal": 10, "revert": 3}
        b = {"revert": 3, "row_removal": 10}
        self.assertEqual(compute_config_checksum(a),
                         compute_config_checksum(b))


# ─────────────────────────────────────────────────────────────────────────
# read_limit_config — defaults, integrity, migration
# ─────────────────────────────────────────────────────────────────────────


class TestReadLimitConfig(unittest.TestCase):

    def test_missing_file_returns_defaults(self):
        import wl_limits
        from wl_constants import DEFAULT_LIMITS
        with _fresh_tmp_lookups() as tmp, _patch_lookups(tmp):
            cfg = wl_limits.read_limit_config()
            for key in DEFAULT_LIMITS:
                self.assertIn(key, cfg)

    def test_missing_keys_are_backfilled_from_defaults(self):
        import wl_limits
        from wl_constants import DEFAULT_LIMITS
        with _fresh_tmp_lookups() as tmp, _patch_lookups(tmp):
            partial = {"row_removal": 42}
            path = wl_limits._get_limit_config_path()
            Path(path).write_text(json.dumps(partial), encoding="utf-8")
            cfg = wl_limits.read_limit_config()
            self.assertEqual(cfg["row_removal"], 42)  # preserved
            # backfilled
            self.assertEqual(cfg["revert"], DEFAULT_LIMITS["revert"])

    def test_corrupt_json_falls_back_to_defaults(self):
        import wl_limits
        from wl_constants import DEFAULT_LIMITS
        with _fresh_tmp_lookups() as tmp, _patch_lookups(tmp):
            path = wl_limits._get_limit_config_path()
            Path(path).write_text("{not json", encoding="utf-8")
            cfg = wl_limits.read_limit_config()
            self.assertEqual(cfg["row_removal"],
                             DEFAULT_LIMITS["row_removal"])

    def test_tampered_checksum_logs_warning_but_returns_data(self):
        import wl_limits
        with _fresh_tmp_lookups() as tmp, _patch_lookups(tmp):
            path = wl_limits._get_limit_config_path()
            Path(path).write_text(json.dumps({
                "row_removal": 42,
                "_checksum": "0" * 64,  # wrong
            }), encoding="utf-8")
            # Matches handler's historical behavior: log and continue,
            # don't reset to defaults (manual tamper recovery is painful).
            with mock.patch.object(wl_limits, "_logger") as logger:
                cfg = wl_limits.read_limit_config()
                # Warning was emitted
                self.assertTrue(logger.warning.called)
            self.assertEqual(cfg["row_removal"], 42)

    def test_reset_hour_utc_migrates_to_reset_time_utc(self):
        import wl_limits
        with _fresh_tmp_lookups() as tmp, _patch_lookups(tmp):
            path = wl_limits._get_limit_config_path()
            Path(path).write_text(json.dumps({
                "row_removal": 10,
                "reset_hour_utc": 3,  # legacy int field
            }), encoding="utf-8")
            cfg = wl_limits.read_limit_config()
            self.assertEqual(cfg.get("reset_time_utc"), "03:00")
            self.assertNotIn("reset_hour_utc", cfg)

    def test_reset_hour_utc_invalid_falls_back_to_00_00(self):
        import wl_limits
        with _fresh_tmp_lookups() as tmp, _patch_lookups(tmp):
            path = wl_limits._get_limit_config_path()
            Path(path).write_text(json.dumps({
                "reset_hour_utc": "bogus",
            }), encoding="utf-8")
            cfg = wl_limits.read_limit_config()
            self.assertEqual(cfg.get("reset_time_utc"), "00:00")


# ─────────────────────────────────────────────────────────────────────────
# write_limit_config — checksum round-trip
# ─────────────────────────────────────────────────────────────────────────


class TestWriteLimitConfig(unittest.TestCase):

    def test_write_then_read_roundtrip_passes_integrity(self):
        import wl_limits
        with _fresh_tmp_lookups() as tmp, _patch_lookups(tmp):
            wl_limits.write_limit_config({"row_removal": 7})
            # No warning should fire on integrity check.
            with mock.patch.object(wl_limits, "_logger") as logger:
                cfg = wl_limits.read_limit_config()
                self.assertFalse(logger.warning.called)
            self.assertEqual(cfg["row_removal"], 7)

    def test_write_persists_checksum_to_disk(self):
        import wl_limits
        with _fresh_tmp_lookups() as tmp, _patch_lookups(tmp):
            wl_limits.write_limit_config({"row_removal": 7})
            path = wl_limits._get_limit_config_path()
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
            self.assertIn("_checksum", raw)
            self.assertEqual(len(raw["_checksum"]), 64)


# ─────────────────────────────────────────────────────────────────────────
# get_counter_period_key — 5-frequency regression lock
# ─────────────────────────────────────────────────────────────────────────


class TestCounterPeriodKey(unittest.TestCase):
    """Locks in all five reset-frequency semantics.

    For each frequency, pins a known ``now`` against a known boundary
    config, then asserts the period key. Any drift means some user's
    counters bucket differently than before — i.e. a silent reset.
    """

    def _patch_now(self, dt_value):
        """Patch datetime.now() inside wl_limits to return dt_value."""
        import wl_limits
        mock_dt = mock.MagicMock(wraps=datetime)
        mock_dt.now.return_value = dt_value
        return mock.patch.object(wl_limits, "datetime", mock_dt)

    def test_never_returns_permanent(self):
        from wl_limits import get_counter_period_key
        key = get_counter_period_key({"reset_frequency": "never"})
        self.assertEqual(key, "permanent")

    def test_daily_after_boundary_returns_today(self):
        from wl_limits import get_counter_period_key
        cfg = {"reset_frequency": "daily", "reset_time_utc": "03:00"}
        now = datetime(2026, 4, 19, 10, 0, tzinfo=timezone.utc)
        with self._patch_now(now):
            self.assertEqual(get_counter_period_key(cfg), "2026-04-19")

    def test_daily_before_boundary_returns_yesterday(self):
        from wl_limits import get_counter_period_key
        cfg = {"reset_frequency": "daily", "reset_time_utc": "03:00"}
        now = datetime(2026, 4, 19, 1, 0, tzinfo=timezone.utc)
        with self._patch_now(now):
            self.assertEqual(get_counter_period_key(cfg), "2026-04-18")

    def test_weekly_returns_iso_format(self):
        from wl_limits import get_counter_period_key
        cfg = {"reset_frequency": "weekly",
               "reset_time_utc": "00:00",
               "reset_day_of_week": 0}  # Monday
        # 2026-04-20 is a Monday
        now = datetime(2026, 4, 20, 12, 0, tzinfo=timezone.utc)
        with self._patch_now(now):
            key = get_counter_period_key(cfg)
            self.assertTrue(key.startswith("2026-W"),
                            f"expected YYYY-Www... got {key}")
            self.assertIn("Mon", key)

    def test_monthly_after_boundary_returns_current_month(self):
        from wl_limits import get_counter_period_key
        cfg = {"reset_frequency": "monthly",
               "reset_time_utc": "00:00",
               "reset_day_of_month": 1}
        now = datetime(2026, 4, 15, 12, 0, tzinfo=timezone.utc)
        with self._patch_now(now):
            self.assertEqual(get_counter_period_key(cfg), "2026-04")

    def test_monthly_before_boundary_returns_previous_month(self):
        from wl_limits import get_counter_period_key
        cfg = {"reset_frequency": "monthly",
               "reset_time_utc": "00:00",
               "reset_day_of_month": 20}
        # Before day 20 of April = still in March's period
        now = datetime(2026, 4, 15, 12, 0, tzinfo=timezone.utc)
        with self._patch_now(now):
            self.assertEqual(get_counter_period_key(cfg), "2026-03")

    def test_monthly_clamps_day_31_on_short_months(self):
        from wl_limits import get_counter_period_key
        cfg = {"reset_frequency": "monthly",
               "reset_time_utc": "00:00",
               "reset_day_of_month": 31}
        # Feb 28 → day clamps to 28, boundary is met, return Feb key.
        now = datetime(2026, 2, 28, 12, 0, tzinfo=timezone.utc)
        with self._patch_now(now):
            self.assertEqual(get_counter_period_key(cfg), "2026-02")

    def test_yearly_after_boundary_returns_current_year(self):
        from wl_limits import get_counter_period_key
        cfg = {"reset_frequency": "yearly",
               "reset_time_utc": "00:00",
               "reset_month": 1,
               "reset_day_of_year": 1}
        now = datetime(2026, 4, 15, 12, 0, tzinfo=timezone.utc)
        with self._patch_now(now):
            self.assertEqual(get_counter_period_key(cfg), "2026")

    def test_yearly_before_boundary_returns_previous_year(self):
        from wl_limits import get_counter_period_key
        cfg = {"reset_frequency": "yearly",
               "reset_time_utc": "00:00",
               "reset_month": 7,
               "reset_day_of_year": 1}
        now = datetime(2026, 4, 15, 12, 0, tzinfo=timezone.utc)
        with self._patch_now(now):
            self.assertEqual(get_counter_period_key(cfg), "2025")

    def test_invalid_time_format_falls_back_to_00_00(self):
        from wl_limits import get_counter_period_key
        cfg = {"reset_frequency": "daily",
               "reset_time_utc": "invalid"}
        now = datetime(2026, 4, 19, 12, 0, tzinfo=timezone.utc)
        with self._patch_now(now):
            # With reset at 00:00, any time in the day is AFTER boundary.
            self.assertEqual(get_counter_period_key(cfg), "2026-04-19")


# ─────────────────────────────────────────────────────────────────────────
# Admin-limits semantics — separate bucket, admin_ action prefix
# ─────────────────────────────────────────────────────────────────────────


class TestAdminLimitsSeparation(unittest.TestCase):
    """Admin counters use their own sub-config and ``admin_`` action prefix.

    The prior wl_limits.check_admin_limit read from the MAIN config
    (broken). After the merge, check_admin_daily_limit reads from
    config['admin_limits'] and tracks under admin_<action_type>.
    """

    def test_admin_counter_uses_admin_prefix(self):
        import wl_limits
        from wl_constants import DEFAULT_ADMIN_LIMITS
        with _fresh_tmp_lookups() as tmp, _patch_lookups(tmp):
            # Write a config with admin_limits sub-config
            wl_limits.write_limit_config({
                "admin_limits": dict(DEFAULT_ADMIN_LIMITS),
            })
            wl_limits.increment_admin_daily_limit("alice", "csv_save", 1)

            counters = wl_limits.read_daily_limits()
            # Counter keyed by admin_<action>, not plain <action>
            for period_key, per_user in counters.items():
                self.assertIn("alice", per_user)
                self.assertIn("admin_csv_save", per_user["alice"])
                self.assertNotIn("csv_save", per_user["alice"])

    def test_check_admin_daily_limit_reads_admin_sub_config(self):
        import wl_limits
        with _fresh_tmp_lookups() as tmp, _patch_lookups(tmp):
            wl_limits.write_limit_config({
                "admin_limits": {
                    "csv_save": 3,
                    "reset_frequency": "daily",
                    "reset_time_utc": "00:00",
                },
            })
            allowed, current, maximum = \
                wl_limits.check_admin_daily_limit("alice", "csv_save", 1)
            self.assertTrue(allowed)
            self.assertEqual(current, 0)
            self.assertEqual(maximum, 3)

    def test_check_admin_permission_returns_toggle(self):
        import wl_limits
        with _fresh_tmp_lookups() as tmp, _patch_lookups(tmp):
            wl_limits.write_limit_config({
                "admin_limits": {"allow_admin_purge_trash": False},
            })
            self.assertFalse(
                wl_limits.check_admin_permission("allow_admin_purge_trash"))

    def test_admin_period_key_independent_of_main_schedule(self):
        import wl_limits
        with _fresh_tmp_lookups() as tmp, _patch_lookups(tmp):
            wl_limits.write_limit_config({
                "reset_frequency": "daily",
                "reset_time_utc": "00:00",
                "admin_limits": {
                    "reset_frequency": "monthly",
                    "reset_time_utc": "00:00",
                    "reset_day_of_month": 1,
                },
            })
            now = datetime(2026, 4, 15, 12, 0, tzinfo=timezone.utc)
            mock_dt = mock.MagicMock(wraps=datetime)
            mock_dt.now.return_value = now
            with mock.patch.object(wl_limits, "datetime", mock_dt):
                admin_key = wl_limits.get_admin_counter_period_key()
            self.assertEqual(admin_key, "2026-04")


# ─────────────────────────────────────────────────────────────────────────
# Analyst-limit semantics (backward compatibility)
# ─────────────────────────────────────────────────────────────────────────


class TestAnalystLimit(unittest.TestCase):

    def test_admin_role_is_exempt(self):
        from wl_limits import check_analyst_limit
        # roles set includes admin — returns unlimited
        with _fresh_tmp_lookups() as tmp, _patch_lookups(tmp):
            allowed, current, maximum = check_analyst_limit(
                "alice", "row_removal", 999, roles=["admin"])
            self.assertTrue(allowed)
            self.assertEqual(maximum, -1)

    def test_limit_disabled_returns_false(self):
        import wl_limits
        with _fresh_tmp_lookups() as tmp, _patch_lookups(tmp):
            wl_limits.write_limit_config({"row_removal": 0})
            allowed, _, maximum = wl_limits.check_analyst_limit(
                "alice", "row_removal", 1, roles=["wl_editor"])
            self.assertFalse(allowed)
            self.assertEqual(maximum, 0)

    def test_over_limit_returns_false(self):
        import wl_limits
        with _fresh_tmp_lookups() as tmp, _patch_lookups(tmp):
            wl_limits.write_limit_config({"row_removal": 2})
            wl_limits.increment_daily_limit("alice", "row_removal", 2)
            allowed, current, maximum = wl_limits.check_analyst_limit(
                "alice", "row_removal", 1, roles=["wl_editor"])
            self.assertFalse(allowed)
            self.assertEqual(current, 2)
            self.assertEqual(maximum, 2)


# ─────────────────────────────────────────────────────────────────────────
# Increment cap + old-period cleanup
# ─────────────────────────────────────────────────────────────────────────


class TestIncrementCapAndCleanup(unittest.TestCase):

    def test_old_periods_are_pruned_on_increment(self):
        import wl_limits
        with _fresh_tmp_lookups() as tmp, _patch_lookups(tmp):
            # Pre-seed with an ancient period
            counters = {
                "1970-01-01": {"ghost": {"row_removal": 99}},
            }
            wl_limits.write_daily_limits(counters)
            wl_limits.write_limit_config({"row_removal": 10})
            wl_limits.increment_daily_limit("alice", "row_removal", 1)
            after = wl_limits.read_daily_limits()
            self.assertNotIn("1970-01-01", after)

    def test_permanent_mode_never_prunes(self):
        import wl_limits
        with _fresh_tmp_lookups() as tmp, _patch_lookups(tmp):
            wl_limits.write_limit_config({
                "reset_frequency": "never",
            })
            wl_limits.increment_daily_limit("alice", "row_removal", 3)
            after = wl_limits.read_daily_limits()
            self.assertIn("permanent", after)
            self.assertEqual(
                after["permanent"]["alice"]["row_removal"], 3)

    def test_overflow_bucket_when_tracked_analysts_exceeds_cap(self):
        import wl_limits
        from wl_constants import MAX_TRACKED_ANALYSTS
        with _fresh_tmp_lookups() as tmp, _patch_lookups(tmp):
            wl_limits.write_limit_config({"row_removal": 10})
            # Fill up to cap — each is a unique user
            for i in range(MAX_TRACKED_ANALYSTS):
                wl_limits.increment_daily_limit(
                    f"user_{i}", "row_removal", 1)
            # This user should land in __overflow__
            wl_limits.increment_daily_limit("user_overflow", "row_removal", 1)
            counters = wl_limits.read_daily_limits()
            any_period = next(iter(counters.values()))
            self.assertIn("__overflow__", any_period)


# ─────────────────────────────────────────────────────────────────────────
# Counter-file location sanity: counters land under _versions/
# ─────────────────────────────────────────────────────────────────────────


class TestCountersWrittenUnderVersions(unittest.TestCase):
    """Regression lock for the original drift bug.

    Anything that writes counters MUST write into ``_versions/`` so the
    approval-gate read path sees them.
    """

    def test_increment_creates_file_under_versions(self):
        import wl_limits
        with _fresh_tmp_lookups() as tmp, _patch_lookups(tmp):
            wl_limits.increment_daily_limit("alice", "row_removal", 1)
            expected = os.path.join(tmp, "_versions", "_daily_limits.json")
            self.assertTrue(os.path.isfile(expected),
                            f"Counters not found at {expected}")

    def test_top_level_path_is_not_used(self):
        import wl_limits
        with _fresh_tmp_lookups() as tmp, _patch_lookups(tmp):
            wl_limits.increment_daily_limit("alice", "row_removal", 1)
            stray = os.path.join(tmp, "_daily_limits.json")
            self.assertFalse(os.path.isfile(stray),
                             "Legacy top-level counter file created — "
                             "silent approval-gate bypass reintroduced.")


if __name__ == "__main__":
    unittest.main()
