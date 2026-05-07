"""
KV-store collection schema contract tests.

Pins the on-disk shape of every Splunk KV collection this app
relies on, so any drift between handler/FIM code and the actual
storage layer would break a test rather than silently corrupt
audit/security state.

Two collections in scope (from ``default/collections.conf``):

- ``wl_cooldowns``  — rate-limit counters, HMAC-signed, schema-versioned
- ``wl_fim_baseline`` — FIM dual-store baseline (mirrors ``.fim_baseline.json``)

What this file does NOT cover (and why):

- ``wl_presence``, ``wl_lockdown`` — these are not real KV
  collections. Presence and lockdown state live in JSON files
  under ``lookups/_versions/`` (``.presence.json``,
  ``_emergency_lockdown.json``). The names appear in
  ``CLAUDE.md`` "DR Runbook" because they could be deleted as
  part of disaster recovery, but they are filesystem state.
- ``wl_fim`` events — those are sourcetype'd events, not KV
  records. Pinned separately in ``test_audit_emission.py``.

Origin
------

Day 5 of Ring 1. Closes the third leg of the storage-layer
triad:

- Day 4 — wl_audit index event schemas (sourcetype=wl_audit)
- Day 5 — KV collection record schemas (this file)
- Day 6 — recovery scripts (tests still to write)

The need for this file surfaced during the build-553 → 614
hardening rounds: every KV-related bug we shipped (HMAC mismatch
flooding tamper flags, schema-version drift after migration,
missing init marker on first install) would have been caught at
test time by a contract assertion on the record shape.
"""

import json
import os
import re
import subprocess

import pytest


pytestmark = pytest.mark.docker


CONTAINER = "wl_manager_test"
CURL_BASE = (
    "https://localhost:8089/servicesNS/nobody/wl_manager/"
    "storage/collections/data"
)

# 64-char lowercase hex — the HMAC-SHA256 output format used by
# both ``_compute_cooldown_checksum`` (handler) and
# ``_compute_baseline_checksum`` (wl_fim).
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────


def _kv_get(collection: str, key: str = "state"):
    """GET a singleton record from a KV collection.

    Returns the parsed JSON dict on 200, or None if Splunk returned
    a "Could not find object" error envelope (record absent — first
    install or post-recovery state).
    """
    env = {**os.environ, "MSYS_NO_PATHCONV": "1"}
    proc = subprocess.run(  # noqa: S603 — list-form, no shell
        [
            "docker", "exec", CONTAINER,
            "curl", "-sk", "-u", "admin:Chang3d!",
            "{}/{}/{}?output_mode=json".format(CURL_BASE, collection, key),
        ],
        capture_output=True, text=True, timeout=15,
        check=False, env=env,
    )
    if proc.returncode != 0:
        pytest.fail("curl failed: {}".format(proc.stderr))
    body = (proc.stdout or "").strip()
    if not body:
        return None
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        pytest.fail("KV body not JSON: {} (body head: {})"
                    .format(exc, body[:200]))
    if isinstance(parsed, dict) and "messages" in parsed:
        return None
    return parsed


def _bootstrap_cooldown_record(container_curl):
    """Trigger an admin write so the wl_cooldowns/state record
    exists for tests that read it.

    Uses ``set_admin_limits`` because it is the canonical
    cooldown-incrementing path. Returns whether the bootstrap
    succeeded — tests skip if not.
    """
    proc = container_curl(
        "/services/custom/wl_manager",
        method="POST",
        data=json.dumps({
            "action": "set_admin_limits",
            "limits": {"csv_save": 50},
        }),
        content_type="application/json",
        check=False,
        user="superadmin1",
    )
    raw = (proc.stdout or "").strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return False
    return bool(parsed.get("success"))


# ─────────────────────────────────────────────────────────────────────
# wl_cooldowns/state — rate-limit counters
# ─────────────────────────────────────────────────────────────────────


