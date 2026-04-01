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
from typing import Dict, List, Tuple
from contextlib import contextmanager

# Handle Splunk bin/ import limitations
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from wl_constants import MAX_VERSIONS, VERSIONS_DIR
from wl_csv import read_csv, write_csv

__all__ = [
    'get_versions_dir',
    'read_version_manifest',
    'write_version_manifest',
    'snapshot_version',
    'get_versions_list',
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
