"""
Integration test fixtures — container-state snapshot and restore.

These fixtures isolate state-mutating tests from each other so test
order doesn't matter and one test's KV/file changes don't bleed into
the next. The user's explicit Ring 1 decision was "container tests
for accuracy" over speed; this fixture is the price we pay for that
accuracy.

Architecture
------------

The handler keeps state in two places:

1. **Filesystem**: ``$SPLUNK_HOME/etc/apps/wl_manager/lookups/``
   - Approval queue + sig sidecar
   - Daily limits, notifications, trash config, lockdown,
     cooldowns, FIM deploy window
   - FIM baseline + alert state, CSV expected hashes, presence
   - Trash directory, version snapshots, all CSV lookup files
   - Recovery log (append-only)

2. **KV store** (Splunk-managed):
   - ``wl_cooldowns`` — rate-limit counters
   - ``wl_fim_baseline`` — dual-store FIM baseline mirror

Splunk's audit indexes (``wl_audit``, ``_internal``) are NOT reset
by this fixture — events emitted by a test stay in the index. Tests
that need to verify audit emission should embed a unique marker in
the event and query by that marker (see ``audit_query`` fixture
to be added in Ring 1 Day 4).

Strategy
--------

**Snapshot** (before each state-mutating test):

1. ``tar -czf /tmp/wl_state_<uuid>.tar.gz`` over ``lookups/`` —
   captures all on-disk state in one atomic file
2. ``curl`` each KV collection to JSON, save to local host

**Yield** to test.

**Restore** (after the test, even on failure):

1. ``rm -rf lookups/`` then untar the snapshot back in place
2. ``DELETE`` then ``POST`` to repopulate each KV collection

All subprocess invocations use ``subprocess.run([list, of, args])``
(no shell, no string interpolation) — the Splunk credentials and
container name are baked-in module constants, never user input.

Cost
----

~2-4 seconds per state-mutating test (tar + KV dump + restore +
KV repopulate). For tests that don't request the fixture, the cost
is zero — the fixture is opt-in via parameter name.

When NOT to use this fixture
----------------------------

- Read-only tests (``get_csv_content``, ``get_pending_approvals``,
  ``list_trash``) — no state mutation, no need to snapshot
- Tests of pure-function helpers — those belong in ``tests/unit/``
- Tests that only verify dispatch table integrity — no state
"""

import os
import json
import subprocess
import sys
import uuid
from pathlib import Path

import pytest


CONTAINER_NAME = "wl_manager_test"
SPLUNK_USER = "admin"
SPLUNK_PASSWORD = "Chang3d!"
APP_PATH = "/opt/splunk/etc/apps/wl_manager"
LOOKUPS_REL = "lookups"  # relative to APP_PATH

# Per CLAUDE.md and the prior session feedback
# (feedback_use_role_specific_accounts.md): always verify as the
# wl-specific role accounts, never as the built-in admin. Built-in
# admin has all roles but the wl-specific users exercise the
# actual RBAC paths the production app uses.
#
# All four users share the same password; they differ only in
# assigned roles (configured in default/authorize.conf and the
# container's setup script).
WL_USERS = {
    "admin":       {"password": SPLUNK_PASSWORD},  # built-in
    "superadmin1": {"password": SPLUNK_PASSWORD},
    "wladmin1":    {"password": SPLUNK_PASSWORD},
    "analyst1":    {"password": SPLUNK_PASSWORD},
}

# KV collections owned by wl_manager. Only these get snapshotted +
# restored; built-in Splunk collections (HomePage, SearchHistory)
# are out of scope.
WL_KV_COLLECTIONS = ("wl_cooldowns", "wl_fim_baseline")


# ─────────────────────────────────────────────────────────────────────
# Container helpers — all use list-form subprocess.run (no shell)
# ─────────────────────────────────────────────────────────────────────


