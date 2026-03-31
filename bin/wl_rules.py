"""
Whitelist Manager — Layer 3: Detection Rules Registry and CSV Mapping.

This module manages the detection rules registry (which rules exist in the system)
and the rule-to-CSV-file mappings (which CSVs are associated with which rules).

It provides independent read/write operations for:
- Detection rules registry (_detection_rules.json)
- Rule-to-CSV mapping (rule_csv_map.csv)

No interdependencies with trash, approval, or audit modules.
"""

import json
import os
import csv
from typing import List, Dict, Optional

# Import sys.path setup from wl_handler pattern
import sys
sys.path.insert(0, os.path.dirname(__file__))

from wl_constants import OWN_LOOKUPS, DETECTION_RULES_FILE, MAPPING_FILE


__all__ = [
    'read_rules_registry',
    'write_rules_registry',
    'read_csv_mapping',
    'get_rule_csv_file',
]


def read_rules_registry() -> List[str]:
    """
    Read the list of registered detection rule names from the rules registry file.

    Returns an empty list if the file is missing or contains invalid JSON.
    This is a silent failure — suitable for initialization and recovery paths.

    Returns:
        List[str]: List of detection rule names, or empty list if file missing/invalid.
    """
    path = os.path.join(OWN_LOOKUPS, DETECTION_RULES_FILE)
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def write_rules_registry(rules: List[str]) -> None:
    """
    Write the list of detection rule names to the rules registry file.

    Writes atomically by writing to a temporary file first, then renaming.
    Ensures the directory exists before writing.

    Args:
        rules: List of detection rule names to register.

    Raises:
        OSError: If unable to write due to permissions or disk errors.
    """
    path = os.path.join(OWN_LOOKUPS, DETECTION_RULES_FILE)
    # Ensure the directory exists
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # Write atomically: temp file then rename
    temp_path = path + ".tmp"
    try:
        with open(temp_path, "w", encoding="utf-8") as fh:
            json.dump(rules, fh, indent=2)
        # Atomic rename
        if os.path.exists(path):
            os.remove(path)
        os.rename(temp_path, path)
    except OSError:
        # Clean up temp file on error
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
        raise


def read_csv_mapping() -> Dict[str, str]:
    """
    Read the rule-to-CSV-file mapping from rule_csv_map.csv.

    Returns a dictionary mapping detection rule names to CSV file names.
    Returns an empty dict if the file is missing or contains invalid CSV.
    This is a silent failure — suitable for initialization and recovery paths.

    Returns:
        Dict[str, str]: Mapping {detection_rule_name: csv_file_name}.
                        If multiple CSVs map to one rule, the last one wins.
                        Returns empty dict if file missing/invalid.
    """
    if not os.path.isfile(MAPPING_FILE):
        return {}
    try:
        mapping = {}
        with open(MAPPING_FILE, "r", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                if row and "rule_name" in row and "csv_file" in row:
                    rule_name = row["rule_name"]
                    csv_file = row["csv_file"]
                    # If multiple CSVs per rule, last one wins
                    mapping[rule_name] = csv_file
        return mapping
    except (csv.Error, OSError, UnicodeDecodeError):
        return {}


def get_rule_csv_file(rule_name: str) -> Optional[str]:
    """
    Look up the CSV file associated with a detection rule.

    This is a convenience function that reads the full mapping and returns
    the CSV file for a single rule, or None if not found.

    Args:
        rule_name: Name of the detection rule to look up.

    Returns:
        Optional[str]: CSV filename associated with the rule, or None if not found.
    """
    mapping = read_csv_mapping()
    return mapping.get(rule_name)
