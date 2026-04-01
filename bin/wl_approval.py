"""
Approval Queue Management Module

Manages approval queue CRUD operations, submission, conflict resolution,
and expiration for Whitelist Manager. Handles both single and dual-admin approval
workflows with proper locking and precondition validation.

Layer 3: Imports from wl_constants (Layer 0), wl_rbac (Layer 1), wl_filelock (Layer 2),
wl_limits (Layer 3), and wl_audit (Layer 2).

Public API:
    - get_pending_for_csv(csv_file: str) -> list
    - get_pending_for_rule(rule_name: str) -> list
    - submit_approval(user, action_type, payload, reason, roles, notify_fn) -> tuple
    - submit_dual_approval(analyst, approver, action_type, payload, reason, roles, notify_fn) -> tuple
    - check_approval_gate(user, action_type, action_count, roles) -> tuple
    - expire_pending_approvals(queue) -> list
    - check_conflicts(queue, action) -> list
    - cancel_conflicts(queue, action, notify_fn) -> tuple
"""

import sys
import os
import json
import time
import uuid
from typing import Dict, List, Tuple, Optional, Callable, Any
from pathlib import Path

# Handle Splunk bin/ import limitations
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from wl_constants import (
    APPROVAL_QUEUE_FILE, APPROVAL_EXPIRY_DAYS, OWN_LOOKUPS
)
from wl_rbac import can_approve, can_approve_own_requests, is_admin
from wl_validation import sanitize_text
from wl_filelock import file_lock
from wl_limits import check_analyst_limit, check_admin_limit
from wl_audit import build_audit_event, post_audit_event
from wl_notify import notify_admins, notify_analyst

__all__ = [
    "get_pending_for_csv",
    "get_pending_for_rule",
    "submit_approval",
    "submit_dual_approval",
    "check_approval_gate",
    "expire_pending_approvals",
    "check_conflicts",
    "cancel_conflicts",
]

# Module-level constants
MIN_REASON_LENGTH = 3
MAX_REASON_LENGTH = 500
RESOLVED_HISTORY_DAYS = 30


def _get_approval_queue_path() -> str:
    """
    Return path to approval_queue.json in lookups directory.

    Returns:
        Absolute path to approval queue file
    """
    os.makedirs(OWN_LOOKUPS, exist_ok=True)
    return os.path.join(OWN_LOOKUPS, APPROVAL_QUEUE_FILE)


def _generate_request_id() -> str:
    """
    Generate unique request ID using UUID4.

    Returns:
        Unique request ID string
    """
    return str(uuid.uuid4())


def _is_expired(entry: Dict[str, Any]) -> bool:
    """
    Check if approval entry is older than APPROVAL_EXPIRY_DAYS.

    Args:
        entry: Approval queue entry dict

    Returns:
        True if entry should be expired, False otherwise
    """
    timestamp = entry.get("timestamp", 0)
    age_seconds = int(time.time()) - timestamp
    age_days = age_seconds / (24 * 3600)
    return age_days >= APPROVAL_EXPIRY_DAYS


def _read_approval_queue() -> Tuple[List[Dict], str]:
    """
    Read approval queue from disk with validation.

    Returns:
        Tuple of (entries list, error_msg string).
        On success: (list, "")
        On error: ([], error_message)
    """
    path = _get_approval_queue_path()
    if not os.path.isfile(path):
        return ([], "")

    try:
        with open(path, "r", encoding="utf-8") as fh:
            queue = json.load(fh)
            if not isinstance(queue, list):
                return ([], "Queue file corrupted: expected list, got " + type(queue).__name__)
            return (queue, "")
    except json.JSONDecodeError as e:
        return ([], f"Queue JSON corrupted: {e}")
    except OSError as e:
        return ([], f"Failed to read queue: {e}")


def _write_approval_queue(queue: List[Dict]) -> Tuple[bool, str]:
    """
    Write approval queue to disk atomically with file locking.

    Uses temp file + rename pattern for atomicity.

    Args:
        queue: List of approval entries to write

    Returns:
        Tuple of (success: bool, error_msg: str)
    """
    path = _get_approval_queue_path()
    temp_path = str(path) + ".tmp"

    try:
        with open(temp_path, "w", encoding="utf-8") as fh:
            with file_lock(path, timeout=10):
                json.dump(queue, fh, indent=2)
        os.replace(temp_path, path)
        return (True, "")
    except (OSError, IOError, Exception) as e:
        # Clean up temp file on error
        try:
            os.remove(temp_path)
        except OSError:
            pass
        return (False, f"Failed to write queue: {e}")