def _run_in_container(*args: str, check: bool = True,
                      timeout: int = 30) -> subprocess.CompletedProcess:
    """Run a command inside ``wl_manager_test`` as root.

    Wraps ``docker exec -u 0 wl_manager_test ...`` with sane
    defaults: 30s timeout, raises on non-zero exit by default.
    Set ``check=False`` for commands where non-zero is expected
    (e.g., probe commands).

    All arguments are passed as a list — no shell interpretation,
    no injection vector.
    """
    env = {**os.environ, "MSYS_NO_PATHCONV": "1"}
    cmd = ["docker", "exec", "-u", "0", CONTAINER_NAME, *args]
    return subprocess.run(  # noqa: S603 — list-form, no shell
        cmd, capture_output=True, text=True, timeout=timeout,
        check=check, env=env,
    )


def _container_curl(path: str, method: str = "GET",
                    data: str = None, content_type: str = None,
                    check: bool = True,
                    timeout: int = 30,
                    user: str = SPLUNK_USER,
                    password: str = None
                    ) -> subprocess.CompletedProcess:
    """Run a curl against the container's local Splunk REST endpoint.

    The container makes localhost:8089 the management port. We run
    curl INSIDE the container to avoid host-side cert + auth
    complications. Returns the CompletedProcess.

    To call as a non-default user, pass ``user=`` (and optionally
    ``password=``; defaults to the password from ``WL_USERS`` for
    the named user). Tests that need to verify role-specific
    behavior (RBAC enforcement, dual-admin approval, superadmin-only
    actions) use this to bypass the built-in admin account.

    Auto-retry on rate-limit
    ------------------------

    The handler's REST endpoint enforces a per-user sliding-window
    rate limit (30 writes / 120 reads per 60 seconds — see
    ``bin/wl_ratelimit.py``). A test suite that issues many rapid
    requests as the same user can hit the limit and see
    ``"Rate limit exceeded"`` even when each individual call is
    legitimate. Tests want to assert real behavior, not race the
    rate limiter.

    On detection of the rate-limit response we sleep briefly and
    retry up to 2 times. The retry preserves test semantics — the
    same call is re-issued, and if it succeeds the test sees the
    success it expected. If the limit is genuinely exhausted (very
    rare in practice) the third attempt returns the rate-limit
    response and the test handles it normally.
    """
    if password is None:
        password = WL_USERS.get(user, {}).get(
            "password", SPLUNK_PASSWORD)

    def _do_call():
        args = ["curl", "-sk", "-u",
                f"{user}:{password}",
                "-X", method,
                f"https://localhost:8089{path}"]
        if data is not None:
            args.extend(["-d", data])
        if content_type is not None:
            args.extend(["-H", f"Content-Type: {content_type}"])
        return _run_in_container(*args, check=check,
                                 timeout=timeout)

    proc = _do_call()
    # Retry up to 2 times on rate-limit response. The handler
    # returns the literal string "Rate limit exceeded" in JSON
    # error responses; we match against it conservatively.
    for retry in range(2):
        if "Rate limit exceeded" not in (proc.stdout or ""):
            break
        # Wait for the sliding window to drain. The window is 60s
        # but recent timestamps prune progressively, so 3-5s is
        # usually enough to free a slot.
        import time as _time
        _time.sleep(3 + retry * 2)
        proc = _do_call()

    return proc


def _list_kv_records(collection: str) -> list:
    """Return all records in a KV collection as a list of dicts.

    Returns ``[]`` if the collection is empty or missing. Raises
    if Splunk returns a non-success status (other than 404 which
    we treat as "collection has no records yet").
    """
    path = (f"/servicesNS/nobody/wl_manager/storage/collections/"
            f"data/{collection}?output_mode=json")
    proc = _container_curl(path, check=False)
    if proc.returncode != 0:
        raise RuntimeError(
            f"curl to {collection} failed: {proc.stderr}")
    body = proc.stdout.strip()
    if not body:
        return []
    try:
        records = json.loads(body)
    except json.JSONDecodeError as exc:
        # Splunk returns HTML on 404 sometimes; treat as empty
        if body.lstrip().startswith("<"):
            return []
        raise RuntimeError(
            f"KV collection {collection} returned non-JSON: "
            f"{body[:200]} ({exc})")
    if not isinstance(records, list):
        # Error envelope from Splunk
        raise RuntimeError(
            f"KV collection {collection} returned non-list: "
            f"{records}")
    return records