class TestCooldownKVSchema:
    """Pins ``wl_cooldowns/state`` envelope + counter payload shape.

    Why this matters: a missing ``schema_version`` field, an
    unsigned ``payload``, or a non-hex ``checksum`` would each
    cause ``_read_cooldowns`` to fail-closed (returning ``None``)
    in production, which manifests as "rate limit counter has
    been tampered with" errors that block every admin write
    until a superadmin runs ``reset_cooldowns.sh``. We don't
    want that to surface only in production.
    """

    REQUIRED_ENVELOPE_FIELDS = {
        "_key", "schema_version", "payload", "checksum",
        "updated_at", "updated_by",
    }

    def test_singleton_record_has_full_envelope(
            self, container_state, container_curl):
        # Bootstrap first — fresh container or post-recovery may
        # not have a record until something writes one.
        if _kv_get("wl_cooldowns") is None:
            if not _bootstrap_cooldown_record(container_curl):
                pytest.skip(
                    "could not bootstrap cooldown record "
                    "(set_admin_limits failed; check superadmin1 role)")

        rec = _kv_get("wl_cooldowns")
        assert rec is not None, "no wl_cooldowns/state record after bootstrap"

        missing = self.REQUIRED_ENVELOPE_FIELDS - set(rec.keys())
        assert not missing, \
            ("wl_cooldowns/state missing envelope fields: {}. "
             "Record: {}".format(missing, rec))

    def test_singleton_key_is_state(self, container_state):
        rec = _kv_get("wl_cooldowns")
        if rec is None:
            pytest.skip("no cooldown record — fresh container")
        assert rec["_key"] == "state", \
            ("wl_cooldowns is a singleton collection — _key MUST "
             "be 'state' (matches _COOLDOWN_KV_KEY constant)")

    def test_schema_version_is_supported(self, container_state):
        rec = _kv_get("wl_cooldowns")
        if rec is None:
            pytest.skip("no cooldown record")
        # _COOLDOWN_SCHEMA_SUPPORTED == {1} as of build 644.
        # If we ever migrate to v2, BOTH this assertion AND the
        # _COOLDOWN_SCHEMA_SUPPORTED set must be updated to admit
        # v1 (legacy) and v2 (new) simultaneously, then a later
        # build can drop v1.
        assert rec["schema_version"] in (1,), \
            ("wl_cooldowns schema_version={} is unsupported. "
             "Bump _COOLDOWN_SCHEMA_SUPPORTED in wl_handler.py if "
             "this is intentional.".format(rec["schema_version"]))

    def test_checksum_is_hmac_sha256_hex(self, container_state):
        rec = _kv_get("wl_cooldowns")
        if rec is None:
            pytest.skip("no cooldown record")
        cs = rec.get("checksum", "")
        assert _HEX64_RE.match(cs), \
            ("wl_cooldowns checksum is not 64-char lowercase hex "
             "(HMAC-SHA256 output): {!r}".format(cs[:80]))

    def test_payload_is_json_serialized_counter_map(
            self, container_state):
        rec = _kv_get("wl_cooldowns")
        if rec is None:
            pytest.skip("no cooldown record")
        try:
            inner = json.loads(rec["payload"])
        except (ValueError, KeyError) as exc:
            pytest.fail("wl_cooldowns payload not valid JSON: {}".format(exc))
        assert isinstance(inner, dict), \
            ("wl_cooldowns payload must decode to a dict "
             "(counter map). Got: {}".format(type(inner).__name__))
        # Counter values must be ints (they're incremented
        # additively; a stray string would silently drift)
        for k, v in inner.items():
            assert isinstance(k, str), \
                "counter key must be string, got {}: {!r}".format(
                    type(k).__name__, k)
            assert isinstance(v, int), \
                "counter value must be int (incremented additively), " \
                "got {}: {!r}".format(type(v).__name__, v)

    def test_updated_metadata_is_present(self, container_state):
        rec = _kv_get("wl_cooldowns")
        if rec is None:
            pytest.skip("no cooldown record")
        assert isinstance(rec.get("updated_at"), int) and \
            rec["updated_at"] > 0, \
            "updated_at must be positive epoch int"
        assert isinstance(rec.get("updated_by"), str) and \
            rec["updated_by"], \
            "updated_by must be a non-empty string"


# ─────────────────────────────────────────────────────────────────────
# wl_fim_baseline/state — FIM dual-store baseline
# ─────────────────────────────────────────────────────────────────────


