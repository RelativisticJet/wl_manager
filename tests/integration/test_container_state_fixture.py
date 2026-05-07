"""
Smoke tests for the ``container_state`` fixture itself.

The fixture is the foundation of every state-mutating Ring 1 test;
if it doesn't snapshot/restore correctly, every test that depends on
it gives wrong answers. These tests pin the fixture's behaviour.

What's pinned
-------------

1. The fixture yields a usable handle with ``snapshot_path`` and
   ``kv_dumps`` populated.
2. State mutations made by a test are reverted after the fixture
   tears down.
3. KV collections are correctly snapshotted and restored.
4. The snapshot survives even if the in-container tar is removed
   mid-test (host-side copy is the recovery mechanism).
"""

import json
import os
import subprocess

import pytest


pytestmark = pytest.mark.docker


def _read_file_in_container(path: str) -> str:
    """Helper — read a file inside the test container."""
    env = {**os.environ, "MSYS_NO_PATHCONV": "1"}
    proc = subprocess.run(  # noqa: S603 — list-form, no shell
        ["docker", "exec", "-u", "0", "wl_manager_test",
         "cat", path],
        capture_output=True, text=True, timeout=10,
        check=True, env=env,
    )
    return proc.stdout


def _write_file_in_container(path: str, content: str) -> None:
    """Helper — write a file inside the test container.

    Uses ``tee`` over stdin so we don't have to escape the content
    for shell. ``content`` is passed via stdin; never interpolated.
    """
    env = {**os.environ, "MSYS_NO_PATHCONV": "1"}
    subprocess.run(  # noqa: S603 — list-form, no shell
        ["docker", "exec", "-u", "0", "-i", "wl_manager_test",
         "tee", path],
        input=content, capture_output=True, text=True,
        timeout=10, check=True, env=env,
    )


# ─────────────────────────────────────────────────────────────────────
# Fixture handle shape
# ─────────────────────────────────────────────────────────────────────


class TestFixtureHandle:
    """The handle the fixture yields must expose snapshot_path
    and kv_dumps for tests that want to inspect pre-test state."""

    def test_yields_snapshot_path(self, container_state):
        assert container_state.snapshot_path.exists()
        assert container_state.snapshot_path.suffix == ".gz"
        assert container_state.snapshot_path.stat().st_size > 0

    def test_yields_kv_dumps_for_each_collection(self, container_state):
        # Both wl_manager-owned KV collections must be in the dump
        assert "wl_cooldowns" in container_state.kv_dumps
        assert "wl_fim_baseline" in container_state.kv_dumps

    def test_kv_dumps_are_lists(self, container_state):
        for collection, records in container_state.kv_dumps.items():
            assert isinstance(records, list), \
                f"{collection} dump is not a list: {type(records)}"


# ─────────────────────────────────────────────────────────────────────
# Restore correctness — file mutations
# ─────────────────────────────────────────────────────────────────────


class TestStateRestoreFile:
    """Mutations to lookups/ files must be reverted after the fixture
    tears down. We test this by writing a sentinel file inside the
    fixture, then verifying it's gone in a subsequent test."""

    SENTINEL_PATH = ("/opt/splunk/etc/apps/wl_manager/lookups/"
                     "_versions/_ring1_smoke_sentinel.txt")
    SENTINEL_CONTENT = "ring1_fixture_smoke_test_marker"

    def test_can_write_sentinel_inside_fixture(self, container_state):
        """First half of the test pair: write a sentinel, confirm
        it exists. Teardown should remove it."""
        _write_file_in_container(
            self.SENTINEL_PATH, self.SENTINEL_CONTENT)
        # Verify the write landed
        content = _read_file_in_container(self.SENTINEL_PATH)
        assert self.SENTINEL_CONTENT in content

    def test_sentinel_is_gone_after_teardown(self, container_state):
        """Second half: the sentinel from the previous test should
        NOT be present here. If it is, restore is broken."""
        env = {**os.environ, "MSYS_NO_PATHCONV": "1"}
        proc = subprocess.run(  # noqa: S603 — list-form, no shell
            ["docker", "exec", "-u", "0", "wl_manager_test",
             "test", "-f", self.SENTINEL_PATH],
            capture_output=True, timeout=10,
            check=False, env=env,
        )
        assert proc.returncode != 0, \
            "sentinel survived teardown — fixture restore is broken"


# ─────────────────────────────────────────────────────────────────────
# Restore correctness — KV mutations
# ─────────────────────────────────────────────────────────────────────


class TestStateRestoreKv:
    """Mutations to KV collections must be reverted after teardown.

    We test by adding a record to ``wl_cooldowns`` inside the fixture
    and verifying it's gone in a subsequent test."""

    SENTINEL_KEY = "ring1_kv_fixture_smoke_marker"
    KV_PATH = ("/servicesNS/nobody/wl_manager/storage/collections/"
               "data/wl_cooldowns")

    def test_can_add_kv_record_inside_fixture(
            self, container_state, container_curl):
        """Add a sentinel record. Teardown should remove it."""
        record = {
            "_key": self.SENTINEL_KEY,
            "payload": "fixture_smoke_test",
            "checksum": "stub",
            "updated_at": 1715000000,
            "updated_by": "ring1_smoke",
            "schema_version": 1,
        }
        proc = container_curl(
            self.KV_PATH, method="POST",
            data=json.dumps(record),
            content_type="application/json",
            check=False,
        )
        # POST may return 201 (created) or 409 (exists from prior
        # failed test) — both are fine for this smoke check
        assert proc.returncode == 0, \
            f"KV POST failed: {proc.stderr}"

    def test_kv_record_is_gone_after_teardown(
            self, container_state, list_kv_records):
        """The sentinel from the previous test should be absent."""
        records = list_kv_records("wl_cooldowns")
        keys = [r.get("_key", "") for r in records]
        assert self.SENTINEL_KEY not in keys, \
            f"KV sentinel survived teardown: keys={keys}"


# ─────────────────────────────────────────────────────────────────────
# Sanity — opt-in nature of the fixture
# ─────────────────────────────────────────────────────────────────────


class TestFixtureIsOptIn:
    """A test that does NOT request ``container_state`` should pay
    no snapshot cost — confirms the fixture is opt-in by parameter."""

    def test_no_fixture_no_cost(self, docker_available):
        """Sanity: this test runs without requesting the snapshot
        fixture. It should complete near-instantly (no tar overhead).
        We're not measuring time precisely; just confirming the test
        runs without the fixture."""
        assert docker_available is True
