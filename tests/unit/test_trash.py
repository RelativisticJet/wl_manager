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
    restore_csv_from_trash,
    restore_rule_from_trash,
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
class TestMoveToTrashMetadataShape:
    """R0-F5 fix: pin the full metadata schema written by
    ``move_to_trash`` to ``metadata.json``.

    Build-641 was the same bug class in a different module
    (``project_pending_info`` dropped ``comment`` from the
    projection). The trash subsystem has the same risk surface:
    if a future refactor drops a field from
    ``build_trash_metadata`` (e.g. ``comment``,
    ``deleted_by``), the trash dashboard and audit-trail
    drilldown silently lose context. We'd find out only when an
    analyst asked "why was this rule deleted?" and the audit
    panel was empty.

    Mechanically the same pattern as
    ``test_pending_info_projection.py`` —
    ``REQUIRED_METADATA_FIELDS`` is the single source of truth
    for the schema, and any drop fails this test.
    """

    REQUIRED_METADATA_FIELDS_COMMON = {
        "item_type",
        "name",
        "deleted_by",
        "deleted_at",
        "deleted_at_human",
        "comment",
        "expiry_ts",
        "expiry_human",
        "retention_days",
        "rule_name",
        "app_context",
    }

    def _read_written_metadata(self, lookups_dir, trash_id):
        """Locate and parse the metadata.json the function just
        wrote, so we can assert on its actual contents (not on
        the in-memory dict)."""
        trash_dir = lookups_dir / "_trash"
        meta_path = trash_dir / trash_id / "metadata.json"
        assert meta_path.exists(), \
            "metadata.json was not written for trash_id {}".format(
                trash_id)
        with meta_path.open(encoding="utf-8") as fh:
            return json.load(fh)

    def test_csv_metadata_has_full_documented_schema(
            self, tmp_path):
        """Pins the FULL field set for a CSV trash entry."""
        lookups_dir = tmp_path / "lookups"
        lookups_dir.mkdir()
        csv_file = lookups_dir / "DR123_test.csv"
        csv_file.write_text("h1,h2\nv1,v2")

        with patch("wl_trash.OWN_LOOKUPS", str(lookups_dir)):
            with patch("wl_trash.build_csv_path",
                       return_value=str(csv_file)):
                trash_id = move_to_trash(
                    item_type="csv",
                    name="DR123_test.csv",
                    user="analyst1",
                    comment="Ring 1 R0-F5 metadata-shape pin",
                    app_context="wl_manager",
                    detection_rule="DR123",
                )

        meta = self._read_written_metadata(lookups_dir, trash_id)

        missing = self.REQUIRED_METADATA_FIELDS_COMMON - set(meta.keys())
        assert not missing, \
            ("CSV trash metadata missing fields: {}. "
             "Field set: {}".format(missing, sorted(meta.keys())))
        # CSV-specific field
        assert "original_path" in meta, \
            "CSV trash metadata must include 'original_path'"

        # Spot-checks on values that build-641-class drops would
        # leave defaulted. If `comment` were silently dropped, it
        # would either be missing (caught above) or be an empty
        # string when the user supplied a real value.
        assert meta["item_type"] == "csv"
        assert meta["name"] == "DR123_test.csv"
        assert meta["deleted_by"] == "analyst1"
        assert meta["comment"] == "Ring 1 R0-F5 metadata-shape pin"
        assert meta["app_context"] == "wl_manager"
        assert meta["rule_name"] == "DR123"

    def test_rule_metadata_has_full_documented_schema(
            self, tmp_path):
        """Pins the FULL field set for a rule trash entry. Rule
        entries differ from CSV entries only in two fields:

        - ``original_path`` is absent (no single CSV path)
        - ``associated_csvs`` is present (list of CSVs that move
          along with the rule)
        """
        lookups_dir = tmp_path / "lookups"
        lookups_dir.mkdir()

        with patch("wl_trash.OWN_LOOKUPS", str(lookups_dir)):
            trash_id = move_to_trash(
                item_type="rule",
                name="DR_RING1_TEST",
                user="wladmin1",
                comment="Ring 1 R0-F5 rule metadata pin",
                associated_csvs=[
                    {"csv_file": "DR_x.csv", "app_context": ""},
                    {"csv_file": "DR_y.csv", "app_context": "wl_manager"},
                ],
            )

        meta = self._read_written_metadata(lookups_dir, trash_id)

        missing = self.REQUIRED_METADATA_FIELDS_COMMON - set(meta.keys())
        assert not missing, \
            ("Rule trash metadata missing fields: {}".format(missing))
        # Rule-specific field
        assert "associated_csvs" in meta, \
            "Rule trash metadata must include 'associated_csvs'"
        assert isinstance(meta["associated_csvs"], list)
        assert len(meta["associated_csvs"]) == 2
        # Rule entries should NOT carry original_path (single
        # CSV concept doesn't apply)
        assert "original_path" not in meta, \
            ("Rule trash metadata accidentally carries "
             "'original_path' — that's a CSV-only field")

        assert meta["item_type"] == "rule"
        assert meta["name"] == "DR_RING1_TEST"
        assert meta["deleted_by"] == "wladmin1"
        assert meta["comment"] == "Ring 1 R0-F5 rule metadata pin"

    def test_metadata_comment_is_sanitized_not_dropped(
            self, tmp_path):
        """Specifically pins: ``comment`` is sanitize_text()ed,
        NOT silently dropped. This is the precise build-641 bug
        that R0-F5 was about — ``project_pending_info`` had a
        case where the comment was dropped from the projection
        dict. Make sure the equivalent doesn't happen for trash.
        """
        lookups_dir = tmp_path / "lookups"
        lookups_dir.mkdir()
        csv_file = lookups_dir / "x.csv"
        csv_file.write_text("a,b\n1,2")

        # Comment with control chars that sanitize_text strips
        raw_comment = "Reason\nwith\tcontrol  chars"
        with patch("wl_trash.OWN_LOOKUPS", str(lookups_dir)):
            with patch("wl_trash.build_csv_path",
                       return_value=str(csv_file)):
                trash_id = move_to_trash(
                    item_type="csv",
                    name="x.csv",
                    user="analyst1",
                    comment=raw_comment,
                )

        meta = self._read_written_metadata(lookups_dir, trash_id)
        # Comment must be present
        assert "comment" in meta, \
            "comment field dropped from trash metadata"
        # Comment is non-empty (sanitize_text doesn't strip
        # legitimate text — only control chars / collapses
        # whitespace)
        assert meta["comment"], \
            ("comment field present but empty — sanitize_text "
             "returned '' for a legitimate input. Bug.")
        # The sanitized output should still contain the substantive
        # words from the input
        assert "Reason" in meta["comment"]
        assert "control" in meta["comment"]
        assert "chars" in meta["comment"]


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


