"""
Whitelist Manager — Layer 3: Soft-Delete, Restore, and Purge Operations.

This module manages the trash system for CSVs and detection rules.
It implements soft-delete (trash items remain for a retention period before auto-purge),
restore (move items back from trash to their original locations),
and permanent purge (delete beyond recovery).

Features:
- Unique trash_id per soft-deleted item (deterministic: name + type + timestamp)
- Retention policy with automatic cleanup
- Edge case mitigation: overwrites duplicate trash entries, recomputes expiry from config
- No explicit locking (low contention; approval queue handles concurrent approvals)
"""

import json
import os
import csv
import shutil
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple, Optional

# Import sys.path setup from wl_handler pattern
import sys
sys.path.insert(0, os.path.dirname(__file__))

from wl_constants import (
    OWN_LOOKUPS, TRASH_DIR, TRASH_CONFIG_FILE,
    VERSIONS_DIR, DETECTION_RULES_FILE, MAPPING_FILE, DEFAULT_TRASH_RETENTION_DAYS
)
from wl_filelock import file_lock
from wl_rules import rules_rmw_lock
from wl_validation import sanitize_text, build_csv_path


__all__ = [
    'move_to_trash',
    'list_trash',
    'restore_from_trash',
    'restore_from_trash_pipeline',
    'purge_trash_item',
    'auto_cleanup_trash',
    'get_trash_dir',
    'read_trash_config',
    'write_trash_config',
    'trash_config_rmw_lock',
    # Refactored sub-functions (may be useful for testing)
    'build_trash_metadata',
    'move_csv_to_trash',
    'move_rule_to_trash',
    'restore_csv_from_trash',
    'restore_rule_from_trash',
]


def _safe_trash_item_dir(trash_id: str) -> Optional[str]:
    """Resolve trash_id to an item directory IFF it stays inside trash_dir.

    Defense-in-depth against `trash_id="../etc"` style traversal. Returns
    the resolved item directory path on success, or None when:
    - trash_id is empty / not a string
    - trash_id contains path separators or starts with '.'
    - the resolved path escapes trash_dir
    - the path doesn't exist as a directory

    Caller is responsible for handling the None case (e.g. returning
    "Trash item not found"). Centralized here so every trash op shares
    the same containment guarantee — see `purge_trash_item` and
    `restore_from_trash` which both feed user-supplied trash_id directly
    into `shutil.rmtree` / `os.path.join`.
    """
    if not trash_id or not isinstance(trash_id, str):
        return None
    # Reject path separators and dotfiles up front — os.path.basename
    # would silently strip the directory portion of "../etc" and let
    # the caller think the input was clean.
    if os.path.basename(trash_id) != trash_id:
        return None
    if trash_id.startswith("."):
        return None
    trash_dir = get_trash_dir()
    item_dir = os.path.realpath(os.path.join(trash_dir, trash_id))
    real_trash = os.path.realpath(trash_dir)
    # Containment check — covers the case where trash_id resolved
    # through a symlink to outside trash_dir.
    if not (item_dir == real_trash
            or item_dir.startswith(real_trash + os.sep)):
        return None
    if not os.path.isdir(item_dir):
        return None
    return item_dir


def get_trash_dir() -> str:
    """
    Return the absolute path to the trash directory.

    Creates the directory if it does not exist.

    Returns:
        str: Absolute path to the trash directory.
    """
    trash = os.path.join(OWN_LOOKUPS, TRASH_DIR)
    os.makedirs(trash, exist_ok=True)
    return trash


def read_trash_config() -> Dict:
    """
    Read the trash configuration JSON file.

    The config file stores settings like retention_days.
    Returns a default config dict if the file is missing or invalid.

    Returns:
        Dict: Configuration dict with at least 'retention_days' key.
    """
    path = os.path.join(OWN_LOOKUPS, VERSIONS_DIR, TRASH_CONFIG_FILE)
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
                if isinstance(data, dict):
                    return data
        except (json.JSONDecodeError, OSError):
            pass
    return {"retention_days": DEFAULT_TRASH_RETENTION_DAYS}


