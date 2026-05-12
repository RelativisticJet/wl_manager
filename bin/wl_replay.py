"""
Approval Action Replay Module — Layer 5 Orchestration

Executes approved actions via domain module pipelines. This module provides
the replay infrastructure for approval workflows, translating approval queue
entries into actual data changes via the extracted domain modules.

Imported by wl_handler.py during process_approval workflow.

Public API:
    - execute_approved_action(context, request_item) -> dict

Module structure:
    - execute_approved_action: Main entry point, dispatches to action handlers
    - _execute_replay_*: Action-specific handlers for each approval action type
    - REPLAY_HANDLERS: Dict dispatch table mapping action_type to handlers
"""

import sys
import os
import csv
import json
from typing import Dict, Any, Tuple

# Handle Splunk bin/ import limitations
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Layer 3: Domain modules (CSV, versions, rules, trash, audit)
from wl_csv import read_csv, write_csv, compute_diff
from wl_versions import snapshot_version, get_versions_list
from wl_rules import (read_rules_registry, write_rules_registry, get_rule_csv_file,
                      create_rule_pipeline, delete_rule_pipeline, delete_csv_pipeline,
                      rules_rmw_lock)
from wl_trash import move_to_trash, restore_from_trash
from wl_audit import build_audit_event, post_audit_event
from wl_logging import get_audit_logger
from wl_validation import resolve_csv_path, safe_realpath, build_csv_path
from wl_constants import OWN_LOOKUPS, APPS_DIR, MAPPING_FILE

# Module logger for non-blocking errors
_logger = get_audit_logger()

__all__ = ["execute_approved_action"]


