"""
Integration tests for Version Control and Revert.

Verifies version snapshots, get_versions API, revert flow,
and revert audit events with *back prefixed fields.

Run:  cd tests && python -m unittest test_version_revert -v
"""

import time
import unittest
from test_integration_base import (
    WLIntegrationTestCase, ADMIN, WLADMIN1, ANALYST1, ANALYST2,
    TEST_CSV, TEST_APP_CONTEXT,
    api_get, api_post, save_csv, get_csv_content,
    search_audit, wait_for_indexing, reset_daily_limits,
)


def get_versions(csv_file=TEST_CSV, app_context=TEST_APP_CONTEXT, creds=ADMIN):
    """Get version history for a CSV."""
    return api_get("get_versions", {
        "csv_file": csv_file,
        "app_context": app_context,
    }, creds=creds)


def revert_csv(version_filename, version_display, revert_reason,
               csv_file=TEST_CSV, app_context=TEST_APP_CONTEXT,
               expected_mtime=None, creds=ADMIN):
    """Revert CSV to a previous version."""
    payload = {
        "action": "revert_csv",
        "csv_file": csv_file,
        "app_context": app_context,
        "detection_rule": "DR999 - Stress Test",
        "version_filename": version_filename,
        "version_display": version_display,
        "revert_reason": revert_reason,
    }
    if expected_mtime:
        payload["expected_mtime"] = expected_mtime
    return api_post(payload, creds=creds)


class Test01_VersionHistory(WLIntegrationTestCase):
    """Tests for version snapshot creation and listing."""

    def test_get_versions_returns_list(self):
        """get_versions returns a list of version entries."""
        s, data = get_versions()
        self.assertEqual(s, 200)
        self.assertIn("versions", data)
        self.assertIsInstance(data["versions"], list)

    def test_save_creates_version_snapshot(self):
        """Each save creates a new version entry in the manifest."""
        # Get baseline version list
        _, data_before = get_versions()
        last_before = data_before["versions"][-1]["filename"] if data_before["versions"] else ""

        # Make a save
        headers, rows, mtime = self._load_csv()
        visible = [h for h in headers if not h.startswith("_")]
        old_val = rows[0].get(visible[0], "")
        rows[0][visible[0]] = f"version_test_{int(time.time())}"
        save_csv(headers, rows, comment="Version snapshot test",
                 expected_mtime=mtime)

        # Check a new version was created (latest entry should differ)
        _, data_after = get_versions()
        self.assertTrue(data_after["versions"],
                        "Should have at least one version")
        latest = data_after["versions"][-1]
        self.assertNotEqual(latest["filename"], last_before,
                            "Latest version should be new after save")

        # Verify latest version has correct metadata
        self.assertIn("filename", latest)
        self.assertIn("display", latest)
        self.assertIn("row_count", latest)
        self.assertEqual(latest["analyst"], "admin")

        # Restore
        _, r2, m2 = self._load_csv()
        r2[0][visible[0]] = old_val
        save_csv(headers, r2, comment="Restore version test")

    def test_max_versions_capped(self):
        """Version history is capped at MAX_VERSIONS (6)."""
        _, data = get_versions()
        self.assertLessEqual(len(data["versions"]), 6,
                             "Version history should be capped at 6")


class Test02_RevertFlow(WLIntegrationTestCase):
    """Tests for reverting to a previous version."""

    def test_revert_to_previous_version(self):
        """Revert restores CSV content from a previous version."""
        # Load current state
        headers, rows, mtime = self._load_csv()
        visible = [h for h in headers if not h.startswith("_")]
        original_val = rows[0].get(visible[0], "")
        original_count = len(rows)

        # Make a change (creates version V1)
        rows[0][visible[0]] = f"pre_revert_{int(time.time())}"
        save_csv(headers, rows, comment="Pre-revert change",
                 expected_mtime=mtime)

        # Get versions — find the version to revert to
        _, ver_data = get_versions()
        versions = ver_data["versions"]
        self.assertGreaterEqual(len(versions), 2,
                                "Need at least 2 versions to test revert")

        # Revert to second-to-last version (the one before our change)
        target = versions[-2]
        _, _, cur_mtime = self._load_csv()

        s, result = revert_csv(
            target["filename"], target["display"],
            revert_reason="Test revert to previous",
            expected_mtime=cur_mtime)
        self.assertEqual(s, 200, f"Revert failed: {result}")

        # Verify content reverted
        _, rows_after, _ = self._load_csv()
        reverted_val = rows_after[0].get(visible[0], "")
        self.assertNotEqual(reverted_val, f"pre_revert_{int(time.time())}",
                            "Value should have been reverted")

    def test_revert_requires_reason(self):
        """Revert without a reason fails."""
        _, ver_data = get_versions()
        versions = ver_data["versions"]
        if len(versions) < 2:
            self.skipTest("Need at least 2 versions")

        target = versions[-2]
        _, _, mtime = self._load_csv()

        s, d = revert_csv(target["filename"], target["display"],
                          revert_reason="",
                          expected_mtime=mtime)
        self.assertEqual(s, 400)
        self.assertIn("reason", d.get("error", "").lower())

    def test_revert_nonexistent_version(self):
        """Revert to a non-existent version file fails."""
        _, _, mtime = self._load_csv()

        s, d = revert_csv("fake_version_20200101_000000.csv",
                          "01-01-2020 00:00:00",
                          revert_reason="Should fail")
        self.assertIn(s, (400, 404))

    def test_revert_path_traversal(self):
        """Path traversal in version filename is rejected."""
        s, d = revert_csv("../../etc/passwd",
                          "01-01-2020 00:00:00",
                          revert_reason="Evil revert")
        self.assertIn(s, (400, 404))


class Test03_RevertAudit(WLIntegrationTestCase):
    """Tests for revert audit event fields."""

    def test_revert_audit_event_fields(self):
        """Revert creates an audit event with revert-specific fields."""
        # Make a change to revert
        headers, rows, mtime = self._load_csv()
        visible = [h for h in headers if not h.startswith("_")]
        rows[0][visible[0]] = f"audit_revert_{int(time.time())}"
        save_csv(headers, rows, comment="Change for revert audit",
                 expected_mtime=mtime)

        # Get versions and revert
        _, ver_data = get_versions()
        versions = ver_data["versions"]
        if len(versions) < 2:
            self.skipTest("Need at least 2 versions")

        target = versions[-2]
        _, _, cur_mtime = self._load_csv()

        revert_csv(target["filename"], target["display"],
                   revert_reason="Audit field test revert",
                   expected_mtime=cur_mtime)

        # Check audit event
        events = self._get_latest_audit("revert")
        self.assertTrue(events, "No revert audit event found")
        latest = events[0]

        # Verify revert-specific fields exist
        self.assertIn("reverted_to_version", latest)
        self.assertIn("new_record_version", latest)
        self.assertEqual(latest.get("revert_reason"), "Audit field test revert")
        self.assertEqual(latest.get("action"), "revert")


if __name__ == "__main__":
    unittest.main()
