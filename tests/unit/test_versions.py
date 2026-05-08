"""
Unit tests for wl_versions module.

Tests cover all public functions with ≥80% coverage:
- get_versions_dir
- read_version_manifest
- write_version_manifest
- snapshot_version
- get_versions_list
"""

import pytest
import json
import os
import sys
import tempfile
import shutil
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock, mock_open
from freezegun import freeze_time

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../bin'))

from wl_versions import (
    get_versions_dir,
    read_version_manifest,
    write_version_manifest,
    snapshot_version,
    get_versions_list,
)


@pytest.mark.unit
class TestGetVersionsDir:
    """Tests for get_versions_dir function."""

    def test_get_versions_dir_creates_if_missing(self, tmp_path):
        """Verify directory created if missing."""
        csv_path = os.path.join(str(tmp_path), "test.csv")
        result = get_versions_dir(csv_path)

        expected = os.path.join(str(tmp_path), "_versions")
        assert result == expected
        assert os.path.isdir(result)

    def test_get_versions_dir_returns_path_if_exists(self, tmp_path):
        """Verify returns path if directory already exists."""
        csv_path = os.path.join(str(tmp_path), "test.csv")
        versions_dir = os.path.join(str(tmp_path), "_versions")
        os.makedirs(versions_dir, exist_ok=True)

        result = get_versions_dir(csv_path)
        assert result == versions_dir
        assert os.path.isdir(result)


@pytest.mark.unit
class TestReadVersionManifest:
    """Tests for read_version_manifest function."""

    def test_read_version_manifest_valid_json(self, tmp_path):
        """Read valid manifest, verify returns dict with correct structure."""
        csv_path = os.path.join(str(tmp_path), "DR102_whitelist.csv")
        os.makedirs(get_versions_dir(csv_path), exist_ok=True)

        manifest = {
            "versions": [
                {
                    "timestamp": "2026-03-31T20:30:45Z",
                    "display": "31-03-2026 20:30:45",
                    "filename": "DR102_whitelist_20260331_203045.csv",
                    "analyst": "admin",
                    "action": "save",
                    "row_count": 42,
                    "col_count": 5,
                }
            ]
        }

        manifest_path = os.path.join(get_versions_dir(csv_path), "DR102_whitelist_versions.json")
        with open(manifest_path, "w") as f:
            json.dump(manifest, f)

        result, error = read_version_manifest(csv_path)
        assert result == manifest
        assert error == ""

    def test_read_version_manifest_missing_file(self, tmp_path):
        """File missing, verify returns empty dict and empty error."""
        csv_path = os.path.join(str(tmp_path), "DR102_whitelist.csv")
        os.makedirs(get_versions_dir(csv_path), exist_ok=True)

        result, error = read_version_manifest(csv_path)
        assert result == {}
        assert error == ""

    def test_read_version_manifest_invalid_json(self, tmp_path):
        """Malformed JSON, verify returns empty dict and error."""
        csv_path = os.path.join(str(tmp_path), "DR102_whitelist.csv")
        os.makedirs(get_versions_dir(csv_path), exist_ok=True)

        manifest_path = os.path.join(get_versions_dir(csv_path), "DR102_whitelist_versions.json")
        with open(manifest_path, "w") as f:
            f.write("{invalid json")

        result, error = read_version_manifest(csv_path)
        assert result == {}
        assert "Invalid JSON" in error

    def test_read_version_manifest_legacy_bare_list_normalized(
            self, tmp_path):
        """R2-D5-F1: a manifest that's a bare JSON list (legacy
        pre-rewrite format, still present in some demo lookups)
        must normalize to ``{"versions": [...]}`` so downstream
        code that calls ``manifest.get("versions", [])`` doesn't
        crash with ``'list' object has no attribute 'get'``.

        This is the format committed in repo demo state for some
        rules — the revert path was crashing on those rules
        before this fix.
        """
        csv_path = os.path.join(str(tmp_path), "DR102_whitelist.csv")
        os.makedirs(get_versions_dir(csv_path), exist_ok=True)

        # Legacy bare-list format
        legacy_manifest = [
            {
                "timestamp": "2026-03-28T22:58:08Z",
                "display": "28-03-2026 22:58:08",
                "filename": "DR102_whitelist_20260328_225808.csv",
                "analyst": "system",
                "action": "original",
                "row_count": 5,
                "col_count": 1,
            },
            {
                "timestamp": "2026-03-29T02:22:36Z",
                "display": "29-03-2026 02:22:36",
                "filename": "DR102_whitelist_20260329_022236.csv",
                "analyst": "analyst2",
                "action": "save",
                "row_count": 4,
                "col_count": 1,
            },
        ]
        manifest_path = os.path.join(
            get_versions_dir(csv_path),
            "DR102_whitelist_versions.json")
        with open(manifest_path, "w") as f:
            json.dump(legacy_manifest, f)

        result, error = read_version_manifest(csv_path)
        assert error == "", (
            f"legacy format should not error, got: {error}")
        assert isinstance(result, dict), (
            f"normalized result must be dict, got {type(result)}")
        assert "versions" in result, (
            "normalized result must have 'versions' key")
        assert result["versions"] == legacy_manifest, (
            "list contents preserved after normalization")
        # Pin the actual usage pattern that was crashing
        assert result.get("versions", []) == legacy_manifest

    def test_read_version_manifest_rejects_non_list_non_dict(
            self, tmp_path):
        """R2-D5-F1: a manifest that's neither a list nor a dict
        (e.g., a string, number) must error out, not silently
        normalize to garbage."""
        csv_path = os.path.join(str(tmp_path), "DR102_whitelist.csv")
        os.makedirs(get_versions_dir(csv_path), exist_ok=True)

        manifest_path = os.path.join(
            get_versions_dir(csv_path),
            "DR102_whitelist_versions.json")
        # Pathological: top-level is a string, not list or dict
        with open(manifest_path, "w") as f:
            f.write('"unexpected scalar"')

        result, error = read_version_manifest(csv_path)
        assert result == {}
        assert "expected list or dict" in error.lower()


