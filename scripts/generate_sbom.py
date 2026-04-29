#!/usr/bin/env python3
"""Generate a CycloneDX 1.5 SBOM from the contents of a .spl release.

Round 8 (2026-04-29). The static `sbom.cdx.json` at the repo root
captures a baseline; this script generates a per-release SBOM that
matches the EXACT contents of `dist/wl_manager-<version>.spl`.

Strategy: extract the .spl tarball into a temp directory, walk every
file inside, hash each one, and emit a CycloneDX `components` array
with one `application:wl_manager` envelope and inner file-component
entries. Customers running automated SCA tools then have a
machine-readable inventory matching the artifact byte-for-byte.

Usage:
    python3 scripts/generate_sbom.py <path-to-spl> <output-path>

Example:
    python3 scripts/generate_sbom.py dist/wl_manager-2.0.0.spl \\
        dist/wl_manager-2.0.0.spl.cdx.json

Exit codes:
    0 — SBOM written
    1 — argv error / .spl not found
    2 — extraction or hashing failure
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import sys
import tarfile
import tempfile
import uuid
from typing import Any, Dict, List


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_app_conf_version(extract_root: str) -> str:
    """Pull the [launcher] version from the bundled `default/app.conf`.

    Falls back to `0.0.0` if the file is unreadable or missing — the
    SBOM still serializes, just with a placeholder version. The build
    number is captured separately as a `splunk:build` property.
    """
    conf = os.path.join(extract_root, "wl_manager", "default", "app.conf")
    try:
        with open(conf, "r", encoding="utf-8") as fh:
            for line in fh:
                m = re.match(r"\s*version\s*=\s*(\S+)", line)
                if m:
                    return m.group(1)
    except OSError:
        pass
    return "0.0.0"


def _read_app_conf_build(extract_root: str) -> str:
    conf = os.path.join(extract_root, "wl_manager", "default", "app.conf")
    try:
        with open(conf, "r", encoding="utf-8") as fh:
            for line in fh:
                m = re.match(r"\s*build\s*=\s*(\S+)", line)
                if m:
                    return m.group(1)
    except OSError:
        pass
    return "0"


def _build_file_components(extract_root: str) -> List[Dict[str, Any]]:
    """One CycloneDX `component` per file inside the .spl, type=file."""
    components: List[Dict[str, Any]] = []
    app_root = os.path.join(extract_root, "wl_manager")
    if not os.path.isdir(app_root):
        # Tarball didn't have the expected wl_manager/ wrapper. Treat
        # extract_root itself as the app root so the SBOM still emits.
        app_root = extract_root
    for dirpath, _dirnames, filenames in os.walk(app_root):
        for fn in sorted(filenames):
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, extract_root).replace(os.sep, "/")
            try:
                size = os.path.getsize(full)
                digest = _sha256_file(full)
            except OSError:
                continue
            components.append({
                "type": "file",
                "bom-ref": "file:" + rel,
                "name": rel,
                "hashes": [{"alg": "SHA-256", "content": digest}],
                "properties": [
                    {"name": "file:size_bytes", "value": str(size)},
                ],
            })
    return components


def main(argv: List[str]) -> int:
    if len(argv) != 3:
        sys.stderr.write(
            "usage: generate_sbom.py <path-to-spl> <output-path>\n")
        return 1
    spl_path, out_path = argv[1], argv[2]
    if not os.path.isfile(spl_path):
        sys.stderr.write("error: .spl not found: " + spl_path + "\n")
        return 1

    timestamp = datetime.datetime.now(datetime.timezone.utc) \
        .strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        with tempfile.TemporaryDirectory(prefix="wl_sbom_") as tmp:
            with tarfile.open(spl_path, "r:gz") as tf:
                # Validate every member path stays inside tmp BEFORE
                # extracting (defense against pathological tarballs).
                for member in tf.getmembers():
                    target = os.path.realpath(os.path.join(tmp, member.name))
                    tmp_real = os.path.realpath(tmp)
                    if not target.startswith(tmp_real + os.sep) \
                            and target != tmp_real:
                        sys.stderr.write(
                            "error: tarball contains path-traversal "
                            "entry: " + member.name + "\n")
                        return 2
                tf.extractall(tmp)
            version = _read_app_conf_version(tmp)
            build = _read_app_conf_build(tmp)
            file_components = _build_file_components(tmp)
    except (tarfile.TarError, OSError) as exc:
        sys.stderr.write("error: " + str(exc) + "\n")
        return 2

    spl_digest = _sha256_file(spl_path)
    spl_purl = "pkg:splunk/wl_manager@" + version

    sbom: Dict[str, Any] = {
        "$schema": "http://cyclonedx.org/schema/bom-1.5.schema.json",
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": "urn:uuid:" + str(uuid.uuid4()),
        "version": 1,
        "metadata": {
            "timestamp": timestamp,
            "tools": [
                {
                    "vendor": "wl_manager",
                    "name": "scripts/generate_sbom.py",
                    "version": "1.0.0",
                }
            ],
            "component": {
                "type": "application",
                "bom-ref": spl_purl,
                "name": "wl_manager",
                "version": version,
                "description": (
                    "Manage detection-rule CSV whitelists with inline "
                    "editing, approval workflows, version control, "
                    "and diff-based audit trail"),
                "publisher": "Security Engineering",
                "licenses": [{"license": {"id": "MIT"}}],
                "purl": spl_purl,
                "hashes": [
                    {"alg": "SHA-256", "content": spl_digest}
                ],
                "properties": [
                    {"name": "splunk:build", "value": build},
                    {"name": "splunk:app_id", "value": "wl_manager"},
                    {"name": "spl:filename",
                     "value": os.path.basename(spl_path)},
                ],
            },
        },
        "components": file_components,
        "dependencies": [
            {"ref": spl_purl, "dependsOn": []}
        ],
        "compositions": [
            {"aggregate": "complete", "assemblies": [spl_purl]}
        ],
    }

    out_dir = os.path.dirname(out_path)
    if out_dir and not os.path.isdir(out_dir):
        os.makedirs(out_dir, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(sbom, fh, indent=2, sort_keys=True)
        fh.write("\n")
    sys.stdout.write(
        "SBOM written: " + out_path + " (" +
        str(len(file_components)) + " files)\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
