"""
Unit tests for wl_trash module.

Tests soft-delete, restore, and purge operations on CSVs and detection rules.
Requires ≥80% coverage of all 8 public functions.
"""

import json
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta

import pytest
from freezegun import freeze_time

# Import wl_trash module (sys.path setup is in wl_trash)
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))) + "/bin")

from wl_trash import (
    move_to_trash,
    list_trash,
    restore_from_trash,
    restore_from_trash_pipeline,
    purge_trash_item,
    auto_cleanup_trash,
    get_trash_dir,
    read_trash_config,
    write_trash_config,
)


@pytest.mark.unit
class TestGetTrashDir:
    """Tests for get_trash_dir function."""

    def test_get_trash_dir_creates_if_missing(self, tmp_path):
        """Test that get_trash_dir creates directory if missing."""
        with patch("wl_trash.OWN_LOOKUPS", str(tmp_path)):
            result = get_trash_dir()

        assert result == os.path.join(str(tmp_path), "_trash")
        assert os.path.isdir(result)

    def test_get_trash_dir_returns_existing(self, tmp_path):
        """Test that get_trash_dir returns existing directory without error."""
        trash_dir = tmp_path / "_trash"
        trash_dir.mkdir()

        with patch("wl_trash.OWN_LOOKUPS", str(tmp_path)):
            result = get_trash_dir()

        assert os.path.isdir(result)


@pytest.mark.unit
class TestReadTrashConfig:
    """Tests for read_trash_config function."""

    def test_read_trash_config_valid_json(self, tmp_path):
        """Test reading valid trash config JSON."""
        versions_dir = tmp_path / "_versions"
        versions_dir.mkdir()
        config_file = versions_dir / "_trash_config.json"
        config_file.write_text(json.dumps({"retention_days": 60}))

        with patch("wl_trash.OWN_LOOKUPS", str(tmp_path)):
            result = read_trash_config()

        assert result["retention_days"] == 60

    def test_read_trash_config_missing_file(self, tmp_path):
        """Test reading when trash config file is missing."""
        with patch("wl_trash.OWN_LOOKUPS", str(tmp_path)):
            result = read_trash_config()

        assert isinstance(result, dict)
        assert "retention_days" in result

    def test_read_trash_config_invalid_json(self, tmp_path):
        """Test reading invalid JSON in trash config file."""
        versions_dir = tmp_path / "_versions"
        versions_dir.mkdir()
        config_file = versions_dir / "_trash_config.json"
        config_file.write_text("{ invalid }")

        with patch("wl_trash.OWN_LOOKUPS", str(tmp_path)):
            result = read_trash_config()

        # Should return default
        assert isinstance(result, dict)
        assert "retention_days" in result


@pytest.mark.unit
class TestWriteTrashConfig:
    """Tests for write_trash_config function."""

    def test_write_trash_config_normal(self, tmp_path):
        """Test writing trash config to file."""
        with patch("wl_trash.OWN_LOOKUPS", str(tmp_path)):
            config = {"retention_days": 45}
            write_trash_config(config)

        versions_dir = tmp_path / "_versions"
        config_file = versions_dir / "_trash_config.json"
        assert config_file.exists()
        content = json.loads(config_file.read_text())
        assert content["retention_days"] == 45

    def test_write_trash_config_creates_directory(self, tmp_path):
        """Test that write_trash_config creates _versions directory if missing."""
        with patch("wl_trash.OWN_LOOKUPS", str(tmp_path)):
            config = {"retention_days": 30}
            write_trash_config(config)

        versions_dir = tmp_path / "_versions"
        assert versions_dir.exists()


@pytest.mark.unit
class TestMoveToTrash:
    """Tests for move_to_trash function."""

    def test_move_to_trash_csv(self, tmp_path):
        """Test moving a CSV file to trash."""
        # Setup
        lookups_dir = tmp_path / "lookups"
        lookups_dir.mkdir()
        csv_file = lookups_dir / "test.csv"
        csv_file.write_text("header1,header2\nval1,val2")

        with patch("wl_trash.OWN_LOOKUPS", str(lookups_dir)):
            with patch("wl_trash.build_csv_path", return_value=str(csv_file)):
                result = move_to_trash(
                    item_type="csv",
                    name="test.csv",
                    user="analyst1",
                    comment="Testing",
                )

        assert isinstance(result, str)
        assert len(result) > 0
        # Original file should be moved to trash
        assert not csv_file.exists()

    def test_move_to_trash_rule(self, tmp_path):
        """Test moving a detection rule to trash."""
        lookups_dir = tmp_path / "lookups"
        lookups_dir.mkdir()

        with patch("wl_trash.OWN_LOOKUPS", str(lookups_dir)):
            result = move_to_trash(
                item_type="rule",
                name="rule_1",
                user="admin1",
                comment="Deleting old rule",
                associated_csvs=[{"csv_file": "DR_1.csv", "app_context": ""}],
            )

        assert isinstance(result, str)
        assert len(result) > 0

    def test_move_to_trash_overwrites_duplicate(self, tmp_path):
        """Test that moving to trash overwrites duplicate entries."""
        lookups_dir = tmp_path / "lookups"
        lookups_dir.mkdir()
        trash_dir = lookups_dir / "_trash"
        trash_dir.mkdir()

        # Create initial trash entry
        initial_id = "test__csv_20260331_120000"
        initial_path = trash_dir / initial_id
        initial_path.mkdir()
        (initial_path / "metadata.json").write_text('{"test": "data"}')

        with patch("wl_trash.OWN_LOOKUPS", str(lookups_dir)):
            with patch("wl_trash.build_csv_path", return_value=None):
                with freeze_time("2026-03-31 12:05:00"):
                    result = move_to_trash(
                        item_type="csv",
                        name="test",
                        user="analyst1",
                        comment="Updated delete",
                    )

        # Initial trash entry should be removed
        assert not initial_path.exists()