@pytest.mark.unit
class TestWriteVersionManifest:
    """Tests for write_version_manifest function."""

    def test_write_version_manifest_normal(self, tmp_path):
        """Write manifest, verify file created with correct JSON."""
        csv_path = os.path.join(str(tmp_path), "DR102_whitelist.csv")
        os.makedirs(get_versions_dir(csv_path), exist_ok=True)

        manifest = {
            "versions": [
                {
                    "timestamp": "2026-03-31T20:30:45Z",
                    "display": "31-03-2026 20:30:45",
                    "filename": "DR102_whitelist_20260331_203045.csv",
                    "analyst": "admin",
                    "action": "save",
                    "row_count": 42,
                    "col_count": 5,
                }
            ]
        }

        success, error = write_version_manifest(csv_path, manifest)
        assert success is True
        assert error == ""

        # Verify file contents
        manifest_path = os.path.join(get_versions_dir(csv_path), "DR102_whitelist_versions.json")
        with open(manifest_path, "r") as f:
            loaded = json.load(f)
        assert loaded == manifest

    def test_write_version_manifest_overwrite(self, tmp_path):
        """Write manifest twice, verify second write overwrites."""
        csv_path = os.path.join(str(tmp_path), "DR102_whitelist.csv")
        os.makedirs(get_versions_dir(csv_path), exist_ok=True)

        manifest1 = {"versions": [{"filename": "v1.csv"}]}
        manifest2 = {"versions": [{"filename": "v2.csv"}]}

        write_version_manifest(csv_path, manifest1)
        write_version_manifest(csv_path, manifest2)

        result, _ = read_version_manifest(csv_path)
        assert result == manifest2


