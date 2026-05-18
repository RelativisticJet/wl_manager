"""
CSV Module — Core CSV data structure operations.

Provides read/write, diff computation, expiration handling, and column width
tracking for whitelist CSV files. Extracted from wl_handler.py for independent
testing and reuse by other modules (versions, audit, approval).

All functions operate on CSV files in isolation — no Splunk REST API calls or
handler context needed. Functions are pure (except for I/O) and can be unit
tested offline.
"""

import csv
import difflib
import json
import logging

_logger = logging.getLogger("wl_manager.wl_csv")
import os
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple, Optional, Any

import hashlib

from wl_constants import (
    OWN_LOOKUPS, MAX_ROWS, MAX_COLUMNS, MAX_CELL_CHARS, MAX_DIFF_ROWS,
    DETECTION_RULES_FILE, VERSIONS_DIR,
    EXPIRE_COLUMN_NAMES,
)
from wl_hmac_key import (
    derive_hash_registry_key as _derive_hash_registry_key,
    compute_registry_checksum as _compute_hash_registry_checksum,
    read_expected_hashes as _read_expected_hashes,
    write_expected_hashes as _write_expected_hashes,
)
from wl_validation import sanitize_text


__all__ = [
    'read_csv',
    'write_csv',
    'compute_diff',
    'get_expire_column',
    'remove_expired_rows',
    'get_column_widths',
    'set_column_widths',
    'save_csv_pipeline',
    'create_csv_pipeline',
    'update_csv_expected_hash',
    'remove_csv_expected_hash',
    'bootstrap_csv_expected_hashes',
    'CSV_EXPECTED_HASHES_FILE',
]


# ═══════════════════════════════════════════════════════════════════════════
# Core CSV read/write operations
# ═══════════════════════════════════════════════════════════════════════════

