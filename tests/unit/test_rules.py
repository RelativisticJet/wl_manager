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
