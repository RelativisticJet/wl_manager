"""
Unit tests for wl_rules module.

Tests detection rules registry and CSV mapping operations.
Requires ≥80% coverage of read_rules_registry, write_rules_registry,
read_csv_mapping, and get_rule_csv_file functions.
"""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Import wl_rules module (sys.path setup is in wl_rules)
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))) + "/bin")

from wl_rules import (
    read_rules_registry,
    write_rules_registry,
    read_csv_mapping,
    get_rule_csv_file,
    get_rule_for_csv,
    delete_rule_pipeline,
    delete_csv_pipeline,
    create_rule_pipeline,
)


@pytest.mark.unit
class TestReadRulesRegistry:
    """Tests for read_rules_registry function."""

    def test_read_rules_registry_valid_json(self, tmp_path):
        """Test reading valid rules registry JSON file."""
        rules_file = tmp_path / "_detection_rules.json"
        expected_rules = ["rule_a", "rule_b", "rule_c"]
        rules_file.write_text(json.dumps(expected_rules))

        with patch("wl_rules.OWN_LOOKUPS", str(tmp_path)):
            result = read_rules_registry()

        assert result == expected_rules

    def test_read_rules_registry_missing_file(self, tmp_path):
        """Test reading when rules registry file is missing."""
        with patch("wl_rules.OWN_LOOKUPS", str(tmp_path)):
            result = read_rules_registry()

        assert result == []

    def test_read_rules_registry_invalid_json(self, tmp_path):
        """Test reading invalid JSON in rules registry file."""
        rules_file = tmp_path / "_detection_rules.json"
        rules_file.write_text("{ invalid json }")

        with patch("wl_rules.OWN_LOOKUPS", str(tmp_path)):
            result = read_rules_registry()

        assert result == []

    def test_read_rules_registry_not_a_list(self, tmp_path):
        """Test reading valid JSON that is not a list."""
        rules_file = tmp_path / "_detection_rules.json"
        rules_file.write_text(json.dumps({"rules": ["a", "b"]}))

        with patch("wl_rules.OWN_LOOKUPS", str(tmp_path)):
            result = read_rules_registry()

        assert result == []

    def test_read_rules_registry_empty_list(self, tmp_path):
        """Test reading empty rules list."""
        rules_file = tmp_path / "_detection_rules.json"
        rules_file.write_text(json.dumps([]))

        with patch("wl_rules.OWN_LOOKUPS", str(tmp_path)):
            result = read_rules_registry()

        assert result == []