def _restore_kv_collection(collection: str, records: list) -> None:
    """Replace the contents of a KV collection with ``records``.

    Strategy: DELETE every existing record, then POST each
    snapshot record back. Done one record at a time because
    Splunk's batch_save endpoint has a different schema than
    individual record updates and we want to preserve _key.
    """
    base = (f"/servicesNS/nobody/wl_manager/storage/collections/"
            f"data/{collection}")

    # Delete all existing
    proc = _container_curl(base, method="DELETE", check=False)
    if proc.returncode != 0:
        raise RuntimeError(
            f"failed to clear KV {collection}: {proc.stderr}")

    # Repost the snapshot
    for record in records:
        # _key is preserved from the original record so anything
        # that references the record by key still works
        body = json.dumps(record)
        proc = _container_curl(base, method="POST",
                               data=body,
                               content_type="application/json",
                               check=False)
        if proc.returncode != 0:
            raise RuntimeError(
                f"failed to POST record to {collection}: "
                f"{proc.stderr}")


# ─────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def docker_available() -> bool:
    """Skip the test class if the test container isn't reachable.

    Use as a fixture parameter on every test class marked with
    ``@pytest.mark.docker``. The actual logic just checks docker
    inspect; tests that need a more thorough probe (e.g., Splunk
    REST is responding) should layer their own readiness check
    on top.
    """
    try:
        proc = subprocess.run(  # noqa: S603 — list-form, no shell
            ["docker", "inspect", CONTAINER_NAME],
            capture_output=True, timeout=5,
        )
        if proc.returncode != 0:
            pytest.skip(f"container {CONTAINER_NAME} not running")
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pytest.skip("docker not available")
    return True