@pytest.mark.unit
class TestRestoreCsvFromTrash:
    """Tests for restore_csv_from_trash (covers lines 469-509 +
    _restore_mapping_for_csv helper, currently the biggest coverage gap
    in wl_trash.py).

    ⚠ Windows test-isolation note:
    The `MAPPING_FILE` constant from `wl_constants` is
    `/opt/splunk/etc/apps/wl_manager/lookups/rule_csv_map.csv`. On
    Windows that resolves to `C:/opt/splunk/...` (leading-slash =
    current drive root), an artifact directory that persists between
    test runs. Tests in this class MUST `patch("wl_trash.MAPPING_FILE",
    str(<tmp_path mapping file>))` in addition to `OWN_LOOKUPS`,
    otherwise state leaks into `C:/opt/splunk/...` and causes
    flake-style "rule already exists" failures on re-run. See
    commit `df82528` for the discovery context.
    """

    def _make_trash_item(self, tmp_path, csv_name="test.csv",
                        app_ctx="", rule_name=""):
        """Helper: build a trash item directory with the CSV inside."""
        lookups = tmp_path / "lookups"
        lookups.mkdir(exist_ok=True)
        trash = lookups / "_trash"
        trash.mkdir(exist_ok=True)
        trash_id = "test__csv_20260519_120000"
        item_dir = trash / trash_id
        item_dir.mkdir()
        (item_dir / csv_name).write_text("header\nvalue1\nvalue2")
        # Add a version snapshot too — should be restored to _versions/
        (item_dir / "test_20260519_115500.csv").write_text("old\n")
        meta = {
            "item_type": "csv",
            "name": csv_name,
            "app_context": app_ctx,
            "rule_name": rule_name,
        }
        return trash_id, str(item_dir), meta, lookups

    def test_restore_csv_name_conflict_returns_error(self, tmp_path):
        """If a file with the same name already exists at the dest, refuse."""
        trash_id, item_dir, meta, lookups = self._make_trash_item(tmp_path)
        # Create a file at the destination
        existing = lookups / "test.csv"
        existing.write_text("conflicting\n")

        with patch("wl_trash.build_csv_path",
                   return_value=str(existing)):
            result_meta, error = restore_csv_from_trash(
                trash_id, item_dir, meta)

        assert "already exists" in error
        assert result_meta is meta

    def test_restore_csv_happy_path(self, tmp_path):
        """CSV restored to dest, version snapshots moved to _versions/."""
        trash_id, item_dir, meta, lookups = self._make_trash_item(tmp_path)
        dest = lookups / "test.csv"
        versions_dir = lookups / "_versions"

        with patch("wl_trash.OWN_LOOKUPS", str(lookups)), \
             patch("wl_trash.build_csv_path", return_value=str(dest)):
            result_meta, error = restore_csv_from_trash(
                trash_id, item_dir, meta)

        assert error == ""
        # CSV moved to destination
        assert dest.exists()
        assert "value1" in dest.read_text()
        # Version snapshot moved to _versions/
        assert versions_dir.exists()
        assert (versions_dir / "test_20260519_115500.csv").exists()

    def test_restore_csv_with_rule_recreates_mapping(self, tmp_path):
        """rule_name in metadata triggers _restore_mapping_for_csv."""
        trash_id, item_dir, meta, lookups = self._make_trash_item(
            tmp_path, rule_name="DR_restored")
        dest = lookups / "test.csv"
        mapping_path = lookups / "rule_csv_map.csv"
        rules_path = lookups / "_detection_rules.json"

        with patch("wl_trash.OWN_LOOKUPS", str(lookups)), \
             patch("wl_trash.MAPPING_FILE", str(mapping_path)), \
             patch("wl_trash.build_csv_path", return_value=str(dest)):
            result_meta, error = restore_csv_from_trash(
                trash_id, item_dir, meta)

        assert error == ""
        # Mapping created with the rule→CSV link
        assert mapping_path.exists()
        mapping_content = mapping_path.read_text()
        assert "DR_restored" in mapping_content
        assert "test.csv" in mapping_content
        # Rule appended to registry
        assert rules_path.exists()
        registered = json.loads(rules_path.read_text())
        assert "DR_restored" in registered

    def test_restore_csv_no_rule_skips_mapping_update(self, tmp_path):
        """If meta has empty rule_name, _restore_mapping_for_csv returns early."""
        trash_id, item_dir, meta, lookups = self._make_trash_item(
            tmp_path, rule_name="")
        dest = lookups / "test.csv"
        mapping_path = lookups / "rule_csv_map.csv"

        with patch("wl_trash.OWN_LOOKUPS", str(lookups)), \
             patch("wl_trash.MAPPING_FILE", str(mapping_path)), \
             patch("wl_trash.build_csv_path", return_value=str(dest)):
            result_meta, error = restore_csv_from_trash(
                trash_id, item_dir, meta)

        assert error == ""
        # No mapping file created
        assert not mapping_path.exists()