class TestFimBaselineKVSchema:
    """Pins ``wl_fim_baseline/state`` envelope + per-file payload shape.

    Why this matters: the dual-store FIM baseline (file +
    KV) defends against single-sided tampering. If the KV record
    drifts to a shape ``wl_fim.py`` no longer recognizes, the
    cross-validation alert (``fim_baseline_kv_fs_divergence``)
    flips on persistently and floods SOC with false positives,
    which trains operators to ignore real signal.
    """

    REQUIRED_ENVELOPE_FIELDS = {
        "_key", "payload", "checksum", "updated_at", "updated_by",
    }
    # Two valid per-file entry schemas in the inner payload:
    # 1. Standard files     — {exists, hash}
    # 2. Append-only logs   — {exists, prefix_hash, size}
    STANDARD_ENTRY_FIELDS = {"exists", "hash"}
    APPEND_ONLY_ENTRY_FIELDS = {"exists", "prefix_hash", "size"}

    def test_singleton_record_has_full_envelope(self, container_state):
        rec = _kv_get("wl_fim_baseline")
        if rec is None:
            pytest.skip(
                "no FIM baseline record (wl_fim.py hasn't run yet — "
                "fresh container or first 60s after start)")
        missing = self.REQUIRED_ENVELOPE_FIELDS - set(rec.keys())
        assert not missing, \
            ("wl_fim_baseline/state missing envelope fields: {}. "
             "Record keys: {}".format(missing, sorted(rec.keys())))

    def test_singleton_key_is_state(self, container_state):
        rec = _kv_get("wl_fim_baseline")
        if rec is None:
            pytest.skip("no FIM baseline record")
        assert rec["_key"] == "state", \
            "wl_fim_baseline is a singleton — _key MUST be 'state'"

    def test_no_schema_version_field(self, container_state):
        """wl_fim_baseline doesn't carry an explicit schema_version
        (unlike wl_cooldowns). Pinning the absence is a deliberate
        contract: if a future contributor adds schema_version they
        must ALSO update wl_fim.py reader to validate it against an
        allow-list, otherwise the schema_version becomes a free-for-all
        attacker-controllable input."""
        rec = _kv_get("wl_fim_baseline")
        if rec is None:
            pytest.skip("no FIM baseline record")
        if "schema_version" in rec:
            pytest.fail(
                "wl_fim_baseline now carries schema_version — "
                "ensure wl_fim.py validates it against a supported "
                "allow-list (mirror _COOLDOWN_SCHEMA_SUPPORTED), "
                "then update this test")

    def test_checksum_is_hmac_sha256_hex(self, container_state):
        rec = _kv_get("wl_fim_baseline")
        if rec is None:
            pytest.skip("no FIM baseline record")
        cs = rec.get("checksum", "")
        assert _HEX64_RE.match(cs), \
            "wl_fim_baseline checksum is not 64-char lowercase hex: " \
            "{!r}".format(cs[:80])

    def test_updated_by_is_wl_fim(self, container_state):
        """Only wl_fim.py should write the baseline. If updated_by
        is anything else, somebody (us, the user, an attacker)
        bypassed the watcher and forged a record."""
        rec = _kv_get("wl_fim_baseline")
        if rec is None:
            pytest.skip("no FIM baseline record")
        assert rec.get("updated_by") == "wl_fim", \
            ("wl_fim_baseline.updated_by must be 'wl_fim'. "
             "Got: {!r} — investigate who wrote this record."
             .format(rec.get("updated_by")))

    def test_payload_entry_schemas_are_known(self, container_state):
        """Every per-file entry must match either the standard
        schema {exists, hash} or the append-only schema
        {exists, prefix_hash, size}. A foreign shape means
        wl_fim.py is producing entries this test doesn't know
        about — possibly a regression, possibly a new feature
        that needs the test updated."""
        rec = _kv_get("wl_fim_baseline")
        if rec is None:
            pytest.skip("no FIM baseline record")
        try:
            inner = json.loads(rec["payload"])
        except (ValueError, KeyError) as exc:
            pytest.fail("FIM payload not valid JSON: {}".format(exc))
        assert isinstance(inner, dict), \
            "FIM payload must decode to a dict (path → entry)"
        assert len(inner) > 0, \
            "FIM baseline is empty — wl_fim.py hasn't snapshotted any files"

        violators = []
        for path, entry in inner.items():
            if not isinstance(entry, dict):
                violators.append(
                    "{}: not a dict ({})".format(path, type(entry).__name__))
                continue
            keys = set(entry.keys())
            if keys == self.STANDARD_ENTRY_FIELDS:
                # Validate types
                if not isinstance(entry["exists"], bool):
                    violators.append(
                        "{}: 'exists' must be bool".format(path))
                if entry["exists"] and not _HEX64_RE.match(entry["hash"]):
                    violators.append(
                        "{}: 'hash' must be 64-hex when exists=True"
                        .format(path))
            elif keys == self.APPEND_ONLY_ENTRY_FIELDS:
                if not isinstance(entry["exists"], bool):
                    violators.append(
                        "{}: 'exists' must be bool".format(path))
                if entry["exists"] and not _HEX64_RE.match(
                        entry["prefix_hash"]):
                    violators.append(
                        "{}: 'prefix_hash' must be 64-hex when exists=True"
                        .format(path))
                if not isinstance(entry["size"], int):
                    violators.append(
                        "{}: 'size' must be int".format(path))
            else:
                violators.append(
                    "{}: unknown entry schema {}".format(path, sorted(keys)))

        assert not violators, \
            ("FIM baseline payload entries with bad schemas:\n  "
             + "\n  ".join(violators[:10]))