def read_csv(filepath: str) -> Tuple[List[str], List[Dict[str, str]]]:
    """
    Read a CSV file and return (headers, rows).

    Args:
        filepath: Path to CSV file.

    Returns:
        Tuple of (headers: list[str], rows: list[dict]) where each row is
        an OrderedDict with column names as keys.

    Raises:
        OSError: If file does not exist or cannot be read.
    """
    with open(filepath, "r", newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        headers = list(reader.fieldnames or [])
        rows = [dict(row) for row in reader]
    return headers, rows


CSV_EXPECTED_HASHES_FILE = ".csv_expected_hashes.json"
"""Filename for the expected-hash registry (stored in lookups/_versions/).
The FIM stat-watcher reads this to distinguish legitimate handler writes
from external modifications (SPL outputlookup, filesystem edits, etc.)."""


def _csv_file_hash(filepath: str) -> str:
    """Compute SHA-256 hash of a file on disk."""
    h = hashlib.sha256()
    with open(filepath, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _get_expected_hashes_path(csv_filepath: str) -> str:
    """Derive the expected-hashes file path from a CSV filepath.

    The hashes file lives in the ``_versions/`` subdirectory next to
    the CSV's parent ``lookups/`` directory.
    """
    parent = os.path.dirname(csv_filepath)
    return os.path.join(parent, VERSIONS_DIR, CSV_EXPECTED_HASHES_FILE)


def update_csv_expected_hash(csv_filepath: str) -> str:
    """Record the current hash of a CSV file in the expected-hashes registry.

    Called automatically by ``write_csv()`` and available for manual use
    (e.g., after ``restore_from_trash`` which copies the file directly).

    Returns:
        The SHA-256 hex digest of the file.
    """
    file_hash = _csv_file_hash(csv_filepath)
    hashes_path = _get_expected_hashes_path(csv_filepath)
    hashes = _read_expected_hashes(hashes_path)
    csv_name = os.path.basename(csv_filepath)
    hashes[csv_name] = file_hash
    _write_expected_hashes(hashes_path, hashes)
    return file_hash


def remove_csv_expected_hash(csv_filepath: str) -> None:
    """Remove a CSV from the expected-hashes registry (on delete/trash)."""
    hashes_path = _get_expected_hashes_path(csv_filepath)
    hashes = _read_expected_hashes(hashes_path)
    csv_name = os.path.basename(csv_filepath)
    if csv_name in hashes:
        del hashes[csv_name]
        _write_expected_hashes(hashes_path, hashes)


def bootstrap_csv_expected_hashes(lookups_dir: str) -> dict:
    """Scan all CSVs from the rule mapping and rebuild the expected-hash registry.

    This is a diff-aware batch operation that:
    1. Reads the PREVIOUS registry (if any) for comparison
    2. Reads rule_csv_map.csv to discover all managed CSV files
    3. Hashes every CSV that exists on disk
    4. Also hashes rule_csv_map.csv itself (sentinel CSV)
    5. Compares new hashes against previous → reports changed CSVs
    6. Writes a single HMAC-signed registry atomically

    The diff step is critical for detecting "bootstrap laundering" — an
    attacker who modifies a CSV then immediately bootstraps to suppress
    the watcher alert.  The changed_csvs list makes this visible in the
    audit trail regardless.

    Returns:
        dict with keys: hashed_count, missing_count, missing_files,
        changed_csvs (list of {csv_file, old_hash, new_hash}),
        new_csvs (list of csv names not in previous registry),
        removed_csvs (list of csv names in previous but not current).
    """
    mapping_path = os.path.join(lookups_dir, "rule_csv_map.csv")
    if not os.path.isfile(mapping_path):
        raise OSError("rule_csv_map.csv not found at %s" % mapping_path)

    # Read the mapping to discover all CSVs
    csv_files = set()
    with open(mapping_path, "r", newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            fname = row.get("csv_file", "").strip()
            if fname:
                csv_files.add(fname)

    # Always include the mapping file itself (sentinel CSV)
    csv_files.add("rule_csv_map.csv")

    hashes_path = os.path.join(lookups_dir, VERSIONS_DIR, CSV_EXPECTED_HASHES_FILE)

    # Read previous registry for diff (empty dict if missing/corrupt = first run)
    old_hashes = _read_expected_hashes(hashes_path)

    new_hashes = {}  # type: Dict[str, str]
    missing = []  # type: List[str]

    for csv_name in sorted(csv_files):
        csv_path = os.path.join(lookups_dir, csv_name)
        if os.path.isfile(csv_path):
            new_hashes[csv_name] = _csv_file_hash(csv_path)
        else:
            missing.append(csv_name)

    # Diff: detect changed, new, and removed CSVs
    changed_csvs = []  # type: List[Dict[str, str]]
    new_csvs = []  # type: List[str]
    removed_csvs = []  # type: List[str]

    for csv_name, new_hash in new_hashes.items():
        old_hash = old_hashes.get(csv_name)
        if old_hash is None:
            new_csvs.append(csv_name)
        elif old_hash != new_hash:
            changed_csvs.append({
                "csv_file": csv_name,
                "old_hash": old_hash,
                "new_hash": new_hash,
            })

    for csv_name in old_hashes:
        if csv_name not in new_hashes:
            removed_csvs.append(csv_name)

    _write_expected_hashes(hashes_path, new_hashes)

    return {
        "hashed_count": len(new_hashes),
        "missing_count": len(missing),
        "missing_files": missing,
        "changed_csvs": changed_csvs,
        "new_csvs": new_csvs,
        "removed_csvs": removed_csvs,
    }


def write_csv(filepath: str, headers: List[str], rows: List[Dict[str, str]]) -> None:
    """
    Write a CSV file atomically (write to temp, then rename).

    After a successful write, automatically updates the expected-hash
    registry so the FIM stat-watcher can distinguish this legitimate
    write from external modifications.

    Args:
        filepath: Path to CSV file to write.
        headers: List of column names.
        rows: List of dicts (each row's data).

    Raises:
        OSError: If permission denied or disk full.
    """
    # Write to temp file first, then atomic rename
    temp_path = filepath + ".tmp"
    try:
        with open(temp_path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=headers, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temp_path, filepath)
    except Exception:
        try:
            os.remove(temp_path)
        except OSError:
            pass
        raise

    # Update expected-hash registry so FIM watcher doesn't false-alarm.
    # Best-effort — hash update failure should NOT block the CSV save.
    try:
        update_csv_expected_hash(filepath)
    except Exception:
        _logger.warning("Failed to update expected hash for %s", filepath)


# ═══════════════════════════════════════════════════════════════════════════
# Diff computation — Refactored into focused sub-functions
# ═══════════════════════════════════════════════════════════════════════════

def compute_columns(
    old_headers: List[str],
    new_headers: List[str],
) -> Dict[str, List[str]]:
    """
    Detect added and removed columns.

    Filters out metadata columns (starting with _) from comparison.

    Args:
        old_headers: Original CSV column names.
        new_headers: New CSV column names.

    Returns:
        Dict with keys:
        - added_columns: List of column names added in new_headers
        - removed_columns: List of column names removed from old_headers
    """
    old_vis = [h for h in old_headers if not h.startswith("_")]
    new_vis = [h for h in new_headers if not h.startswith("_")]
    old_vis_set = set(old_vis)
    new_vis_set = set(new_vis)

    removed_columns = [h for h in old_vis if h not in new_vis_set]
    added_columns = [h for h in new_vis if h not in old_vis_set]

    return {
        "added_columns": added_columns,
        "removed_columns": removed_columns,
    }


def compute_added(
    old_rows: List[Dict[str, str]],
    new_rows: List[Dict[str, str]],
    common_headers: List[str],
) -> List[Dict[str, str]]:
    """
    Detect rows newly added in new_rows using Counter-based comparison.

    Iterates in REVERSE because frontend appends new rows at the end.
    Reverse iteration picks truly-new rows from the back instead of
    pre-existing duplicates from the front.

    Args:
        old_rows: Original CSV rows.
        new_rows: New CSV rows.
        common_headers: Headers present in both old and new.

    Returns:
        List of truly-new row dicts in original order.
    """
    def _row_key(row: Dict[str, str]) -> Tuple[str, ...]:
        return tuple(row.get(h, "") for h in common_headers)

    old_key_counts = Counter(_row_key(r) for r in old_rows)
    new_key_counts = Counter(_row_key(r) for r in new_rows)

    _add_remaining = Counter()
    for k in new_key_counts:
        excess = new_key_counts[k] - old_key_counts.get(k, 0)
        if excess > 0:
            _add_remaining[k] = excess

    added_raw = []
    for r in reversed(new_rows):
        k = _row_key(r)
        if _add_remaining.get(k, 0) > 0:
            added_raw.append(r)
            _add_remaining[k] -= 1
    added_raw.reverse()  # restore original (append) order

    return added_raw


def compute_removed(
    old_rows: List[Dict[str, str]],
    new_rows: List[Dict[str, str]],
    common_headers: List[str],
) -> List[Dict[str, str]]:
    """
    Detect rows removed from old_rows using Counter-based comparison.

    Args:
        old_rows: Original CSV rows.
        new_rows: New CSV rows.
        common_headers: Headers present in both old and new.

    Returns:
        List of truly-removed row dicts.
    """
    def _row_key(row: Dict[str, str]) -> Tuple[str, ...]:
        return tuple(row.get(h, "") for h in common_headers)

    old_key_counts = Counter(_row_key(r) for r in old_rows)
    new_key_counts = Counter(_row_key(r) for r in new_rows)

    _rem_remaining = Counter()
    for k in old_key_counts:
        excess = old_key_counts[k] - new_key_counts.get(k, 0)
        if excess > 0:
            _rem_remaining[k] = excess

    removed_raw = []
    for r in old_rows:
        k = _row_key(r)
        if _rem_remaining.get(k, 0) > 0:
            removed_raw.append(r)
            _rem_remaining[k] -= 1

    return removed_raw


def _find_row_positions(
    row_key: Tuple[str, ...],
    old_rows: List[Dict[str, str]],
    new_rows: List[Dict[str, str]],
    common_headers: List[str],
) -> Tuple[int, int]:
    """
    Find 1-based positions of a row key in old and new row lists.

    Returns (old_position, new_position) where 0 means not found.
    """
    def _row_key(row: Dict[str, str]) -> Tuple[str, ...]:
        return tuple(row.get(h, "") for h in common_headers)

    old_pos = 0
    for idx_o, r in enumerate(old_rows):
        if _row_key(r) == row_key:
            old_pos = idx_o + 1
            break

    new_pos = 0
    for idx_n, r in enumerate(new_rows):
        if _row_key(r) == row_key:
            new_pos = idx_n + 1
            break

    return old_pos, new_pos


def compute_edited(
    added_raw: List[Dict[str, str]],
    removed_raw: List[Dict[str, str]],
    old_rows: List[Dict[str, str]],
    new_rows: List[Dict[str, str]],
    common_headers: List[str],
) -> Tuple[List[Dict], List[Dict[str, str]], List[Dict[str, str]]]:
    """
    Pair added rows with removed rows using >50% field overlap heuristic.

    Detects "edited" rows when most fields stay the same and only a few change.
    Pairs removed_raw entries with added_raw entries that share the most
    unchanged visible fields, requiring at least half the fields to match
    (to avoid pairing completely different rows).

    Args:
        added_raw: Rows detected as added.
        removed_raw: Rows detected as removed.
        old_rows: Original CSV rows (for position lookup).
        new_rows: New CSV rows (for position lookup).
        common_headers: Headers present in both old and new.

    Returns:
        Tuple of (edited, remaining_added, remaining_removed) where:
        - edited: List of {old_row, new_row, old_row_num, row_num, changed_fields}
        - remaining_added: Unpaired rows from added_raw
        - remaining_removed: Unpaired rows from removed_raw
    """
    def _row_key(row: Dict[str, str]) -> Tuple[str, ...]:
        return tuple(row.get(h, "") for h in common_headers)

    def _field_overlap(
        old_row: Dict[str, str],
        new_row: Dict[str, str],
    ) -> Tuple[int, int, List[Dict[str, str]]]:
        """Return (matching_count, total_fields, changed_fields_list)."""
        matching = 0
        changed = []
        for h in common_headers:
            ov = old_row.get(h, "")
            nv = new_row.get(h, "")
            if ov == nv:
                matching += 1
            else:
                changed.append({"field": h, "before": ov, "after": nv})
        return matching, len(common_headers), changed

    edited = []
    paired_old_ids = set()   # id() of paired old row objects
    paired_new_ids = set()   # id() of paired new row objects

    # Guard against O(n²×m) explosion: skip edit detection if
    # both sides exceed MAX_DIFF_ROWS (treat all as pure adds/removes)
    used_removed_indices = set()
    skip_edit_detection = (len(added_raw) > MAX_DIFF_ROWS
                           or len(removed_raw) > MAX_DIFF_ROWS)

    if not skip_edit_detection:
        for new_row in added_raw:
            new_k = _row_key(new_row)
            best_score = -1
            best_idx = -1
            best_changed = []

            for ri, old_row in enumerate(removed_raw):
                if ri in used_removed_indices:
                    continue
                matching, total, changed = _field_overlap(old_row, new_row)
                if matching > best_score:
                    best_score = matching
                    best_idx = ri
                    best_changed = changed

            # Require at least half the fields to be unchanged
            if best_idx >= 0 and best_score >= len(common_headers) / 2:
                old_row = removed_raw[best_idx]
                old_k = _row_key(old_row)
                used_removed_indices.add(best_idx)

                # Find 1-based positions
                old_pos, new_pos = _find_row_positions(old_k, old_rows, new_rows, common_headers)

                edited.append({
                    "old_row": old_row,
                    "new_row": new_row,
                    "old_row_num": old_pos,
                    "row_num": new_pos,
                    "changed_fields": best_changed,
                })
                paired_old_ids.add(id(old_row))
                paired_new_ids.add(id(new_row))

    # Remove paired rows from added/removed lists (by identity, not key,
    # so duplicate rows aren't all removed when only one was paired)
    added = [r for r in added_raw if id(r) not in paired_new_ids]
    removed = [r for r in removed_raw if id(r) not in paired_old_ids]

    return edited, added, removed


def compute_diff(
    old_headers: List[str],
    old_rows: List[Dict[str, str]],
    new_headers: List[str],
    new_rows: List[Dict[str, str]],
) -> Dict[str, Any]:
    """
    Compare old vs new CSV content and return a structured diff.

    Orchestrates sub-functions to compute columns, added, removed, and edited
    rows using similarity-based matching. Returns both structured data and
    text-based unified diff format.

    Args:
        old_headers: Original CSV column names.
        old_rows: Original CSV rows (list of dicts).
        new_headers: New CSV column names.
        new_rows: New CSV rows (list of dicts).

    Returns:
        Dict with keys:
        - added: List of new row dicts
        - removed: List of deleted row dicts
        - edited: List of dicts with {old_row, new_row, old_row_num, row_num, changed_fields}
        - added_count, removed_count, edited_count: Int counts
        - added_columns, removed_columns: List of column names added/removed
        - text_diff: List of unified-diff style lines (Git-style)
    """
    all_headers = list(dict.fromkeys(old_headers + new_headers))
    visible_headers = [h for h in all_headers if not h.startswith("_")]

    # Compute visible headers for row matching
    old_vis_set = set(h for h in old_headers if not h.startswith("_"))
    new_vis_set = set(h for h in new_headers if not h.startswith("_"))
    common_headers = [h for h in visible_headers if h in old_vis_set and h in new_vis_set]

    # Compute columns
    col_changes = compute_columns(old_headers, new_headers)

    # Compute added/removed/edited rows
    added_raw = compute_added(old_rows, new_rows, common_headers)
    removed_raw = compute_removed(old_rows, new_rows, common_headers)
    edited, added, removed = compute_edited(
        added_raw, removed_raw, old_rows, new_rows, common_headers
    )

    # Generate text diff
    def _rows_to_lines(headers: List[str], rows: List[Dict[str, str]]) -> List[str]:
        lines = [",".join(headers)]
        for r in rows:
            # Coerce missing/None values to "" — a row may carry an
            # explicit ``None`` for a column (e.g. after schema drift)
            # and ``dict.get(h, "")`` only substitutes when the key is
            # absent, not when the value is None.
            lines.append(",".join(
                ("" if r.get(h) is None else str(r.get(h)))
                for h in headers
            ))
        return lines

    old_vis = [h for h in old_headers if not h.startswith("_")]
    new_vis = [h for h in new_headers if not h.startswith("_")]
    old_lines = _rows_to_lines(old_vis, old_rows)
    new_lines = _rows_to_lines(new_vis, new_rows)
    text_diff = list(
        difflib.unified_diff(
            old_lines, new_lines, fromfile="before", tofile="after", lineterm=""
        )
    )

    return {
        "added": added,
        "removed": removed,
        "edited": edited,
        "added_count": len(added),
        "removed_count": len(removed),
        "edited_count": len(edited),
        "added_columns": col_changes["added_columns"],
        "removed_columns": col_changes["removed_columns"],
        "text_diff": text_diff,
    }


# ═══════════════════════════════════════════════════════════════════════════
# Expiration handling
# ═══════════════════════════════════════════════════════════════════════════

def get_expire_column(headers: List[str]) -> Optional[str]:
    """
    Find the expiration column in headers (case-insensitive).

    Args:
        headers: List of CSV column names.

    Returns:
        The column name if found, None otherwise.
    """
    for h in headers:
        if h.lower() in EXPIRE_COLUMN_NAMES:
            return h
    return None


def remove_expired_rows(
    headers: List[str],
    rows: List[Dict[str, str]],
    tz_offset_minutes: int = 0,
) -> Tuple[List[Dict[str, str]], int]:
    """
    Filter out rows where an expiration column contains a past date/time.

    Supports two date formats:
    - UTC (new):    "YYYY-MM-DD HH:MM UTC" — " UTC" suffix, compared against UTC now
    - Legacy local: "YYYY-MM-DD HH:MM"     — no suffix, compared against user's
                    local time derived from tz_offset_minutes

    Also tolerates date-only variants ("YYYY-MM-DD UTC" / "YYYY-MM-DD").

    Args:
        headers: CSV column names.
        rows: CSV rows (list of dicts).
        tz_offset_minutes: Minutes to offset from UTC for legacy local time comparison.

    Returns:
        Tuple of (kept_rows, expired_count) where:
        - kept_rows: Rows that are still valid
        - expired_count: Number of rows removed
    """
    expire_col = get_expire_column(headers)
    if not expire_col:
        return rows, 0

    now_utc = datetime.now(timezone.utc)

    # Legacy fallback: convert UTC "now" to user's local time
    user_offset = timedelta(minutes=-tz_offset_minutes)
    user_tz = timezone(user_offset)
    now_local = now_utc.astimezone(user_tz).replace(tzinfo=None)

    kept = []
    expired_count = 0

    for row in rows:
        exp_val = (row.get(expire_col) or "").strip()
        if not exp_val:
            kept.append(row)
            continue

        # Detect UTC format (" UTC" suffix)
        is_utc = exp_val.endswith(" UTC")
        parse_val = exp_val[:-4] if is_utc else exp_val

        parsed = False
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                exp_date = datetime.strptime(parse_val, fmt)
                parsed = True
                break
            except ValueError:
                continue

        if not parsed:
            kept.append(row)
            continue

        if is_utc:
            # UTC value — compare directly against UTC now
            exp_date = exp_date.replace(tzinfo=timezone.utc)
            if exp_date < now_utc:
                expired_count += 1
            else:
                kept.append(row)
        else:
            # Legacy naive local — compare against user's local time
            if exp_date < now_local:
                expired_count += 1
            else:
                kept.append(row)

    return kept, expired_count


# ═══════════════════════════════════════════════════════════════════════════
# Column width tracking
# ═══════════════════════════════════════════════════════════════════════════

def get_column_widths(csv_path: str) -> Dict[str, int]:
    """
    Read column widths JSON file (side-car to CSV).

    Column widths are stored in a JSON file next to the CSV version snapshots,
    mapping column names to pixel widths (for frontend rendering).

    Args:
        csv_path: Path to CSV file.

    Returns:
        Dict {col_name: width_px} or empty dict if file missing or invalid JSON.
    """
    versions_dir = os.path.join(os.path.dirname(csv_path), VERSIONS_DIR)
    base = os.path.splitext(os.path.basename(csv_path))[0]
    widths_path = os.path.join(versions_dir, base + "_colwidths.json")

    if not os.path.isfile(widths_path):
        return {}

    try:
        with open(widths_path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return {}


def set_column_widths(csv_path: str, widths: Dict[str, int]) -> None:
    """
    Write column widths JSON file.

    Creates the _versions/ directory if needed and stores the widths dict.
    Silently ignores file errors (non-critical feature).

    Args:
        csv_path: Path to CSV file.
        widths: Dict {col_name: width_px}.
    """
    parent = os.path.dirname(csv_path)
    versions_dir = os.path.join(parent, VERSIONS_DIR)
    os.makedirs(versions_dir, exist_ok=True)

    base = os.path.splitext(os.path.basename(csv_path))[0]
    widths_path = os.path.join(versions_dir, base + "_colwidths.json")

    try:
        with open(widths_path, "w", encoding="utf-8") as fh:
            json.dump(widths, fh, indent=2)
    except (OSError, IOError):
        pass  # Silently fail for non-critical feature


# ═══════════════════════════════════════════════════════════════════════════
# Pipeline functions — Pure operations extracted from handler
# ═══════════════════════════════════════════════════════════════════════════

def save_csv_pipeline(
    csv_path: str,
    new_headers: List[str],
    new_rows: List[Dict[str, str]],
    comment: str,
    analyst: str,
    session_key: str,
    removal_reasons: Optional[List[Dict]] = None,
    bulk_removal: Optional[List[Dict]] = None,
    column_removal_reasons: Optional[List[Dict]] = None,
    row_reorder: Optional[Dict] = None,
    column_reorder: Optional[Dict] = None,
    column_renames: Optional[List[Dict]] = None,
    explicit_row_add_reason: Optional[str] = None,
    has_comment_col: bool = False,
    csv_file: str = "",
    app_context: str = "",
    detection_rule: str = "",
) -> Dict[str, Any]:
    """
    Execute the complete save operation for a CSV: diff, audit, write, snapshot.

    This pipeline contains the core business logic for saving a CSV file:
    1. Compute diff (added/removed/edited rows)
    2. Build and post audit events for each change type
    3. Write the CSV file atomically
    4. Create a version snapshot
    5. Return structured result

    The handler retains responsibility for:
    - Optimistic locking (mtime checking)
    - Approval gates and limits (decision logic)
    - RBAC (who can perform what actions)

    Args:
        csv_path: Absolute filesystem path to CSV file.
        new_headers: New CSV column names.
        new_rows: New CSV rows (list of dicts).
        comment: Summary comment for the save.
        analyst: Username of the analyst making the change.
        session_key: Splunk session key for REST API calls.
        removal_reasons: List of {row, reason} dicts for per-row removal reasons.
        bulk_removal: List of {reason} dicts for bulk removal.
        column_removal_reasons: List of {column, reason} dicts for column removals.
        row_reorder: Dict with {from_position, to_position} for row reorder.
        column_reorder: Dict with {column, from_position, to_position} for column reorder.
        column_renames: List of {old_name, new_name} dicts for column renames.
        explicit_row_add_reason: Explicit reason for row additions (may be "__per_row__").
        has_comment_col: Whether CSV has a Comment column.
        csv_file: Short name of CSV file (for audit events, e.g., "DR130_priv_escalation.csv").
        app_context: App context (e.g., "whitelist_manager").
        detection_rule: Detection rule name.

    Returns:
        Dict with keys:
        - success: bool — True if save succeeded
        - message: str — Human-readable status message
        - error: str — Error description if success=False
        - data: dict — On success: {removed_row_count, added_row_count, edited_row_count, new_version}
        - diff: dict — The computed diff (for debugging/logging)

    Raises:
        OSError: If file I/O fails (caught internally and returned in error field)
    """
    # Import here to avoid circular dependencies
    from wl_audit import post_audit_event, build_audit_event
    from wl_versions import snapshot_version

    removal_reasons = removal_reasons or []
    bulk_removal = bulk_removal or []
    column_removal_reasons = column_removal_reasons or []

    try:
        # Read BEFORE state
        old_headers, old_rows = read_csv(csv_path)
        if not new_headers:
            new_headers = old_headers

        # Enforce reorder-only: discard cell edits when reorder is present
        if row_reorder or column_reorder:
            clean_rows = [dict(r) for r in old_rows]
            if row_reorder and isinstance(row_reorder, dict):
                fr = row_reorder.get("from_position")
                to = row_reorder.get("to_position")
                if (isinstance(fr, int) and isinstance(to, int)
                        and 1 <= fr <= len(clean_rows)
                        and 1 <= to <= len(clean_rows)):
                    moved = clean_rows.pop(fr - 1)
                    clean_rows.insert(to - 1, moved)
            if column_reorder and isinstance(column_reorder, dict):
                col = column_reorder.get("column", "")
                fr = column_reorder.get("from_position")
                to = column_reorder.get("to_position")
                if (col and isinstance(fr, int) and isinstance(to, int)
                        and col in old_headers):
                    new_headers = list(old_headers)
                    actual_idx = new_headers.index(col)
                    new_headers.pop(actual_idx)
                    vis = [h for h in new_headers if not h.startswith("_")]
                    target_col = None
                    if 1 <= to <= len(vis):
                        target_col = vis[to - 1]
                    if target_col:
                        ins_idx = new_headers.index(target_col)
                        if fr < to:
                            new_headers.insert(ins_idx + 1, col)
                        else:
                            new_headers.insert(ins_idx, col)
                    else:
                        new_headers.append(col)
            new_rows = clean_rows

        # Compute diff
        diff = compute_diff(old_headers, old_rows, new_headers, new_rows)

        # Filter out rename-paired columns from add/remove diff results
        if column_renames:
            rename_old = {r["old_name"] for r in column_renames}
            rename_new = {r["new_name"] for r in column_renames}
            diff["removed_columns"] = [c for c in diff["removed_columns"] if c not in rename_old]
            diff["added_columns"] = [c for c in diff["added_columns"] if c not in rename_new]

        has_row_changes = diff["added_count"] > 0 or diff["removed_count"] > 0 or diff["edited_count"] > 0
        has_col_changes = bool(diff.get("added_columns")) or bool(diff.get("removed_columns"))
        has_rename = bool(column_renames)
        has_reorder = bool(row_reorder) or bool(column_reorder)
        if not has_row_changes and not has_col_changes and not has_rename and not has_reorder:
            # Even with no changes, update the expected hash so the FIM
            # watcher has a baseline for this CSV (handles bootstrapping
            # on first save attempt after fresh install).
            try:
                update_csv_expected_hash(csv_path)
            except Exception:
                pass
            return {
                "success": True,
                "message": "No changes detected",
                "error": "",
                "data": {
                    "removed_row_count": 0,
                    "added_row_count": 0,
                    "edited_row_count": 0,
                    "new_version": None,
                },
                "diff": diff,
            }

        # Stamp row-level history on newly added rows
        ts_now = str(int(datetime.now(timezone.utc).timestamp()))
        added_ids = {id(entry) for entry in diff["added"]}
        for row in new_rows:
            if id(row) in added_ids:
                row["_added_by"] = analyst
                row["_added_at"] = ts_now

        # Ensure metadata columns in header
        write_headers = list(new_headers)
        for meta in ("_added_by", "_added_at"):
            if meta not in write_headers:
                write_headers.append(meta)

        # Write CSV file
        write_csv(csv_path, write_headers, new_rows)

        # Snapshot version
        new_version = None
        try:
            new_version, _ = snapshot_version(csv_path, analyst, action_label="save")
        except OSError as exc:
            # Log warning but don't fail the save — version snapshot is optional
            pass

        # Build audit events
        ts = int(datetime.now(timezone.utc).timestamp())
        summary_comment = comment
        if has_comment_col and (not comment or comment == "__per_row__"):
            summary_comment = "See per-row comments"

        common = {
            "timestamp": ts,
            "analyst": analyst,
            "detection_rule": detection_rule,
            "csv_file": csv_file,
            "app_context": app_context,
            "comment": summary_comment,
        }

        def _clean_entry(row):
            return {k: v for k, v in row.items() if not k.startswith("_")}

        def _build_row_fields(entries, row_num_map):
            lines = []
            for entry in entries:
                row_num = row_num_map.get(id(entry), 0)
                cleaned = _clean_entry(entry)
                for col_name, col_val in sorted(cleaned.items()):
                    field_name = "{}_row_{}".format(col_name, row_num)
                    lines.append("{}: {}".format(field_name, col_val))
            return lines

        # Map added rows to positions in new_rows
        new_row_id_to_pos = {id(row): i + 1 for i, row in enumerate(new_rows)}
        added_row_map = {}
        for entry in diff["added"]:
            pos = new_row_id_to_pos.get(id(entry))
            if pos is not None:
                added_row_map[id(entry)] = pos

        # Post "added" audit event
        if diff["added_count"] > 0:
            added_values = _build_row_fields(diff["added"], added_row_map)
            evt = dict(common, **{
                "action": "row_added",
                "added_row_count": diff["added_count"],
                "value": added_values,
                "row_add_reason": explicit_row_add_reason or summary_comment,
                "added_by": analyst,
                "added_at": ts,
            })
            post_audit_event(session_key, evt)

        # Map removed rows to positions in old_rows
        old_row_id_to_pos = {id(row): i + 1 for i, row in enumerate(old_rows)}
        def _removed_row_map(removed_entries):
            rmap = {}
            for entry in removed_entries:
                pos = old_row_id_to_pos.get(id(entry))
                if pos is not None:
                    rmap[id(entry)] = pos
            return rmap

        # Post removal audit events
        if bulk_removal and diff["removed_count"] > 0:
            bulk_reason = bulk_removal[0].get("reason", "") if bulk_removal else ""
            removed_values = _build_row_fields(
                diff["removed"], _removed_row_map(diff["removed"])
            )
            evt = dict(common, **{
                "action": "row_removed_multiple" if diff["removed_count"] > 1 else "row_removed",
                "removed_row_count": diff["removed_count"],
                "value": removed_values,
                "row_remove_reason": bulk_reason,
                "removed_by": analyst,
                "removed_at": ts,
            })
            post_audit_event(session_key, evt)
        elif diff["removed_count"] > 0:
            single_reason = ""
            for rr in removal_reasons:
                single_reason = rr.get("reason", "")

            removed_values = _build_row_fields(
                diff["removed"], _removed_row_map(diff["removed"])
            )
            evt = dict(common, **{
                "action": "row_removed",
                "removed_row_count": diff["removed_count"],
                "value": removed_values,
                "row_remove_reason": single_reason,
                "removed_by": analyst,
                "removed_at": ts,
            })
            post_audit_event(session_key, evt)

        # Post "edited" audit event
        if diff["edited_count"] > 0:
            edit_value_lines = []
            edit_details = {}
            for edit_entry in diff["edited"]:
                rn = edit_entry["row_num"]
                for change in edit_entry["changed_fields"]:
                    field = change["field"]
                    before_key = "{}_row_{}_before".format(field, rn)
                    after_key = "{}_row_{}_after".format(field, rn)
                    edit_details[before_key] = change["before"]
                    edit_details[after_key] = change["after"]
                    edit_value_lines.append("{}: {}".format(before_key, change["before"]))
                    edit_value_lines.append("{}: {}".format(after_key, change["after"]))

            edit_comment = summary_comment
            if (bulk_removal or removal_reasons) and diff["removed_count"] > 0:
                edit_comment = "Edited alongside removal"

            evt = dict(common, **{
                "action": "row_edited",
                "edited_row_count": diff["edited_count"],
                "value": edit_value_lines,
                "row_edit_reason": edit_comment,
                "edited_by": analyst,
                "edited_at": ts,
            })
            post_audit_event(session_key, evt)

        # Post column removal audit event
        if diff.get("removed_columns"):
            col_reason = ""
            for cr in column_removal_reasons:
                if cr.get("column") in diff["removed_columns"]:
                    col_reason = cr.get("reason", "")
                    break

            value_lines = []
            for col in diff["removed_columns"]:
                for i, row in enumerate(old_rows):
                    cell = row.get(col, "")
                    if cell:
                        value_lines.append("{}_row_{}: {}".format(col, i + 1, cell))

            evt = dict(common, **{
                "action": "column_removed",
                "column_count": len(diff["removed_columns"]),
                "columns": diff["removed_columns"],
                "value": value_lines,
                "column_remove_reason": col_reason,
                "changed_by": analyst,
                "changed_at": ts,
            })
            post_audit_event(session_key, evt)

        # Post column addition audit event
        if diff.get("added_columns"):
            evt = dict(common, **{
                "action": "column_added",
                "column_count": len(diff["added_columns"]),
                "columns": diff["added_columns"],
                "value": ["column: " + c for c in diff["added_columns"]],
                "changed_by": analyst,
                "changed_at": ts,
            })
            post_audit_event(session_key, evt)

        # Post column rename audit events
        if column_renames:
            for cr in column_renames:
                evt = dict(common, **{
                    "action": "column_renamed",
                    "column_renamed_before": cr["old_name"],
                    "column_renamed_after": cr["new_name"],
                    "column_count": 1,
                    "value": [cr["old_name"] + " -> " + cr["new_name"]],
                    "changed_by": analyst,
                    "changed_at": ts,
                })
                post_audit_event(session_key, evt)

        # Post row reorder audit event
        if row_reorder and isinstance(row_reorder, dict):
            evt = dict(common, **{
                "action": "row_reordered",
                "row_number_before": row_reorder.get("from_position"),
                "row_number_after": row_reorder.get("to_position"),
                "reordered_by": analyst,
                "reordered_at": ts,
            })
            post_audit_event(session_key, evt)

        # Post column reorder audit event
        if column_reorder and isinstance(column_reorder, dict):
            evt = dict(common, **{
                "action": "column_reordered",
                "column_name": column_reorder.get("column"),
                "column_number_before": column_reorder.get("from_position"),
                "column_number_after": column_reorder.get("to_position"),
                "reordered_by": analyst,
                "reordered_at": ts,
            })
            post_audit_event(session_key, evt)

        # Return success
        return {
            "success": True,
            "message": "CSV saved successfully",
            "error": "",
            "data": {
                "removed_row_count": diff["removed_count"],
                "added_row_count": diff["added_count"],
                "edited_row_count": diff["edited_count"],
                "new_version": new_version,
            },
            "diff": diff,
        }

    except OSError as exc:
        _logger.error("Failed to save CSV: %s", exc, exc_info=True)
        return {
            "success": False,
            "message": "",
            "error": "Failed to save CSV. Check server logs for details.",
            "data": {},
            "diff": {},
        }
    except Exception as exc:
        _logger.error("Unexpected error during save: %s", exc, exc_info=True)
        return {
            "success": False,
            "message": "",
            "error": "Unexpected error during save. Check server logs for details.",
            "data": {},
            "diff": {},
        }


def create_csv_pipeline(
    csv_path: str,
    headers: List[str],
    initial_rows: List[Dict[str, str]],
    analyst: str,
    session_key: str,
    csv_file: str = "",
    app_context: str = "",
    detection_rule: str = "",
) -> Dict[str, Any]:
    """
    Execute the CSV creation pipeline: create file with headers/rows, snapshot, audit.

    Creates a new CSV file with provided headers and initial rows, creates an
    initial version snapshot, and posts an audit event with full metadata.

    The handler retains responsibility for:
    - Validation of headers, rows, rule name, CSV filename
    - Approval gates and limits
    - RBAC (who can create CSVs)
    - Duplicate detection (rule already exists, CSV already exists)
    - Mapping file updates
    - Rules registry cleanup

    Args:
        csv_path: Absolute filesystem path to CSV file.
        headers: List of column names for the CSV.
        initial_rows: List of dicts (initial row data to populate CSV).
        analyst: Username of the analyst creating the file.
        session_key: Splunk session key for REST API calls.
        csv_file: Short name of CSV file (for audit events).
        app_context: App context (e.g., "whitelist_manager").
        detection_rule: Detection rule name.

    Returns:
        Dict with keys:
        - success: bool — True if creation succeeded
        - message: str — Human-readable status message
        - error: str — Error description if success=False
        - data: dict — On success: {new_version, column_count, imported_row_count}
    """
    from wl_audit import build_audit_event, post_audit_event
    from wl_versions import snapshot_version

    try:
        # Create CSV file with headers and initial rows
        write_csv(csv_path, headers, initial_rows)

        # Snapshot initial version
        new_version = None
        try:
            new_version, _ = snapshot_version(csv_path, analyst, action_label="created")
        except OSError:
            pass

        # Build and post audit event with full metadata
        evt = build_audit_event(
            action="csv_created",
            analyst=analyst,
            detection_rule=detection_rule,
            csv_file=csv_file,
            app_context=app_context,
            status="created",
            column_count=len(headers),
            columns=headers,
            imported_row_count=len(initial_rows),
        )
        post_audit_event(session_key, evt)

        return {
            "success": True,
            "message": "CSV created with {} column(s)".format(len(headers)),
            "error": "",
            "data": {
                "new_version": new_version,
                "column_count": len(headers),
                "imported_row_count": len(initial_rows),
            },
        }

    except OSError as exc:
        _logger.error("Failed to create CSV: %s", exc, exc_info=True)
        return {
            "success": False,
            "message": "",
            "error": "Failed to create CSV. Check server logs for details.",
            "data": {},
        }
    except Exception as exc:
        _logger.error("Unexpected error during creation: %s", exc, exc_info=True)
        return {
            "success": False,
            "message": "",
            "error": "Unexpected error during creation. Check server logs for details.",
            "data": {},
        }
