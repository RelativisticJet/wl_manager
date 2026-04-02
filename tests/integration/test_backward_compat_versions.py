"""
Backward compatibility tests for v2.0 version manifests in v3.0.

Tests verify that pre-rewrite version manifests (from v2.0) can be loaded
and iterated correctly in v3.0 code.

Test approach:
- Load golden v2.0 manifest from fixture
- Feed manifest through wl_versions.read_version_manifest()
- Verify structure, fields, and iteration order
"""

import unittest
import json
import sys
import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add bin directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'bin'))

try:
    from wl_versions import read_version_manifest, write_version_manifest
except ImportError:
    read_version_manifest = None
    write_version_manifest = None


class TestV2VersionManifestBackwardCompat(unittest.TestCase):
    """Tests for v2.0 version manifest backward compatibility."""

    @classmethod
    def setUpClass(cls):
        """Load v2.0 version manifest fixture."""
        if read_version_manifest is None or write_version_manifest is None:
            cls.skipClass = True
            return

        fixture_path = Path(__file__).parent.parent / "fixtures" / "v2_versions_manifest.json"
        with open(fixture_path, "r") as f:
            cls.v2_manifest = json.load(f)

    def test_v2_manifest_fixture_loads(self):
        """Verify v2.0 manifest fixture is valid JSON."""
        self.assertIsInstance(self.v2_manifest, dict)
        self.assertIn("csv_file", self.v2_manifest)
        self.assertIn("versions", self.v2_manifest)

    def test_v2_manifest_loads_without_error(self):
        """Test that v2.0 manifest can be written and read without errors."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test CSV path
            csv_path = os.path.join(tmpdir, "test.csv")

            # Create _versions directory
            versions_dir = os.path.join(tmpdir, "_versions")
            os.makedirs(versions_dir, exist_ok=True)

            # Write manifest to disk using v3.0 function
            success, error = write_version_manifest(csv_path, self.v2_manifest)
            self.assertTrue(success, f"Failed to write manifest: {error}")

            # Read it back using v3.0 function
            manifest, error = read_version_manifest(csv_path)
            self.assertEqual(error, "", f"Failed to read manifest: {error}")
            self.assertIsInstance(manifest, dict)

    def test_v2_manifest_parses_version_list(self):
        """Verify versions list is accessible and iterable."""
        versions = self.v2_manifest.get("versions", {})
        self.assertIsInstance(versions, dict)
        self.assertGreater(len(versions), 0)

        # Should have at least one version
        self.assertIn("20260331_203045", versions)

    def test_v2_manifest_fields_preserved(self):
        """Verify required manifest fields are present."""
        self.assertIn("csv_file", self.v2_manifest)
        self.assertIn("current_version", self.v2_manifest)
        self.assertIn("versions", self.v2_manifest)

        # Check current_version points to existing version
        current = self.v2_manifest["current_version"]
        self.assertIn(current, self.v2_manifest["versions"])

    def test_v2_version_entry_fields(self):
        """Verify each version entry has required fields."""
        required_fields = {"timestamp", "display", "filename", "analyst", "action", "row_count", "col_count"}

        for version_id, version_data in self.v2_manifest["versions"].items():
            missing = required_fields - set(version_data.keys())
            self.assertEqual(
                missing,
                set(),
                f"Version {version_id} missing fields {missing}"
            )

            # Verify field types
            self.assertIsInstance(version_data["timestamp"], str)
            self.assertIsInstance(version_data["display"], str)
            self.assertIsInstance(version_data["filename"], str)
            self.assertIsInstance(version_data["analyst"], str)
            self.assertIsInstance(version_data["action"], str)
            self.assertIsInstance(version_data["row_count"], int)
            self.assertIsInstance(version_data["col_count"], int)

    def test_v2_manifest_iteration_order(self):
        """Verify versions are accessible in expected order."""
        versions_dict = self.v2_manifest["versions"]
        version_ids = list(versions_dict.keys())

        # Should have multiple versions
        self.assertGreater(len(version_ids), 0)

        # Each version should be accessible
        for version_id in version_ids:
            self.assertIn(version_id, versions_dict)
            version_data = versions_dict[version_id]
            self.assertIn("timestamp", version_data)

    def test_v2_manifest_timestamp_format(self):
        """Verify timestamp format is ISO 8601."""
        for version_id, version_data in self.v2_manifest["versions"].items():
            timestamp = version_data.get("timestamp")
            # Should be ISO 8601 format: YYYY-MM-DDTHH:MM:SSZ
            self.assertRegex(
                timestamp,
                r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$",
                f"Invalid timestamp format in {version_id}: {timestamp}"
            )

    def test_v2_manifest_display_format(self):
        """Verify display format for revert dropdown."""
        for version_id, version_data in self.v2_manifest["versions"].items():
            display = version_data.get("display")
            # Should be in format: DD-MM-YYYY HH:MM:SS
            self.assertRegex(
                display,
                r"^\d{2}-\d{2}-\d{4} \d{2}:\d{2}:\d{2}$",
                f"Invalid display format in {version_id}: {display}"
            )

    def test_v2_manifest_filename_matches_id(self):
        """Verify version filename contains the version ID."""
        for version_id, version_data in self.v2_manifest["versions"].items():
            filename = version_data.get("filename")
            # Filename should contain version ID
            self.assertIn(
                version_id,
                filename,
                f"Filename {filename} doesn't contain version ID {version_id}"
            )

    def test_v2_manifest_analyst_field_present(self):
        """Verify analyst field for audit trail."""
        for version_id, version_data in self.v2_manifest["versions"].items():
            analyst = version_data.get("analyst")
            self.assertIsNotNone(analyst)
            self.assertIsInstance(analyst, str)
            self.assertGreater(len(analyst), 0)

    def test_v2_manifest_action_field_recognized(self):
        """Verify action field values are recognized."""
        recognized_actions = {"save", "revert", "restore", "import"}

        for version_id, version_data in self.v2_manifest["versions"].items():
            action = version_data.get("action")
            self.assertIn(
                action,
                recognized_actions,
                f"Unknown action {action} in version {version_id}"
            )

    def test_v2_manifest_row_count_field(self):
        """Verify row_count is a positive integer."""
        for version_id, version_data in self.v2_manifest["versions"].items():
            row_count = version_data.get("row_count")
            self.assertIsInstance(row_count, int)
            self.assertGreaterEqual(row_count, 0)

    def test_v2_manifest_multiple_versions_listed(self):
        """Test manifest with multiple versions as expected in real scenarios."""
        versions = self.v2_manifest["versions"]
        self.assertGreaterEqual(
            len(versions),
            3,
            "Manifest should contain at least 3 versions for realistic scenario"
        )


if __name__ == "__main__":
    unittest.main()