@pytest.mark.unit
class TestRestoreRuleFromTrash:
    """Tests for restore_rule_from_trash (covers lines 575-647).

    ⚠ Windows test-isolation note (same constraint as
    TestRestoreCsvFromTrash above):
    `wl_trash.MAPPING_FILE` resolves to `C:/opt/splunk/...` on Windows
    because the constant is a leading-slash POSIX path that Python
    interprets as relative to the current drive root. Every test in
    this class MUST `patch("wl_trash.MAPPING_FILE", ...)` to a
    tmp_path file in addition to `patch("wl_trash.OWN_LOOKUPS", ...)`,
    otherwise mapping writes leak into `C:/opt/splunk/...` and cause
    flake-style "rule already exists" / cross-test contamination
    failures on re-run. See commit `df82528` for the discovery
    context and the matching warning on TestRestoreCsvFromTrash.
    """

    def _make_rule_trash_item(self, tmp_path, rule_name="DR_restored",
                              csv_names=("DR_a.csv", "DR_b.csv")):
        """Helper: build a trash item dir for a rule with associated CSVs."""
        lookups = tmp_path / "lookups"
        lookups.mkdir(exist_ok=True)
        trash = lookups / "_trash"
        trash.mkdir(exist_ok=True)
        trash_id = "DR_restored__rule_20260519_120000"
        item_dir = trash / trash_id
        item_dir.mkdir()
        # Each CSV stored under the trash item dir
        for csv_name in csv_names:
            (item_dir / csv_name).write_text(f"hdr\n{csv_name}_row\n")
        # Also a version snapshot
        (item_dir / "extra_version.csv").write_text("v\n")
        meta = {
            "item_type": "rule",
            "name": rule_name,
            "associated_csvs": [
                {"csv_file": c, "app_context": ""} for c in csv_names
            ],
        }
        return trash_id, str(item_dir), meta, lookups

    def test_restore_rule_already_registered_returns_error(self, tmp_path):
        """If rule_name is already in _detection_rules.json, refuse."""
        trash_id, item_dir, meta, lookups = self._make_rule_trash_item(
            tmp_path)
        rules_path = lookups / "_detection_rules.json"
        rules_path.write_text(json.dumps(["DR_restored"]))  # already present
        mapping_path = lookups / "rule_csv_map.csv"

        with patch("wl_trash.OWN_LOOKUPS", str(lookups)), \
             patch("wl_trash.MAPPING_FILE", str(mapping_path)):
            result_meta, error = restore_rule_from_trash(
                trash_id, item_dir, meta)

        assert "already exists" in error
        assert result_meta is meta

    def test_restore_rule_already_in_mapping_returns_error(self, tmp_path):
        """If rule_name is present in mapping CSV (even without registry), refuse."""
        trash_id, item_dir, meta, lookups = self._make_rule_trash_item(
            tmp_path)
        mapping_path = lookups / "rule_csv_map.csv"
        mapping_path.write_text(
            "rule_name,csv_file,app_context\nDR_restored,other.csv,\n")

        with patch("wl_trash.OWN_LOOKUPS", str(lookups)), \
             patch("wl_trash.MAPPING_FILE", str(mapping_path)):
            result_meta, error = restore_rule_from_trash(
                trash_id, item_dir, meta)

        assert "already exists" in error

    def test_restore_rule_happy_path(self, tmp_path):
        """All CSVs restored, mappings recreated, rule re-registered."""
        trash_id, item_dir, meta, lookups = self._make_rule_trash_item(
            tmp_path)
        rules_path = lookups / "_detection_rules.json"
        mapping_path = lookups / "rule_csv_map.csv"

        # Compute destinations for each CSV
        def fake_build(csv_file, app_context=""):
            return str(lookups / csv_file)

        with patch("wl_trash.OWN_LOOKUPS", str(lookups)), \
             patch("wl_trash.MAPPING_FILE", str(mapping_path)), \
             patch("wl_trash.build_csv_path", side_effect=fake_build):
            result_meta, error = restore_rule_from_trash(
                trash_id, item_dir, meta)

        assert error == ""
        # Each CSV restored
        assert (lookups / "DR_a.csv").exists()
        assert (lookups / "DR_b.csv").exists()
        # Version snapshot moved to _versions/
        assert (lookups / "_versions" / "extra_version.csv").exists()
        # Rule registered
        registered = json.loads(rules_path.read_text())
        assert "DR_restored" in registered
        # Mapping has both CSVs
        mapping_text = mapping_path.read_text()
        assert "DR_a.csv" in mapping_text
        assert "DR_b.csv" in mapping_text

    def test_restore_rule_handles_non_list_registry(self, tmp_path):
        """If _detection_rules.json is malformed (not a list), treat as empty."""
        trash_id, item_dir, meta, lookups = self._make_rule_trash_item(
            tmp_path)
        rules_path = lookups / "_detection_rules.json"
        # Write a malformed registry (a dict, not a list)
        rules_path.write_text(json.dumps({"not": "a list"}))
        mapping_path = lookups / "rule_csv_map.csv"

        def fake_build(csv_file, app_context=""):
            return str(lookups / csv_file)

        with patch("wl_trash.OWN_LOOKUPS", str(lookups)), \
             patch("wl_trash.MAPPING_FILE", str(mapping_path)), \
             patch("wl_trash.build_csv_path", side_effect=fake_build):
            result_meta, error = restore_rule_from_trash(
                trash_id, item_dir, meta)

        # Treated as empty registry → restore succeeds
        assert error == ""
        registered = json.loads(rules_path.read_text())
        assert "DR_restored" in registered

    def test_restore_rule_with_no_associated_csvs(self, tmp_path):
        """Rule with empty associated_csvs list still restores the rule entry."""
        trash_id, item_dir, meta, lookups = self._make_rule_trash_item(
            tmp_path, csv_names=())
        # Remove the version file too — minimal restore
        for f in os.listdir(item_dir):
            if f != "metadata.json":
                os.remove(os.path.join(item_dir, f))
        meta["associated_csvs"] = []
        rules_path = lookups / "_detection_rules.json"
        mapping_path = lookups / "rule_csv_map.csv"

        with patch("wl_trash.OWN_LOOKUPS", str(lookups)), \
             patch("wl_trash.MAPPING_FILE", str(mapping_path)):
            result_meta, error = restore_rule_from_trash(
                trash_id, item_dir, meta)

        assert error == ""
        registered = json.loads(rules_path.read_text())
        assert "DR_restored" in registered


