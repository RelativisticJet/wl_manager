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
    "generate_request_id",
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


# ─────────────────────────────────────────────────────────────────────
# HMAC integrity layer (round 6, 2026-04-29)
#
# The queue file format on-disk is unchanged (still a JSON list of
# entries), so emergency tooling and forensic scripts can read it
# without knowing about the HMAC layer. A sidecar ``.approval_queue.sig``
# stores the HMAC of the queue's SHA-256 digest, signed with the same
# GUID-derived key used by the CSV expected-hash registry.
#
# Failure mode: if the sig file is missing OR its HMAC doesn't verify
# OR the recorded SHA-256 doesn't match the queue file's current
# SHA-256, ``_read_approval_queue`` returns an empty list with a clear
# error message — fail-closed. This means an attacker who writes the
# queue file directly (bypassing the handler) is detected on the
# NEXT read, which happens on every approval-related action and is
# far more frequent than the FIM watcher's 15-second cycle.
#
# Bootstrap: the first read after deploy will see queue + no sig
# (legacy state). It accepts that state once, writes a fresh sig
# alongside the existing queue, and emits an INFO event. After that,
# missing sig = tamper.
# ─────────────────────────────────────────────────────────────────────

_APPROVAL_SIG_BASENAME = ".approval_queue.sig"


def _get_approval_sig_path() -> str:
    """Return path to the sidecar HMAC signature file."""
    return os.path.join(OWN_LOOKUPS, _APPROVAL_SIG_BASENAME)


def _hash_queue_bytes(queue_bytes: bytes) -> str:
    """SHA-256 of the on-disk queue file bytes (the canonical input
    to the HMAC). We hash the raw bytes — not a re-serialized form —
    so the verification matches exactly what is on disk."""
    import hashlib
    return hashlib.sha256(queue_bytes).hexdigest()


def _compute_sig_envelope(queue_bytes: bytes) -> Dict[str, Any]:
    """Return a dict ready to write to the sidecar sig file."""
    from wl_hmac_key import (
        derive_hash_registry_key, compute_registry_checksum)
    sha = _hash_queue_bytes(queue_bytes)
    body = {"sha256": sha, "_signed_at": int(time.time())}
    body["_checksum"] = compute_registry_checksum(
        body, derive_hash_registry_key())
    return body


def _verify_queue_sig(queue_bytes: bytes) -> Tuple[bool, str]:
    """Return ``(is_valid, reason)``.

    - ``(True, "")`` if the sig file exists, the HMAC verifies, and
      the recorded SHA-256 matches ``queue_bytes``.
    - ``(True, "bootstrap")`` if the sig file is missing AND the
      queue is non-empty — caller MUST write a fresh sig immediately.
    - ``(True, "empty")`` if the queue file is missing/empty AND
      the sig file is missing — fresh-install no-op.
    - ``(False, "<reason>")`` for any tamper indicator.
    """
    sig_path = _get_approval_sig_path()

    if not os.path.isfile(sig_path):
        if not queue_bytes:
            return (True, "empty")
        # Legacy / first-run bootstrap. Caller writes a fresh sig.
        return (True, "bootstrap")

    try:
        with open(sig_path, "r", encoding="utf-8") as fh:
            sig = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        return (False, f"sig_unreadable: {exc}")

    stored_checksum = sig.pop("_checksum", None)
    if not stored_checksum:
        return (False, "sig_missing_checksum")

    from wl_hmac_key import (
        derive_hash_registry_key, compute_registry_checksum)
    expected = compute_registry_checksum(
        sig, derive_hash_registry_key())
    if stored_checksum != expected:
        return (False, "sig_hmac_mismatch")

    actual_sha = _hash_queue_bytes(queue_bytes)
    if sig.get("sha256") != actual_sha:
        return (False, "queue_sha_mismatch")

    return (True, "")


def _write_queue_sig(queue_bytes: bytes) -> Tuple[bool, str]:
    """Atomically write a fresh sig file matching ``queue_bytes``.

    Returns ``(success, error_msg)``. On failure the caller may want
    to log but should NOT fail the queue write — a missing sig will
    be lazily re-bootstrapped on the next read.
    """
    sig_path = _get_approval_sig_path()
    temp_path = sig_path + ".tmp"
    try:
        envelope = _compute_sig_envelope(queue_bytes)
        with open(temp_path, "w", encoding="utf-8") as fh:
            json.dump(envelope, fh, indent=2, sort_keys=True)
        os.replace(temp_path, sig_path)
        return (True, "")
    except Exception as exc:
        try:
            os.remove(temp_path)
        except OSError:
            pass
        return (False, f"failed to write approval sig: {exc}")