@pytest.fixture(scope="session", autouse=True)
def _restore_canonical_demo_state(docker_available, request):
    """Copy host ``lookups/`` into the container at session start.

    Why this exists (R2-D7 cascade root cause)
    ------------------------------------------

    ``container_state`` (function-scoped) snapshots whatever state
    exists at test start. If a previous test session crashed
    mid-run, hit a teardown error, or hung partway through —
    leaving the container in a damaged state (e.g., missing
    ``rule_csv_map.csv``) — every subsequent ``container_state``
    snapshot captures the damage and propagates it forward
    through the entire suite. Symptom: tests pass in isolation
    but fail in a full suite run with errors like ``CSV file
    not found``, ``no mappings in demo state``, ``rule_csv_map.csv
    not found``.

    This session-level fixture short-circuits the inheritance:
    every session starts by force-restoring the
    version-controlled ``lookups/`` directory (the committed
    canonical demo state) into the container, so tests always
    begin from a known-good baseline regardless of how the prior
    session ended.

    Disabled when:

    - ``WL_SKIP_STATE_RESTORE=1`` is set (escape hatch for
      benchmarking against a custom container state)
    - ``--no-state-restore`` is passed to pytest (same)

    The restore is idempotent: copying host files into a
    matching container directory just overwrites identical files
    in place. Cost is ~1-2s per session.
    """
    if os.environ.get("WL_SKIP_STATE_RESTORE") == "1":
        return
    if request.config.getoption("--no-state-restore", default=False):
        return

    # Locate the host's lookups/ directory. ``conftest.py`` lives
    # at ``tests/integration/conftest.py``, so two parents up is
    # the repo root.
    repo_root = Path(__file__).resolve().parents[2]
    host_lookups = repo_root / "lookups"
    if not host_lookups.is_dir():
        # Repo not laid out as expected — skip rather than fail.
        # Tests that depend on demo state will skip with their
        # own "no mappings in demo state" check.
        return

    # Copy host lookups/ → container lookups/, then chown to splunk
    env = {**os.environ, "MSYS_NO_PATHCONV": "1"}
    cp_proc = subprocess.run(  # noqa: S603 — list-form, no shell
        ["docker", "cp",
         str(host_lookups) + os.sep + ".",
         f"{CONTAINER_NAME}:{APP_PATH}/{LOOKUPS_REL}/"],
        capture_output=True, text=True, timeout=30,
        check=False, env=env,
    )
    if cp_proc.returncode != 0:
        # Soft-fail: log but don't break the session.
        sys.stderr.write(
            f"warning: canonical state restore (docker cp) "
            f"returned {cp_proc.returncode}: {cp_proc.stderr}\n")
        return
    # Ensure runtime-state subdirectories exist inside the container.
    # `lookups/_versions/` is .gitignored (its contents are runtime
    # state — version snapshots, FIM baseline, cooldown markers — that
    # don't belong in version control), so on a fresh CI checkout the
    # directory doesn't exist on the host and `docker cp` above copies
    # nothing for it. Without `_versions/` present, the handler can't
    # write version snapshots, FIM can't write its baseline, and
    # several tests fail with "directory does not exist" cascades.
    # `_trash/` is partially git-tracked (specific items inside) so it
    # usually exists on checkout, but ensure here for symmetry and
    # robustness against an empty-`_trash/` edge case.
    subprocess.run(  # noqa: S603 — list-form, no shell
        ["docker", "exec", "-u", "0", CONTAINER_NAME,
         "mkdir", "-p",
         f"{APP_PATH}/{LOOKUPS_REL}/_versions",
         f"{APP_PATH}/{LOOKUPS_REL}/_trash"],
        capture_output=True, timeout=10,
        check=False, env=env,
    )
    # Chown so Splunk can read/write the restored files
    subprocess.run(  # noqa: S603 — list-form, no shell
        ["docker", "exec", "-u", "0", CONTAINER_NAME,
         "chown", "-R", "splunk:splunk",
         f"{APP_PATH}/{LOOKUPS_REL}"],
        capture_output=True, timeout=10,
        check=False, env=env,
    )


def pytest_addoption(parser):
    """Register the ``--no-state-restore`` flag so the
    session-level state restore can be disabled without
    setting the env var (useful for repeated runs in
    quick-iteration mode)."""
    parser.addoption(
        "--no-state-restore", action="store_true",
        default=False,
        help="Skip the session-start canonical-state restore "
             "(see _restore_canonical_demo_state in conftest.py).",
    )