def write_trash_config(config: Dict) -> None:
    """
    Write the trash configuration JSON file.

    Atomically writes the config by creating the directory if needed
    and writing to disk.

    Args:
        config: Configuration dict to write (must include 'retention_days').

    Raises:
        OSError: If unable to write due to permissions or disk errors.
    """
    versions_dir = os.path.join(OWN_LOOKUPS, VERSIONS_DIR)
    os.makedirs(versions_dir, exist_ok=True)
    path = os.path.join(versions_dir, TRASH_CONFIG_FILE)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(config, fh, indent=2)


@contextmanager
def trash_config_rmw_lock(timeout: float = 5):
    """Cross-process RMW lock around the trash configuration file.

    Ring 6.1 Day 6.1.7a: callers that perform
    read_trash_config → modify → write_trash_config (e.g.
    ``_action_set_trash_retention`` in wl_handler.py) must hold this
    lock for the full cycle so two concurrent superadmins cannot
    clobber each other's edits.

    NOTE on path divergence (pre-existing, out of scope for 6.1.7a):
    ``read_trash_config`` and ``write_trash_config`` use
    ``OWN_LOOKUPS/VERSIONS_DIR/TRASH_CONFIG_FILE`` whereas
    ``wl_handler.py::_action_set_trash_retention`` and
    ``wl_handler.py::_action_get_trash_config`` use
    ``OWN_LOOKUPS/TRASH_CONFIG_FILE`` (no versions_dir). The lock
    used by the handler must therefore live alongside the
    handler's actual file path, not the wl_trash.py internal one.
    Caller passes the appropriate path; this helper just builds
    the sibling .rmw.lock.
    """
    os.makedirs(OWN_LOOKUPS, exist_ok=True)
    # Use the handler's flat-lookups path (where the live config
    # actually lives) so the lock guards the production RMW. When
    # the path divergence is fixed in a future ring, this lock and
    # the writer paths can be reunified.
    lock_path = os.path.join(OWN_LOOKUPS, TRASH_CONFIG_FILE) + ".rmw.lock"
    with file_lock(lock_path, timeout=timeout):
        yield


def build_trash_metadata(
    item_type: str,
    name: str,
    user: str,
    comment: str,
    app_context: str = "",
    version: str = "",
    detection_rule: str = "",
    associated_csvs: Optional[List[Dict]] = None,
    csv_path: Optional[str] = None,
    now: int = None,
) -> Dict:
    """
    Construct metadata dict for a trash item.

    Args:
        item_type: "csv" or "rule"
        name: CSV filename or rule name
        user: Username performing the delete action
        comment: Reason/comment for deletion
        app_context: Optional app context for CSV path resolution
        version: Optional version identifier (for CSV reverts)
        detection_rule: Optional detection rule name (for CSV context)
        associated_csvs: Optional list of {csv_file, app_context} dicts (for rule items)
        csv_path: Original CSV path (for CSV items)
        now: Timestamp (for testing; defaults to current time)

    Returns:
        Dict with item_type, name, deleted_by, deleted_at, comment, expiry_ts, etc.
    """
    if now is None:
        now = int(time.time())

    config = read_trash_config()
    retention_days = config.get("retention_days", DEFAULT_TRASH_RETENTION_DAYS)
    expiry_ts = now + (retention_days * 86400)

    metadata = {
        "item_type": item_type,
        "name": name,
        "deleted_by": user,
        "deleted_at": now,
        "deleted_at_human": time.strftime(
            "%Y-%m-%d %H:%M:%S UTC", time.gmtime(now)
        ),
        "comment": sanitize_text(comment) if comment else "",
        "expiry_ts": expiry_ts,
        "expiry_human": time.strftime(
            "%Y-%m-%d %H:%M:%S UTC", time.gmtime(expiry_ts)
        ),
        "retention_days": retention_days,
        "rule_name": detection_rule,
        "app_context": app_context,
    }

    if item_type == "csv" and csv_path:
        metadata["original_path"] = csv_path
    elif item_type == "rule":
        metadata["associated_csvs"] = associated_csvs or []

    return metadata