# ═════════════════════════════════════════════════════════════════════════════
# Mutation-survivor coverage (2026-05-20 batch).
#
# Baseline mutmut on bin/wl_trash.py reported ~53.2% kill rate (177 of 378
# mutations survived) on 2026-05-19. Survivors cluster in the same five
# patterns identified for wl_csv (see docs/MUTATION_TESTING.md). Tests
# below target the contracts most likely to be silently broken by
# mutations: pipeline return-dict shape, function-return tuple shapes,
# build_trash_metadata key contracts, and restore-message template.
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestMutationCoverageGroupAReturnEnvelope:
    """Group A: restore_from_trash_pipeline 4-key envelope.

    Both branches (success and error) MUST carry {success, message,
    error, data}. String-wrap mutations on any key would surface as
    missing.
    """

    REQUIRED_KEYS = {"success", "message", "error", "data"}

    def test_pipeline_error_branch_has_all_four_keys(self, tmp_path):
        """Error branch (item not found) still carries the full envelope."""
        with patch("wl_trash.restore_from_trash",
                   return_value=({}, "Trash item not found")), \
             patch("wl_audit.build_audit_event", return_value={}), \
             patch("wl_audit.post_audit_event", return_value=(True, "")):
            result = restore_from_trash_pipeline(
                item_id="nonexistent",
                analyst="alice",
                session_key="sk",
            )
        missing = self.REQUIRED_KEYS - set(result.keys())
        assert not missing, (
            f"error-branch missing keys: {missing}; got: {set(result.keys())}"
        )
        assert result["success"] is False
        assert result["data"] == {}

    def test_pipeline_success_branch_has_all_four_keys(self, tmp_path):
        """Success branch carries {success, message, error, data}."""
        with patch("wl_trash.restore_from_trash",
                   return_value=(
                       {"item_type": "csv", "name": "test.csv",
                        "rule_name": "DR"},
                       "")), \
             patch("wl_audit.build_audit_event", return_value={}), \
             patch("wl_audit.post_audit_event", return_value=(True, "")):
            result = restore_from_trash_pipeline(
                item_id="trash_123",
                analyst="alice",
                session_key="sk",
            )
        missing = self.REQUIRED_KEYS - set(result.keys())
        assert not missing, (
            f"success-branch missing keys: {missing}; "
            f"got: {set(result.keys())}"
        )
        assert result["success"] is True
        assert result["error"] == ""

    def test_pipeline_success_message_template_exact_wording(self):
        """Message template: '{ITEM_TYPE_UPPER} \\'{name}\\' restored from trash'.

        Kills string-wrap mutations on the message template AND on the
        .upper() call (mutations dropping .upper() would yield lowercase).
        """
        with patch("wl_trash.restore_from_trash",
                   return_value=(
                       {"item_type": "csv", "name": "test.csv",
                        "rule_name": "DR"},
                       "")), \
             patch("wl_audit.build_audit_event", return_value={}), \
             patch("wl_audit.post_audit_event", return_value=(True, "")):
            result = restore_from_trash_pipeline(
                item_id="trash_123",
                analyst="alice",
                session_key="sk",
            )
        assert result["message"] == "CSV 'test.csv' restored from trash", (
            f"message template drift; got: {result['message']!r}"
        )

    def test_pipeline_success_data_has_item_type_and_name(self):
        """data dict carries exactly {item_type, item_name} on success."""
        with patch("wl_trash.restore_from_trash",
                   return_value=(
                       {"item_type": "rule", "name": "DR_x",
                        "rule_name": "DR_x"},
                       "")), \
             patch("wl_audit.build_audit_event", return_value={}), \
             patch("wl_audit.post_audit_event", return_value=(True, "")):
            result = restore_from_trash_pipeline(
                item_id="trash_456",
                analyst="alice",
                session_key="sk",
            )
        assert set(result["data"].keys()) == {"item_type", "item_name"}, (
            f"data dict shape drift; got: {result['data']!r}"
        )
        assert result["data"]["item_type"] == "rule"
        assert result["data"]["item_name"] == "DR_x"


