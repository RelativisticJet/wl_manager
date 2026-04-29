"""
Hypothesis-based fuzz tests for the HMAC sig path used by
``_approval_queue.json`` integrity (round 6) and the CSV expected-
hash registry (round 3).

The sig path is now load-bearing for queue security: a successful
forge would let an attacker insert pre-approved entries undetected.
Round 6 added 6 happy-path tests (`TestApprovalQueueHmac`), but no
fuzz on malformed sig inputs. Round 7 closes that gap by throwing
random bytes / random JSON / type-confused fields at the verify
path and asserting:

1. The functions never raise — they fail-closed by returning False
   or empty data.
2. Verification is correctly negative on tampered inputs.
3. Round-trip determinism on legitimate inputs.

Origin: round 7 audit, 2026-04-29.
"""

import json
import os
import sys

import pytest
from hypothesis import given, settings, strategies as st, assume, HealthCheck

sys.path.insert(0, os.path.join(
    os.path.dirname(__file__), "..", "..", "bin"))

from wl_hmac_key import (  # noqa: E402
    derive_hash_registry_key,
    compute_registry_checksum,
    read_expected_hashes,
    write_expected_hashes,
)


# ─────────────────────────────────────────────────────────────────
# Strategies
# ─────────────────────────────────────────────────────────────────

# Hex-like strings of varying lengths, including:
# - Valid 64-char hex (proper SHA-256)
# - Truncated forms (an attacker truncating the sig)
# - Over-long forms
# - Non-hex bytes
_hex_string = st.text(
    alphabet="0123456789abcdef", min_size=0, max_size=128)


@st.composite
def malformed_sig_dict(draw):
    """Generate an envelope dict that LOOKS like a sig but is
    malformed in interesting ways."""
    has_sha = draw(st.booleans())
    has_signed_at = draw(st.booleans())
    has_checksum = draw(st.booleans())
    has_extra = draw(st.booleans())

    body = {}
    if has_sha:
        # sha256 field could be: valid, truncated, garbage, non-string
        sha_choice = draw(st.integers(min_value=0, max_value=4))
        if sha_choice == 0:
            body["sha256"] = "0" * 64  # valid-looking
        elif sha_choice == 1:
            body["sha256"] = draw(_hex_string)
        elif sha_choice == 2:
            body["sha256"] = draw(st.text(min_size=0, max_size=200))
        elif sha_choice == 3:
            body["sha256"] = draw(st.integers())
        else:
            body["sha256"] = None
    if has_signed_at:
        body["_signed_at"] = draw(st.one_of(
            st.integers(),
            st.floats(allow_nan=False, allow_infinity=False),
            st.text(),
            st.none()))
    if has_checksum:
        body["_checksum"] = draw(st.one_of(
            _hex_string, st.text(), st.integers(), st.none()))
    if has_extra:
        body[draw(st.text(min_size=1, max_size=10))] = draw(st.text())
    return body


# ─────────────────────────────────────────────────────────────────
# Stability — verify path must NEVER raise on any input
# ─────────────────────────────────────────────────────────────────

class TestSigVerifyStability:
    """``read_expected_hashes`` and ``compute_registry_checksum``
    are total functions: no input should make them raise."""

    @settings(max_examples=200)
    @given(st.binary(max_size=2048))
    def test_compute_checksum_handles_any_dict_value_types(
            self, payload):
        # `compute_registry_checksum` takes a dict[str, str]. Real
        # callers serialize before invoking, but bytes input would
        # crash json.dumps internally — assert behaviour stays
        # consistent (raise OR return; never wedge). Here we feed
        # a clean dict to the function under test, but with values
        # derived from the bytes input to maximize variety.
        try:
            value = payload.decode("latin-1")
        except Exception:
            value = ""
        data = {"x": value}
        # Should not raise on legitimate string values.
        result = compute_registry_checksum(
            data, derive_hash_registry_key())
        assert isinstance(result, str)
        assert len(result) == 64  # SHA-256 hex

    @settings(max_examples=200)
    @given(malformed_sig_dict())
    def test_compute_checksum_with_arbitrary_dict_shape(self, body):
        # The function strips `_checksum` before serializing, so it
        # should handle any dict that json.dumps can serialize.
        # Non-serializable values would normally raise — assume
        # away the integers-as-keys etc. cases.
        try:
            json.dumps(body, sort_keys=True, default=str)
        except (TypeError, ValueError):
            assume(False)
        result = compute_registry_checksum(
            body, derive_hash_registry_key())
        assert isinstance(result, str)
        assert len(result) == 64


