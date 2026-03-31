"""
Audit Event Construction and Posting Module

Provides structured audit event building and HTTP posting to Splunk's
wl_audit index. Designed for reuse by approval queue and other backend
components that need to log structured events.

Public API:
    - build_audit_event(): Construct structured audit event dict
    - post_audit_event(): Post event to wl_audit index via REST API
    - get_audit_logger(): Return configured audit logger
"""

import json
import ssl
import socket
import time
from datetime import datetime, timezone
from typing import Dict, Tuple, Any
import logging

try:
    import urllib.request
    import urllib.parse
except ImportError:
    urllib = None  # Offline testing

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from wl_constants import AUDIT_INDEX, AUDIT_SOURCETYPE, AUDIT_SOURCE, MAX_AUDIT_VALUE_LINES
from wl_logging import get_audit_logger

__all__ = [
    'build_audit_event',
    'post_audit_event',
    'get_audit_logger',
]


def build_audit_event(
    action: str,
    analyst: str,
    detection_rule: str,
    csv_file: str,
    **kwargs
) -> Dict[str, Any]:
    """
    Construct a structured audit event dict for posting to wl_audit index.

    Parameters:
        action: Event action type (e.g., "added", "removed", "edited", "revert", "auto_removed")
        analyst: Username performing the action
        detection_rule: Name of the detection rule being modified
        csv_file: Name of the CSV file being modified
        **kwargs: Additional event fields (comment, removed_row_count, edited_row_count, etc.)

    Returns:
        Dict with all required and optional audit event fields ready for posting.

    Examples:
        >>> evt = build_audit_event(
        ...     action="added",
        ...     analyst="jsmith",
        ...     detection_rule="Suspicious Login",
        ...     csv_file="login_whitelist.csv",
        ...     comment="Added trusted IP",
        ...     removed_row_count=0
        ... )
        >>> evt["action"]
        'added'
        >>> evt["analyst"]
        'jsmith'
    """
    # Build base event with required fields
    ts = int(datetime.now(timezone.utc).timestamp())

    event = {
        "timestamp": ts,
        "action": action,
        "analyst": analyst,
        "detection_rule": detection_rule,
        "csv_file": csv_file,
        "app_context": kwargs.get("app_context", ""),
        "comment": kwargs.get("comment", ""),
    }

    # Merge in all additional kwargs (for flexibility with different action types)
    for key, value in kwargs.items():
        if key not in ("app_context", "comment"):  # Already handled above
            event[key] = value

    return event


def post_audit_event(session_key: str, event: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Post an audit event to the wl_audit index via Splunk REST API.

    Uses HTTP POST to Splunk's /services/receivers/simple endpoint.
    Non-blocking: failures are logged but do not raise exceptions.

    Parameters:
        session_key: Splunk session/auth token from request
        event: Structured event dict (typically from build_audit_event)

    Returns:
        Tuple[bool, str]: (success_bool, error_msg)
            - (True, "") on success (HTTP 200-299)
            - (False, error_message) on failure (4xx/5xx, network error, timeout)

    Examples:
        >>> evt = build_audit_event("added", "jsmith", "rule1", "file.csv")
        >>> success, error = post_audit_event("session_abc123", evt)
        >>> if success:
        ...     print("Posted OK")
        ... else:
        ...     print(f"Failed: {error}")
    """
    logger = get_audit_logger()

    if not session_key:
        msg = "No session key provided for audit posting"
        logger.warning(msg)
        return False, msg

    if urllib is None:
        msg = "urllib not available (offline environment)"
        logger.debug(msg)
        return False, msg

    try:
        # Truncate value arrays to prevent oversized audit events
        if "value" in event and isinstance(event["value"], list):
            if len(event["value"]) > MAX_AUDIT_VALUE_LINES:
                truncated_count = len(event["value"]) - MAX_AUDIT_VALUE_LINES
                event["value"] = event["value"][:MAX_AUDIT_VALUE_LINES]
                event["value"].append(
                    "... truncated {} more entries".format(truncated_count)
                )

        # Build REST API URL with query parameters
        qs = urllib.parse.urlencode({
            "index": AUDIT_INDEX,
            "sourcetype": AUDIT_SOURCETYPE,
            "source": AUDIT_SOURCE,
        })
        url = "https://127.0.0.1:8089/services/receivers/simple?%s" % qs

        # Serialize event to JSON
        event_data = json.dumps(event, default=str).encode("utf-8")

        # Build HTTP request
        req = urllib.request.Request(url, data=event_data, method="POST")
        req.add_header("Authorization", "Splunk %s" % session_key)
        req.add_header("Content-Type", "application/json")

        # Disable SSL verification for self-signed cert at localhost:8089
        # (No data leaves the machine, MITM risk negligible)
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        # Post request with 10-second timeout
        response = urllib.request.urlopen(req, context=ctx, timeout=10)
        status_code = response.status

        if 200 <= status_code < 300:
            return True, ""
        else:
            error_msg = f"HTTP {status_code}: {response.reason}"
            logger.error(f"post_audit_event failed: {error_msg}")
            return False, error_msg

    except urllib.error.HTTPError as e:
        error_msg = f"HTTP {e.code}: {e.reason}"
        logger.error(f"post_audit_event HTTP error: {error_msg}")
        return False, error_msg
    except urllib.error.URLError as e:
        error_msg = f"URL error: {str(e)}"
        logger.error(f"post_audit_event URL error: {error_msg}")
        return False, error_msg
    except socket.timeout:
        error_msg = "Request timeout (10s)"
        logger.error(f"post_audit_event timeout: {error_msg}")
        return False, error_msg
    except Exception as e:
        error_msg = str(e)
        logger.error(f"post_audit_event error: {error_msg}")
        return False, error_msg