@pytest.mark.unit
class TestSnapshotVersion:
    """Tests for snapshot_version function."""

    @freeze_time("2026-03-31 20:30:45")
    def test_snapshot_version_creates_copy(self, tmp_path):
        """Snapshot a CSV, verify timestamped copy created in _versions/."""
        # Create test CSV
        csv_path = os.path.join(str(tmp_path), "DR102_whitelist.csv")
        with open(csv_path, "w") as f:
            f.write("user,ip\njsmith,10.0.0.1\n")

        timestamp_id, error = snapshot_version(csv_path, "admin", "save")

        assert error == ""
        assert timestamp_id == "20260331_203045"

        versions_dir = get_versions_dir(csv_path)
        snapshot_file = os.path.join(versions_dir, f"DR102_whitelist_{timestamp_id}.csv")
        assert os.path.isfile(snapshot_file)

    @freeze_time("2026-03-31 20:30:45")
    def test_snapshot_version_updates_manifest(self, tmp_path):
        """Snapshot, verify manifest updated with version entry."""
        csv_path = os.path.join(str(tmp_path), "DR102_whitelist.csv")
        with open(csv_path, "w") as f:
            f.write("user,ip\njsmith,10.0.0.1\n")

        snapshot_version(csv_path, "admin", "save")

        manifest, _ = read_version_manifest(csv_path)
        assert "versions" in manifest
        assert len(manifest["versions"]) == 1

        entry = manifest["versions"][0]
        assert entry["analyst"] == "admin"
        assert entry["action"] == "save"
        assert entry["row_count"] == 1  # 1 data row
        assert entry["col_count"] == 2  # user, ip

    @freeze_time("2026-03-31 20:30:45")
    def test_snapshot_version_enforces_max_versions(self, tmp_path):
        """Create MAX_VERSIONS+1 snapshots, verify only MAX_VERSIONS kept."""
        from wl_versions import MAX_VERSIONS

        csv_path = os.path.join(str(tmp_path), "DR102_whitelist.csv")
        with open(csv_path, "w") as f:
            f.write("user,ip\njsmith,10.0.0.1\n")

        # Create MAX_VERSIONS + 1 snapshots
        for i in range(MAX_VERSIONS + 1):
            # Increment time by 1 second to avoid collision
            with freeze_time(f"2026-03-31 20:30:{45+i}"):
                snapshot_version(csv_path, f"admin{i}", "save")

        manifest, _ = read_version_manifest(csv_path)
        assert len(manifest["versions"]) == MAX_VERSIONS

        # Verify oldest was removed
        versions_dir = get_versions_dir(csv_path)
        files = os.listdir(versions_dir)
        # Filter to just snapshot CSVs
        snapshot_files = [f for f in files if f.endswith(".csv")]
        assert len(snapshot_files) == MAX_VERSIONS


@pytest.mark.unit
class TestGetVersionsList:
    """Tests for get_versions_list function."""

    def test_get_versions_list_empty(self, tmp_path):
        """Empty manifest, verify returns empty list."""
        csv_path = os.path.join(str(tmp_path), "DR102_whitelist.csv")
        os.makedirs(get_versions_dir(csv_path), exist_ok=True)

        result, error = get_versions_list(csv_path)
        assert result == []
        assert error == ""

    def test_get_versions_list_multiple_versions(self, tmp_path):
        """Multiple snapshots, verify sorted newest-first with display format."""
        csv_path = os.path.join(str(tmp_path), "DR102_whitelist.csv")
        os.makedirs(get_versions_dir(csv_path), exist_ok=True)

        manifest = {
            "versions": [
                {
                    "timestamp": "2026-03-31T20:30:00Z",
                    "display": "31-03-2026 20:30:00",
                    "filename": "DR102_whitelist_20260331_203000.csv",
                    "analyst": "admin",
                    "action": "save",
                    "row_count": 40,
                    "col_count": 5,
                },
                {
                    "timestamp": "2026-03-31T20:31:00Z",
                    "display": "31-03-2026 20:31:00",
                    "filename": "DR102_whitelist_20260331_203100.csv",
                    "analyst": "analyst1",
                    "action": "save",
                    "row_count": 42,
                    "col_count": 5,
                },
            ]
        }

        manifest_path = os.path.join(get_versions_dir(csv_path), "DR102_whitelist_versions.json")
        with open(manifest_path, "w") as f:
            json.dump(manifest, f)

        result, error = get_versions_list(csv_path)
        assert error == ""
        assert len(result) == 2

        # Verify sorted newest-first
        assert result[0]["timestamp"] == "2026-03-31T20:31:00Z"
        assert result[1]["timestamp"] == "2026-03-31T20:30:00Z"

        # Verify structure
        assert "version_id" in result[0]
        assert "display" in result[0]
        assert "analyst" in result[0]

    def test_get_versions_list_missing_manifest(self, tmp_path):
        """No manifest file, verify returns empty list."""
        csv_path = os.path.join(str(tmp_path), "DR102_whitelist.csv")
        os.makedirs(get_versions_dir(csv_path), exist_ok=True)

        result, error = get_versions_list(csv_path)
        assert result == []


@pytest.mark.unit
class TestSnapshotVersionIntegration:
    """Integration tests for snapshot_version function."""

    @freeze_time("2026-03-31 20:30:45")
    def test_snapshot_and_retrieve(self, tmp_path):
        """Full cycle: create snapshot, read manifest, get versions list."""
        csv_path = os.path.join(str(tmp_path), "DR102_whitelist.csv")
        with open(csv_path, "w") as f:
            f.write("user,ip\njsmith,10.0.0.1\njdoe,10.0.0.2\n")

        # Create snapshot
        timestamp_id, error = snapshot_version(csv_path, "admin", "save")
        assert error == ""

        # Read manifest
        manifest, error = read_version_manifest(csv_path)
        assert error == ""
        assert len(manifest["versions"]) == 1

        # Get versions list
        versions, error = get_versions_list(csv_path)
        assert error == ""
        assert len(versions) == 1
        assert versions[0]["row_count"] == 2

    def test_snapshot_with_missing_csv(self, tmp_path):
        """Snapshot non-existent CSV, verify error."""
        csv_path = os.path.join(str(tmp_path), "nonexistent.csv")

        timestamp_id, error = snapshot_version(csv_path, "admin", "save")
        assert timestamp_id == ""
        assert "Failed to read CSV" in error