def _move_versions_for_csv(csv_name: str, item_dir: str) -> None:
    """
    Move version snapshots and manifest for a single CSV into item_dir.

    Args:
        csv_name: CSV filename (e.g., "DR999.csv")
        item_dir: Destination trash item directory
    """
    versions_src = os.path.join(OWN_LOOKUPS, VERSIONS_DIR)
    base = csv_name.replace(".csv", "")
    manifest_name = "{}_versions.json".format(base)
    manifest_path = os.path.join(versions_src, manifest_name)

    if not os.path.isfile(manifest_path):
        return

    # Move manifest
    shutil.move(manifest_path, os.path.join(item_dir, manifest_name))

    # Move snapshot CSV files
    try:
        with open(os.path.join(item_dir, manifest_name), "r", encoding="utf-8") as fh:
            manifest = json.load(fh)
        # Manifest can be a list (array) or dict with "versions" key
        ver_list = manifest if isinstance(manifest, list) else manifest.get("versions", [])
        for ver in ver_list:
            vf = ver.get("filename", "")
            vf_path = os.path.join(versions_src, vf)
            if vf and os.path.isfile(vf_path):
                shutil.move(vf_path, os.path.join(item_dir, vf))
    except (json.JSONDecodeError, OSError):
        pass  # manifest unreadable — snapshot files lost


def move_csv_to_trash(
    name: str,
    app_context: str,
    item_dir: str,
) -> Optional[str]:
    """
    Move a CSV file and its version snapshots into trash item directory.

    Args:
        name: CSV filename (e.g., "DR999.csv")
        app_context: App context for path resolution
        item_dir: Destination trash item directory

    Returns:
        The CSV path if found and moved, None otherwise

    Raises:
        OSError: If file operations fail
    """
    csv_path = build_csv_path(name, app_context)
    if csv_path and os.path.isfile(csv_path):
        shutil.move(csv_path, os.path.join(item_dir, name))

    # Move version snapshots for this CSV
    _move_versions_for_csv(name, item_dir)

    return csv_path


def move_rule_to_trash(
    associated_csvs: Optional[List[Dict]],
    item_dir: str,
) -> None:
    """
    Move CSVs associated with a deleted rule into trash item directory.

    Args:
        associated_csvs: List of {csv_file, app_context} dicts
        item_dir: Destination trash item directory

    Raises:
        OSError: If file operations fail
    """
    for csv_info in (associated_csvs or []):
        csv_name = csv_info.get("csv_file", "")
        csv_app = csv_info.get("app_context", "")
        csv_path = build_csv_path(csv_name, csv_app)
        if csv_path and os.path.isfile(csv_path):
            shutil.move(csv_path, os.path.join(item_dir, csv_name))
        # Also move version snapshots for this CSV
        _move_versions_for_csv(csv_name, item_dir)


