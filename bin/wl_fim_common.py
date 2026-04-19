"""Shared helpers for the FIM scripts and the cooldown migration tool.

Consolidated on 2026-04-19 (Phase 3b of the graphify audit). Previously
each of ``wl_fim.py``, ``wl_fim_watch.py``, and ``wl_migrate_cooldowns.py``
shipped its own copy of the same 4 helpers:

- GUID reading from Splunk's ``instance.cfg``
- SHA-256 hashing of a file's contents in chunks
- KV-store REST URL construction
- Appending to the FIM notification-queue JSONL

Net risk of the duplication: a subtle fix in one copy (e.g. handling
``PermissionError`` separately from ``OSError``) never propagates to the
siblings, leading to mismatched behavior across the FIM scripts — the
kind of drift that breaks correlation searches and floods the audit
index with inconsistent events.

Intentionally NOT consolidated:

- ``_emit`` in ``wl_fim.py`` vs ``wl_fim_watch.py``. They diverge on
  purpose: ``wl_fim`` is a scripted input (re-invoked) with edge-
  triggered state dedup; ``wl_fim_watch`` is a persistent daemon that
  reads lockdown state per-event and unconditionally surfaces each file
  change. Merging would regress one or the other.

See CLAUDE.md Decision Log 2026-04-19.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Optional

DEFAULT_INSTANCE_CFG = "/opt/splunk/etc/instance.cfg"


def read_splunk_guid(
    instance_cfg_path: str = DEFAULT_INSTANCE_CFG,
    strict: bool = False,
) -> str:
    """Return the ``guid`` value from the given ``instance.cfg``.

    Args:
        instance_cfg_path: Path to ``instance.cfg``. Callers override
            this in tests.
        strict: If ``True``, raises ``RuntimeError`` when the GUID can't
            be read. The migration tool (one-shot admin operation) uses
            strict mode so operators see failures loudly; the FIM
            scripts (scheduled inputs) use the default best-effort mode
            so a missing file falls back to an unkeyed HMAC rather than
            crashing the scheduled input.

    Returns:
        The GUID string, or ``""`` if missing/unreadable and
        ``strict=False``.
    """
    try:
        with open(instance_cfg_path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line.startswith("guid"):
                    parts = line.split("=", 1)
                    if len(parts) == 2:
                        return parts[1].strip()
    except OSError:
        if strict:
            raise RuntimeError(
                "Cannot read server GUID from " + instance_cfg_path)
        return ""
    if strict:
        raise RuntimeError(
            "Cannot read server GUID from " + instance_cfg_path)
    return ""


def file_hash_sha256(path: str) -> Optional[str]:
    """Return the hex SHA-256 of ``path``'s contents, or ``None``.

    Returns ``None`` if the file is missing or unreadable — callers
    distinguish "missing file" from "missing hash" themselves. Uses
    64KiB chunks so large CSVs don't exhaust memory.
    """
    if not os.path.isfile(path):
        return None
    try:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def kv_collection_url(
    app_name: str,
    collection: str,
    suffix: str = "",
) -> str:
    """Build a Splunk KV-store REST URL for ``collection`` under ``app_name``.

    Example::

        >>> kv_collection_url("wl_manager", "wl_cooldowns", "/state")
        'https://localhost:8089/servicesNS/nobody/wl_manager/storage/collections/data/wl_cooldowns/state'

    The base is always ``localhost:8089`` because every caller is an
    in-container script talking to the local splunkd.
    """
    base = ("https://localhost:8089/servicesNS/nobody/{}"
            "/storage/collections/data/{}").format(app_name, collection)
    return base + suffix


def queue_fim_notification(event: dict, queue_path: str) -> None:
    """Append a FIM event to the notification-queue JSONL.

    Both FIM scripts push HIGH/CRITICAL events into this queue; the
    handler's ``get_notifications`` action drains entries into each
    superadmin's per-user notification list on their next poll.

    The queue is append-only and JSONL; on Linux, ``O_APPEND`` makes
    short writes atomic, so no lock is required. Directory is created
    if missing. Write errors are swallowed — the indexed audit event
    remains the authoritative record; the bell is a UX convenience.
    """
    try:
        path = (event.get("monitored_path", "")
                or event.get("path", "")
                or event.get("csv_file", ""))
        key_parts = [
            str(event.get("timestamp", "")),
            event.get("action", ""),
            path,
        ]
        event_id = "fim_" + "_".join(p.replace("/", "-") for p in key_parts)
        queued = {
            "id": event_id,
            "timestamp": event.get("timestamp"),
            "action": event.get("action"),
            "severity": event.get("severity"),
            "path": path,
            "lockdown_active": event.get("lockdown_active", False),
            "details": event.get("details", "")[:500],
            # Caller sets source_script explicitly; fall back to the
            # generic "wl_fim" when absent so malformed events remain
            # traceable.
            "source_script": event.get("source_script", "wl_fim"),
        }
        os.makedirs(os.path.dirname(queue_path), exist_ok=True)
        with open(queue_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(queued) + "\n")
    except OSError:
        pass
