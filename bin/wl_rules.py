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
from contextlib import contextmanager
from typing import List, Dict, Optional, Tuple, Any

# Import sys.path setup from wl_handler pattern
import sys
sys.path.insert(0, os.path.dirname(__file__))

from wl_constants import (
    OWN_LOOKUPS, DETECTION_RULES_FILE, MAPPING_FILE, MAX_DETECTION_RULES,
    DEFAULT_TRASH_RETENTION_DAYS,
)
from wl_csv import update_csv_expected_hash
from wl_filelock import file_lock
from wl_validation import is_ascii_name


_logger = logging.getLogger("wl_rules")

# Cross-process lock for any read-modify-write on the rules registry
# (DETECTION_RULES_FILE) OR the rule-to-CSV mapping (MAPPING_FILE).
# Both files are mutated together by create/delete pipelines and must
# be serialized across Splunk worker processes. Pre-Ring-6.1 this was
# a threading.Lock(), which provided zero cross-process protection
# (R6-F5: deleted rules silently reverted under concurrent admin
# activity). The sibling .rmw.lock file is the kernel-level lock
# domain; data files stay touched only by the read/write themselves.
_RULES_RMW_LOCK_PATH = MAPPING_FILE + ".rmw.lock"


@contextmanager
def rules_rmw_lock(timeout: float = 10):
    """
    Exclusive cross-process lock for rules-registry + mapping RMW.

    Hold this context manager around any sequence that reads either
    DETECTION_RULES_FILE or MAPPING_FILE and writes one or both. Use
    `timeout=10` by default — sufficient for any single legitimate
    operation, will raise TimeoutError if another worker holds the
    lock longer (indicates a stuck process worth investigating).

    Callers in `wl_rules.py` use this internally; `wl_handler.py`
    callers should ALSO use this when modifying rules state, so the
    two modules share one lock domain (not two threading.Locks that
    don't synchronize).
    """
    with file_lock(_RULES_RMW_LOCK_PATH, timeout=timeout):
        yield