@pytest.mark.unit
class TestWriteRulesRegistry:
    """Tests for write_rules_registry function."""

    def test_write_rules_registry_normal(self, tmp_path):
        """Test writing rules registry to file."""
        with patch("wl_rules.OWN_LOOKUPS", str(tmp_path)):
            rules = ["rule_a", "rule_b"]
            write_rules_registry(rules)

        # Verify file was created and contains correct data
        rules_file = tmp_path / "_detection_rules.json"
        assert rules_file.exists()
        content = json.loads(rules_file.read_text())
        assert content == rules

    def test_write_rules_registry_creates_directory(self, tmp_path):
        """Test that write_rules_registry creates directory if missing."""
        nested_path = tmp_path / "nested" / "path"
        with patch("wl_rules.OWN_LOOKUPS", str(nested_path)):
            rules = ["rule_x"]
            write_rules_registry(rules)

        rules_file = nested_path / "_detection_rules.json"
        assert rules_file.exists()

    def test_write_rules_registry_overwrites_existing(self, tmp_path):
        """Test that write_rules_registry overwrites existing file."""
        rules_file = tmp_path / "_detection_rules.json"
        rules_file.write_text(json.dumps(["old_rule"]))

        with patch("wl_rules.OWN_LOOKUPS", str(tmp_path)):
            new_rules = ["new_rule_a", "new_rule_b"]
            write_rules_registry(new_rules)

        content = json.loads(rules_file.read_text())
        assert content == new_rules

    def test_write_rules_registry_atomic(self, tmp_path):
        """Test that write_rules_registry uses atomic rename."""
        with patch("wl_rules.OWN_LOOKUPS", str(tmp_path)):
            rules = ["rule_1", "rule_2"]
            write_rules_registry(rules)

        # Verify temp file was cleaned up
        temp_file = tmp_path / "_detection_rules.json.tmp"
        assert not temp_file.exists()

    def test_write_rules_registry_empty_list(self, tmp_path):
        """Test writing empty rules list."""
        with patch("wl_rules.OWN_LOOKUPS", str(tmp_path)):
            write_rules_registry([])

        rules_file = tmp_path / "_detection_rules.json"
        content = json.loads(rules_file.read_text())
        assert content == []

    def test_write_rules_registry_cleans_tempfile_on_rename_error(self, tmp_path):
        """If os.rename fails, the .tmp file is cleaned up and OSError
        re-raised (covers wl_rules.py lines 126-133).
        """
        import wl_rules
        with patch("wl_rules.OWN_LOOKUPS", str(tmp_path)), \
             patch.object(wl_rules.os, "rename",
                          side_effect=OSError("simulated rename failure")):
            with pytest.raises(OSError, match="simulated rename failure"):
                write_rules_registry(["rule_x"])

        # Temp file must be cleaned up (covers the inner try/except)
        temp_file = tmp_path / "_detection_rules.json.tmp"
        assert not temp_file.exists(), \
            "temp file was not cleaned up after rename failure"

    def test_write_rules_registry_swallows_cleanup_oserror(self, tmp_path):
        """If os.remove(temp_path) ALSO fails, the original OSError still
        propagates (covers the inner OSError-swallowing branch at line 131-132).
        """
        import wl_rules
        call_count = {"remove": 0}
        original_remove = os.remove

        def flaky_remove(path):
            call_count["remove"] += 1
            # First remove call (target file) succeeds; second (temp cleanup) fails
            if call_count["remove"] >= 1 and path.endswith(".tmp"):
                raise OSError("cleanup also failed")
            return original_remove(path)

        with patch("wl_rules.OWN_LOOKUPS", str(tmp_path)), \
             patch.object(wl_rules.os, "rename",
                          side_effect=OSError("rename failed")), \
             patch.object(wl_rules.os, "remove", side_effect=flaky_remove):
            with pytest.raises(OSError, match="rename failed"):
                write_rules_registry(["rule_x"])


@pytest.mark.unit
class TestReadCsvMapping:
    """Tests for read_csv_mapping function."""

    def test_read_csv_mapping_valid_csv(self, tmp_path):
        """Test reading valid rule_csv_map.csv file."""
        csv_file = tmp_path / "rule_csv_map.csv"
        csv_content = "rule_name,csv_file,app_context\nrule_a,DR_a.csv,\nrule_b,DR_b.csv,app1"
        csv_file.write_text(csv_content)

        with patch("wl_rules.MAPPING_FILE", str(csv_file)):
            result = read_csv_mapping()

        assert len(result) == 2
        assert result["rule_a"] == "DR_a.csv"
        assert result["rule_b"] == "DR_b.csv"

    def test_read_csv_mapping_missing_file(self):
        """Test reading when rule_csv_map.csv is missing."""
        with patch("wl_rules.MAPPING_FILE", "/nonexistent/path/rule_csv_map.csv"):
            result = read_csv_mapping()

        assert result == {}

    def test_read_csv_mapping_empty_csv(self, tmp_path):
        """Test reading empty CSV file (header only)."""
        csv_file = tmp_path / "rule_csv_map.csv"
        csv_file.write_text("rule_name,csv_file,app_context\n")

        with patch("wl_rules.MAPPING_FILE", str(csv_file)):
            result = read_csv_mapping()

        assert result == {}

    def test_read_csv_mapping_missing_headers(self, tmp_path):
        """Test reading CSV with missing required headers."""
        csv_file = tmp_path / "rule_csv_map.csv"
        csv_content = "name,file\nrule_a,DR_a.csv"
        csv_file.write_text(csv_content)

        with patch("wl_rules.MAPPING_FILE", str(csv_file)):
            result = read_csv_mapping()

        # Should handle gracefully and return empty dict
        assert result == {}

    def test_read_csv_mapping_invalid_csv(self, tmp_path):
        """Test reading malformed CSV file."""
        csv_file = tmp_path / "rule_csv_map.csv"
        csv_file.write_text("rule_name,csv_file\nrule_a,\"unclosed quote")

        with patch("wl_rules.MAPPING_FILE", str(csv_file)):
            result = read_csv_mapping()

        # Should handle CSV parsing error gracefully
        assert isinstance(result, dict)

    def test_read_csv_mapping_duplicate_rules_last_wins(self, tmp_path):
        """Test that when a rule appears multiple times, last CSV wins."""
        csv_file = tmp_path / "rule_csv_map.csv"
        csv_content = "rule_name,csv_file,app_context\nrule_a,DR_old.csv,\nrule_a,DR_new.csv,"
        csv_file.write_text(csv_content)

        with patch("wl_rules.MAPPING_FILE", str(csv_file)):
            result = read_csv_mapping()

        assert result["rule_a"] == "DR_new.csv"


