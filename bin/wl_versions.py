"""
Version snapshot and manifest management for CSV files.

Provides functions to create timestamped snapshots of CSV files, maintain
version manifests, and retrieve version lists for revert operations.
"""

import sys
import os
import json
import shutil
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple, Any, Optional
from contextlib import contextmanager

# Handle Splunk bin/ import limitations
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from wl_constants import MAX_VERSIONS, VERSIONS_DIR
from wl_csv import read_csv, write_csv, compute_diff

__all__ = [
    'get_versions_dir',
    'read_version_manifest',
    'write_version_manifest',
    'snapshot_version',
    'get_versions_list',
    'revert_csv_pipeline',
]

# Try to import fcntl for file locking (Unix-like systems)
try:
    import fcntl
except ImportError:
    fcntl = None


def get_versions_dir(csv_path: str) -> str:
    """
    Get the _versions/ directory path for a CSV file.

    Creates the directory if it does not exist.

    Args:
        csv_path: Absolute path to the CSV file

    Returns:
        Absolute path to the _versions/ subdirectory
    """
    parent = os.path.dirname(csv_path)
    versions_dir = os.path.join(parent, VERSIONS_DIR)
    os.makedirs(versions_dir, exist_ok=True)
    return versions_dir


def _get_version_manifest_path(csv_path: str) -> str:
    """
    Get the path to the version manifest JSON file for a CSV.

    Args:
        csv_path: Absolute path to the CSV file

    Returns:
        Absolute path to the manifest JSON file
    """
    base = os.path.splitext(os.path.basename(csv_path))[0]
    versions_dir = get_versions_dir(csv_path)
    return os.path.join(versions_dir, base + "_versions.json")


def read_version_manifest(csv_path: str) -> Tuple[Dict, str]:
    """
    Read the version manifest for a CSV file.

    Manifest structure:
    {
        "csv_file": "DR102_whitelist.csv",
        "current_version": "20260331_203045",
        "versions": {
            "20260331_203045": {
                "timestamp": "2026-03-31T20:30:45Z",
                "display": "31-03-2026 20:30:45",
                "filename": "DR102_whitelist_20260331_203045.csv",
                "analyst": "admin",
                "action": "save",
                "row_count": 42,
                "col_count": 5
            }
        }
    }

    Args:
        csv_path: Absolute path to the CSV file

    Returns:
        Tuple of (manifest_dict, error_string). On success: (manifest, "").
        On error: ({}, error_message)
    """
    manifest_path = _get_version_manifest_path(csv_path)
    if not os.path.isfile(manifest_path):
        return {}, ""

    try:
        with open(manifest_path, "r", encoding="utf-8") as fh:
            manifest = json.load(fh)
        # Schema-tolerant normalization. Three formats have existed
        # in the wild:
        #   1. bare list of entries (legacy, pre-versioning rewrite)
        #   2. dict with "versions" as a list (current, what writers
        #      produce)
        #   3. dict with "versions" as a dict-of-dicts (docstring
        #      describes this; never actually shipped)
        # Downstream code expects #2. Coerce #1 → #2 here so the
        # revert path doesn't crash on
        # `'list' object has no attribute 'get'` when reading a
        # legacy-format manifest. R2-D5-F1.
        if isinstance(manifest, list):
            manifest = {"versions": manifest}
        elif not isinstance(manifest, dict):
            return {}, "Invalid manifest: expected list or dict"
        return manifest, ""
    except json.JSONDecodeError as e:
        return {}, f"Invalid JSON in manifest: {str(e)}"
    except OSError as e:
        return {}, f"Failed to read manifest: {str(e)}"


def write_version_manifest(csv_path: str, manifest: Dict) -> Tuple[bool, str]:
    """
    Write the version manifest to disk atomically.

    Uses file locking on Unix-like systems to prevent corruption.

    Args:
        csv_path: Absolute path to the CSV file
        manifest: Manifest dictionary to write

    Returns:
        Tuple of (success, error_string). On success: (True, "").
        On error: (False, error_message)
    """
    manifest_path = _get_version_manifest_path(csv_path)

    try:
        with open(manifest_path, "w", encoding="utf-8") as fh:
            if fcntl:
                try:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except (IOError, OSError):
                    fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                json.dump(manifest, fh, indent=2)
            finally:
                if fcntl:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        return True, ""
    except OSError as e:
        return False, f"Failed to write manifest: {str(e)}"
    except Exception as e:
        return False, f"Unexpected error writing manifest: {str(e)}"