def move_to_trash(
    item_type: str,
    name: str,
    user: str,
    comment: str,
    app_context: str = "",
    version: str = "",
    detection_rule: str = "",
    associated_csvs: Optional[List[Dict]] = None,
) -> str:
    """
    Move a CSV file or detection rule to the trash directory.

    This creates a soft-delete entry with metadata and retains the item
    until the retention period expires. Duplicate entries (same name+type)
    are overwritten to prevent storage bloat from delete→restore→delete cycles.

    Args:
        item_type: Type of item being trashed: "csv" or "rule".
        name: CSV filename or rule name.
        user: Username performing the delete action.
        comment: Reason/comment for the deletion.
        app_context: Optional app context for CSV path resolution.
        version: Optional version identifier (for CSV reverts).
        detection_rule: Optional detection rule name (for CSV context).
        associated_csvs: Optional list of {csv_file, app_context} dicts (for rule items).

    Returns:
        str: Unique trash_id for the trashed item (deterministic: name__type__timestamp).

    Raises:
        OSError: If file operations fail (copy, move, or directory creation).
    """
    trash_dir = get_trash_dir()
    now = int(time.time())
    now_str = time.strftime("%Y%m%d_%H%M%S", time.gmtime(now))

    # EC3: Use a deterministic trash ID based on name + type
    # so repeated delete→restore→delete overwrites, not accumulates
    trash_id = "{}__{}_{}".format(name, item_type, now_str)

    # EC3: Remove any existing trash entry for this exact name+type
    for existing in os.listdir(trash_dir):
        if existing.startswith("{}__{}".format(name, item_type)):
            old_path = os.path.join(trash_dir, existing)
            if os.path.isdir(old_path):
                shutil.rmtree(old_path, ignore_errors=True)

    item_dir = os.path.join(trash_dir, trash_id)
    os.makedirs(item_dir, exist_ok=True)

    # Dispatch to type-specific handler
    csv_path = None
    if item_type == "csv":
        csv_path = move_csv_to_trash(name, app_context, item_dir)
    elif item_type == "rule":
        move_rule_to_trash(associated_csvs, item_dir)

    # Build and write metadata
    metadata = build_trash_metadata(
        item_type, name, user, comment, app_context, version, detection_rule,
        associated_csvs, csv_path, now
    )

    # Write metadata last (after all files are moved)
    with open(os.path.join(item_dir, "metadata.json"), "w", encoding="utf-8") as fh:
        json.dump(metadata, fh, indent=2)

    return trash_id


def list_trash() -> Tuple[List[Dict], str]:
    """
    List all items currently in the trash.

    Returns items sorted by deletion time (newest first).
    Recomputes expiry from current config to prevent tampering.

    Returns:
        Tuple[List[Dict], str]: (items_list, error_string).
                                items_list is empty if trash is empty.
                                error_string is empty if no error.
                                Each item includes: trash_id, item_type, name,
                                deleted_by, deleted_at, expiry_ts, days_remaining, etc.
    """
    try:
        trash_dir = get_trash_dir()
        config = read_trash_config()
        retention_days = config.get("retention_days", DEFAULT_TRASH_RETENTION_DAYS)
        items = []
        for entry_name in os.listdir(trash_dir):
            entry_path = os.path.join(trash_dir, entry_name)
            if not os.path.isdir(entry_path):
                continue
            meta_path = os.path.join(entry_path, "metadata.json")
            if not os.path.isfile(meta_path):
                continue
            try:
                with open(meta_path, "r", encoding="utf-8") as fh:
                    meta = json.load(fh)
                # EC8: Recompute expiry from current config
                deleted_at = meta.get("deleted_at", 0)
                meta["expiry_ts"] = deleted_at + (retention_days * 86400)
                meta["expiry_human"] = time.strftime(
                    "%Y-%m-%d %H:%M:%S UTC", time.gmtime(meta["expiry_ts"])
                )
                meta["trash_id"] = entry_name
                meta["days_remaining"] = max(
                    0, (meta["expiry_ts"] - int(time.time())) // 86400
                )
                items.append(meta)
            except (json.JSONDecodeError, OSError):
                continue
        items.sort(key=lambda x: x.get("deleted_at", 0), reverse=True)
        return items, ""
    except Exception as e:
        return [], str(e)