@pytest.mark.unit
class TestGetRuleCsvFile:
    """Tests for get_rule_csv_file function."""

    def test_get_rule_csv_file_found(self, tmp_path):
        """Test looking up CSV for an existing rule."""
        csv_file = tmp_path / "rule_csv_map.csv"
        csv_content = "rule_name,csv_file,app_context\nrule_a,DR_a.csv,"
        csv_file.write_text(csv_content)

        with patch("wl_rules.MAPPING_FILE", str(csv_file)):
            result = get_rule_csv_file("rule_a")

        assert result == "DR_a.csv"

    def test_get_rule_csv_file_not_found(self, tmp_path):
        """Test looking up CSV for a nonexistent rule."""
        csv_file = tmp_path / "rule_csv_map.csv"
        csv_content = "rule_name,csv_file,app_context\nrule_a,DR_a.csv,"
        csv_file.write_text(csv_content)

        with patch("wl_rules.MAPPING_FILE", str(csv_file)):
            result = get_rule_csv_file("nonexistent_rule")

        assert result is None


@pytest.mark.unit
class TestGetRuleForCsv:
    """Tests for get_rule_for_csv (reverse lookup, lines 183-189)."""

    def test_reverse_lookup_finds_rule(self, tmp_path):
        """CSV present in mapping → return its rule name."""
        csv_file = tmp_path / "rule_csv_map.csv"
        csv_file.write_text(
            "rule_name,csv_file,app_context\n"
            "rule_x,DR_x.csv,\n"
            "rule_y,DR_y.csv,wl_manager\n"
        )
        with patch("wl_rules.MAPPING_FILE", str(csv_file)):
            assert get_rule_for_csv("DR_y.csv") == "rule_y"
            assert get_rule_for_csv("DR_x.csv") == "rule_x"

    def test_reverse_lookup_returns_empty_string_when_csv_missing(self, tmp_path):
        """CSV not present in any mapping → empty string."""
        csv_file = tmp_path / "rule_csv_map.csv"
        csv_file.write_text(
            "rule_name,csv_file,app_context\nrule_a,DR_a.csv,\n"
        )
        with patch("wl_rules.MAPPING_FILE", str(csv_file)):
            assert get_rule_for_csv("missing.csv") == ""

    def test_reverse_lookup_returns_empty_on_missing_mapping_file(self, tmp_path):
        """No mapping file at all → empty string (read_csv_mapping returns {})."""
        nonexistent = tmp_path / "no_such_mapping.csv"
        with patch("wl_rules.MAPPING_FILE", str(nonexistent)):
            assert get_rule_for_csv("anything.csv") == ""

    def test_get_rule_csv_file_mapping_missing(self):
        """Test looking up CSV when mapping file is missing."""
        with patch("wl_rules.MAPPING_FILE", "/nonexistent/path/rule_csv_map.csv"):
            result = get_rule_csv_file("rule_a")

        assert result is None

    def test_get_rule_csv_file_empty_mapping(self, tmp_path):
        """Test looking up CSV in empty mapping."""
        csv_file = tmp_path / "rule_csv_map.csv"
        csv_file.write_text("rule_name,csv_file,app_context\n")

        with patch("wl_rules.MAPPING_FILE", str(csv_file)):
            result = get_rule_csv_file("any_rule")

        assert result is None