@contextmanager
def _csv_file_lock(csv_path: str):
    """
    Acquire an exclusive lock on a CSV file for the read-modify-write cycle.

    Uses a separate .lock file next to the CSV to avoid interfering with readers.
    On Windows (no fcntl), this is a no-op — optimistic locking still provides protection.

    Args:
        csv_path: Absolute path to the CSV file

    Yields:
        None (context manager)
    """
    if not fcntl:
        yield
        return

    lock_path = csv_path + ".lock"
    fh = open(lock_path, "w")  # noqa: SIM115
    try:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (IOError, OSError):
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        try:
            fh.close()
        except Exception:
            pass
        try:
            os.remove(lock_path)
        except OSError:
            pass


def snapshot_version(csv_path: str, analyst: str, action_label: str = "save") -> Tuple[str, str]:
    """
    Create a timestamped snapshot of a CSV file and update the manifest.

    Steps:
    1. Read current CSV
    2. Generate timestamp ID (format: "%Y%m%d_%H%M%S")
    3. Create snapshot file: {versions_dir}/{csv_name}_{timestamp_id}.csv
    4. Write snapshot to disk
    5. Update manifest with version entry
    6. Enforce MAX_VERSIONS limit (delete oldest snapshots)
    7. Write updated manifest

    Args:
        csv_path: Absolute path to the CSV file
        analyst: Username of analyst creating the snapshot
        action_label: Action label for the version (e.g., "save", "revert")

    Returns:
        Tuple of (timestamp_id, error_string). On success: (timestamp_id, "").
        On error: ("", error_message)
    """
    # Acquire lock for read-modify-write cycle
    with _csv_file_lock(csv_path):
        try:
            # Read current CSV
            headers, rows = read_csv(csv_path)
        except Exception as e:
            return "", f"Failed to read CSV: {str(e)}"

        now = datetime.now(timezone.utc)
        ts_file = now.strftime("%Y%m%d_%H%M%S")
        ts_display = now.strftime("%d-%m-%Y %H:%M:%S")
        ts_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")

        base = os.path.splitext(os.path.basename(csv_path))[0]
        versions_dir = get_versions_dir(csv_path)
        snapshot_name = f"{base}_{ts_file}.csv"
        snapshot_path = os.path.join(versions_dir, snapshot_name)

        # Prevent filename collision when two snapshots happen in the same second
        if os.path.exists(snapshot_path):
            ts_file_ms = now.strftime("%Y%m%d_%H%M%S_") + str(now.microsecond // 1000)
            snapshot_name = f"{base}_{ts_file_ms}.csv"
            snapshot_path = os.path.join(versions_dir, snapshot_name)

        # Write snapshot to disk
        try:
            write_csv(snapshot_path, headers, rows)
        except Exception as e:
            return "", f"Failed to write snapshot: {str(e)}"

        # Count rows and visible columns in the snapshot
        row_count = len(rows)
        col_count = len([h for h in headers if not h.startswith("_")])

        # Read current manifest
        manifest, error = read_version_manifest(csv_path)
        if error and manifest == {}:
            # If we can't read the manifest, start fresh
            manifest = {"versions": []}

        # Ensure structure
        if not isinstance(manifest, dict):
            manifest = {"versions": []}
        if "versions" not in manifest:
            manifest["versions"] = []

        # Append new version entry
        version_entry = {
            "timestamp": ts_iso,
            "display": ts_display,
            "filename": snapshot_name,
            "analyst": analyst,
            "action": action_label,
            "row_count": row_count,
            "col_count": col_count,
        }
        manifest["versions"].append(version_entry)

        # Keep only the last MAX_VERSIONS entries
        while len(manifest.get("versions", [])) > MAX_VERSIONS:
            oldest = manifest["versions"].pop(0)
            old_path = os.path.join(versions_dir, oldest.get("filename", ""))
            try:
                os.remove(old_path)
            except OSError:
                pass

        # Write updated manifest
        success, error = write_version_manifest(csv_path, manifest)
        if not success:
            return "", error

        return ts_file, ""


def get_versions_list(csv_path: str) -> Tuple[List[Dict], str]:
    """
    Get list of all versions for a CSV file, sorted newest-first.

    Each item in the list:
    {
        "version_id": "20260331_203045",
        "timestamp": "2026-03-31T20:30:45Z",
        "display": "31-03-2026 20:30:45",
        "analyst": "admin",
        "action": "save",
        "row_count": 42,
        "col_count": 5
    }

    Args:
        csv_path: Absolute path to the CSV file

    Returns:
        Tuple of (versions_list, error_string). On success: (list, "").
        On error: ([], error_message)
    """
    manifest, error = read_version_manifest(csv_path)
    if error and manifest == {}:
        return [], error

    if not manifest or "versions" not in manifest:
        return [], ""

    versions = manifest.get("versions", [])
    if not isinstance(versions, list):
        return [], "Invalid versions list in manifest"

    # Build list with version_id (timestamp from filename)
    result = []
    for entry in versions:
        filename = entry.get("filename", "")
        # Extract timestamp from filename: "DR102_whitelist_20260331_203045.csv"
        # Timestamp format is: _YYYYMMDD_HHMMSS (or _YYYYMMDD_HHMMSS_mmm for collisions)
        # Remove .csv extension first
        if filename.endswith(".csv"):
            name_without_ext = filename[:-4]
        else:
            name_without_ext = filename

        # Extract the rightmost timestamp part (after the last underscore that starts a timestamp)
        # Timestamp always starts with 8 digits (YYYYMMDD) followed by underscore and 6 digits (HHMMSS)
        # Could also have _mmm suffix for milliseconds
        match = re.search(r'_(\d{8}_\d{6}(?:_\d+)?)$', name_without_ext)
        if match:
            version_id = match.group(1)
        else:
            version_id = ""

        result.append({
            "version_id": version_id,
            "timestamp": entry.get("timestamp", ""),
            "display": entry.get("display", ""),
            "analyst": entry.get("analyst", ""),
            "action": entry.get("action", ""),
            "row_count": entry.get("row_count", 0),
            "col_count": entry.get("col_count", 0),
        })

    # Sort newest-first (reverse chronological order)
    result.sort(key=lambda x: x["timestamp"], reverse=True)

    return result, ""


# ═══════════════════════════════════════════════════════════════════════════
# Revert pipeline — extracted from handler
# ═══════════════════════════════════════════════════════════════════════════

def revert_csv_pipeline(
    csv_path: str,
    version_filename: str,
    version_display: str,
    revert_reason: str,
    analyst: str,
    session_key: str,
    csv_file: str = "",
    app_context: str = "",
    detection_rule: str = "",
) -> Dict[str, Any]:
    """
    Execute the complete revert operation for a CSV: restore from snapshot,
    compute diff with *back fields, audit, and create new snapshot.

    This pipeline contains the core business logic for reverting a CSV file:
    1. Read current CSV (BEFORE state)
    2. Read the version to revert to (NEW state)
    3. Compute diff (what changed between current and reverted version)
    4. Overwrite CSV with reverted version content
    5. Remove the source version from manifest
    6. Create a new snapshot (becomes the new current version)
    7. Build and post revert audit event with *back suffix fields
    8. Return structured result

    The handler retains responsibility for:
    - Optimistic locking (mtime checking)
    - Approval gates and limits (decision logic)
    - RBAC (who can revert)
    - Version existence checks

    Args:
        csv_path: Absolute filesystem path to CSV file.
        version_filename: Filename of the version to revert to (e.g., "DR102_whitelist_20260331_203045.csv").
        version_display: Display string for the version (e.g., "31-03-2026 12:37:16 (42 rows, by admin)").
        revert_reason: Human-readable reason for the revert.
        analyst: Username of the analyst performing the revert.
        session_key: Splunk session key for REST API calls.
        csv_file: Short name of CSV file (for audit events, e.g., "DR102_whitelist.csv").
        app_context: App context (e.g., "whitelist_manager").
        detection_rule: Detection rule name.

    Returns:
        Dict with keys:
        - success: bool — True if revert succeeded
        - message: str — Human-readable status message
        - error: str — Error description if success=False
        - data: dict — On success: {
                reverted_from_version: str (display of version before revert),
                reverted_to_version: str (display of version selected),
                new_version: str (timestamp of new snapshot),
                restoredback_row_count: int,
                removedback_row_count: int,
                editedback_row_count: int,
            }
        - diff: dict — The computed diff (for debugging/logging)
    """
    from wl_audit import post_audit_event

    try:
        # Read BEFORE state (current CSV)
        old_headers, old_rows = read_csv(csv_path)

        # Locate and read the version file
        versions_dir = get_versions_dir(csv_path)
        version_path = os.path.join(versions_dir, version_filename)
        if not os.path.isfile(version_path):
            return {
                "success": False,
                "message": "",
                "error": "Version file not found: {}".format(version_filename),
                "data": {},
                "diff": {},
            }

        new_headers, new_rows = read_csv(version_path)

        # Compute diff between current and reverted version
        diff = compute_diff(old_headers, old_rows, new_headers, new_rows)

        # Overwrite CSV with reverted version content
        write_csv(csv_path, new_headers, new_rows)

        # Get current version display before modifying manifest
        current_version_display = ""
        try:
            manifest, _ = read_version_manifest(csv_path)
            if manifest:
                versions_list = manifest.get("versions", [])
                if versions_list:
                    current_version_display = versions_list[-1].get("display", "")
        except OSError:
            pass

        # Remove the source version from manifest
        # (it will be replaced by the revert snapshot, avoiding duplicates)
        try:
            manifest, _ = read_version_manifest(csv_path)
            updated_versions = []
            for entry in manifest.get("versions", []):
                if entry.get("filename") == version_filename:
                    old_path = os.path.join(versions_dir, entry["filename"])
                    try:
                        os.remove(old_path)
                    except OSError:
                        pass
                else:
                    updated_versions.append(entry)
            manifest["versions"] = updated_versions
            _, _ = write_version_manifest(csv_path, manifest)
        except OSError:
            pass  # Non-fatal — proceed with revert even if manifest update fails

        # Snapshot the revert (becomes the new current version)
        new_record_version = ""
        try:
            new_version, _ = snapshot_version(csv_path, analyst, action_label="revert")
            # Get the display string for the new version
            manifest, _ = read_version_manifest(csv_path)
            if manifest:
                versions_list = manifest.get("versions", [])
                if versions_list:
                    new_record_version = versions_list[-1].get("display", "")
        except OSError:
            pass  # Non-fatal — revert succeeded, just can't snapshot

        # Build audit event with *back suffix fields
        ts = int(datetime.now(timezone.utc).timestamp())
        value_lines = []

        # Helper: helper for visible-key matching
        vis_hdrs = [h for h in (new_headers or old_headers) if not h.startswith("_")]

        def _vis_key(row):
            return tuple(row.get(h, "") for h in vis_hdrs)

        # Map restored (added) rows to positions in new_rows
        # diff entries are same objects as in new_rows/old_rows, so use id()
        rev_new_id_to_pos = {id(r): i + 1 for i, r in enumerate(new_rows)}
        for entry in diff.get("added", []):
            row_num = rev_new_id_to_pos.get(id(entry), 0)
            cleaned = {k: v for k, v in entry.items() if not k.startswith("_")}
            for col, val in sorted(cleaned.items()):
                value_lines.append("restoredback_{}_row_{}: {}".format(col, row_num, val))

        # Map reverted-away (removed) rows to positions in old_rows
        rev_old_id_to_pos = {id(r): i + 1 for i, r in enumerate(old_rows)}
        for entry in diff.get("removed", []):
            row_num = rev_old_id_to_pos.get(id(entry), 0)
            cleaned = {k: v for k, v in entry.items() if not k.startswith("_")}
            for col, val in sorted(cleaned.items()):
                value_lines.append("removedback_{}_row_{}: {}".format(col, row_num, val))

        # Edited rows: show field changes
        for entry in diff.get("edited", []):
            old_rn = entry.get("old_row_num", 0)
            new_rn = entry.get("row_num", 0)
            row_label = "{}_{}".format(old_rn, new_rn) if old_rn != new_rn else str(new_rn)
            for chg in entry.get("changed_fields", []):
                value_lines.append("changedback_{}_row_{}: {} -> {}".format(
                    chg["field"], row_label, chg["before"], chg["after"]))

        # Detect row position changes
        old_key_positions = {}
        for idx, r in enumerate(old_rows):
            k = _vis_key(r)
            old_key_positions.setdefault(k, []).append(idx + 1)

        new_key_positions = {}
        for idx, r in enumerate(new_rows):
            k = _vis_key(r)
            new_key_positions.setdefault(k, []).append(idx + 1)

        moveback_rows = []
        for k in old_key_positions:
            if k not in new_key_positions:
                continue
            old_pos_list = old_key_positions[k]
            new_pos_list = new_key_positions[k]
            for i in range(min(len(old_pos_list), len(new_pos_list))):
                if old_pos_list[i] != new_pos_list[i]:
                    row_id = ", ".join("{}={}".format(vis_hdrs[j], k[j])
                                       for j in range(min(2, len(vis_hdrs)))
                                       if j < len(k) and k[j])
                    moveback_rows.append({
                        "row_id": row_id,
                        "before": old_pos_list[i],
                        "after": new_pos_list[i],
                    })

        for mr in moveback_rows:
            rn = mr["before"]
            value_lines.append("moveback_row_{}_number_before: {}".format(rn, rn))
            value_lines.append("moveback_row_{}_number_after: {}".format(rn, mr["after"]))
            if mr["row_id"]:
                value_lines.append("moveback_row_{}_id: {}".format(rn, mr["row_id"]))

        # Detect column position changes
        old_vis_cols = [h for h in old_headers if not h.startswith("_")]
        new_vis_cols = [h for h in new_headers if not h.startswith("_")]
        common_cols = set(old_vis_cols) & set(new_vis_cols)

        moveback_cols = []
        for col in common_cols:
            old_pos = old_vis_cols.index(col) + 1
            new_pos = new_vis_cols.index(col) + 1
            if old_pos != new_pos:
                moveback_cols.append({
                    "column": col,
                    "before": old_pos,
                    "after": new_pos,
                })

        moveback_cols.sort(key=lambda x: x["before"])
        for mc in moveback_cols:
            cn = mc["before"]
            value_lines.append("moveback_column_{}_name: {}".format(cn, mc["column"]))
            value_lines.append("moveback_column_{}_number_before: {}".format(cn, cn))
            value_lines.append("moveback_column_{}_number_after: {}".format(cn, mc["after"]))

        # Post revert audit event
        evt = {
            "timestamp": ts,
            "analyst": analyst,
            "detection_rule": detection_rule,
            "csv_file": csv_file,
            "app_context": app_context,
            "comment": revert_reason,
            "revert_reason": revert_reason,
            "action": "revert",
            "reverted_from_version": current_version_display,
            "reverted_to_version": version_display,
            "new_record_version": new_record_version,
            "row_count_before": len(old_rows),
            "row_count_after": len(new_rows),
            "restoredback_row_count": diff["added_count"],
            "removedback_row_count": diff["removed_count"],
            "editedback_row_count": diff["edited_count"],
            "restoredback_column_count": len(diff.get("added_columns", [])),
            "restoredback_column_name": diff.get("added_columns", []),
            "removedback_column_count": len(diff.get("removed_columns", [])),
            "removedback_column_name": diff.get("removed_columns", []),
            "moveback_row_count": len(moveback_rows),
            "moveback_column_count": len(moveback_cols),
            "value": value_lines,
            "reverted_by": analyst,
            "reverted_at": ts,
        }
        post_audit_event(session_key, evt)

        # Return success
        return {
            "success": True,
            "message": "CSV reverted successfully",
            "error": "",
            "data": {
                "reverted_from_version": current_version_display,
                "reverted_to_version": version_display,
                "new_version": new_record_version,
                "restoredback_row_count": diff["added_count"],
                "removedback_row_count": diff["removed_count"],
                "editedback_row_count": diff["edited_count"],
            },
            "diff": diff,
        }

    except OSError as exc:
        return {
            "success": False,
            "message": "",
            "error": "Failed to revert CSV: {}".format(str(exc)),
            "data": {},
            "diff": {},
        }
    except Exception as exc:
        return {
            "success": False,
            "message": "",
            "error": "Unexpected error during revert: {}".format(str(exc)),
            "data": {},
            "diff": {},
        }
