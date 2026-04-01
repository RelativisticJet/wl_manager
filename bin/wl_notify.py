"""
Admin and Analyst Notification Module

Provides notification system for approval queue events. Sends notifications
to admins on submission and to analysts on approval/rejection/auto-cancel events.

Layer 3: Imports from wl_rbac (Layer 1) and wl_logging (Layer 1).

Public API:
    - notify_admins(session_key: str, notification_type: str, details: dict) -> tuple
    - notify_analyst(session_key: str, analyst: str, notification_type: str, details: dict) -> tuple
"""

import sys
import os
import json
from typing import Dict, Tuple, Optional, Any

# Handle Splunk bin/ import limitations
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from wl_rbac import get_admin_users
from wl_logging import get_audit_logger

__all__ = [
    "notify_admins",
    "notify_analyst",
]

# Module-level logger
_logger = get_audit_logger()


def _get_notification_message(
    notification_type: str,
    details: Dict[str, Any]
) -> str:
    """
    Format human-readable notification message based on type.

    Args:
        notification_type: Type of notification
        details: Event details dict

    Returns:
        Human-readable message string
    """
    analyst = details.get("analyst", "")
    action_type = details.get("action_type", "").replace("_", " ")
    csv_file = details.get("csv_file", "")
    detection_rule = details.get("detection_rule", "")
    reason = details.get("reason", "")
    resolution_time = details.get("resolution_time", "")

    if notification_type == "approval_pending":
        subject = f"[Whitelist Manager] Approval required: {action_type}"
        body = f"""
Analyst: {analyst}
Action: {action_type}
Rule: {detection_rule}
CSV: {csv_file}
Reason: {reason}

Please review and approve/reject this request.
"""

    elif notification_type == "approval_approved":
        subject = f"[Whitelist Manager] Approval granted: {action_type}"
        body = f"""
Your {action_type} request has been APPROVED.

Rule: {detection_rule}
CSV: {csv_file}
Reason: {reason}
Resolved at: {resolution_time}
"""

    elif notification_type == "approval_rejected":
        subject = f"[Whitelist Manager] Approval denied: {action_type}"
        body = f"""
Your {action_type} request has been REJECTED.

Rule: {detection_rule}
CSV: {csv_file}
Reason: {reason}
Resolved at: {resolution_time}
"""

    elif notification_type == "approval_cancelled":
        subject = f"[Whitelist Manager] Approval cancelled: {action_type}"
        body = f"""
Your {action_type} request has been AUTO-CANCELLED.

Reason: {reason}
Rule: {detection_rule}
CSV: {csv_file}
"""

    elif notification_type == "approval_expired":
        subject = f"[Whitelist Manager] Approval expired: {action_type}"
        body = f"""
Your {action_type} request has EXPIRED (no longer pending).

Rule: {detection_rule}
CSV: {csv_file}
"""

    else:
        subject = "[Whitelist Manager] Notification"
        body = json.dumps(details, indent=2)

    return f"{subject}\n\n{body}"


def _send_splunk_notification(
    session_key: str,
    user: str,
    message: str
) -> Tuple[bool, str]:
    """
    Send notification to user via Splunk.

    This is a low-level helper that would integrate with Splunk's notification
    system. For now, just logs the notification.

    Args:
        session_key: Splunk session key (unused, but passed for auth)
        user: Username to notify
        message: Message text

    Returns:
        Tuple of (success: bool, error_msg: str)
    """
    try:
        # In production, this would use Splunk SDK or REST API to create a notification
        # For now, log the notification intent
        _logger.info(f"NOTIFICATION to {user}: {message[:100]}...")
        return (True, "")
    except Exception as e:
        return (False, str(e))


def notify_admins(
    session_key: str,
    notification_type: str,
    details: Dict[str, Any]
) -> Tuple[bool, str]:
    """
    Send notification to all admins about an approval event.

    Non-blocking: notification failures are logged but don't raise exceptions.

    Args:
        session_key: Splunk session key
        notification_type: Type of notification (e.g., "approval_pending")
        details: Event details dict

    Returns:
        Tuple of (success: bool, error_msg: str)
        (True, "") if at least one admin notified successfully
        (False, error_msg) if all notifications failed
    """
    try:
        # Get list of admin users
        admins = get_admin_users(session_key)

        if not admins:
            # No admins to notify, but that's OK
            _logger.info("No admins found to notify")
            return (True, "")

        # Format message
        message = _get_notification_message(notification_type, details)

        # Send to each admin (non-blocking)
        errors = []
        success_count = 0

        for admin in admins:
            success, error = _send_splunk_notification(session_key, admin, message)
            if success:
                success_count += 1
            else:
                errors.append(f"{admin}: {error}")

        if success_count > 0:
            return (True, "")

        # All notifications failed
        error_msg = "; ".join(errors) if errors else "Failed to notify any admins"
        _logger.error(f"notify_admins failed: {error_msg}")
        return (False, error_msg)

    except Exception as e:
        _logger.error(f"notify_admins exception: {e}")
        return (False, str(e))


def notify_analyst(
    session_key: str,
    analyst: str,
    notification_type: str,
    details: Dict[str, Any]
) -> Tuple[bool, str]:
    """
    Send notification to analyst about approval outcome.

    Non-blocking: notification failures are logged but don't raise exceptions.

    Args:
        session_key: Splunk session key
        analyst: Username of analyst
        notification_type: Type of notification (e.g., "approval_approved")
        details: Event details dict

    Returns:
        Tuple of (success: bool, error_msg: str)
        (True, "") on success
        (False, error_msg) on failure
    """
    try:
        if not analyst:
            return (False, "Invalid analyst username")

        # Format message
        message = _get_notification_message(notification_type, details)

        # Send notification
        success, error = _send_splunk_notification(session_key, analyst, message)

        if not success:
            _logger.error(f"notify_analyst failed for {analyst}: {error}")

        return (success, error)

    except Exception as e:
        _logger.error(f"notify_analyst exception: {e}")
        return (False, str(e))