def _restore_mapping_for_csv(csv_name: str, app_ctx: str, rule_name: str) -> None:
    """
    Restore rule mapping and registry entry for a CSV.

    Helper function to reduce complexity in restore_csv_from_trash.

    Args:
        csv_name: CSV filename
        app_ctx: App context
        rule_name: Associated rule name
    """
    if not rule_name:
        return

    # Read current mapping
    if os.path.isfile(MAPPING_FILE):
        with open(MAPPING_FILE, "r", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            mapping = list(reader) if reader else []
    else:
        mapping = []

    existing = [
        e for e in mapping
        if e.get("csv_file") == csv_name and e.get("rule_name") == rule_name
    ]
    if not existing:
        mapping.append(
            {
                "rule_name": rule_name,
                "csv_file": csv_name,
                "app_context": app_ctx,
            }
        )
        with open(MAPPING_FILE, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(
                fh,
                fieldnames=["rule_name", "csv_file", "app_context"],
                extrasaction="ignore",
            )
            writer.writeheader()
            writer.writerows(mapping)

    # Also ensure the rule is in the registry
    rules_path = os.path.join(OWN_LOOKUPS, DETECTION_RULES_FILE)
    if os.path.isfile(rules_path):
        with open(rules_path, "r", encoding="utf-8") as fh:
            registered = json.load(fh)
    else:
        registered = []
    if not isinstance(registered, list):
        registered = []
    if rule_name not in registered:
        registered.append(rule_name)
        with open(rules_path, "w", encoding="utf-8") as fh:
            json.dump(registered, fh, indent=2)


def restore_csv_from_trash(trash_id: str, item_dir: str, meta: Dict) -> Tuple[Dict, str]:
    """
    Restore a CSV file from trash item directory back to its original location.

    Restores the CSV file and version snapshots, and updates the rule mapping
    if applicable. Prevents restoration if a name conflict exists.

    Args:
        trash_id: Trash item identifier (for error context).
        item_dir: Trash item directory containing files to restore.
        meta: Metadata dict from the trash item.

    Returns:
        Tuple[Dict, str]: (metadata_dict, error_string).
                          error_string is empty on success, or error message on failure.
    """
    csv_name = meta.get("name", "")
    app_ctx = meta.get("app_context", "")
    rule_name = meta.get("rule_name", "")

    # EC2: Check for name conflict
    dest_path = build_csv_path(csv_name, app_ctx)
    if dest_path and os.path.isfile(dest_path):
        return meta, "Cannot restore: '{}' already exists. Rename or delete the existing file first.".format(
            csv_name
        )

    # Restore CSV file
    src = os.path.join(item_dir, csv_name)
    if os.path.isfile(src) and dest_path:
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        shutil.move(src, dest_path)

    # Restore version snapshots
    versions_dst = os.path.join(OWN_LOOKUPS, VERSIONS_DIR)
    os.makedirs(versions_dst, exist_ok=True)
    for fname in os.listdir(item_dir):
        if fname == "metadata.json" or fname == csv_name:
            continue
        shutil.move(os.path.join(item_dir, fname), os.path.join(versions_dst, fname))

    # EC1: Restore rule mapping if rule still exists or re-register
    _restore_mapping_for_csv(csv_name, app_ctx, rule_name)

    return meta, ""  # Success


def restore_rule_from_trash(trash_id: str, item_dir: str, meta: Dict) -> Tuple[Dict, str]:
    """
    Restore a detection rule from trash item directory back to its original location.

    Restores all associated CSVs and version snapshots, and recreates all mapping
    entries and rule registry entry. Prevents restoration if a name conflict exists.

    Args:
        trash_id: Trash item identifier (for error context).
        item_dir: Trash item directory containing files to restore.
        meta: Metadata dict from the trash item.

    Returns:
        Tuple[Dict, str]: (metadata_dict, error_string).
                          error_string is empty on success, or error message on failure.
    """
    rule_name = meta.get("name", "")
    associated_csvs = meta.get("associated_csvs", [])

    # EC2: Check if rule already exists
    rules_path = os.path.join(OWN_LOOKUPS, DETECTION_RULES_FILE)
    if os.path.isfile(rules_path):
        with open(rules_path, "r", encoding="utf-8") as fh:
            registered = json.load(fh)
    else:
        registered = []
    if not isinstance(registered, list):
        registered = []

    if os.path.isfile(MAPPING_FILE):
        with open(MAPPING_FILE, "r", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            mapping = list(reader) if reader else []
    else:
        mapping = []

    existing_rule_csvs = [e for e in mapping if e.get("rule_name") == rule_name]
    if rule_name in registered or existing_rule_csvs:
        return meta, "Cannot restore: rule '{}' already exists. Remove the existing rule first.".format(
            rule_name
        )

    # Restore each associated CSV file
    versions_dst = os.path.join(OWN_LOOKUPS, VERSIONS_DIR)
    os.makedirs(versions_dst, exist_ok=True)
    restored_csvs = []

    for csv_info in associated_csvs:
        csv_name = csv_info.get("csv_file", "")
        csv_app = csv_info.get("app_context", "")
        src = os.path.join(item_dir, csv_name)
        dest = build_csv_path(csv_name, csv_app)
        if os.path.isfile(src) and dest:
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.move(src, dest)
            restored_csvs.append(csv_name)

    # Restore version files (manifests + snapshots)
    for fname in os.listdir(item_dir):
        if fname == "metadata.json":
            continue
        if fname in [c.get("csv_file", "") for c in associated_csvs]:
            continue  # already moved above
        shutil.move(os.path.join(item_dir, fname), os.path.join(versions_dst, fname))

    # EC1: Recreate rule mapping entries
    for csv_info in associated_csvs:
        mapping.append(
            {
                "rule_name": rule_name,
                "csv_file": csv_info.get("csv_file", ""),
                "app_context": csv_info.get("app_context", ""),
            }
        )
    with open(MAPPING_FILE, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["rule_name", "csv_file", "app_context"],
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(mapping)

    # Re-register the rule
    registered.append(rule_name)
    with open(rules_path, "w", encoding="utf-8") as fh:
        json.dump(registered, fh, indent=2)

    return meta, ""  # Success


def restore_from_trash(trash_id: str) -> Tuple[Dict, str]:
    """
    Restore a trashed item back to its original location.

    For CSV items: restores the CSV file and version snapshots,
    and updates the rule mapping if applicable.

    For rule items: restores all associated CSVs and version snapshots,
    and recreates all mapping entries and rule registry entry.

    Prevents restoring if a name conflict exists (new item with same name).

    Args:
        trash_id: Unique identifier of the trash item to restore.

    Returns:
        Tuple[Dict, str]: (metadata_dict, error_string).
                          metadata_dict is the restored item's metadata.
                          error_string is empty if successful, or an error message if not.
    """
    try:
        item_dir = _safe_trash_item_dir(trash_id)
        if item_dir is None:
            return {}, "Trash item not found"

        meta_path = os.path.join(item_dir, "metadata.json")
        if not os.path.isfile(meta_path):
            return {}, "Trash metadata missing"

        with open(meta_path, "r", encoding="utf-8") as fh:
            meta = json.load(fh)

        item_type = meta.get("item_type", "")

        # Ring 6.1 R6-F5 class fix (Day 6.1.7b): wrap the
        # type-specific restore in the SAME lock the canonical
        # wl_rules pipelines hold. Both restore paths read +
        # modify + write MAPPING_FILE (and the registry, for
        # rule-restore) — without this wrap a concurrent
        # create_rule / delete_rule / delete_csv could read a
        # stale snapshot and clobber the restore's writes. The
        # lock spans the shutil.move operations too, which is
        # correct: restore must be atomic relative to other
        # pipeline ops on the same mapping/registry.
        with rules_rmw_lock():
            # Dispatch to type-specific handler
            if item_type == "csv":
                result, error = restore_csv_from_trash(
                    trash_id, item_dir, meta)
            elif item_type == "rule":
                result, error = restore_rule_from_trash(
                    trash_id, item_dir, meta)
            else:
                return {}, "Unknown item type"

            if error:
                return result, error

            # Clean up the trash entry directory
            shutil.rmtree(item_dir, ignore_errors=True)

        return meta, ""  # Success

    except Exception as e:
        return {}, str(e)


def purge_trash_item(trash_id: str) -> Tuple[bool, str]:
    """
    Permanently delete a trashed item (no recovery possible).

    Removes the item directory and all its contents from the trash.

    Args:
        trash_id: Unique identifier of the trash item to permanently delete.

    Returns:
        Tuple[bool, str]: (success, error_string).
                          success is True if purged, False if item not found or error.
                          error_string is empty if successful.
    """
    try:
        item_dir = _safe_trash_item_dir(trash_id)
        if item_dir is None:
            return False, "Trash item not found"
        shutil.rmtree(item_dir, ignore_errors=True)
        return True, ""  # Success
    except Exception as e:
        return False, str(e)


def auto_cleanup_trash() -> int:
    """
    Automatically purge trash items past their retention period.

    This is called lazily (on trash list/access), not via a background thread,
    so it cannot race with active browsing.
    Expiry is recomputed from config, not stored metadata.

    Returns:
        int: Number of items purged.
    """
    try:
        config = read_trash_config()
        retention_days = config.get("retention_days", DEFAULT_TRASH_RETENTION_DAYS)
        now = int(time.time())
        trash_dir = get_trash_dir()
        purged = 0

        for entry_name in os.listdir(trash_dir):
            entry_path = os.path.join(trash_dir, entry_name)
            if not os.path.isdir(entry_path):
                continue
            meta_path = os.path.join(entry_path, "metadata.json")
            if not os.path.isfile(meta_path):
                continue
            try:
                with open(meta_path, "r", encoding="utf-8") as fh:
                    meta = json.load(fh)
                deleted_at = meta.get("deleted_at", 0)
                # EC8: Use config retention, not stored expiry
                expiry = deleted_at + (retention_days * 86400)
                if now >= expiry:
                    shutil.rmtree(entry_path, ignore_errors=True)
                    purged += 1
            except (json.JSONDecodeError, OSError):
                continue
        return purged
    except Exception:
        return 0


# ═══════════════════════════════════════════════════════════════════════════
# Pipeline Functions (Layer 3 orchestration)
# ═══════════════════════════════════════════════════════════════════════════

def restore_from_trash_pipeline(
    item_id: str,
    analyst: str,
    session_key: str,
    comment: str = "",
) -> Dict:
    """
    Restore item from trash with audit event posting.

    Wraps restore_from_trash with structured return and audit trail.

    The handler retains responsibility for:
    - Input validation
    - RBAC checks
    - Response formatting

    Args:
        item_id: Trash item identifier.
        analyst: Username performing the restore.
        session_key: Splunk session key for audit posting.
        comment: Optional reason for restoration.

    Returns:
        Dict with keys:
        - success: bool
        - message: str — Human-readable status
        - error: str — Error description if success=False
        - data: dict — {item_type, item_name} on success
    """
    from wl_audit import build_audit_event, post_audit_event

    meta, error = restore_from_trash(item_id)
    if error:
        return {
            "success": False,
            "message": "",
            "error": error,
            "data": {},
        }

    item_type = meta.get("item_type", "")
    item_name = meta.get("name", "")

    evt = build_audit_event(
        action="restored",
        analyst=analyst,
        detection_rule=meta.get("rule_name", "") if item_type == "csv" else item_name,
        csv_file=item_name if item_type == "csv" else "",
        comment=comment or "Restored from trash",
        item_type=item_type,
        trash_id=item_id,
    )
    post_audit_event(session_key, evt)

    return {
        "success": True,
        "message": "{} '{}' restored from trash".format(
            item_type.upper(), item_name),
        "error": "",
        "data": {
            "item_type": item_type,
            "item_name": item_name,
        },
    }