__all__ = [
    'read_rules_registry',
    'write_rules_registry',
    'read_csv_mapping',
    'get_rule_csv_file',
    'get_rule_for_csv',
    'create_rule_pipeline',
    'delete_rule_pipeline',
    'delete_csv_pipeline',
    'rules_rmw_lock',
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
    # ASCII-only enforcement. Python's c.isalnum() is Unicode-aware and
    # accepts CJK ideographs, Cyrillic, Greek, etc. — see is_ascii_name()
    # in wl_validation.py for the full rationale (filesystem paths,
    # SPL search, homoglyph attacks).
    if not is_ascii_name(detection_rule, allow_spaces=True):
        raise ValueError(
            "Detection rule name can only contain ASCII letters (A-Z, a-z), "
            "numbers, underscores, hyphens, dots, and spaces"
        )
    if not any(c.isascii() and c.isalnum() for c in detection_rule):
        raise ValueError(
            "Detection rule name must contain at least one letter or number"
        )

    # Single cross-process RMW lock covers BOTH the mapping check and
    # the registry RMW. Pre-Ring-6.1 the mapping check was lockless
    # AND the registry used a per-process threading.Lock — so two
    # workers could both see "rule not present in mapping", both pass
    # the registry uniqueness check, both append, and write_rules_registry
    # would race on the file. The single file_lock here serializes
    # all rule-create attempts across workers.
    with rules_rmw_lock():
        mapping = read_csv_mapping()
        if detection_rule in mapping:
            raise ValueError("Rule '{}' already exists in CSV mapping".format(detection_rule))

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


# ═══════════════════════════════════════════════════════════════════════════
# Deletion Pipelines (Layer 3 orchestration)
# ═══════════════════════════════════════════════════════════════════════════

def _read_mapping_rows() -> List[Dict]:
    """Read rule_csv_map.csv as list of row dicts (rule_name, csv_file, app_context)."""
    if not os.path.isfile(MAPPING_FILE):
        return []
    try:
        with open(MAPPING_FILE, "r", newline="", encoding="utf-8-sig") as fh:
            return list(csv.DictReader(fh))
    except (csv.Error, OSError, UnicodeDecodeError):
        return []


def _write_mapping_rows(rows: List[Dict]) -> None:
    """Write rule_csv_map.csv atomically (temp+rename).

    Pre-Ring-6.1 this did a direct overwrite (`open("w") → writerows`),
    which created a window where readers could observe an empty or
    partially-written file. Now writes to a temp file and renames
    on completion — atomic on POSIX, prevents torn reads.

    After writing, updates the expected-hash registry so the FIM
    watcher can distinguish this legitimate write from external
    modifications (SPL outputlookup, filesystem edits).
    """
    temp_path = MAPPING_FILE + ".tmp"
    try:
        with open(temp_path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(
                fh, fieldnames=["rule_name", "csv_file", "app_context"],
                extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temp_path, MAPPING_FILE)
    except OSError:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
        raise
    # Update expected hash — best effort (don't block mapping write on hash failure)
    try:
        update_csv_expected_hash(MAPPING_FILE)
    except Exception:
        _logger.warning("Failed to update expected hash for rule_csv_map.csv")


def delete_rule_pipeline(
    rule_name: str,
    removal_type: str,
    comment: str,
    analyst: str,
    session_key: str,
) -> Dict[str, Any]:
    """
    Delete a detection rule: remove from mapping and registry, soft-delete CSVs.

    Handles the core business logic of rule deletion:
    1. Reads mapping to find affected CSVs
    2. Removes rule entries from mapping file
    3. Removes rule from registry
    4. If permanent: moves rule + CSVs to trash via wl_trash
    5. Posts audit event

    The handler retains responsibility for:
    - Input validation (rule_name, removal_type, comment)
    - RBAC and admin daily limit checks
    - Dual-admin gate (3+ CSVs)
    - Approval queue cancellation
    - Incrementing admin daily limit counter

    Args:
        rule_name: Detection rule name to delete.
        removal_type: "unlink" (remove mapping only) or "permanent" (soft-delete files).
        comment: Reason for deletion.
        analyst: Username performing the action.
        session_key: Splunk session key for audit posting.

    Returns:
        Dict with keys:
        - success: bool
        - message: str — Human-readable status
        - error: str — Error description if success=False
        - data: dict — {affected_csvs, trashed, trash_id, rule_also_removed}
    """
    from wl_audit import build_audit_event, post_audit_event
    from wl_trash import move_to_trash, read_trash_config
    from wl_validation import build_csv_path

    # Single cross-process RMW lock covers the entire pipeline:
    # mapping read → mapping write → registry RMW. Pre-Ring-6.1 the
    # mapping RMW was lockless, the registry RMW used a per-process
    # threading.Lock, and the two cycles were not synchronized with
    # each other even within one worker. R6-F5 manifested as deleted
    # rules silently reappearing because two workers each took a
    # stale snapshot of the registry; the later writer overwrote the
    # earlier writer's deletion. Holding one file_lock for the whole
    # body closes that window.
    with rules_rmw_lock():
        mapping = _read_mapping_rows()
        affected_entries = [e for e in mapping if e.get("rule_name") == rule_name]
        affected_csvs = [e["csv_file"] for e in affected_entries]

        # Case 1: Rule has no CSVs — just remove from registry
        if not affected_csvs:
            registered = read_rules_registry()
            if rule_name not in registered:
                return {
                    "success": False,
                    "message": "",
                    "error": "Rule '{}' not found in mapping or registry".format(rule_name),
                    "data": {},
                }
            registered.remove(rule_name)
            write_rules_registry(registered)

            evt = build_audit_event(
                action="dr_removed",
                analyst=analyst,
                detection_rule=rule_name,
                csv_file="",
                comment=comment,
                removal_type=removal_type,
                csv_count=0,
                csv_files="",
            )
            post_audit_event(session_key, evt)

            return {
                "success": True,
                "message": "Rule '{}' removed (had no CSV files)".format(rule_name),
                "error": "",
                "data": {"affected_csvs": [], "trashed": False, "trash_id": ""},
            }

        # Case 2: Rule has CSVs — remove from mapping and registry
        new_mapping = [e for e in mapping if e.get("rule_name") != rule_name]
        _write_mapping_rows(new_mapping)

        registered = read_rules_registry()
        if rule_name in registered:
            registered.remove(rule_name)
            write_rules_registry(registered)

    trashed = False
    trash_id = ""
    if removal_type == "permanent":
        associated = [{"csv_file": e["csv_file"],
                       "app_context": e.get("app_context", "")}
                      for e in affected_entries]
        try:
            trash_id = move_to_trash(
                "rule", rule_name, analyst, comment,
                associated_csvs=associated)
            trashed = True
        except Exception as exc:
            _logger.error("Failed to move rule to trash: %s", exc)
            for entry in affected_entries:
                csv_name = entry["csv_file"]
                app_ctx = entry.get("app_context", "")
                csv_path = build_csv_path(csv_name, app_ctx)
                if csv_path and os.path.isfile(csv_path):
                    try:
                        os.remove(csv_path)
                    except OSError:
                        pass

    evt = build_audit_event(
        action="dr_removed",
        analyst=analyst,
        detection_rule=rule_name,
        csv_file="",
        comment=comment,
        removal_type="trashed" if trashed else removal_type,
        csv_count=len(affected_csvs),
        csv_files=", ".join(affected_csvs),
        trash_id=trash_id,
    )
    post_audit_event(session_key, evt)

    if trashed:
        verb = "moved to trash"
    elif removal_type == "permanent":
        verb = "deleted"
    else:
        verb = "unlinked"

    msg = "Rule '{}' {} ({} CSV file{})".format(
        rule_name, verb, len(affected_csvs),
        "s" if len(affected_csvs) != 1 else "")
    if trashed:
        config = read_trash_config()
        days = config.get("retention_days", DEFAULT_TRASH_RETENTION_DAYS)
        msg += ". Recoverable for {} days.".format(days)

    return {
        "success": True,
        "message": msg,
        "error": "",
        "data": {
            "affected_csvs": affected_csvs,
            "trashed": trashed,
            "trash_id": trash_id,
        },
    }


def delete_csv_pipeline(
    csv_file: str,
    removal_type: str,
    comment: str,
    analyst: str,
    session_key: str,
    rule_name: str = "",
) -> Dict[str, Any]:
    """
    Delete a CSV file: remove from mapping, soft-delete file if permanent.

    Handles the core business logic of CSV deletion:
    1. Finds the CSV entry in mapping (resolves rule_name if not provided)
    2. Checks if this is the last CSV for its rule
    3. Removes from mapping file
    4. If permanent: moves CSV to trash via wl_trash
    5. Posts audit event

    The handler retains responsibility for:
    - Input validation (csv_file, removal_type, comment)
    - RBAC and admin daily limit checks
    - Approval queue cancellation
    - Incrementing admin daily limit counter

    Args:
        csv_file: CSV filename to delete.
        removal_type: "unlink" (remove mapping only) or "permanent" (soft-delete file).
        comment: Reason for deletion.
        analyst: Username performing the action.
        session_key: Splunk session key for audit posting.
        rule_name: Detection rule name (resolved from mapping if empty).

    Returns:
        Dict with keys:
        - success: bool
        - message: str — Human-readable status
        - error: str — Error description if success=False
        - data: dict — {rule_also_removed, trashed, trash_id, app_context}
    """
    from wl_audit import build_audit_event, post_audit_event
    from wl_trash import move_to_trash, read_trash_config
    from wl_validation import build_csv_path

    # Single cross-process RMW lock covers the mapping RMW and
    # (conditionally) the registry RMW. Matches the structure of
    # delete_rule_pipeline — R6-F5 affected this pipeline too because
    # the two RMW cycles were independently lockless across workers.
    with rules_rmw_lock():
        mapping = _read_mapping_rows()

        # Find the specific entry
        found_entry = None
        for e in mapping:
            if e.get("csv_file") == csv_file:
                if not rule_name:
                    rule_name = e.get("rule_name", "")
                found_entry = e
                break

        if not found_entry:
            return {
                "success": False,
                "message": "",
                "error": "CSV '{}' not found in mapping".format(csv_file),
                "data": {},
            }

        app_context = found_entry.get("app_context", "")

        # Check if this is the last CSV for the rule
        rule_csvs = [e["csv_file"] for e in mapping
                     if e.get("rule_name") == rule_name]
        rule_also_removed = (len(rule_csvs) == 1)

        # Remove the CSV entry from mapping
        new_mapping = [e for e in mapping
                       if not (e.get("csv_file") == csv_file
                               and e.get("rule_name") == rule_name)]
        _write_mapping_rows(new_mapping)

        # If last CSV for rule, also remove rule from registry
        if rule_also_removed:
            registered = read_rules_registry()
            if rule_name in registered:
                registered.remove(rule_name)
                write_rules_registry(registered)

    trashed = False
    trash_id = ""
    if removal_type == "permanent":
        try:
            trash_id = move_to_trash(
                "csv", csv_file, analyst, comment,
                app_context=app_context, detection_rule=rule_name)
            trashed = True
        except Exception as exc:
            _logger.error("Failed to move CSV to trash: %s", exc)
            csv_path = build_csv_path(csv_file, app_context)
            if csv_path and os.path.isfile(csv_path):
                try:
                    os.remove(csv_path)
                except OSError:
                    pass

    evt = build_audit_event(
        action="csv_removed",
        analyst=analyst,
        detection_rule=rule_name,
        csv_file=csv_file,
        app_context=app_context,
        comment=comment,
        removal_type="trashed" if trashed else removal_type,
        rule_also_removed=rule_also_removed,
        file_deleted=trashed,
        trash_id=trash_id,
    )
    post_audit_event(session_key, evt)

    if trashed:
        verb = "moved to trash"
    elif removal_type == "permanent":
        verb = "deleted"
    else:
        verb = "unlinked"
    msg = "CSV '{}' {}".format(csv_file, verb)
    if rule_also_removed:
        msg += " (last CSV — rule '{}' also removed)".format(rule_name)
    if trashed:
        config = read_trash_config()
        days = config.get("retention_days", DEFAULT_TRASH_RETENTION_DAYS)
        msg += ". Recoverable for {} days.".format(days)

    return {
        "success": True,
        "message": msg,
        "error": "",
        "data": {
            "rule_also_removed": rule_also_removed,
            "trashed": trashed,
            "trash_id": trash_id,
            "app_context": app_context,
            "rule_name": rule_name,
            "affected_csvs": [csv_file],
        },
    }
