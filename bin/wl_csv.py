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
import json
import os
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple, Optional, Any

from wl_constants import (
    OWN_LOOKUPS, MAX_ROWS, MAX_COLUMNS, MAX_CELL_CHARS, MAX_DIFF_ROWS,
    DETECTION_RULES_FILE, VERSIONS_DIR,
    EXPIRE_COLUMN_NAMES,
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


def write_csv(filepath: str, headers: List[str], rows: List[Dict[str, str]]) -> None:
    """
    Write a CSV file atomically (write to temp, then rename).

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


# ═══════════════════════════════════════════════════════════════════════════
# Diff computation
# ═══════════════════════════════════════════════════════════════════════════

def compute_diff(
    old_headers: List[str],
    old_rows: List[Dict[str, str]],
    new_headers: List[str],
    new_rows: List[Dict[str, str]],
) -> Dict[str, Any]:
    """
    Compare old vs new CSV content and return a structured diff.

    Uses similarity-based matching for edit detection:
    - Identifies rows that are purely added or removed
    - Pairs removed rows with added rows if >50% of fields match (likely edits)
    - Uses Counter-based comparison to handle duplicate rows correctly
    - Skips expensive edit detection if either side exceeds MAX_DIFF_ROWS

    Args:
        old_headers: Original CSV column names.
        old_rows: Original CSV rows (list of dicts).
        new_headers: New CSV column names.
        new_rows: New CSV rows (list of dicts).

    Returns:
        Dict with keys:
        - added: List of new row dicts
        - removed: List of deleted row dicts
        - edited: List of dicts with keys {old_row, new_row, old_row_num, row_num, changed_fields}
        - added_count, removed_count, edited_count: Int counts
        - added_columns, removed_columns: List of column names added/removed
        - text_diff: List of unified-diff style lines (Git-style)
    """
    all_headers = list(dict.fromkeys(old_headers + new_headers))

    # Only compare visible (non-metadata) columns for diff detection.
    # Internal _ columns (_added_by, _added_at, _review_status) are
    # bookkeeping and should not trigger change events.
    visible_headers = [h for h in all_headers if not h.startswith("_")]

    # ── Detect column-level changes ─────────────────────────────
    old_vis = [h for h in old_headers if not h.startswith("_")]
    new_vis = [h for h in new_headers if not h.startswith("_")]
    old_vis_set = set(old_vis)
    new_vis_set = set(new_vis)
    removed_columns = [h for h in old_vis if h not in new_vis_set]
    added_columns = [h for h in new_vis if h not in old_vis_set]

    # Use only headers common to both old and new for row identity
    # matching and edit detection.  This prevents false "edited" events
    # when columns are added or removed (missing column defaults to ""
    # via .get(), causing every row key to mismatch).
    common_headers = [h for h in visible_headers
                      if h in old_vis_set and h in new_vis_set]

    def _row_key(row: Dict[str, str]) -> Tuple[str, ...]:
        return tuple(row.get(h, "") for h in common_headers)

    # Count-based (multiset) comparison so duplicate rows are handled
    # correctly.  A simple set loses count information: if old has 2
    # copies of key X and new has 4, the set approach sees X in both
    # and reports zero adds.  Counter-based logic detects the 2 extras.
    old_key_counts = Counter(_row_key(r) for r in old_rows)
    new_key_counts = Counter(_row_key(r) for r in new_rows)

    # Build added_raw: rows in new whose key count exceeds old's count.
    # Iterate in REVERSE because the frontend appends new rows at the end.
    # Forward iteration would pick pre-existing duplicates from the front
    # instead of the actually-new rows from the back.
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

    # Build removed_raw: rows in old whose key count exceeds new's count
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

    # ── Detect edits: similarity-based matching ─────────────────
    # A row is "edited" when most of its fields stay the same and
    # only a few change.  We pair removed_raw entries with added_raw
    # entries that share the most unchanged visible fields, requiring
    # at least half the fields to match (to avoid pairing completely
    # different rows that merely ended up at the same position).
    edited = []

    paired_old_ids = set()   # id() of paired old row objects
    paired_new_ids = set()   # id() of paired new row objects

    def _field_overlap(old_row: Dict[str, str], new_row: Dict[str, str]) -> Tuple[int, int, List[Dict[str, str]]]:
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

    # For each added row, find the best-matching removed row
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

                # Find 1-based positions in old_rows and new_rows
                old_pos = 0
                for idx_o, r in enumerate(old_rows):
                    if _row_key(r) == old_k:
                        old_pos = idx_o + 1
                        break
                new_pos = 0
                for idx_n, r in enumerate(new_rows):
                    if _row_key(r) == new_k:
                        new_pos = idx_n + 1
                        break

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

    # Text-based unified diff (like `git diff`)
    def _rows_to_lines(headers: List[str], rows: List[Dict[str, str]]) -> List[str]:
        lines = [",".join(headers)]
        for r in rows:
            lines.append(",".join(r.get(h, "") for h in headers))
        return lines

    # Use only visible headers for the text diff so metadata columns
    # don't pollute the human-readable output.
    import difflib
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
        "added_columns": added_columns,
        "removed_columns": removed_columns,
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