@pytest.mark.unit
class TestMutationCoverageGroupBTupleContracts:
    """Group B: function-return tuple shapes.

    Functions that return `Tuple[X, str]` (X = list/dict/bool) must
    preserve their arity. A mutation that drops or duplicates an
    element would change the tuple length.
    """

    def test_list_trash_returns_two_tuple_of_list_and_str(self, tmp_path):
        """list_trash → (List[Dict], str)."""
        with patch("wl_trash.get_trash_dir", return_value=str(tmp_path)):
            ret = list_trash()
        assert isinstance(ret, tuple) and len(ret) == 2, (
            f"expected 2-tuple, got: {ret!r}"
        )
        items, error = ret
        assert isinstance(items, list)
        assert isinstance(error, str)

    def test_purge_trash_item_returns_two_tuple_of_bool_and_str(
        self, tmp_path
    ):
        """purge_trash_item → (bool, str). Test the not-found branch."""
        with patch("wl_trash.get_trash_dir", return_value=str(tmp_path)):
            ret = purge_trash_item("nonexistent_id")
        assert isinstance(ret, tuple) and len(ret) == 2, (
            f"expected 2-tuple, got: {ret!r}"
        )
        success, error = ret
        assert isinstance(success, bool)
        assert isinstance(error, str)
        assert success is False, "purging nonexistent item must return False"

    def test_restore_from_trash_returns_two_tuple_on_not_found(
        self, tmp_path
    ):
        """restore_from_trash for missing id → ({}, "Trash item not found")."""
        with patch("wl_trash.get_trash_dir", return_value=str(tmp_path)):
            ret = restore_from_trash("nonexistent_id")
        assert isinstance(ret, tuple) and len(ret) == 2, (
            f"expected 2-tuple, got: {ret!r}"
        )
        meta, error = ret
        assert isinstance(meta, dict)
        assert isinstance(error, str)
        assert meta == {}, "not-found meta must be empty dict"
        assert "not found" in error.lower(), (
            f"expected 'not found' substring; got: {error!r}"
        )