# ─────────────────────────────────────────────────────────────────────
# Cross-collection invariants
# ─────────────────────────────────────────────────────────────────────


class TestKVCollectionDefinitions:
    """Pins that ``default/collections.conf`` declares the fields
    the runtime code actually writes. A drift here means writes
    silently land outside the schema, which Splunk allows but which
    breaks any consumer that filters by declared field type.
    """

    COOLDOWN_DECLARED_FIELDS = {
        "payload", "checksum", "updated_at", "updated_by",
        "schema_version",
    }
    FIM_DECLARED_FIELDS = {
        "payload", "checksum", "updated_at", "updated_by",
    }

    def _read_collections_conf(self):
        """Returns dict {collection_name: set_of_declared_fields}."""
        # collections.conf is mounted from the host into the container.
        # Read from the host copy — that's what gets deployed.
        path = os.path.join(
            os.path.dirname(__file__), "..", "..",
            "default", "collections.conf")
        path = os.path.abspath(path)
        if not os.path.isfile(path):
            pytest.fail("collections.conf not found at {}".format(path))
        result = {}
        current = None
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("[") and line.endswith("]"):
                    current = line[1:-1]
                    result[current] = set()
                elif line.startswith("field.") and "=" in line and current:
                    name = line.split("=", 1)[0].strip()
                    fname = name.split(".", 1)[1].strip()
                    result[current].add(fname)
        return result

    def test_wl_cooldowns_declares_all_runtime_fields(self):
        defs = self._read_collections_conf()
        assert "wl_cooldowns" in defs, \
            "wl_cooldowns missing from collections.conf"
        missing = self.COOLDOWN_DECLARED_FIELDS - defs["wl_cooldowns"]
        assert not missing, \
            ("collections.conf [wl_cooldowns] missing field "
             "declarations: {}".format(missing))

    def test_wl_fim_baseline_declares_all_runtime_fields(self):
        defs = self._read_collections_conf()
        assert "wl_fim_baseline" in defs, \
            "wl_fim_baseline missing from collections.conf"
        missing = self.FIM_DECLARED_FIELDS - defs["wl_fim_baseline"]
        assert not missing, \
            ("collections.conf [wl_fim_baseline] missing field "
             "declarations: {}".format(missing))

    def test_no_undeclared_collections_referenced_at_runtime(self):
        """If runtime code references a KV collection name not in
        collections.conf, every operation will 404. Catch this at
        test time."""
        defs = self._read_collections_conf()
        declared = set(defs.keys())
        # Hard-coded inventory of collections this codebase uses.
        # If the team adds a new one, both this set AND
        # collections.conf must be updated, and the tests above
        # must grow a new class for the new collection's schema.
        used_at_runtime = {"wl_cooldowns", "wl_fim_baseline"}
        undeclared = used_at_runtime - declared
        assert not undeclared, \
            ("Runtime code references KV collections not in "
             "collections.conf: {}. Add a [stanza] for each.")