def generate_request_id() -> str:
    """Generate a unique, opaque request ID.

    Returns a UUID4 string (122 bits of entropy — collision probability
    is effectively zero). Chosen over the legacy
    ``req_<ts>_<rand>_<user>`` format for two reasons:

    - **Collision resistance.** Second-resolution timestamp + 4 decimal
      digits of randomness gives ~14 bits of entropy per second; under
      bursty traffic (many approvals submitted within the same second)
      collisions are realistically possible.
    - **No PII leak.** Embedding the creator's username in the ID means
      the ID shows up in URLs, audit events, and shared logs. A URL
      visible to another admin reveals whose request it is without the
      viewer needing to open the record. UUIDs leak nothing.

    Per-request metadata (creator, timestamp, csv, detection_rule)
    still lives in the approval queue entry — the ID is purely an
    opaque handle.

    Phase 4 consolidation (2026-04-19): ``wl_handler.py`` previously
    shipped its own ``_generate_request_id(user, csv_file, rule)``
    producing the legacy format. Both generators were active in
    production, so the approval queue held IDs in two formats. This
    is now the single source of truth. See CLAUDE.md Decision Log.
    """
    return str(uuid.uuid4())


# Backward-compat alias — kept so any importer that still references
# the private underscore name doesn't break. Prefer ``generate_request_id``
# for new code.
_generate_request_id = generate_request_id


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
    Read approval queue from disk with validation AND HMAC verification.

    Returns:
        Tuple of (entries list, error_msg string).
        On success: (list, "")
        On HMAC mismatch: ([], "QUEUE_TAMPERED: <reason>") — fail-closed
        On other error: ([], error_message)

    See the HMAC integrity layer comment block for the threat model
    and bootstrap behavior.
    """
    path = _get_approval_queue_path()
    if not os.path.isfile(path):
        # Fresh install / cleared queue. Verify_queue_sig handles
        # the "no queue + no sig" case as the empty bootstrap.
        valid, reason = _verify_queue_sig(b"")
        if not valid:
            return ([], f"QUEUE_TAMPERED: {reason}")
        return ([], "")

    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError as e:
        return ([], f"Failed to read queue: {e}")

    valid, reason = _verify_queue_sig(raw)
    if not valid:
        # Hard fail-closed. Returning [] here means callers will
        # see "no pending requests" rather than execute on
        # potentially attacker-modified entries.
        return ([], f"QUEUE_TAMPERED: {reason}")

    try:
        queue = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        return ([], f"Queue JSON corrupted: {e}")
    if not isinstance(queue, list):
        return ([], "Queue file corrupted: expected list, got " + type(queue).__name__)

    if reason == "bootstrap":
        # First read after upgrade: write the sig now so subsequent
        # reads can detect tampering. Best-effort — log on failure
        # but don't fail the read.
        ok, sig_err = _write_queue_sig(raw)
        if not ok:
            # Non-fatal — next write will retry.
            pass

    return (queue, "")


def _write_approval_queue(queue: List[Dict]) -> Tuple[bool, str]:
    """
    Write approval queue to disk atomically with file locking AND
    refresh the HMAC sidecar signature.

    Uses temp file + rename pattern for atomicity. The sig is written
    AFTER the queue replace succeeds — if the sig write fails, the
    queue is still consistent and the next read will report
    ``sig_hmac_mismatch`` (fail-closed) rather than processing
    tampered data.

    Args:
        queue: List of approval entries to write

    Returns:
        Tuple of (success: bool, error_msg: str)
    """
    path = _get_approval_queue_path()
    temp_path = str(path) + ".tmp"

    try:
        with file_lock(path, timeout=10):
            payload = json.dumps(queue, indent=2).encode("utf-8")
            with open(temp_path, "wb") as fh:
                fh.write(payload)
            os.replace(temp_path, path)
            # Refresh the sidecar sig under the same lock so a
            # concurrent reader cannot observe queue-new + sig-old.
            sig_ok, sig_err = _write_queue_sig(payload)
            if not sig_ok:
                # Queue itself is fine; report the sig error so the
                # caller can log it. Future reads will fail-closed
                # until the sig catches up on the next write.
                return (True, f"queue_written_sig_failed: {sig_err}")
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
    request_id = generate_request_id()
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
            "request_id": generate_request_id(),
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
