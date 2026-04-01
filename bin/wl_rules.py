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
import logging
from threading import Lock
from typing import List, Dict, Optional, Tuple

# Import sys.path setup from wl_handler pattern
import sys
sys.path.insert(0, os.path.dirname(__file__))

from wl_constants import OWN_LOOKUPS, DETECTION_RULES_FILE, MAPPING_FILE, MAX_DETECTION_RULES


_logger = logging.getLogger("wl_rules")
_detection_rules_lock = Lock()

__all__ = [
    'read_rules_registry',
    'write_rules_registry',
    'read_csv_mapping',
    'get_rule_csv_file',
    'get_rule_for_csv',
    'create_rule_pipeline',
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


def get_rule_for_csv(csv_file: str) -> str:
    """Reverse lookup: find the detection rule name for a given CSV file."""
    mapping = read_csv_mapping()
    for rule, csvf in mapping.items():
        if csvf == csv_file:
            return rule
    return ""


# ═══════════════════════════════════════════════════════════════════════════
# Pipeline Functions (Layer 3 orchestration)
# ═══════════════════════════════════════════════════════════════════════════

def create_rule_pipeline(detection_rule: str) -> Dict:
    """
    Register a new detection rule name (without creating a CSV).

    Validates name, checks uniqueness in both mapping and registry,
    persists to registry file under lock.

    Args:
        detection_rule: Rule name to register (will be stripped).

    Returns:
        Dict with keys: success (bool), detection_rule (str), message (str).

    Raises:
        ValueError: Invalid or duplicate rule name, or limit reached.
        OSError: Failed to write registry file.
    """
    detection_rule = (detection_rule or "").strip()

    if not detection_rule:
        raise ValueError("Detection rule name is required")
    if len(detection_rule) > 100:
        raise ValueError(
            "Detection rule name too long: {} chars (max 100)".format(len(detection_rule))
        )
    if not all(c.isalnum() or c in ("_", "-", ".", " ") for c in detection_rule):
        raise ValueError(
            "Detection rule name can only contain letters, "
            "numbers, underscores, hyphens, dots, and spaces"
        )
    if not any(c.isalnum() for c in detection_rule):
        raise ValueError(
            "Detection rule name must contain at least one letter or number"
        )

    # Check mapping (rule_csv_map.csv)
    mapping = read_csv_mapping()
    if detection_rule in mapping:
        raise ValueError("Rule '{}' already exists in CSV mapping".format(detection_rule))

    # Check registry under lock
    with _detection_rules_lock:
        registered = read_rules_registry()
        if detection_rule in registered:
            raise ValueError("Rule '{}' is already registered".format(detection_rule))
        if len(registered) >= MAX_DETECTION_RULES:
            raise ValueError(
                "Maximum number of registered rules reached ({})".format(MAX_DETECTION_RULES)
            )
        registered.append(detection_rule)
        write_rules_registry(registered)  # raises OSError on failure

    return {
        "success": True,
        "detection_rule": detection_rule,
        "message": "Detection rule '{}' registered".format(detection_rule),
    }