@pytest.mark.unit
class TestManifestStructure:
    """Tests for manifest structure and format."""

    def test_manifest_structure_preserved(self, tmp_path):
        """Write and read manifest, verify structure preserved."""
        csv_path = os.path.join(str(tmp_path), "test.csv")
        os.makedirs(get_versions_dir(csv_path), exist_ok=True)

        manifest = {
            "versions": [
                {
                    "timestamp": "2026-03-31T20:30:45Z",
                    "display": "31-03-2026 20:30:45",
                    "filename": "test_20260331_203045.csv",
                    "analyst": "admin",
                    "action": "save",
                    "row_count": 42,
                    "col_count": 5,
                }
            ]
        }

        write_version_manifest(csv_path, manifest)
        result, _ = read_version_manifest(csv_path)

        assert result == manifest
        assert "versions" in result
        assert isinstance(result["versions"], list)


@pytest.mark.unit
class TestErrorHandling:
    """Tests for error handling paths."""

    def test_snapshot_version_with_internal_columns(self, tmp_path):
        """Snapshot with internal columns, verify col_count excludes them."""
        csv_path = os.path.join(str(tmp_path), "test.csv")
        with open(csv_path, "w") as f:
            f.write("user,ip,_added_by\njsmith,10.0.0.1,admin\n")

        timestamp_id, error = snapshot_version(csv_path, "admin", "save")
        assert error == ""

        manifest, _ = read_version_manifest(csv_path)
        assert manifest["versions"][0]["col_count"] == 2  # user, ip (not _added_by)

    def test_snapshot_version_empty_csv(self, tmp_path):
        """Snapshot empty CSV (headers only), verify row_count is 0."""
        csv_path = os.path.join(str(tmp_path), "test.csv")
        with open(csv_path, "w") as f:
            f.write("user,ip\n")

        timestamp_id, error = snapshot_version(csv_path, "admin", "save")
        assert error == ""

        manifest, _ = read_version_manifest(csv_path)
        assert manifest["versions"][0]["row_count"] == 0

    def test_get_versions_list_invalid_manifest_structure(self, tmp_path):
        """Invalid manifest structure (no versions key), verify handles gracefully."""
        csv_path = os.path.join(str(tmp_path), "test.csv")
        os.makedirs(get_versions_dir(csv_path), exist_ok=True)

        # Write invalid manifest
        manifest_path = os.path.join(get_versions_dir(csv_path), "test_versions.json")
        with open(manifest_path, "w") as f:
            json.dump({"some_key": []}, f)

        result, error = get_versions_list(csv_path)
        assert result == []
        assert error == ""

    def test_snapshot_handles_timestamp_collision(self, tmp_path):
        """Two snapshots with collision, verify millisecond suffix added to file."""
        csv_path = os.path.join(str(tmp_path), "test.csv")
        with open(csv_path, "w") as f:
            f.write("user\njsmith\n")

        with freeze_time("2026-03-31 20:30:45"):
            ts1, _ = snapshot_version(csv_path, "admin", "save")
            # Immediately call again to trigger collision detection
            ts2, _ = snapshot_version(csv_path, "admin", "save")

        # Both calls should succeed
        assert ts1 == "20260331_203045"
        assert ts2 == "20260331_203045"

        # Verify both snapshots created (second with millisecond suffix)
        versions_dir = get_versions_dir(csv_path)
        files = sorted([f for f in os.listdir(versions_dir) if f.endswith(".csv")])
        assert len(files) == 2
        # First should be base timestamp, second should have millisecond suffix
        assert "test_20260331_203045.csv" in files
        assert any("test_20260331_203045_" in f for f in files)

    def test_write_version_manifest_empty_dict(self, tmp_path):
        """Write empty manifest, verify no error."""
        csv_path = os.path.join(str(tmp_path), "test.csv")
        os.makedirs(get_versions_dir(csv_path), exist_ok=True)

        success, error = write_version_manifest(csv_path, {})
        assert success is True
        assert error == ""

    def test_get_versions_list_with_missing_optional_fields(self, tmp_path):
        """Manifest with missing optional fields, verify defaults."""
        csv_path = os.path.join(str(tmp_path), "test.csv")
        os.makedirs(get_versions_dir(csv_path), exist_ok=True)

        # Minimal manifest
        manifest = {
            "versions": [
                {
                    "timestamp": "2026-03-31T20:30:45Z",
                    "filename": "test_20260331_203045.csv",
                }
            ]
        }

        manifest_path = os.path.join(get_versions_dir(csv_path), "test_versions.json")
        with open(manifest_path, "w") as f:
            json.dump(manifest, f)

        result, error = get_versions_list(csv_path)
        assert len(result) == 1
        assert result[0]["analyst"] == ""  # Default to empty string
        assert result[0]["row_count"] == 0  # Default to 0