# ════════════════════════════════════════════════════════════════════════════
# Pipeline Tests
# ════════════════════════════════════════════════════════════════════════════

def _setup_mapping(tmp_path, rows):
    """Helper: write a rule_csv_map.csv with given rows."""
    import csv as csv_mod
    csv_file = tmp_path / "rule_csv_map.csv"
    with open(str(csv_file), "w", newline="", encoding="utf-8") as fh:
        writer = csv_mod.DictWriter(
            fh, fieldnames=["rule_name", "csv_file", "app_context"])
        writer.writeheader()
        writer.writerows(rows)
    return str(csv_file)


def _setup_registry(tmp_path, rules):
    """Helper: write a detection rules registry."""
    rules_file = tmp_path / "_detection_rules.json"
    rules_file.write_text(json.dumps(rules))


@pytest.mark.unit
class TestDeleteRulePipeline:
    """Tests for delete_rule_pipeline."""

    @patch("wl_audit.post_audit_event")
    @patch("wl_audit.build_audit_event", return_value={"action": "dr_removed"})
    def test_delete_rule_no_csvs(self, mock_build, mock_post, tmp_path):
        """Delete a rule that has no CSVs — removes from registry only."""
        _setup_mapping(tmp_path, [])
        _setup_registry(tmp_path, ["orphan_rule"])
        mapping_path = str(tmp_path / "rule_csv_map.csv")

        with patch("wl_rules.MAPPING_FILE", mapping_path), \
             patch("wl_rules.OWN_LOOKUPS", str(tmp_path)):
            result = delete_rule_pipeline(
                "orphan_rule", "permanent", "cleanup", "admin", "sess123")

        assert result["success"] is True
        assert "no CSV" in result["message"]
        # Rule removed from registry
        with patch("wl_rules.OWN_LOOKUPS", str(tmp_path)):
            assert "orphan_rule" not in read_rules_registry()
        mock_post.assert_called_once()

    @patch("wl_audit.post_audit_event")
    @patch("wl_audit.build_audit_event", return_value={"action": "dr_removed"})
    def test_delete_rule_not_found(self, mock_build, mock_post, tmp_path):
        """Delete a rule that doesn't exist anywhere."""
        _setup_mapping(tmp_path, [])
        _setup_registry(tmp_path, ["other_rule"])
        mapping_path = str(tmp_path / "rule_csv_map.csv")

        with patch("wl_rules.MAPPING_FILE", mapping_path), \
             patch("wl_rules.OWN_LOOKUPS", str(tmp_path)):
            result = delete_rule_pipeline(
                "ghost_rule", "permanent", "test", "admin", "sess123")

        assert result["success"] is False
        assert "not found" in result["error"]

    @patch("wl_audit.post_audit_event")
    @patch("wl_audit.build_audit_event", return_value={"action": "dr_removed"})
    @patch("wl_trash.move_to_trash", return_value="rule1__rule__20260402")
    def test_delete_rule_with_csvs_permanent(
        self, mock_trash, mock_build, mock_post, tmp_path
    ):
        """Delete a rule with CSVs using permanent removal — trashes the bundle."""
        rows = [
            {"rule_name": "rule1", "csv_file": "DR1.csv", "app_context": ""},
            {"rule_name": "rule1", "csv_file": "DR2.csv", "app_context": ""},
            {"rule_name": "rule2", "csv_file": "DR3.csv", "app_context": ""},
        ]
        mapping_path = _setup_mapping(tmp_path, rows)
        _setup_registry(tmp_path, ["rule1", "rule2"])

        with patch("wl_rules.MAPPING_FILE", mapping_path), \
             patch("wl_rules.OWN_LOOKUPS", str(tmp_path)):
            result = delete_rule_pipeline(
                "rule1", "permanent", "decommission", "admin", "sess123")

        assert result["success"] is True
        assert result["data"]["trashed"] is True
        assert set(result["data"]["affected_csvs"]) == {"DR1.csv", "DR2.csv"}
        mock_trash.assert_called_once()

        # Mapping should no longer have rule1 entries
        import csv as csv_mod
        with open(mapping_path, "r", encoding="utf-8") as fh:
            remaining = list(csv_mod.DictReader(fh))
        assert all(r["rule_name"] != "rule1" for r in remaining)
        assert len(remaining) == 1  # rule2 still there

        # Registry should not have rule1
        with patch("wl_rules.OWN_LOOKUPS", str(tmp_path)):
            reg = read_rules_registry()
        assert "rule1" not in reg
        assert "rule2" in reg

    @patch("wl_audit.post_audit_event")
    @patch("wl_audit.build_audit_event", return_value={"action": "dr_removed"})
    def test_delete_rule_unlink(self, mock_build, mock_post, tmp_path):
        """Delete a rule with unlink — removes mapping but doesn't trash files."""
        rows = [{"rule_name": "rule1", "csv_file": "DR1.csv", "app_context": ""}]
        mapping_path = _setup_mapping(tmp_path, rows)
        _setup_registry(tmp_path, ["rule1"])

        with patch("wl_rules.MAPPING_FILE", mapping_path), \
             patch("wl_rules.OWN_LOOKUPS", str(tmp_path)):
            result = delete_rule_pipeline(
                "rule1", "unlink", "unlinking", "admin", "sess123")

        assert result["success"] is True
        assert result["data"]["trashed"] is False
        assert "unlinked" in result["message"]

    @patch("wl_audit.post_audit_event")
    @patch("wl_audit.build_audit_event", return_value={"action": "dr_removed"})
    @patch("wl_trash.move_to_trash", side_effect=OSError("disk full"))
    def test_delete_rule_trash_failure_fallback(
        self, mock_trash, mock_build, mock_post, tmp_path
    ):
        """When trash fails, falls back to hard delete."""
        rows = [{"rule_name": "rule1", "csv_file": "DR1.csv", "app_context": ""}]
        mapping_path = _setup_mapping(tmp_path, rows)
        _setup_registry(tmp_path, ["rule1"])

        with patch("wl_rules.MAPPING_FILE", mapping_path), \
             patch("wl_rules.OWN_LOOKUPS", str(tmp_path)), \
             patch("wl_validation.build_csv_path", return_value=None):
            result = delete_rule_pipeline(
                "rule1", "permanent", "test", "admin", "sess123")

        assert result["success"] is True
        assert result["data"]["trashed"] is False