@pytest.mark.unit
class TestListTrash:
    """Tests for list_trash function."""

    def test_list_trash_empty(self, tmp_path):
        """Test listing trash when it's empty."""
        with patch("wl_trash.OWN_LOOKUPS", str(tmp_path)):
            items, error = list_trash()

        assert items == []
        assert error == ""

    def test_list_trash_multiple_items(self, tmp_path):
        """Test listing multiple trash items."""
        lookups_dir = tmp_path / "lookups"
        lookups_dir.mkdir()
        trash_dir = lookups_dir / "_trash"
        trash_dir.mkdir()
        versions_dir = lookups_dir / "_versions"
        versions_dir.mkdir()

        # Create two trash items
        for i in range(2):
            item_dir = trash_dir / f"item_{i}"
            item_dir.mkdir()
            meta = {
                "item_type": "csv",
                "name": f"csv_{i}.csv",
                "deleted_by": "user",
                "deleted_at": int(time.time()) - (i * 3600),  # Different times
            }
            (item_dir / "metadata.json").write_text(json.dumps(meta))

        with patch("wl_trash.OWN_LOOKUPS", str(lookups_dir)):
            items, error = list_trash()

        assert len(items) == 2
        assert error == ""
        # Should be sorted by deleted_at (newest first)
        assert items[0]["deleted_at"] >= items[1]["deleted_at"]

    def test_list_trash_error_handling(self, tmp_path):
        """Test that list_trash handles errors gracefully."""
        with patch("wl_trash.OWN_LOOKUPS", "/nonexistent/path"):
            items, error = list_trash()

        # Should return empty list, not crash
        assert items == []


@pytest.mark.unit
class TestRestoreFromTrash:
    """Tests for restore_from_trash function."""

    def test_restore_from_trash_not_found(self, tmp_path):
        """Test restoring a trash item that doesn't exist."""
        with patch("wl_trash.OWN_LOOKUPS", str(tmp_path)):
            meta, error = restore_from_trash("nonexistent_id")

        assert meta == {}
        assert "not found" in error.lower()

    def test_restore_from_trash_success_csv(self, tmp_path):
        """Test successfully restoring a CSV from trash."""
        lookups_dir = tmp_path / "lookups"
        lookups_dir.mkdir()
        trash_dir = lookups_dir / "_trash"
        trash_dir.mkdir()

        # Create trash item
        trash_id = "test__csv_20260331_120000"
        item_dir = trash_dir / trash_id
        item_dir.mkdir()
        csv_file = item_dir / "test.csv"
        csv_file.write_text("header\nvalue")
        meta = {
            "item_type": "csv",
            "name": "test.csv",
            "deleted_by": "user",
            "deleted_at": int(time.time()),
            "app_context": "",
            "rule_name": "",
        }
        (item_dir / "metadata.json").write_text(json.dumps(meta))

        with patch("wl_trash.OWN_LOOKUPS", str(lookups_dir)):
            with patch("wl_trash.build_csv_path", return_value=str(lookups_dir / "test.csv")):
                meta_result, error = restore_from_trash(trash_id)

        # Metadata should be returned, no error
        assert meta_result["item_type"] == "csv"
        assert error == ""
        # Item directory should be cleaned up
        assert not item_dir.exists()


@pytest.mark.unit
class TestPurgeTrashItem:
    """Tests for purge_trash_item function."""

    def test_purge_trash_item_success(self, tmp_path):
        """Test permanently purging a trash item."""
        lookups_dir = tmp_path / "lookups"
        lookups_dir.mkdir()
        trash_dir = lookups_dir / "_trash"
        trash_dir.mkdir()

        # Create trash item
        item_dir = trash_dir / "test_item"
        item_dir.mkdir()
        (item_dir / "metadata.json").write_text('{"test": "data"}')

        with patch("wl_trash.OWN_LOOKUPS", str(lookups_dir)):
            success, error = purge_trash_item("test_item")

        assert success is True
        assert error == ""
        assert not item_dir.exists()

    def test_purge_trash_item_not_found(self, tmp_path):
        """Test purging a trash item that doesn't exist."""
        with patch("wl_trash.OWN_LOOKUPS", str(tmp_path)):
            success, error = purge_trash_item("nonexistent")

        assert success is False
        assert "not found" in error.lower()