def execute_approved_action(context: Dict[str, Any], request_item: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute an approved action using domain module pipelines.

    Dispatches approved requests to action-specific handlers via REPLAY_HANDLERS dict.
    Validates preconditions (CSV exists, rule exists) before execution.
    Returns structured result dict on success or error.

    Args:
        context: Dict with approval metadata
            {original_analyst, approving_admin, second_admin, is_dual_admin,
             request_id, action_type, session_key, approved_at}
        request_item: Dict with action payload
            {action_type, csv_file, detection_rule, payload, ...}

    Returns:
        Dict: {success: bool, message: str (optional), data: dict (optional),
               error: str (optional), error_type: str (optional)}
    """
    action_type = request_item.get("action_type", "")

    # Validate action type
    if action_type not in REPLAY_HANDLERS:
        return {
            "success": False,
            "error": f"Unknown action type: {action_type}",
            "error_type": "unknown_action_type"
        }

    # Validate preconditions for actions requiring CSV files
    _csv_required_actions = {"save_csv", "add_row", "remove_rows", "revert_csv"}
    if action_type in _csv_required_actions:
        csv_file = request_item.get("csv_file", "")
        app_context = request_item.get("app_context", "")

        # Resolve path to CSV
        path = resolve_csv_path(csv_file, app_context)
        if path is None:
            fallback = os.path.join(OWN_LOOKUPS, csv_file)
            if os.path.isfile(fallback) and safe_realpath(fallback, APPS_DIR):
                path = safe_realpath(fallback, APPS_DIR)

        if path is None:
            return {
                "success": False,
                "error": "CSV file no longer exists",
                "error_type": "missing_csv"
            }

    # Validate preconditions for actions requiring detection rules
    _rule_required_actions = {"create_rule", "delete_rule"}
    if action_type in _rule_required_actions:
        rule_name = request_item.get("detection_rule", "")
        rules = read_rules_registry()

        if action_type == "create_rule" and rule_name in rules:
            return {
                "success": False,
                "error": f"Detection rule '{rule_name}' already exists",
                "error_type": "rule_exists"
            }
        elif action_type == "delete_rule" and rule_name not in rules:
            return {
                "success": False,
                "error": f"Detection rule '{rule_name}' not found",
                "error_type": "rule_not_found"
            }

    # Dispatch to action handler
    handler = REPLAY_HANDLERS[action_type]
    try:
        result = handler(context, request_item)
        return result
    except Exception as e:
        error_msg = str(e)
        _logger.error(f"Replay handler {action_type} raised exception: {error_msg}", exc_info=True)
        return {
            "success": False,
            "error": f"Handler error: {error_msg}",
            "error_type": "handler_exception"
        }


def _execute_replay_save_csv(context: Dict[str, Any], request_item: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute save_csv, add_row, or remove_rows action via save_csv_pipeline.

    All three actions use the same CSV write pathway, so they're handled
    by a single replay handler.

    Args:
        context: Approval context with metadata
        request_item: Contains csv_file, headers, rows, comment, etc.

    Returns:
        Dict: {success: bool, message: str (optional), error: str (optional)}
    """
    csv_file = request_item.get("csv_file", "")
    app_context = request_item.get("app_context", "")
    headers = request_item.get("headers", [])
    rows = request_item.get("rows", [])
    comment = request_item.get("comment", "")

    # Resolve CSV path
    path = resolve_csv_path(csv_file, app_context)
    if path is None:
        fallback = os.path.join(OWN_LOOKUPS, csv_file)
        if os.path.isfile(fallback) and safe_realpath(fallback, APPS_DIR):
            path = safe_realpath(fallback, APPS_DIR)

    if path is None:
        return {
            "success": False,
            "error": "CSV file not found",
            "error_type": "missing_csv"
        }

    try:
        # Write CSV to disk
        write_csv(path, headers, rows)

        # Create version snapshot (path, analyst, action_label)
        analyst = context.get("original_analyst", "")
        version_id, _ = snapshot_version(path, analyst, "save_csv")

        # Post audit event
        session_key = context.get("session_key", "")
        approving_admin = context.get("approving_admin", "")
        request_id = context.get("request_id", "")

        audit_evt = build_audit_event(
            action="replay_save_csv",
            analyst=approving_admin,
            detection_rule=request_item.get("detection_rule", ""),
            csv_file=csv_file,
            app_context=app_context,
            comment=f"Approved by {approving_admin} (request {request_id}), originally submitted by {analyst}. {comment}",
            request_id=request_id,
            original_analyst=analyst,
            approving_admin=approving_admin
        )

        post_result, post_error = post_audit_event(session_key, audit_evt)
        if not post_result:
            _logger.error(f"Audit posting failed for replay_save_csv: {post_error}")

        return {
            "success": True,
            "message": "CSV saved successfully",
            "data": {"version_id": version_id}
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "error_type": "save_failed"
        }


def _execute_replay_revert_csv(context: Dict[str, Any], request_item: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute revert_csv action — restore CSV to a previous version.

    Args:
        context: Approval context with metadata
        request_item: Contains csv_file, app_context, version_id, comment

    Returns:
        Dict: {success: bool, message: str, data: dict (optional), error: str (optional)}
    """
    csv_file = request_item.get("csv_file", "")
    app_context = request_item.get("app_context", "")
    version_id = request_item.get("version_id", "")
    comment = request_item.get("comment", "")

    try:
        # Get version manifest to find the version file
        from wl_versions import read_version_manifest, get_versions_dir

        versions_dir = get_versions_dir()
        manifest_path = os.path.join(versions_dir, f"{csv_file}_versions.json")

        if not os.path.isfile(manifest_path):
            return {
                "success": False,
                "error": "Version history not found",
                "error_type": "missing_versions"
            }

        manifest, _ = read_version_manifest(csv_file)
        if not manifest:
            return {
                "success": False,
                "error": "Failed to read version manifest",
                "error_type": "manifest_error"
            }

        # Find version file matching version_id
        version_file = None
        for v in manifest.get("versions", []):
            if v.get("version_id") == version_id:
                version_file = os.path.join(versions_dir, v.get("filename", ""))
                break

        if not version_file or not os.path.isfile(version_file):
            return {
                "success": False,
                "error": "Version file not found",
                "error_type": "missing_version_file"
            }

        # Read version CSV data
        headers, rows = read_csv(version_file)

        # Write CSV to current location
        path = resolve_csv_path(csv_file, app_context)
        if path is None:
            fallback = os.path.join(OWN_LOOKUPS, csv_file)
            if os.path.isfile(fallback) and safe_realpath(fallback, APPS_DIR):
                path = safe_realpath(fallback, APPS_DIR)

        if path is None:
            return {
                "success": False,
                "error": "CSV file not found",
                "error_type": "missing_csv"
            }

        write_csv(path, headers, rows)

        # Create new version snapshot of reverted state (path, analyst, action_label)
        analyst = context.get("original_analyst", "")
        new_version_id, _ = snapshot_version(path, analyst, "revert_csv")

        # Post audit event
        session_key = context.get("session_key", "")
        approving_admin = context.get("approving_admin", "")
        request_id = context.get("request_id", "")

        audit_evt = build_audit_event(
            action="replay_revert_csv",
            analyst=approving_admin,
            detection_rule=request_item.get("detection_rule", ""),
            csv_file=csv_file,
            app_context=app_context,
            comment=f"Reverted to {version_id} by {approving_admin}. {comment}",
            request_id=request_id,
            reverted_to_version=version_id,
            new_record_version=new_version_id,
            original_analyst=analyst
        )

        post_result, post_error = post_audit_event(session_key, audit_evt)
        if not post_result:
            _logger.error(f"Audit posting failed for replay_revert_csv: {post_error}")

        return {
            "success": True,
            "message": "CSV reverted successfully",
            "data": {"version_id": new_version_id}
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "error_type": "revert_failed"
        }


def _execute_replay_create_rule(context: Dict[str, Any], request_item: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute create_rule action — delegates to create_rule_pipeline.
    """
    rule_name = request_item.get("detection_rule", "")

    result = create_rule_pipeline(rule_name)

    if not result.get("success"):
        return {
            "success": False,
            "error": result.get("error", "Create rule failed"),
            "error_type": "create_rule_failed",
        }

    return {
        "success": True,
        "message": result.get("message", "Rule created"),
    }


def _execute_replay_delete_rule(context: Dict[str, Any], request_item: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute delete_rule action — delegates to delete_rule_pipeline.

    The pipeline handles: mapping removal, registry cleanup, trash, and audit.
    """
    rule_name = request_item.get("detection_rule", "")
    original = request_item.get("payload", {})
    reason = (original.get("comment") or original.get("approval_reason")
              or request_item.get("comment", "") or "Approved via approval queue")
    removal_type = original.get("removal_type", "permanent")
    session_key = context.get("session_key", "")
    analyst = context.get("original_analyst", "")

    result = delete_rule_pipeline(
        rule_name, removal_type, reason, analyst, session_key)

    if not result.get("success"):
        return {
            "success": False,
            "error": result.get("error", "Delete rule failed"),
            "error_type": "delete_rule_failed",
        }

    return {
        "success": True,
        "message": result.get("message", "Rule deleted"),
        "data": result.get("data", {}),
    }


def _execute_replay_delete_csv(context: Dict[str, Any], request_item: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute delete_csv action — delegates to delete_csv_pipeline.

    The pipeline handles: mapping removal, trash, last-rule cleanup, and audit.
    """
    csv_file = request_item.get("csv_file", "")
    original = request_item.get("payload", {})
    reason = (original.get("comment") or original.get("approval_reason")
              or request_item.get("comment", "") or "Approved via approval queue")
    removal_type = original.get("removal_type", "permanent")
    rule_name = original.get("rule_name", request_item.get("detection_rule", ""))
    session_key = context.get("session_key", "")
    analyst = context.get("original_analyst", "")

    result = delete_csv_pipeline(
        csv_file, removal_type, reason, analyst, session_key,
        rule_name=rule_name)

    if not result.get("success"):
        return {
            "success": False,
            "error": result.get("error", "Delete CSV failed"),
            "error_type": "delete_csv_failed",
        }

    return {
        "success": True,
        "message": result.get("message", "CSV deleted"),
        "data": result.get("data", {}),
    }


def _execute_replay_create_csv(context: Dict[str, Any], request_item: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute create_csv action — create new CSV file and update mapping.

    Args:
        context: Approval context with metadata
        request_item: Contains csv_file, app_context, detection_rule, columns

    Returns:
        Dict: {success: bool, message: str, error: str (optional)}
    """
    csv_file = request_item.get("csv_file", "")
    app_context = request_item.get("app_context", "")
    detection_rule = request_item.get("detection_rule", "")
    # The original create_csv payload is stored under "payload"
    original = request_item.get("payload", {})
    columns = original.get("headers", original.get("columns", []))

    try:
        # Build CSV path
        path = build_csv_path(csv_file, app_context)
        if path is None:
            # build_csv_path returns None when csv_file fails is_safe_filename
            # (non-ASCII, traversal, control chars, etc.). This catches legacy
            # queue entries submitted before ASCII tightening.
            return {
                "success": False,
                "error": (
                    f"Invalid CSV file name '{csv_file}' — only ASCII "
                    "letters, digits, underscores, and hyphens are allowed"
                ),
                "error_type": "invalid_csv_name"
            }

        if os.path.isfile(path):
            return {
                "success": False,
                "error": f"CSV file '{csv_file}' already exists",
                "error_type": "csv_exists"
            }

        # Create new CSV with headers only
        empty_rows = []
        write_csv(path, columns, empty_rows)

        # Create version snapshot (path, analyst, action_label)
        analyst = context.get("original_analyst", "")
        version_id, _ = snapshot_version(path, analyst, "create_csv")

        # Update rule-CSV mapping file
        # Ring 6.1 R6-F5 class fix (Day 6.1.7b): serialize the RMW
        # against the canonical pipeline in wl_rules so a concurrent
        # create_rule / delete_rule / delete_csv cannot read a stale
        # snapshot and clobber this replay's mapping append.
        try:
            with rules_rmw_lock():
                existing = []
                if os.path.isfile(MAPPING_FILE):
                    with open(MAPPING_FILE, "r", newline="",
                              encoding="utf-8-sig") as fh:
                        existing = list(csv.DictReader(fh))
                existing.append({
                    "rule_name": detection_rule,
                    "csv_file": csv_file,
                    "app_context": app_context or "wl_manager",
                })
                with open(MAPPING_FILE, "w", newline="",
                          encoding="utf-8") as fh:
                    writer = csv.DictWriter(
                        fh,
                        fieldnames=["rule_name", "csv_file", "app_context"],
                        extrasaction="ignore")
                    writer.writeheader()
                    writer.writerows(existing)
        except OSError as exc:
            _logger.error(f"Failed to update mapping for create_csv: {exc}")

        # Post audit event
        session_key = context.get("session_key", "")
        approving_admin = context.get("approving_admin", "")
        request_id = context.get("request_id", "")

        audit_evt = build_audit_event(
            action="csv_created",
            analyst=analyst,
            detection_rule=detection_rule,
            csv_file=csv_file,
            app_context=app_context,
            status="approved",
            comment="CSV created via approval by {}. Columns: {}".format(
                approving_admin, ", ".join(columns)),
            request_id=request_id,
        )

        post_result, post_error = post_audit_event(session_key, audit_evt)
        if not post_result:
            _logger.error(f"Audit posting failed for replay_create_csv: {post_error}")

        return {
            "success": True,
            "message": f"CSV '{csv_file}' created successfully",
            "data": {"version_id": version_id}
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "error_type": "create_csv_failed"
        }


# Dispatch table mapping action types to handlers
REPLAY_HANDLERS = {
    "save_csv": _execute_replay_save_csv,
    "add_row": _execute_replay_save_csv,  # Same pipeline
    "remove_rows": _execute_replay_save_csv,  # Same pipeline
    "create_csv": _execute_replay_create_csv,
    "create_rule": _execute_replay_create_rule,
    "delete_csv": _execute_replay_delete_csv,
    "delete_rule": _execute_replay_delete_rule,
    "remove_csv": _execute_replay_delete_csv,   # Alias: approval queue uses remove_*
    "remove_rule": _execute_replay_delete_rule,  # Alias: approval queue uses remove_*
    "revert_csv": _execute_replay_revert_csv,
}