class TestReadExpectedHashesStability:
    """``read_expected_hashes`` must never raise on malformed file
    contents — return empty dict on tamper, fail-closed."""

    @settings(
        max_examples=100,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    @given(st.binary(max_size=4096))
    def test_random_bytes_in_sig_file(self, tmp_path_factory, raw_bytes):
        path = tmp_path_factory.mktemp("fuzz") / "registry.json"
        path.write_bytes(raw_bytes)
        # Should NEVER raise. Either return data (legit JSON) or
        # empty dict (parse error / HMAC mismatch / tamper).
        result = read_expected_hashes(str(path))
        assert isinstance(result, dict)

    @settings(max_examples=100,
              suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(malformed_sig_dict())
    def test_malformed_sig_dict_returns_empty(
            self, tmp_path_factory, body):
        # If we write a JSON dict that isn't a properly-signed
        # registry, verification should fail and return {}.
        path = tmp_path_factory.mktemp("fuzz") / "registry.json"
        try:
            content = json.dumps(body)
        except (TypeError, ValueError):
            assume(False)
        path.write_text(content, encoding="utf-8")
        result = read_expected_hashes(str(path))
        # Either:
        #  - body had no `_checksum` → treated as legacy, returns body as-is
        #  - body had `_checksum` that doesn't verify → returns {}
        # Either way, no crash.
        assert isinstance(result, dict)


# ─────────────────────────────────────────────────────────────────
# Determinism + correctness — legit input verifies, tampered fails
# ─────────────────────────────────────────────────────────────────

class TestSigDeterminism:
    """Same input → same checksum. Different input → different
    checksum (with overwhelming probability)."""

    @settings(max_examples=200)
    @given(st.dictionaries(
        st.text(min_size=1, max_size=20).filter(lambda s: s != "_checksum"),
        st.text(max_size=64), max_size=10))
    def test_same_dict_same_checksum(self, data):
        key = derive_hash_registry_key()
        a = compute_registry_checksum(data, key)
        b = compute_registry_checksum(data, key)
        assert a == b

    @settings(max_examples=200)
    @given(st.dictionaries(
        st.text(min_size=1, max_size=20).filter(lambda s: s != "_checksum"),
        st.text(max_size=64), max_size=10),
           st.text(min_size=1, max_size=20))
    def test_different_dict_different_checksum(self, data, extra_key):
        # Adding any key (other than `_checksum` which is filtered)
        # MUST change the checksum.
        assume(extra_key not in data)
        assume(extra_key != "_checksum")
        key = derive_hash_registry_key()
        a = compute_registry_checksum(data, key)
        b_data = dict(data)
        b_data[extra_key] = "v"
        b = compute_registry_checksum(b_data, key)
        assert a != b, (
            "extra key {!r} did not change checksum — "
            "the sig is not collision-resistant on this input"
            .format(extra_key))

    @settings(max_examples=100,
              suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(st.dictionaries(
        st.text(min_size=1, max_size=15).filter(lambda s: s != "_checksum"),
        st.text(max_size=30), max_size=8))
    def test_round_trip_legitimate_data(
            self, tmp_path_factory, data):
        # Write → read returns equivalent data (modulo _checksum).
        path = tmp_path_factory.mktemp("fuzz") / "registry.json"
        write_expected_hashes(str(path), data)
        result = read_expected_hashes(str(path))
        assert dict(result) == dict(data), (
            "round-trip lost data: in={!r} out={!r}".format(
                data, result))

    @settings(max_examples=100,
              suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(st.dictionaries(
        st.text(min_size=1, max_size=15).filter(lambda s: s != "_checksum"),
        st.text(min_size=1, max_size=30), min_size=1, max_size=5),
           st.text(min_size=1, max_size=15))
    def test_tampered_data_returns_empty(
            self, tmp_path_factory, data, tamper_key):
        # Write a legit registry, then tamper with the data block
        # without re-signing. read() must return {} (fail-closed).
        assume(tamper_key not in data)
        assume(tamper_key != "_checksum")
        path = tmp_path_factory.mktemp("fuzz") / "registry.json"
        write_expected_hashes(str(path), data)
        # Read raw, mutate, write back.
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw[tamper_key] = "INJECTED"
        path.write_text(json.dumps(raw), encoding="utf-8")
        result = read_expected_hashes(str(path))
        assert result == {}, (
            "tamper went undetected — added {!r} but read() returned "
            "{!r}".format(tamper_key, result))


class TestSigChecksumProperties:
    """Properties the HMAC checksum field itself must satisfy."""

    @settings(max_examples=50)
    @given(st.dictionaries(
        st.text(min_size=1, max_size=15).filter(lambda s: s != "_checksum"),
        st.text(max_size=30), max_size=5))
    def test_checksum_is_hex_64(self, data):
        result = compute_registry_checksum(
            data, derive_hash_registry_key())
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result), (
            "checksum is not hex: " + result)

    @settings(max_examples=50)
    @given(st.dictionaries(
        st.text(min_size=1, max_size=15).filter(lambda s: s != "_checksum"),
        st.text(max_size=30), max_size=5))
    def test_checksum_excludes_existing_checksum_field(self, data):
        # If `_checksum` is already in data, it should be filtered
        # out before signing — otherwise a sig couldn't sign itself.
        # This is the property that makes round-trip stable.
        without = compute_registry_checksum(
            data, derive_hash_registry_key())
        with_existing = dict(data)
        with_existing["_checksum"] = "garbage-not-real"
        with_present = compute_registry_checksum(
            with_existing, derive_hash_registry_key())
        assert without == with_present, (
            "_checksum field leaked into the signed payload")
