"""Shared HMAC helpers for the CSV expected-hash integrity registry.

Extracted from ``wl_csv.py`` and ``wl_fim_watch.py`` on 2026-04-19 to
eliminate drift risk between the handler-side writer and the FIM-watcher-
side verifier. Previously both files contained independent copies of the
key-derivation and checksum logic; a silent change in one would cause
the other to flag every legitimate CSV write as tampering.

See:
    - ``CLAUDE.md`` Decision Log entry 2026-04-19.
    - ``tests/test_wl_hmac_key.py`` — regression lock (hardcoded known
      input/output bytes).

Registry file format::

    {
        "rule_csv_map.csv": "<sha256>",
        "DR20_whitelist.csv": "<sha256>",
        ...
        "_checksum": "<hmac-sha256>"
    }

The ``_checksum`` is ``HMAC-SHA256(key, sorted_json_without_checksum)``.
The key is derived from the Splunk server GUID + a module-level salt, so
it rotates on container rebuild but stays stable across process restarts
within the same container.
"""

from __future__ import annotations

import hashlib
import hmac as _hmac
import json
import os
from typing import Callable, Dict, Optional

# Path to the Splunk instance configuration that holds the server GUID.
# Module-level (not a constant from wl_constants) so tests can monkey-patch
# it via ``unittest.mock.patch.object``.
INSTANCE_CFG_PATH = "/opt/splunk/etc/instance.cfg"

# Salt is loaded from wl_constants when available. If the bundled-Python
# scripted-input context cannot find wl_constants (bare test harness,
# before sys.path is set), fall back to the same literal bytes so the
# derived key stays byte-identical across all call sites.
# The regression-lock tests (test_wl_hmac_key.py::TestRegressionLock)
# pin this value — changing it is a breaking change that invalidates
# every existing registry and MUST include a migration plan.
try:
    from wl_constants import FIM_HMAC_SALT  # type: ignore
except ImportError:
    FIM_HMAC_SALT = b"wl_manager_fim_integrity_v1"


def derive_hash_registry_key() -> bytes:
    """Derive the HMAC signing key for the expected-hash registry.

    Key construction: ``sha256(salt + guid)`` where ``guid`` is read from
    the first ``guid = <value>`` line of ``INSTANCE_CFG_PATH``. If the
    file is unreadable or contains no GUID, falls back to ``sha256(salt)``
    — verification still works; the key is just weaker (shared across
    all Splunk installs rather than unique per instance).
    """
    guid = ""
    try:
        with open(INSTANCE_CFG_PATH, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line.startswith("guid"):
                    parts = line.split("=", 1)
                    if len(parts) == 2:
                        guid = parts[1].strip()
                        break
    except OSError:
        pass
    if guid:
        return hashlib.sha256(FIM_HMAC_SALT + guid.encode("utf-8")).digest()
    return hashlib.sha256(FIM_HMAC_SALT).digest()


def compute_registry_checksum(hashes: Dict[str, str], key: bytes) -> str:
    """Compute HMAC-SHA256 over sorted JSON of the registry.

    Strips any existing ``_checksum`` key from the input so that re-reading
    a signed registry produces the same checksum (the checksum can't sign
    itself). Both writer and verifier MUST produce identical output for
    identical inputs — see the regression-lock test.
    """
    filtered = {k: v for k, v in hashes.items() if k != "_checksum"}
    payload = json.dumps(filtered, sort_keys=True)
    return _hmac.new(
        key, payload.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def read_expected_hashes(
    path: str,
    on_tamper: Optional[Callable[[], None]] = None,
) -> Dict[str, str]:
    """Read and HMAC-verify the expected-hashes registry.

    Args:
        path: Path to the registry JSON file.
        on_tamper: Optional callback fired when HMAC verification fails.
            The FIM watcher passes a handler that emits a CRITICAL
            ``fim_csv_hash_registry_tampered`` audit event. The handler
            (wl_csv) passes ``None`` and relies on logging.

    Returns:
        The hash entries (without ``_checksum``) if HMAC is valid, OR
        the raw data if the file is legacy (no ``_checksum`` key — such
        files will be re-signed on next write). Returns an empty dict
        on missing file, JSON parse error, or HMAC mismatch — callers
        treat an empty dict as "all CSVs are unregistered" (fail-closed).
    """
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}

    stored = data.pop("_checksum", None)
    if stored is None:
        # Pre-HMAC legacy file — accept, will be re-signed on next write.
        return data

    key = derive_hash_registry_key()
    expected = compute_registry_checksum(data, key)
    if stored != expected:
        if on_tamper is not None:
            on_tamper()
        return {}
    return data


def write_expected_hashes(path: str, hashes: Dict[str, str]) -> None:
    """Atomically write the expected-hashes registry with HMAC signature.

    Writes to ``<path>.tmp`` then ``os.replace`` to avoid leaving a
    half-written file visible to the FIM watcher. If the write fails,
    the temp file is removed (best-effort) and the exception propagates.
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    key = derive_hash_registry_key()
    body = {k: v for k, v in hashes.items() if k != "_checksum"}
    body["_checksum"] = compute_registry_checksum(body, key)
    temp = path + ".tmp"
    try:
        with open(temp, "w", encoding="utf-8") as fh:
            json.dump(body, fh, indent=2)
        os.replace(temp, path)
    except Exception:
        try:
            os.remove(temp)
        except OSError:
            pass
        raise