@pytest.mark.unit
class TestManifestEdgeCases:
    """Tests for manifest edge cases."""

    def test_snapshot_with_normal_operation(self, tmp_path):
        """Normal snapshot operation with valid CSV."""
        csv_path = os.path.join(str(tmp_path), "test.csv")
        with open(csv_path, "w") as f:
            f.write("user\njsmith\n")

        ts, error = snapshot_version(csv_path, "admin", "save")
        assert error == ""
        assert ts != ""  # Should get a valid timestamp

    def test_get_versions_list_invalid_versions_not_list(self, tmp_path):
        """Manifest where versions is not a list."""
        csv_path = os.path.join(str(tmp_path), "test.csv")
        os.makedirs(get_versions_dir(csv_path), exist_ok=True)

        manifest = {
            "versions": "not a list"
        }

        manifest_path = os.path.join(get_versions_dir(csv_path), "test_versions.json")
        with open(manifest_path, "w") as f:
            json.dump(manifest, f)

        result, error = get_versions_list(csv_path)
        assert result == []
        assert "Invalid versions list" in error


@pytest.mark.unit
class TestVersionIdExtraction:
    """Tests for version ID extraction from filenames."""

    def test_get_versions_list_extracts_version_id(self, tmp_path):
        """Verify version_id correctly extracted from filename."""
        csv_path = os.path.join(str(tmp_path), "DR102_whitelist.csv")
        os.makedirs(get_versions_dir(csv_path), exist_ok=True)

        manifest = {
            "versions": [
                {
                    "timestamp": "2026-03-31T20:30:45Z",
                    "display": "31-03-2026 20:30:45",
                    "filename": "DR102_whitelist_20260331_203045.csv",
                    "analyst": "admin",
                    "action": "save",
                    "row_count": 42,
                    "col_count": 5,
                }
            ]
        }

        manifest_path = os.path.join(get_versions_dir(csv_path), "DR102_whitelist_versions.json")
        with open(manifest_path, "w") as f:
            json.dump(manifest, f)

        result, _ = get_versions_list(csv_path)
        assert result[0]["version_id"] == "20260331_203045"

    def test_get_versions_list_handles_malformed_filename(self, tmp_path):
        """Malformed filename without underscore, verify handles gracefully."""
        csv_path = os.path.join(str(tmp_path), "test.csv")
        os.makedirs(get_versions_dir(csv_path), exist_ok=True)

        manifest = {
            "versions": [
                {
                    "timestamp": "2026-03-31T20:30:45Z",
                    "filename": "test.csv",  # No timestamp
                    "analyst": "admin",
                    "action": "save",
                    "row_count": 0,
                }
            ]
        }

        manifest_path = os.path.join(get_versions_dir(csv_path), "test_versions.json")
        with open(manifest_path, "w") as f:
            json.dump(manifest, f)

        result, _ = get_versions_list(csv_path)
        assert len(result) == 1
        assert result[0]["version_id"] == ""  # Empty when malformed

    def test_get_versions_list_filename_without_csv_extension(self, tmp_path):
        """Filename without .csv extension, verify still processed."""
        csv_path = os.path.join(str(tmp_path), "test.csv")
        os.makedirs(get_versions_dir(csv_path), exist_ok=True)

        manifest = {
            "versions": [
                {
                    "timestamp": "2026-03-31T20:30:45Z",
                    "filename": "test_20260331_203045",  # No .csv extension
                    "analyst": "admin",
                    "action": "save",
                    "row_count": 0,
                }
            ]
        }

        manifest_path = os.path.join(get_versions_dir(csv_path), "test_versions.json")
        with open(manifest_path, "w") as f:
            json.dump(manifest, f)

        result, _ = get_versions_list(csv_path)
        assert len(result) == 1
        # Version ID should be extracted even without .csv
        assert result[0]["version_id"] == "20260331_203045"
