"""
Pipeline Functions — Layer 4 Business Logic Orchestration

This module provides high-level pipeline functions that orchestrate CSV operations,
version control, rule management, and trash operations. Used by both wl_handler.py
and wl_replay.py to ensure consistent business logic across approval and direct flows.

Each pipeline function:
- Takes raw input parameters
- Calls domain module functions (wl_csv, wl_versions, wl_rules, wl_trash)
- Returns (success: bool, message: str, data: dict) tuple

This module is the single source of truth for business logic orchestration,
reducing duplication between handler and replay modules.
"""

import os
from typing import Tuple, Dict, Any, List, Optional

from wl_constants import OWN_LOOKUPS
from wl_validation import build_csv_path, resolve_csv_path, safe_realpath
from wl_csv import read_csv, write_csv, compute_diff
from wl_versions import snapshot_version, get_versions_list, read_version_manifest
from wl_rules import read_rules_registry, write_rules_registry, read_csv_mapping, get_rule_csv_file
from wl_trash import move_to_trash, restore_from_trash
from wl_audit import post_audit_event


__all__ = [
    'save_csv_pipeline',
    'create_csv_pipeline',
    'revert_csv_pipeline',
    'create_rule_pipeline',
    'remove_rule_pipeline',
    'remove_csv_pipeline',
    'restore_csv_pipeline',
]


# ═══════════════════════════════════════════════════════════════════════════
# CSV Operation Pipelines
# ═══════════════════════════════════════════════════════════════════════════

def save_csv_pipeline(csv_file: str, new_rows: List[Dict],
                      new_headers: Optional[List[str]] = None,
                      expected_mtime: Optional[float] = None,
                      comment: str = "", reason: str = "", user: str = "") -> Tuple[bool, str, Dict]:
    """
    Save CSV file with diff computation, version snapshot, and audit logging.

    This is a thin wrapper that delegates to domain modules for the actual work.
    The handler's _save_csv_inner logic remains in the handler (for now) to preserve
    its complex approval gate and limit enforcement logic.

    Args:
        csv_file: CSV file name (e.g., "DR102.csv")
        new_rows: New row list (list of dicts)
        new_headers: New headers list or None to keep existing
        expected_mtime: Optimistic lock timestamp or None
        comment: Optional comment for audit
        reason: Reason for change
        user: Analyst username

    Returns:
        Tuple: (success: bool, message: str, data: dict)
    """
    try:
        path = build_csv_path(csv_file)
        if not os.path.isfile(path):
            return (False, "CSV file not found", {})

        # Read current CSV
        old_headers, old_rows = read_csv(path)
        if new_headers is None:
            new_headers = old_headers

        # Compute diff
        diff = compute_diff(old_headers, old_rows, new_headers, new_rows)

        # Check if changes exist
        has_changes = (diff.get("added_count", 0) > 0 or
                      diff.get("removed_count", 0) > 0 or
                      diff.get("edited_count", 0) > 0)

        if not has_changes:
            return (True, "No changes detected", {"diff": diff})

        # Write CSV (atomic)
        write_csv(path, new_headers, new_rows)

        # Snapshot version
        success, msg = snapshot_version(path, len(new_rows), user)
        if not success:
            return (False, f"Failed to snapshot version: {msg}", {})

        # Post audit event
        event = {
            "action": "save_csv",
            "csv_file": csv_file,
            "analyst": user,
            "comment": comment,
            "added_row_count": diff.get("added_count", 0),
            "removed_row_count": diff.get("removed_count", 0),
            "edited_row_count": diff.get("edited_count", 0),
        }
        post_audit_event(event)

        return (True, "CSV saved successfully", {"diff": diff})

    except Exception as e:
        return (False, f"Error in save_csv_pipeline: {str(e)}", {})