@pytest.mark.unit
class TestAutoCleanupTrash:
    """Tests for auto_cleanup_trash function."""

    @freeze_time("2026-03-31")
    def test_auto_cleanup_trash_expired(self, tmp_path):
        """Test cleaning up expired trash items."""
        lookups_dir = tmp_path / "lookups"
        lookups_dir.mkdir()
        trash_dir = lookups_dir / "_trash"
        trash_dir.mkdir()
        versions_dir = lookups_dir / "_versions"
        versions_dir.mkdir()

        # Create an expired trash item (30 days old)
        old_time = int(time.time()) - (35 * 86400)
        item_dir = trash_dir / "old_item"
        item_dir.mkdir()
        meta = {
            "item_type": "csv",
            "name": "old.csv",
            "deleted_by": "user",
            "deleted_at": old_time,
        }
        (item_dir / "metadata.json").write_text(json.dumps(meta))

        # Create a non-expired trash item (5 days old)
        recent_time = int(time.time()) - (5 * 86400)
        item_dir2 = trash_dir / "recent_item"
        item_dir2.mkdir()
        meta2 = {
            "item_type": "csv",
            "name": "recent.csv",
            "deleted_by": "user",
            "deleted_at": recent_time,
        }
        (item_dir2 / "metadata.json").write_text(json.dumps(meta2))

        # Set config with 30-day retention
        config = {"retention_days": 30}
        config_file = versions_dir / "_trash_config.json"
        config_file.write_text(json.dumps(config))

        with patch("wl_trash.OWN_LOOKUPS", str(lookups_dir)):
            count = auto_cleanup_trash()

        # Old item should be purged, recent item should remain
        assert count >= 1
        assert not (trash_dir / "old_item").exists()
        assert (trash_dir / "recent_item").exists()

    def test_auto_cleanup_trash_empty(self, tmp_path):
        """Test cleanup when trash is empty."""
        with patch("wl_trash.OWN_LOOKUPS", str(tmp_path)):
            count = auto_cleanup_trash()

        assert count == 0


# ════════════════════════════════════════════════════════════════════════════
# Pipeline Tests
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.unit
class TestRestoreFromTrashPipeline:
    """Tests for restore_from_trash_pipeline."""

    @patch("wl_audit.post_audit_event")
    @patch("wl_audit.build_audit_event", return_value={"action": "restored"})
    @patch("wl_trash.restore_from_trash")
    def test_restore_csv_success(self, mock_restore, mock_build, mock_post):
        """Successful CSV restoration returns structured result and posts audit."""
        mock_restore.return_value = (
            {"item_type": "csv", "name": "DR1.csv", "rule_name": "rule1"},
            ""
        )

        result = restore_from_trash_pipeline(
            "DR1__csv__20260402", "admin", "sess123", comment="restoring")

        assert result["success"] is True
        assert "DR1.csv" in result["message"]
        assert result["data"]["item_type"] == "csv"
        assert result["data"]["item_name"] == "DR1.csv"
        mock_post.assert_called_once()

    @patch("wl_audit.post_audit_event")
    @patch("wl_audit.build_audit_event", return_value={"action": "restored"})
    @patch("wl_trash.restore_from_trash")
    def test_restore_rule_success(self, mock_restore, mock_build, mock_post):
        """Successful rule restoration."""
        mock_restore.return_value = (
            {"item_type": "rule", "name": "my_rule", "rule_name": ""},
            ""
        )

        result = restore_from_trash_pipeline(
            "my_rule__rule__20260402", "admin", "sess123")

        assert result["success"] is True
        assert "RULE" in result["message"]
        mock_post.assert_called_once()

    @patch("wl_trash.restore_from_trash")
    def test_restore_not_found(self, mock_restore):
        """Restore non-existent item returns error."""
        mock_restore.return_value = ({}, "Trash item not found")

        result = restore_from_trash_pipeline(
            "ghost__csv__20260402", "admin", "sess123")

        assert result["success"] is False
        assert "not found" in result["error"]

    @patch("wl_trash.restore_from_trash")
    def test_restore_conflict(self, mock_restore):
        """Restore with name conflict returns error."""
        mock_restore.return_value = (
            {"item_type": "csv", "name": "DR1.csv"},
            "Cannot restore: 'DR1.csv' already exists."
        )

        result = restore_from_trash_pipeline(
            "DR1__csv__20260402", "admin", "sess123")

        assert result["success"] is False
        assert "already exists" in result["error"]
