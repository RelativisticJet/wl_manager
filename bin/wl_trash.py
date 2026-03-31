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
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple, Optional

# Import sys.path setup from wl_handler pattern
import sys
sys.path.insert(0, os.path.dirname(__file__))

from wl_constants import (
    OWN_LOOKUPS, TRASH_DIR, TRASH_RETENTION_DAYS, TRASH_CONFIG_FILE,
    VERSIONS_DIR, DETECTION_RULES_FILE, MAPPING_FILE, DEFAULT_TRASH_RETENTION_DAYS
)
from wl_validation import sanitize_text, build_csv_path


__all__ = [
    'move_to_trash',
    'list_trash',
    'restore_from_trash',
    'purge_trash_item',
    'auto_cleanup_trash',
    'get_trash_dir',
    'read_trash_config',
    'write_trash_config',
]


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

    config = read_trash_config()
    # EC8: Compute expiry from config, not metadata — prevents tamper
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

    if item_type == "csv":
        # Move the CSV file itself
        csv_path = build_csv_path(name, app_context)
        if csv_path and os.path.isfile(csv_path):
            shutil.move(csv_path, os.path.join(item_dir, name))

        # Copy version snapshots for this CSV
        versions_src = os.path.join(OWN_LOOKUPS, VERSIONS_DIR)
        base = name.replace(".csv", "")
        manifest_name = "{}_versions.json".format(base)
        manifest_path = os.path.join(versions_src, manifest_name)

        if os.path.isfile(manifest_path):
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

        metadata["original_path"] = csv_path or ""

    elif item_type == "rule":
        metadata["associated_csvs"] = associated_csvs or []
        # Move each associated CSV into the trash bundle
        for csv_info in (associated_csvs or []):
            csv_name = csv_info.get("csv_file", "")
            csv_app = csv_info.get("app_context", "")
            csv_path = build_csv_path(csv_name, csv_app)
            if csv_path and os.path.isfile(csv_path):
                shutil.move(csv_path, os.path.join(item_dir, csv_name))
            # Also move version snapshots for each CSV
            versions_src = os.path.join(OWN_LOOKUPS, VERSIONS_DIR)
            base = csv_name.replace(".csv", "")
            manifest_name = "{}_versions.json".format(base)
            manifest_path = os.path.join(versions_src, manifest_name)
            if os.path.isfile(manifest_path):
                shutil.move(manifest_path, os.path.join(item_dir, manifest_name))
                try:
                    with open(os.path.join(item_dir, manifest_name), "r", encoding="utf-8") as fh:
                        manifest = json.load(fh)
                    # Manifest can be a list or dict with "versions" key
                    ver_list = manifest if isinstance(manifest, list) else manifest.get("versions", [])
                    for ver in ver_list:
                        vf = ver.get("filename", "")
                        vf_path = os.path.join(versions_src, vf)
                        if vf and os.path.isfile(vf_path):
                            shutil.move(vf_path, os.path.join(item_dir, vf))
                except (json.JSONDecodeError, OSError):
                    pass

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
        trash_dir = get_trash_dir()
        item_dir = os.path.join(trash_dir, trash_id)
        if not os.path.isdir(item_dir):
            return {}, "Trash item not found"

        meta_path = os.path.join(item_dir, "metadata.json")
        if not os.path.isfile(meta_path):
            return {}, "Trash metadata missing"

        with open(meta_path, "r", encoding="utf-8") as fh:
            meta = json.load(fh)

        item_type = meta.get("item_type", "")
        name = meta.get("name", "")

        if item_type == "csv":
            csv_name = name
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
            if rule_name:
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

        elif item_type == "rule":
            rule_name = name
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
        trash_dir = get_trash_dir()
        item_dir = os.path.join(trash_dir, trash_id)
        if not os.path.isdir(item_dir):
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