def create_csv_pipeline(csv_file: str, headers: Optional[List[str]] = None,
                       comment: str = "", user: str = "") -> Tuple[bool, str, Dict]:
    """
    Create new CSV file with headers and initial version snapshot.

    Args:
        csv_file: CSV file name (e.g., "NEW_RULE.csv")
        headers: Optional list of column headers
        comment: Optional comment for audit
        user: Username for audit

    Returns:
        Tuple: (success: bool, message: str, data: dict)
    """
    try:
        path = build_csv_path(csv_file)

        # Check if file already exists
        if os.path.isfile(path):
            return (False, "CSV file already exists", {})

        # Create file with headers or empty
        if headers is None:
            headers = []

        write_csv(path, headers, [])

        # Snapshot version
        success, msg = snapshot_version(path, 0, user)
        if not success:
            return (False, f"Failed to snapshot version: {msg}", {})

        # Post audit event
        event = {
            "action": "create_csv",
            "csv_file": csv_file,
            "analyst": user,
            "comment": comment,
        }
        post_audit_event(event)

        return (True, "CSV created successfully", {})

    except Exception as e:
        return (False, f"Error in create_csv_pipeline: {str(e)}", {})


# ═══════════════════════════════════════════════════════════════════════════
# Version Control Pipelines
# ═══════════════════════════════════════════════════════════════════════════

def revert_csv_pipeline(csv_file: str, version_id: str, reason: str = "",
                       user: str = "") -> Tuple[bool, str, Dict]:
    """
    Revert CSV to a previous version.

    Args:
        csv_file: CSV file name
        version_id: Version ID from dropdown (timestamp format)
        reason: Reason for revert
        user: Admin username

    Returns:
        Tuple: (success: bool, message: str, data: dict)
    """
    try:
        path = build_csv_path(csv_file)
        if not os.path.isfile(path):
            return (False, "CSV file not found", {})

        # Read current version
        old_headers, old_rows = read_csv(path)

        # Get versions list and find the selected version
        versions = get_versions_list(csv_file)
        if not versions:
            return (False, "No previous versions available", {})

        # Find version by ID
        version_file = None
        for v in versions:
            if v.get("version_id") == version_id:
                version_file = v.get("file_path")
                break

        if not version_file:
            return (False, f"Version not found: {version_id}", {})

        # Read old version
        new_headers, new_rows = read_csv(version_file)

        # Compute diff (new = old version content, old = current)
        diff = compute_diff(old_headers, old_rows, new_headers, new_rows)

        # Write current CSV with old version content
        write_csv(path, new_headers, new_rows)

        # Delete the reverted-to version file
        try:
            os.remove(version_file)
        except OSError:
            pass  # Log but don't fail

        # Create new snapshot of reverted state
        success, msg = snapshot_version(path, len(new_rows), user)
        if not success:
            return (False, f"Failed to snapshot version: {msg}", {})

        # Post audit event with revert-specific fields
        event = {
            "action": "revert",
            "csv_file": csv_file,
            "analyst": user,
            "comment": reason,
            "reverted_to_version": version_id,
            "restoredback_row_count": diff.get("added_count", 0),
            "removedback_row_count": diff.get("removed_count", 0),
            "editedback_row_count": diff.get("edited_count", 0),
        }
        post_audit_event(event)

        return (True, "CSV reverted successfully", {})

    except Exception as e:
        return (False, f"Error in revert_csv_pipeline: {str(e)}", {})


# ═══════════════════════════════════════════════════════════════════════════
# Rule Management Pipelines
# ═══════════════════════════════════════════════════════════════════════════