@pytest.mark.unit
class TestDeleteCsvPipeline:
    """Tests for delete_csv_pipeline."""

    @patch("wl_audit.post_audit_event")
    @patch("wl_audit.build_audit_event", return_value={"action": "csv_removed"})
    @patch("wl_trash.move_to_trash", return_value="DR1__csv__20260402")
    def test_delete_csv_permanent(self, mock_trash, mock_build, mock_post, tmp_path):
        """Delete a CSV with permanent removal — trashes the file."""
        rows = [
            {"rule_name": "rule1", "csv_file": "DR1.csv", "app_context": ""},
            {"rule_name": "rule1", "csv_file": "DR2.csv", "app_context": ""},
        ]
        mapping_path = _setup_mapping(tmp_path, rows)
        _setup_registry(tmp_path, ["rule1"])

        with patch("wl_rules.MAPPING_FILE", mapping_path), \
             patch("wl_rules.OWN_LOOKUPS", str(tmp_path)):
            result = delete_csv_pipeline(
                "DR1.csv", "permanent", "removing", "admin", "sess123")

        assert result["success"] is True
        assert result["data"]["trashed"] is True
        assert result["data"]["rule_also_removed"] is False
        mock_trash.assert_called_once()

    @patch("wl_audit.post_audit_event")
    @patch("wl_audit.build_audit_event", return_value={"action": "csv_removed"})
    @patch("wl_trash.move_to_trash", return_value="DR1__csv__20260402")
    def test_delete_csv_last_for_rule(
        self, mock_trash, mock_build, mock_post, tmp_path
    ):
        """Deleting last CSV for a rule also removes the rule from registry."""
        rows = [{"rule_name": "rule1", "csv_file": "DR1.csv", "app_context": ""}]
        mapping_path = _setup_mapping(tmp_path, rows)
        _setup_registry(tmp_path, ["rule1"])

        with patch("wl_rules.MAPPING_FILE", mapping_path), \
             patch("wl_rules.OWN_LOOKUPS", str(tmp_path)):
            result = delete_csv_pipeline(
                "DR1.csv", "permanent", "removing", "admin", "sess123")

        assert result["success"] is True
        assert result["data"]["rule_also_removed"] is True

        # Rule should be removed from registry
        with patch("wl_rules.OWN_LOOKUPS", str(tmp_path)):
            assert "rule1" not in read_rules_registry()

    @patch("wl_audit.post_audit_event")
    @patch("wl_audit.build_audit_event", return_value={"action": "csv_removed"})
    def test_delete_csv_not_found(self, mock_build, mock_post, tmp_path):
        """Delete a CSV that doesn't exist in mapping."""
        rows = [{"rule_name": "rule1", "csv_file": "DR1.csv", "app_context": ""}]
        mapping_path = _setup_mapping(tmp_path, rows)

        with patch("wl_rules.MAPPING_FILE", mapping_path):
            result = delete_csv_pipeline(
                "nonexistent.csv", "permanent", "test", "admin", "sess123")

        assert result["success"] is False
        assert "not found" in result["error"]

    @patch("wl_audit.post_audit_event")
    @patch("wl_audit.build_audit_event", return_value={"action": "csv_removed"})
    def test_delete_csv_unlink(self, mock_build, mock_post, tmp_path):
        """Delete CSV with unlink — removes mapping only."""
        rows = [{"rule_name": "rule1", "csv_file": "DR1.csv", "app_context": ""}]
        mapping_path = _setup_mapping(tmp_path, rows)
        _setup_registry(tmp_path, ["rule1"])

        with patch("wl_rules.MAPPING_FILE", mapping_path), \
             patch("wl_rules.OWN_LOOKUPS", str(tmp_path)):
            result = delete_csv_pipeline(
                "DR1.csv", "unlink", "test", "admin", "sess123")

        assert result["success"] is True
        assert result["data"]["trashed"] is False
        assert "unlinked" in result["message"]

    @patch("wl_audit.post_audit_event")
    @patch("wl_audit.build_audit_event", return_value={"action": "csv_removed"})
    def test_delete_csv_resolves_rule_name(self, mock_build, mock_post, tmp_path):
        """When rule_name not provided, pipeline resolves it from mapping."""
        rows = [{"rule_name": "auto_rule", "csv_file": "DR1.csv", "app_context": ""}]
        mapping_path = _setup_mapping(tmp_path, rows)
        _setup_registry(tmp_path, ["auto_rule"])

        with patch("wl_rules.MAPPING_FILE", mapping_path), \
             patch("wl_rules.OWN_LOOKUPS", str(tmp_path)):
            result = delete_csv_pipeline(
                "DR1.csv", "unlink", "test", "admin", "sess123",
                rule_name="")  # empty — should be resolved

        assert result["success"] is True
        assert result["data"]["rule_name"] == "auto_rule"