def _validate_queue_entry(entry: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Validate approval queue entry has required fields.

    Args:
        entry: Entry dict to validate

    Returns:
        Tuple of (valid: bool, error_msg: str)
    """
    required = ["request_id", "status", "timestamp", "analyst", "action_type"]
    for field in required:
        if field not in entry:
            return (False, f"Missing required field: {field}")

    if entry.get("status") not in ("pending", "approved", "rejected", "expired", "cancelled"):
        return (False, f"Invalid status: {entry.get('status')}")

    return (True, "")


def expire_pending_approvals(queue: Optional[List[Dict]] = None) -> List[Dict]:
    """
    Remove expired entries from approval queue.

    Expires pending entries older than APPROVAL_EXPIRY_DAYS.
    Also removes resolved entries (approved/rejected) older than RESOLVED_HISTORY_DAYS.

    Args:
        queue: Approval queue list (default: read from disk)

    Returns:
        Modified queue with expired entries removed
    """
    if queue is None:
        queue, _ = _read_approval_queue()

    now = int(time.time())
    expired_threshold = now - (APPROVAL_EXPIRY_DAYS * 24 * 3600)
    history_threshold = now - (RESOLVED_HISTORY_DAYS * 24 * 3600)

    filtered = []
    for entry in queue:
        timestamp = entry.get("timestamp", 0)

        # Expire pending if old enough
        if entry.get("status") == "pending" and timestamp <= expired_threshold:
            continue  # Skip (expire)

        # Prune resolved history if old enough
        if entry.get("status") in ("approved", "rejected", "expired", "cancelled"):
            if timestamp <= history_threshold:
                continue  # Skip (prune)

        filtered.append(entry)

    return filtered


def get_pending_for_csv(csv_file: str) -> List[Dict]:
    """
    Get all pending approval requests for a specific CSV file.

    Calls expire_pending_approvals first to clean up old entries.

    Args:
        csv_file: CSV filename (e.g., "DR123_whitelist.csv")

    Returns:
        List of pending entries for that CSV
    """
    queue, _ = _read_approval_queue()
    queue = expire_pending_approvals(queue)
    return [e for e in queue if e.get("csv_file") == csv_file and e.get("status") == "pending"]


def get_pending_for_rule(rule_name: str) -> List[Dict]:
    """
    Get all pending approval requests for a specific detection rule.

    Calls expire_pending_approvals first to clean up old entries.

    Args:
        rule_name: Detection rule name

    Returns:
        List of pending entries for that rule
    """
    queue, _ = _read_approval_queue()
    queue = expire_pending_approvals(queue)
    return [e for e in queue if e.get("detection_rule") == rule_name and e.get("status") == "pending"]


def check_approval_gate(
    user: str,
    action_type: str,
    action_count: int,
    roles: List[str]
) -> Tuple[bool, str]:
    """
    Check if action needs approval based on limits.

    Uses wl_limits.check_analyst_limit to determine if action is allowed.

    Args:
        user: Username
        action_type: Action type (e.g., "save_csv")
        action_count: Number of actions
        roles: User's roles

    Returns:
        Tuple of (needs_approval: bool, error_msg: str)
        If needs_approval=False and error_msg != "", action is disabled (error)
        If needs_approval=False and error_msg == "", action is allowed without approval
        If needs_approval=True, action must be queued for approval
    """
    allowed, current, max_limit = check_analyst_limit(user, action_type, action_count, roles)

    if not allowed:
        if max_limit == 0:
            msg = f"Action '{action_type}' is disabled by administrator"
        else:
            remaining = max(0, max_limit - current)
            msg = f"Daily limit exceeded for '{action_type}'. Remaining: {remaining}/{max_limit}"
        return (False, msg)

    # For now, no action requires explicit approval (all pass through if not rate-limited)
    # In Phase 4, this may be extended to support approval thresholds
    return (False, "")


def _validate_submission_inputs(
    user: str,
    action_type: str,
    payload: Dict[str, Any],
    reason: str
) -> Tuple[bool, str]:
    """
    Validate submission inputs for approval request.

    Returns:
        (True, sanitized_reason) if all inputs valid
        (False, error_msg) if any input invalid
    """
    # Validate user (must be non-empty string)
    if not user or not isinstance(user, str):
        return (False, "Invalid user")

    # Validate action_type (must be non-empty string)
    if not action_type or not isinstance(action_type, str):
        return (False, "Invalid action_type")

    # Validate payload (must be dict)
    if not isinstance(payload, dict):
        return (False, "Payload must be dict")

    # Validate reason (3-500 chars per wl_constants)
    if not reason or len(reason) < MIN_REASON_LENGTH:
        return (False, f"Reason must be at least {MIN_REASON_LENGTH} characters")
    if len(reason) > MAX_REASON_LENGTH:
        return (False, f"Reason must be at most {MAX_REASON_LENGTH} characters")

    # Sanitize reason text
    reason = sanitize_text(reason)

    return (True, reason)


def _create_queue_entry(
    user: str,
    action_type: str,
    payload: Dict[str, Any],
    reason: str
) -> Tuple[Dict[str, Any], str]:
    """
    Create a new approval queue entry for pending request.

    Args:
        user: Analyst username
        action_type: Type of action
        payload: Action payload dict
        reason: Sanitized reason text

    Returns:
        (entry: dict, error: str)
        On success: (valid_entry_dict, "")
        On failure: ({}, error_message)
    """
    request_id = _generate_request_id()
    now = int(time.time())

    entry = {
        "request_id": request_id,
        "status": "pending",
        "timestamp": now,
        "analyst": user,
        "action_type": action_type,
        "payload": payload,
        "reason": reason,
        "csv_file": payload.get("csv_file", ""),
        "detection_rule": payload.get("detection_rule", ""),
    }

    # Validate entry structure
    valid, err = _validate_queue_entry(entry)
    if not valid:
        return ({}, err)

    return (entry, "")


def submit_approval(
    user: str,
    action_type: str,
    payload: Dict[str, Any],
    reason: str,
    roles: List[str],
    notify_fn: Optional[Callable] = None,
    session_key: Optional[str] = None
) -> Tuple[bool, str, Dict]:
    """
    Submit action for approval or execute immediately if no gate needed.
    Validates submission, checks approval gate, creates queue entry, notifies admins.

    Args:
        user: Username submitting
        action_type: Type of action (e.g., "save_csv")
        payload: Action-specific data dict
        reason: Reason for action (required, 3-500 chars)
        roles: User's roles
        notify_fn: Optional callback for legacy notification (deprecated)
        session_key: Splunk session key for wl_notify integration

    Returns:
        Tuple of (success: bool, error_msg: str, entry: dict)
    """
    valid, reason_or_error = _validate_submission_inputs(user, action_type, payload, reason)
    if not valid:
        return (False, reason_or_error, {})
    sanitized_reason = reason_or_error

    # Check approval gate
    action_count = payload.get("action_count", 1)
    needs_approval, limit_error = check_approval_gate(user, action_type, action_count, roles)

    if limit_error:
        return (False, limit_error, {})

    # If no approval needed, return success without queueing
    if not needs_approval:
        entry = {
            "request_id": _generate_request_id(),
            "status": "approved",
            "timestamp": int(time.time()),
            "analyst": user,
            "action_type": action_type,
            "payload": payload,
            "reason": sanitized_reason,
            "resolved_by": "direct",
            "resolved_at": int(time.time()),
        }
        return (True, "", entry)

    # Create queue entry for approval
    entry, create_error = _create_queue_entry(user, action_type, payload, sanitized_reason)
    if create_error:
        return (False, create_error, {})

    # Read current queue, expire old entries, add new entry
    queue, read_err = _read_approval_queue()
    if read_err:
        return (False, read_err, {})

    queue = expire_pending_approvals(queue)
    queue.append(entry)

    # Write queue atomically
    success, write_err = _write_approval_queue(queue)
    if not success:
        return (False, write_err, {})

    # Trigger notification via wl_notify (direct call, not callback)
    if session_key:
        try:
            notify_admins(session_key, "approval_pending", {
                "analyst": user,
                "action_type": action_type,
                "reason": sanitized_reason,
                "csv_file": payload.get("csv_file", ""),
                "detection_rule": payload.get("detection_rule", ""),
            })
        except Exception:
            pass  # Non-blocking: log but don't fail operation

    # Legacy callback support (for backward compatibility during transition)
    if notify_fn:
        try:
            notify_fn("approval_pending", {
                "analyst": user,
                "action_type": action_type,
                "reason": sanitized_reason,
                "csv_file": payload.get("csv_file", ""),
                "detection_rule": payload.get("detection_rule", ""),
            })
        except Exception:
            pass  # Non-blocking

    return (True, "", entry)


def submit_dual_approval(
    analyst_user: str,
    approver_user: str,
    action_type: str,
    payload: Dict[str, Any],
    reason: str,
    roles: List[str],
    notify_fn: Optional[Callable] = None
) -> Tuple[bool, str, Dict]:
    """
    Submit action requiring two-admin approval.

    Similar to submit_approval but marks entry as dual-admin type.

    Args:
        analyst_user: Analyst submitting
        approver_user: Primary approver (usually the other admin)
        action_type: Type of action
        payload: Action-specific data
        reason: Reason for action
        roles: Analyst's roles
        notify_fn: Optional callback for notifications

    Returns:
        Tuple of (success: bool, error_msg: str, entry: dict)
    """
    # Validate both users
    if not analyst_user or not approver_user:
        return (False, "Both analyst and approver must be specified", {})

    # Submit as normal approval
    success, error, entry = submit_approval(analyst_user, action_type, payload, reason, roles, notify_fn)

    if success and entry:
        # Mark as dual-admin
        entry["approval_type"] = "dual_admin"
        entry["approver"] = approver_user

    return (success, error, entry)


def check_conflicts(queue: List[Dict], action: Dict[str, Any]) -> List[Dict]:
    """
    Dry-run: Return list of queue entries that would be cancelled by this action.

    Does not modify queue or notify.

    Args:
        queue: Approval queue
        action: Action dict with "action_type", "csv_file", "detection_rule"

    Returns:
        List of entries that conflict with this action
    """
    action_type = action.get("action_type", "")
    csv_file = action.get("csv_file", "")
    detection_rule = action.get("detection_rule", "")

    conflicts = []

    for entry in queue:
        if entry.get("status") != "pending":
            continue

        conflict = False

        if action_type == "delete_rule":
            # Delete rule cancels all pending edits/actions for that rule
            if entry.get("detection_rule") == detection_rule:
                conflict = True

        elif action_type == "delete_csv":
            # Delete CSV cancels pending edits for that CSV (under that rule)
            if (entry.get("csv_file") == csv_file and
                    entry.get("detection_rule") == detection_rule):
                conflict = True

        elif action_type == "restore_csv":
            # Restore CSV cancels pending "create_csv" requests for same name
            if (entry.get("action_type") == "create_csv" and
                    entry.get("csv_file") == csv_file):
                conflict = True

        if conflict:
            conflicts.append(entry)

    return conflicts


def cancel_conflicts(
    queue: List[Dict],
    action: Dict[str, Any],
    notify_fn: Optional[Callable] = None,
    session_key: Optional[str] = None
) -> Tuple[List[Dict], List[Dict]]:
    """
    Cancel all queue entries that conflict with an approved action.

    Returns new queue (doesn't mutate input). Calls notify_analyst for each cancellation.

    Args:
        queue: Approval queue (not modified)
        action: Action that was approved
        notify_fn: Optional callback(analyst, notification_type, details) for legacy support
        session_key: Optional Splunk session key for notifying affected analysts

    Returns:
        Tuple of (new_queue: list, cancelled_entries: list)
    """
    # Get conflicts
    conflicts = check_conflicts(queue, action)

    if not conflicts:
        return (queue, [])

    # Create new queue without conflicts
    cancelled_ids = {e.get("request_id") for e in conflicts}
    new_queue = [e for e in queue if e.get("request_id") not in cancelled_ids]

    # Mark cancelled entries with metadata
    now = int(time.time())
    cancelled_entries = []
    for entry in conflicts:
        entry["status"] = "cancelled"
        entry["resolved_by"] = "system"
        entry["resolved_at"] = now
        entry["cancelled_by_action"] = action.get("action_type", "")
        entry["cancelled_by_analyst"] = action.get("analyst", "")
        cancelled_entries.append(entry)

        # Notify analyst via wl_notify (if session_key provided)
        if session_key:
            try:
                notify_analyst(
                    session_key,
                    entry.get("analyst", ""),
                    "approval_cancelled_by_conflict",
                    {
                        "action_type": entry.get("action_type", ""),
                        "reason": f"Auto-cancelled: conflicting {action.get('action_type', '')} action was approved",
                        "csv_file": entry.get("csv_file", ""),
                        "detection_rule": entry.get("detection_rule", ""),
                    }
                )
            except Exception:
                pass  # Non-blocking: log but don't fail cancellation

        # Legacy callback support (for backward compatibility during transition)
        if notify_fn:
            try:
                notify_fn(entry.get("analyst"), "approval_cancelled", {
                    "action_type": entry.get("action_type", ""),
                    "reason": f"Cancelled due to {action.get('action_type', '')} approval",
                    "cancelled_by_action": action.get("action_type", ""),
                })
            except Exception:
                pass  # Non-blocking

    return (new_queue, cancelled_entries)
