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
    "is_ascii_name",
    "is_valid_app_context",
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

# ASCII identifier regex — used by detection rule names and CSV filenames.
# We must NOT use Python's c.isalnum() here because it is Unicode-aware and
# accepts CJK ideographs (e.g. '检' is a Unicode "letter"), Cyrillic, Greek,
# Arabic, etc. ASCII-only is enforced because:
#   1. Rule names become parts of filesystem paths (CSVs live at
#      lookups/<csv>.csv; version manifests at lookups/_versions/<csv>_versions.json)
#   2. CSV filenames need to be safe for SPL search expressions, dashboard
#      drilldowns, audit log readability, and cross-platform copy/backup
#   3. Defense against homoglyph attacks (zero-width spaces, lookalike chars)
# See discussion 2026-04-26 with user — gap was found via stress test that
# accidentally allowed `DR_压力测试_检...` through both create_rule and
# create_csv submission paths.
_ASCII_NAME_RE = re.compile(r'^[A-Za-z0-9_\-. ]+$')
_ASCII_FILENAME_STEM_RE = re.compile(r'^[A-Za-z0-9_\-]+$')


def validate_ascii_text(text):
    """Return an error string if text contains non-ASCII characters, else None."""
    if not text or not isinstance(text, str):
        return None
    match = _NON_ASCII_RE.search(text)
    if match:
        return "Only ASCII characters are allowed in text fields"
    return None


def is_ascii_name(text, allow_spaces=True):
    """Return True if text is a valid ASCII identifier-like name.

    Allowed: a-z, A-Z, 0-9, underscore, hyphen, dot. Spaces are allowed
    by default (used by detection rule names which can be human-readable
    titles). Pass allow_spaces=False for fields that must not contain
    spaces (e.g. CSV filenames where space → "_" replacement is the
    pipeline norm).

    Also rejects whitespace-only strings (e.g. "   ") even though spaces
    pass the regex — a name with no actual content would create blank-
    titled rules and downstream display bugs.
    """
    if not text or not isinstance(text, str):
        return False
    if allow_spaces:
        if not _ASCII_NAME_RE.match(text):
            return False
    else:
        if not _ASCII_FILENAME_STEM_RE.match(text):
            return False
    # Defense-in-depth: require at least one non-space character. Without
    # this, "   " would pass the spaces-allowed regex.
    return any(not c.isspace() for c in text)


# Splunk app names by convention are alphanumeric + underscore + hyphen.
# We never allow spaces, dots, slashes, or non-ASCII because the value is
# joined into a filesystem path: etc/apps/<app_context>/lookups/...
# Length cap of 100 matches typical Splunk app naming and protects against
# pathological input.
_APP_CONTEXT_RE = re.compile(r'^[A-Za-z0-9_\-]{1,100}$')


def is_valid_app_context(text):
    """Return True if text is a valid Splunk app context name.

    Splunk app names follow the convention `[a-zA-Z0-9_-]+`. The value
    flows into `os.path.join(APPS_DIR, app_context, "lookups", ...)` so
    we must reject path separators, dots (no traversal), and any
    non-ASCII characters before the path is constructed.

    Empty string is considered valid here — the caller is expected to
    apply a default (typically APP_NAME / "wl_manager") when the field
    is omitted.
    """
    if not text:
        return True  # empty → caller substitutes default
    if not isinstance(text, str):
        return False
    return bool(_APP_CONTEXT_RE.match(text))


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

    # Stem must be ASCII alphanumeric / underscore / hyphen ONLY,
    # AND contain at least one alphanumeric. This matches the stricter
    # is_ascii_name(allow_spaces=False) contract.
    #
    # Origin: round 5 hypothesis fuzz test (2026-04-29) found that
    # is_safe_filename was accepting names like "0;.csv" — semicolons
    # are SPL command separators and would break dashboard renders.
    # Earlier code only required ≥1 alphanumeric and ASCII-only; that
    # let through `; & | ( ) @ #` etc. which were never legitimate in
    # this app's lookups (existing files all use the strict set).
    stem = name.rsplit(".", 1)[0]
    if not stem:
        return False
    # Reject non-ASCII characters anywhere in the filename
    if _NON_ASCII_RE.search(name):
        return False
    # Reject control characters (NUL, BEL, BS, etc.) anywhere — null
    # bytes in particular are a classic C-string path-truncation attack.
    if any(ord(c) < 0x20 or ord(c) == 0x7f for c in name):
        return False
    # Stem must match the same regex used for CSV filename stems in
    # is_ascii_name(allow_spaces=False). This brings the two validators
    # into alignment — only A-Za-z0-9_- chars allowed.
    if not _ASCII_FILENAME_STEM_RE.match(stem):
        return False
    # ALSO require ≥1 alphanumeric: the regex above accepts pure
    # `___` or `---` strings, but a filename with no actual letter or
    # digit is operationally meaningless and would create confusing
    # entries in the lookups dir.
    if not any(c.isascii() and c.isalnum() for c in stem):
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