@pytest.mark.unit
class TestMutationCoverageGroupCMetadataShape:
    """Group C: build_trash_metadata dict-key contract.

    The metadata dict written to disk for every trash item must carry
    the documented keys. Mutations that wrap keys (e.g. "item_type" →
    "XXitem_typeXX") would silently corrupt every trash item.
    """

    BASE_REQUIRED_KEYS = {
        "item_type", "name", "deleted_by", "deleted_at",
        "deleted_at_human", "comment", "expiry_ts", "expiry_human",
        "retention_days", "rule_name", "app_context",
    }

    def test_metadata_csv_item_has_base_keys_plus_original_path(self):
        from wl_trash import build_trash_metadata
        with patch("wl_trash.read_trash_config",
                   return_value={"retention_days": 30}):
            meta = build_trash_metadata(
                item_type="csv",
                name="DR_test.csv",
                user="alice",
                comment="cleanup",
                csv_path="/lookups/DR_test.csv",
                now=1700000000,
            )
        missing = self.BASE_REQUIRED_KEYS - set(meta.keys())
        assert not missing, (
            f"csv-item missing base keys: {missing}; got: {set(meta.keys())}"
        )
        # CSV-item-only key: original_path
        assert "original_path" in meta, (
            "csv-item missing 'original_path'"
        )
        assert meta["original_path"] == "/lookups/DR_test.csv"
        # Rule-item-only key MUST NOT be present
        assert "associated_csvs" not in meta, (
            "csv-item must NOT have 'associated_csvs' key"
        )

    def test_metadata_rule_item_has_base_keys_plus_associated_csvs(self):
        from wl_trash import build_trash_metadata
        with patch("wl_trash.read_trash_config",
                   return_value={"retention_days": 30}):
            meta = build_trash_metadata(
                item_type="rule",
                name="DR_test",
                user="alice",
                comment="cleanup",
                associated_csvs=[{"csv_file": "x.csv", "app_context": ""}],
                now=1700000000,
            )
        missing = self.BASE_REQUIRED_KEYS - set(meta.keys())
        assert not missing, (
            f"rule-item missing base keys: {missing}; got: {set(meta.keys())}"
        )
        assert "associated_csvs" in meta
        assert meta["associated_csvs"] == [
            {"csv_file": "x.csv", "app_context": ""}
        ]
        # CSV-item-only key MUST NOT be present
        assert "original_path" not in meta, (
            "rule-item must NOT have 'original_path' key"
        )

    def test_metadata_expiry_ts_equals_now_plus_retention_days_seconds(self):
        """expiry_ts = now + retention_days * 86400 (precise arithmetic).

        Mutations to 86400 (e.g. → 86401) or to the multiplication would
        shift expiry by the affected amount.
        """
        from wl_trash import build_trash_metadata
        with patch("wl_trash.read_trash_config",
                   return_value={"retention_days": 7}):
            meta = build_trash_metadata(
                item_type="csv",
                name="x.csv",
                user="u",
                comment="",
                now=1700000000,
            )
        assert meta["expiry_ts"] == 1700000000 + 7 * 86400, (
            f"expiry_ts arithmetic drift; got: {meta['expiry_ts']!r}"
        )
        assert meta["retention_days"] == 7