def create_rule_pipeline(rule_name: str, csv_file: str, reason: str = "",
                        user: str = "") -> Tuple[bool, str, Dict]:
    """
    Create new detection rule and register it.

    Args:
        rule_name: Detection rule name (e.g., "DR102_WHITELIST")
        csv_file: Associated CSV file
        reason: Reason for creation
        user: Admin username

    Returns:
        Tuple: (success: bool, message: str, data: dict)
    """
    try:
        # Validate rule doesn't already exist
        rules = read_rules_registry()
        if rule_name in rules:
            return (False, "Detection rule already exists", {})

        # Validate CSV exists
        csv_path = build_csv_path(csv_file)
        if not os.path.isfile(csv_path):
            return (False, "Associated CSV file not found", {})

        # Add rule to registry
        rules[rule_name] = {
            "created_by": user,
            "created_at": os.path.getctime(csv_path),
        }
        success, msg = write_rules_registry(rules)
        if not success:
            return (False, f"Failed to write rules registry: {msg}", {})

        # Update mapping (rule_csv_map.csv)
        mapping = read_csv_mapping()
        mapping[rule_name] = csv_file
        # Note: write_csv_mapping would need to be created or use write_csv

        # Post audit event
        event = {
            "action": "create_rule",
            "detection_rule": rule_name,
            "csv_file": csv_file,
            "analyst": user,
            "comment": reason,
        }
        post_audit_event(event)

        return (True, "Detection rule created successfully", {})

    except Exception as e:
        return (False, f"Error in create_rule_pipeline: {str(e)}", {})


def remove_rule_pipeline(rule_name: str, reason: str = "",
                        user: str = "") -> Tuple[bool, str, Dict]:
    """
    Remove detection rule from registry (soft delete to trash).

    Args:
        rule_name: Detection rule name
        reason: Reason for deletion
        user: Admin username

    Returns:
        Tuple: (success: bool, message: str, data: dict)
    """
    try:
        # Validate rule exists
        rules = read_rules_registry()
        if rule_name not in rules:
            return (False, "Detection rule not found", {})

        # Move rule to trash
        success, msg = move_to_trash(rule_name, item_type="rule")
        if not success:
            return (False, f"Failed to move rule to trash: {msg}", {})

        # Remove from registry
        del rules[rule_name]
        success, msg = write_rules_registry(rules)
        if not success:
            return (False, f"Failed to write rules registry: {msg}", {})

        # Post audit event
        event = {
            "action": "delete_rule",
            "detection_rule": rule_name,
            "analyst": user,
            "comment": reason,
        }
        post_audit_event(event)

        return (True, "Detection rule deleted successfully", {})

    except Exception as e:
        return (False, f"Error in remove_rule_pipeline: {str(e)}", {})


# ═══════════════════════════════════════════════════════════════════════════
# Trash Management Pipelines
# ═══════════════════════════════════════════════════════════════════════════

def remove_csv_pipeline(csv_file: str, reason: str = "",
                       user: str = "") -> Tuple[bool, str, Dict]:
    """
    Remove CSV file (soft delete to trash).

    Args:
        csv_file: CSV file name
        reason: Reason for deletion
        user: Analyst username

    Returns:
        Tuple: (success: bool, message: str, data: dict)
    """
    try:
        csv_path = build_csv_path(csv_file)
        if not os.path.isfile(csv_path):
            return (False, "CSV file not found", {})

        # Move to trash
        success, msg = move_to_trash(csv_file, item_type="csv")
        if not success:
            return (False, f"Failed to move CSV to trash: {msg}", {})

        # Post audit event
        event = {
            "action": "delete_csv",
            "csv_file": csv_file,
            "analyst": user,
            "comment": reason,
        }
        post_audit_event(event)

        return (True, "CSV deleted successfully", {})

    except Exception as e:
        return (False, f"Error in remove_csv_pipeline: {str(e)}", {})


def restore_csv_pipeline(item_id: str, user: str = "") -> Tuple[bool, str, Dict]:
    """
    Restore CSV from trash.

    Args:
        item_id: Trash item ID
        user: Admin username

    Returns:
        Tuple: (success: bool, message: str, data: dict)
    """
    try:
        # Restore from trash
        success, msg = restore_from_trash(item_id, item_type="csv")
        if not success:
            return (False, f"Failed to restore from trash: {msg}", {})

        # Post audit event
        event = {
            "action": "restore",
            "item_id": item_id,
            "item_type": "csv",
            "analyst": user,
        }
        post_audit_event(event)

        return (True, "CSV restored successfully", {})

    except Exception as e:
        return (False, f"Error in restore_csv_pipeline: {str(e)}", {})
