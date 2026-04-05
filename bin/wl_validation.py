"""
Input validation and security helpers for Whitelist Manager.

Provides:
- sanitize_text: Strip disallowed characters
- is_safe_filename: Validate filenames for traversal attacks
- safe_realpath: Resolve symlinks and verify containment
- build_csv_path: Build absolute path without checking existence
- resolve_csv_path: Build and verify path exists and is safe

All functions are pure (no state, no side effects).
Layer 2: imports only from wl_constants and stdlib.
"""

import os
import re
from typing import Optional, Tuple

__all__ = [
    "sanitize_text",
    "validate_ascii_text",
    "is_safe_filename",
    "safe_realpath",
    "build_csv_path",
    "resolve_csv_path",
]

import sys
sys.path.insert(0, os.path.dirname(__file__))

from wl_constants import (
    _CONTROL_CHAR_RE,
    _SANITIZE_RE,
    _SAFE_COLNAME_RE,
    APPS_DIR,
    OWN_LOOKUPS,
)


def sanitize_text(text: str, max_length: int = 500) -> str:
    """
    Sanitize user-provided text field.

    Removes control characters, collapses whitespace, and truncates.

    Args:
        text: Input string
        max_length: Maximum length (default 500)

    Returns:
        Sanitized string
    """
    if not text or not isinstance(text, str):
        return ""

    # Strip control characters
    cleaned = _CONTROL_CHAR_RE.sub("", text)
    # Sanitize special characters (keep common punctuation)
    cleaned = _SANITIZE_RE.sub("", cleaned)
    # Collapse whitespace
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    # Truncate
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length]

    return cleaned


_NON_ASCII_RE = re.compile(r'[^\x00-\x7F]')


def validate_ascii_text(text):
    """Return an error string if text contains non-ASCII characters, else None."""
    if not text or not isinstance(text, str):
        return None
    match = _NON_ASCII_RE.search(text)
    if match:
        return "Only ASCII characters are allowed in text fields"
    return None


def is_safe_filename(name: str, allowed_extensions: Tuple[str, ...] = (".csv",)) -> bool:
    """
    Validate filename for path traversal attacks.

    Returns True only if:
    - name is a plain filename (no path separators)
    - name doesn't start with .
    - name has allowed extension
    - stem contains at least one alphanumeric character

    Args:
        name: Filename to validate
        allowed_extensions: Allowed extensions (default (".csv",))

    Returns:
        True if safe, False otherwise
    """
    if not name or not isinstance(name, str):
        return False

    # Reject if contains path separators
    if os.path.basename(name) != name:
        return False

    # Reject if starts with dot
    if name.startswith("."):
        return False

    # Check extension
    if not any(name.lower().endswith(ext) for ext in allowed_extensions):
        return False

    # Stem must contain at least one alphanumeric character
    stem = name.rsplit(".", 1)[0]
    if not stem or not any(c.isalnum() for c in stem):
        return False

    return True


def safe_realpath(path: str, allowed_base: str) -> Optional[str]:
    """
    Resolve symlinks and verify the real path is under allowed_base.

    Args:
        path: Path to resolve
        allowed_base: Base directory (symlinks must resolve within this)

    Returns:
        Real path if safe, None if traversal detected
    """
    try:
        real = os.path.realpath(path)
        real_base = os.path.realpath(allowed_base)

        # Check if real path is under allowed_base
        if not (real.startswith(real_base + os.sep) or real == real_base):
            return None

        return real
    except (OSError, ValueError):
        return None


def build_csv_path(csv_file: str, app_context: str = "") -> Optional[str]:
    """
    Build absolute path to a lookup CSV file (without checking existence).

    Args:
        csv_file: Filename (must pass is_safe_filename check)
        app_context: App name context (default: wl_manager own lookups)

    Returns:
        Absolute path if safe, None if filename is invalid
    """
    if not is_safe_filename(csv_file):
        return None

    if app_context:
        # Restrict app name to basename (prevent traversal)
        safe_app = os.path.basename(app_context)
        lookups_dir = os.path.join(APPS_DIR, safe_app, "lookups")
        path = os.path.join(lookups_dir, csv_file)
    else:
        path = os.path.join(OWN_LOOKUPS, csv_file)

    # Normalize and verify path is under APPS_DIR
    normed = os.path.normpath(path)
    apps_normed = os.path.normpath(APPS_DIR)

    if not normed.startswith(apps_normed):
        return None

    return normed


def resolve_csv_path(csv_file: str, app_context: str = "") -> Optional[str]:
    """
    Build absolute path to a lookup CSV and verify it exists and is safe.

    Args:
        csv_file: Filename
        app_context: App name context

    Returns:
        Real absolute path if file exists and is safe, None otherwise
    """
    path = build_csv_path(csv_file, app_context)
    if path is None:
        return None

    # Check existence
    if not os.path.isfile(path):
        return None

    # Verify symlink safety
    safe = safe_realpath(path, APPS_DIR)
    if safe is None:
        return None

    return safe