@pytest.fixture
def container_state(docker_available, tmp_path):
    """Snapshot + restore container state around a test.

    Use this fixture in any integration test that mutates state.
    The fixture:

    1. Tars ``lookups/`` to a snapshot file in ``tmp_path``
    2. Dumps each KV collection to JSON in ``tmp_path``
    3. Yields control to the test
    4. After the test (success or failure), restores the snapshot

    The fixture has function scope, so each test gets its own
    snapshot. Test order doesn't matter; failures don't pollute
    the next test.

    Yields
    ------
    A small helper object with:

    - ``snapshot_path`` (Path): the tar.gz of the snapshotted
      ``lookups/`` directory, useful for tests that want to
      inspect the pre-test state
    - ``kv_dumps`` (dict): {collection_name: [records...]} of the
      KV state at snapshot time
    """
    # ── Snapshot ────────────────────────────────────────────────
    snapshot_id = uuid.uuid4().hex[:8]
    container_tar = f"/tmp/wl_state_{snapshot_id}.tar.gz"

    # tar lookups/ inside the container — atomic, captures all
    # files including dotfiles. Excludes nothing; everything
    # under lookups/ is application state.
    proc = _run_in_container(
        "tar", "-czf", container_tar, "-C", APP_PATH, LOOKUPS_REL,
        check=False, timeout=60,
    )
    if proc.returncode != 0:
        pytest.fail(
            f"snapshot tar failed: {proc.stderr}\n"
            f"stdout: {proc.stdout}")

    # Copy tar to host temp dir for safekeeping (in case container
    # restarts mid-test)
    host_snapshot = tmp_path / f"wl_state_{snapshot_id}.tar.gz"
    cp_proc = subprocess.run(  # noqa: S603 — list-form, no shell
        ["docker", "cp",
         f"{CONTAINER_NAME}:{container_tar}",
         str(host_snapshot)],
        capture_output=True, text=True, timeout=60,
        env={**os.environ, "MSYS_NO_PATHCONV": "1"},
    )
    if cp_proc.returncode != 0:
        pytest.fail(
            f"docker cp failed: {cp_proc.stderr}")

    # Dump KV collections to JSON files in tmp_path
    kv_dumps = {}
    for collection in WL_KV_COLLECTIONS:
        try:
            kv_dumps[collection] = _list_kv_records(collection)
        except RuntimeError as exc:
            # Some KV collections may not be created yet on a
            # fresh container — treat as empty
            print(f"warning: KV {collection} dump skipped: {exc}")
            kv_dumps[collection] = []

    # ── Build snapshot handle for the test ──────────────────────
    class SnapshotHandle:
        pass
    handle = SnapshotHandle()
    handle.snapshot_path = host_snapshot
    handle.kv_dumps = kv_dumps
    handle.container_tar = container_tar

    # ── Yield to test ───────────────────────────────────────────
    try:
        yield handle
    finally:
        # ── Restore (always, even on test failure) ─────────────
        _restore_container_state(host_snapshot, kv_dumps,
                                 container_tar)


def _restore_container_state(host_snapshot: Path,
                             kv_dumps: dict,
                             container_tar: str) -> None:
    """Restore lookups/ and KV collections from a snapshot.

    Best-effort: if the container_tar is gone (container
    restarted mid-test), we re-copy from the host snapshot.
    """
    # If the in-container tar still exists, use it directly. If
    # not, restore from the host copy.
    probe = _run_in_container("test", "-f", container_tar,
                              check=False)
    if probe.returncode != 0:
        # Container restarted? Copy host snapshot back in.
        cp_proc = subprocess.run(  # noqa: S603 — list-form
            ["docker", "cp", str(host_snapshot),
             f"{CONTAINER_NAME}:{container_tar}"],
            capture_output=True, text=True, timeout=60,
            env={**os.environ, "MSYS_NO_PATHCONV": "1"},
        )
        if cp_proc.returncode != 0:
            raise RuntimeError(
                f"restore copy-back failed: {cp_proc.stderr}")

    # Wipe lookups/ then untar the snapshot back into APP_PATH.
    # We use rm -rf on lookups/ specifically — NOT on the whole
    # app dir — because default/, bin/, appserver/ are read-only
    # from a test's perspective.
    _run_in_container(
        "rm", "-rf", f"{APP_PATH}/{LOOKUPS_REL}",
        check=True, timeout=30,
    )
    _run_in_container(
        "tar", "-xzf", container_tar, "-C", APP_PATH,
        check=True, timeout=60,
    )

    # Restore KV collections
    for collection, records in kv_dumps.items():
        try:
            _restore_kv_collection(collection, records)
        except RuntimeError as exc:
            # Don't fail teardown — a KV restore failure means
            # the test container is in an indeterminate state
            # but failing here would mask the test's actual
            # failure. Log and continue.
            print(f"WARNING: KV {collection} restore failed: "
                  f"{exc}")

    # Clean up the in-container tar
    _run_in_container("rm", "-f", container_tar, check=False)


# ─────────────────────────────────────────────────────────────────────
# Helper fixtures exposed to tests
# ─────────────────────────────────────────────────────────────────────


@pytest.fixture
def container_curl():
    """Expose ``_container_curl`` to tests as a fixture.

    Tests that don't mutate state (and so don't need
    ``container_state``) often still need to issue REST calls.
    """
    return _container_curl


@pytest.fixture
def list_kv_records():
    """Expose KV record listing to tests."""
    return _list_kv_records
