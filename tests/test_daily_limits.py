"""
Integration tests for Daily Limits feature.

Verifies limit enforcement, configuration, reset, and boundary behavior.

Run:  cd tests && python -m unittest test_daily_limits -v
"""

import time
import unittest
from test_integration_base import (
    WLIntegrationTestCase, ADMIN, WLADMIN1, ANALYST1, ANALYST2,
    TEST_CSV, TEST_RULE, TEST_APP_CONTEXT,
    api_post, save_csv, get_csv_content, reset_daily_limits,
    wait_for_indexing,
)


def get_daily_limits(creds=WLADMIN1):
    """Read current daily limit config."""
    return api_post({"action": "get_daily_limits"}, creds=creds)


def set_daily_limits(limits, creds=WLADMIN1):
    """Update daily limits."""
    return api_post({"action": "set_daily_limits", "limits": limits},
                    creds=creds)


def get_analyst_usage(analyst=None, creds=WLADMIN1):
    """Get usage stats for an analyst."""
    payload = {"action": "get_analyst_usage"}
    if analyst:
        payload["analyst"] = analyst
    return api_post(payload, creds=creds)


def reset_usage(analyst=None, creds=WLADMIN1):
    """Reset usage counters."""
    payload = {"action": "reset_daily_usage"}
    if analyst:
        payload["analyst"] = analyst
    return api_post(payload, creds=creds)


class Test01_LimitConfig(WLIntegrationTestCase):
    """Tests for reading and setting daily limit configuration."""

    def test_get_limits_returns_defaults(self):
        """GET limits returns config with defaults and current limits."""
        s, d = get_daily_limits()
        self.assertEqual(s, 200)
        self.assertIn("limits", d)
        self.assertIn("defaults", d)
        limits = d["limits"]
        self.assertIn("row_removal", limits)
        self.assertIn("column_removal", limits)
        self.assertIn("revert", limits)

    def test_set_and_read_limits(self):
        """Set a custom limit, read it back, then restore."""
        # Read original
        s, orig = get_daily_limits()
        self.assertEqual(s, 200)
        orig_val = orig["limits"].get("row_removal", 10)

        # Set custom
        s2, d2 = set_daily_limits({"row_removal": 5})
        self.assertEqual(s2, 200)

        # Read back
        s3, d3 = get_daily_limits()
        self.assertEqual(d3["limits"]["row_removal"], 5)

        # Restore
        set_daily_limits({"row_removal": orig_val})

    def test_set_limit_to_zero_means_unlimited(self):
        """Setting a limit to 0 means unlimited (no enforcement)."""
        s, orig = get_daily_limits()
        orig_val = orig["limits"].get("row_removal", 10)

        set_daily_limits({"row_removal": 0})
        s2, d2 = get_daily_limits()
        self.assertEqual(d2["limits"]["row_removal"], 0)

        # Restore
        set_daily_limits({"row_removal": orig_val})

    def test_reset_factory_defaults(self):
        """reset_factory_defaults restores hardcoded defaults."""
        # Change something
        set_daily_limits({"row_removal": 99})
        s2, d2 = get_daily_limits()
        self.assertEqual(d2["limits"]["row_removal"], 99)

        # Reset factory
        reset_daily_limits(creds=ADMIN)

        # Check it's back to default
        s3, d3 = get_daily_limits()
        default_val = d3["defaults"]["row_removal"]
        self.assertEqual(d3["limits"]["row_removal"], default_val)


class Test02_LimitEnforcement(WLIntegrationTestCase):
    """Tests for limit enforcement during save operations."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Reset usage and set tight limits for testing
        reset_usage(creds=WLADMIN1)
        time.sleep(0.5)

    def _save_edit(self, creds=ADMIN):
        """Make a single-cell edit and save. Returns (status, result)."""
        headers, rows, mtime = self._load_csv(creds=creds)
        visible = [h for h in headers if not h.startswith("_")]
        rows[0][visible[0]] = f"limit_test_{int(time.time())}"
        return save_csv(headers, rows, comment="Limit test edit",
                        expected_mtime=mtime, creds=creds)

    def test_edit_within_limit_succeeds(self):
        """Edits within the daily limit succeed."""
        # Ensure limit is generous
        set_daily_limits({"row_edit": 50})
        reset_usage(analyst="admin", creds=WLADMIN1)
        time.sleep(0.3)

        s, r = self._save_edit()
        self.assertEqual(s, 200)

        # Restore limit
        reset_daily_limits(creds=ADMIN)

    def test_edit_exceeding_limit_returns_429(self):
        """Edits beyond the limit are blocked with 429."""
        # Set very tight limit
        set_daily_limits({"row_edit": 1})
        reset_usage(analyst="analyst1", creds=WLADMIN1)
        time.sleep(0.3)

        # First edit should succeed (unique value)
        headers, rows, mtime = self._load_csv(creds=ANALYST1)
        visible = [h for h in headers if not h.startswith("_")]
        original_val = rows[0].get(visible[0], "")
        rows[0][visible[0]] = f"limit_1st_{int(time.time())}"
        s1, _ = save_csv(headers, rows, comment="1st edit",
                         expected_mtime=mtime, creds=ANALYST1)
        self.assertEqual(s1, 200)

        # Second edit — reload to get fresh mtime, change to different value
        headers2, rows2, mtime2 = self._load_csv(creds=ANALYST1)
        rows2[0][visible[0]] = f"limit_2nd_{int(time.time())}"
        s2, d2 = save_csv(headers2, rows2, comment="2nd edit",
                          expected_mtime=mtime2, creds=ANALYST1)
        self.assertEqual(s2, 429,
                         f"Expected 429 daily limit, got {s2}: {d2}")

        # Restore
        reset_daily_limits(creds=ADMIN)
        reset_usage(analyst="analyst1", creds=WLADMIN1)

    def test_different_users_have_separate_limits(self):
        """Each user has their own limit counter."""
        set_daily_limits({"row_edit": 1})
        reset_usage(creds=WLADMIN1)
        time.sleep(0.3)

        # ANALYST1's first edit
        s1, _ = self._save_edit(creds=ANALYST1)
        self.assertEqual(s1, 200)

        # ANALYST2's first edit (separate counter, should succeed)
        headers, rows, mtime = self._load_csv()
        visible = [h for h in headers if not h.startswith("_")]
        rows[0][visible[0]] = f"limit_a2_{int(time.time())}"
        s2, d2 = save_csv(headers, rows, comment="Analyst2 limit test",
                          expected_mtime=mtime, creds=ANALYST2)
        self.assertEqual(s2, 200,
                         f"ANALYST2 should have separate counter: {d2}")

        # Restore
        reset_daily_limits(creds=ADMIN)
        reset_usage(creds=WLADMIN1)


class Test03_UsageTracking(WLIntegrationTestCase):
    """Tests for viewing and resetting usage counters."""

    def test_get_analyst_usage(self):
        """Can retrieve usage stats for an analyst."""
        s, d = get_analyst_usage(analyst="admin")
        self.assertEqual(s, 200)

    def test_reset_individual_analyst(self):
        """Can reset a single analyst's counters."""
        s, d = reset_usage(analyst="analyst1")
        self.assertEqual(s, 200)

    def test_reset_all_analysts(self):
        """Can reset all analysts' counters."""
        s, d = reset_usage()
        self.assertEqual(s, 200)


if __name__ == "__main__":
    unittest.main()