@pytest.mark.unit
class TestCreateRulePipeline:
    """Tests for create_rule_pipeline — the 8 validation branches at
    wl_rules.py:213-261 plus the cross-process-locked happy path.
    """

    def test_empty_name_raises_value_error(self):
        with pytest.raises(ValueError, match="required"):
            create_rule_pipeline("")

    def test_whitespace_only_name_raises_value_error(self):
        with pytest.raises(ValueError, match="required"):
            create_rule_pipeline("   ")

    def test_name_too_long_raises_value_error(self):
        with pytest.raises(ValueError, match="too long"):
            create_rule_pipeline("a" * 101)

    def test_name_with_non_ascii_raises_value_error(self):
        with pytest.raises(ValueError, match="ASCII"):
            create_rule_pipeline("DR_тест")

    def test_name_with_only_special_chars_raises_value_error(self):
        # Passes the ASCII check (allow_spaces=True permits dots/hyphens/etc)
        # but fails the "must contain at least one alphanumeric" check.
        with pytest.raises(ValueError, match="at least one letter"):
            create_rule_pipeline("---...")

    def test_duplicate_in_mapping_raises_value_error(self, tmp_path):
        """Rule already present in rule_csv_map.csv → ValueError."""
        rows = [{"rule_name": "DR_existing", "csv_file": "x.csv",
                 "app_context": ""}]
        mapping_path = _setup_mapping(tmp_path, rows)
        _setup_registry(tmp_path, [])

        with patch("wl_rules.MAPPING_FILE", mapping_path), \
             patch("wl_rules.OWN_LOOKUPS", str(tmp_path)):
            with pytest.raises(ValueError, match="already exists in CSV mapping"):
                create_rule_pipeline("DR_existing")

    def test_duplicate_in_registry_raises_value_error(self, tmp_path):
        """Rule already registered in _detection_rules.json → ValueError."""
        mapping_path = _setup_mapping(tmp_path, [])  # empty mapping
        _setup_registry(tmp_path, ["DR_already_registered"])

        with patch("wl_rules.MAPPING_FILE", mapping_path), \
             patch("wl_rules.OWN_LOOKUPS", str(tmp_path)):
            with pytest.raises(ValueError, match="already registered"):
                create_rule_pipeline("DR_already_registered")

    def test_max_rules_exceeded_raises_value_error(self, tmp_path):
        """At MAX_DETECTION_RULES limit → ValueError."""
        from wl_constants import MAX_DETECTION_RULES
        mapping_path = _setup_mapping(tmp_path, [])
        # Fill registry to the limit
        full_registry = [f"DR_{i}" for i in range(MAX_DETECTION_RULES)]
        _setup_registry(tmp_path, full_registry)

        with patch("wl_rules.MAPPING_FILE", mapping_path), \
             patch("wl_rules.OWN_LOOKUPS", str(tmp_path)):
            with pytest.raises(ValueError, match="Maximum number"):
                create_rule_pipeline("DR_one_too_many")

    def test_happy_path_appends_to_registry(self, tmp_path):
        """Valid new rule → success, persisted to registry."""
        mapping_path = _setup_mapping(tmp_path, [])
        _setup_registry(tmp_path, ["DR_existing"])

        with patch("wl_rules.MAPPING_FILE", mapping_path), \
             patch("wl_rules.OWN_LOOKUPS", str(tmp_path)):
            result = create_rule_pipeline("DR_new")
            # Verify registered
            assert result["success"] is True
            assert result["detection_rule"] == "DR_new"
            assert "registered" in result["message"]
            # Verify persisted
            persisted = read_rules_registry()
            assert "DR_new" in persisted
            assert "DR_existing" in persisted  # original kept

    def test_name_stripped_of_surrounding_whitespace(self, tmp_path):
        """Whitespace around a valid name is stripped before validation."""
        mapping_path = _setup_mapping(tmp_path, [])
        _setup_registry(tmp_path, [])

        with patch("wl_rules.MAPPING_FILE", mapping_path), \
             patch("wl_rules.OWN_LOOKUPS", str(tmp_path)):
            result = create_rule_pipeline("  DR_padded  ")
        assert result["detection_rule"] == "DR_padded"
