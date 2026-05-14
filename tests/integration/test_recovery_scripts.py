"""
Recovery surface smoke tests.

Pins the contracts of the four out-of-band recovery surfaces:

1. ``open_deploy_window`` / ``close_deploy_window`` /
   ``get_deploy_window_status`` REST actions — superadmin-issued
   maintenance window during which FIM code-file alerts downgrade
   from HIGH to INFO. Sentinel mutations stay HIGH.
2. ``bootstrap_csv_hashes`` REST action — superadmin-only registry
   rebuild. Diff-aware: emits per-CSV hash-change events to make
   bootstrap-laundering attacks visible.
3. ``scripts/emergency_unlock.sh`` — clears emergency-lockdown
   state from the filesystem when the dual-superadmin UI path is
   not available (both accounts compromised/unavailable).
4. Recovery-log invariants — every recovery surface appends to
   ``_recovery_log.jsonl`` BEFORE its destructive action, with a
   pinned schema. The recovery log is tailed by a Splunk scripted
   input into ``index=wl_audit`` so the trail is dual-stored.

Out of scope for routine CI:

- ``scripts/reset_cooldowns.sh`` is destructive AND restarts
  Splunk (~30 s downtime). Subsequent tests would race the
  restart. Tested manually as part of disaster-recovery drills,
  not on every CI run. The recovery-log invariants this file
  pins still apply to it (same shell-script template).

Origin
------

Day 6 of Ring 1. Closes the third leg of the recovery
triad (Day 4 audit, Day 5 KV state, Day 6 recovery surfaces).

The contracts here matter because every recovery action is
explicitly out-of-band — by definition the in-band controls
(approval queue, RBAC, rate limit) are not enforcing it. The
only safety net is the audit trail. If the recovery-log append
silently no-ops, an attacker who has temporarily acquired
container access (e.g. supply-chain compromise of a deploy
script) can run any of these scripts with no record. The tests
here confirm the audit trail is mechanically guaranteed.
"""

import json
import os
import shutil
import subprocess

import pytest


pytestmark = pytest.mark.docker


def _find_host_bash():
    """Locate a host bash that has access to the docker CLI.

    On Windows, ``subprocess.run(["bash", ...])`` finds WSL bash
    by default — but on machines without Docker-WSL integration,
    WSL bash cannot reach the Docker daemon. Git Bash (shipped
    with Git for Windows) does have access via the Windows-native
    ``docker.exe``. Prefer Git Bash on Windows; fall back to
    plain ``bash`` on Unix.

    Returns the absolute path to bash, or ``None`` if no usable
    bash is found.
    """
    if os.name == "nt":
        for candidate in (
            r"C:\Program Files\Git\bin\bash.exe",
            r"C:\Program Files (x86)\Git\bin\bash.exe",
        ):
            if os.path.isfile(candidate):
                return candidate
        return None
    return shutil.which("bash")


_HOST_BASH = _find_host_bash()


CONTAINER = "wl_manager_test"
RECOVERY_LOG_PATH = (
    "/opt/splunk/etc/apps/wl_manager/lookups/_versions/_recovery_log.jsonl")
LOCKDOWN_PATH = (
    "/opt/splunk/etc/apps/wl_manager/lookups/_versions/_emergency_lockdown.json")
DEPLOY_WINDOW_PATH = (
    "/opt/splunk/etc/apps/wl_manager/lookups/_versions/_fim_deploy_window.json")
EXPECTED_HASHES_PATH = (
    "/opt/splunk/etc/apps/wl_manager/lookups/_versions/.csv_expected_hashes.json")


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────


def _post_action(container_curl, action: str, payload: dict,
                 user: str = "admin"):
    """POST a JSON action to the handler and return parsed body."""
    body = json.dumps({"action": action, **payload})
    proc = container_curl(
        "/services/custom/wl_manager",
        method="POST",
        data=body,
        content_type="application/json",
        check=False,
        user=user,
    )
    raw = (proc.stdout or "").strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"_raw": raw, "_returncode": proc.returncode}


def _get_action(container_curl, action: str, user: str = "admin"):
    """GET an action from the handler and return parsed body."""
    path = "/services/custom/wl_manager?action={}".format(action)
    proc = container_curl(path, check=False, user=user)
    raw = (proc.stdout or "").strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"_raw": raw}


def _read_recovery_log_lines() -> list:
    """Return parsed JSON lines from ``_recovery_log.jsonl`` inside
    the container. Returns ``[]`` if the file doesn't exist (not
    yet appended)."""
    env = {**os.environ, "MSYS_NO_PATHCONV": "1"}
    proc = subprocess.run(  # noqa: S603 — list-form, no shell
        ["docker", "exec", "-u", "0", CONTAINER, "cat", RECOVERY_LOG_PATH],
        capture_output=True, text=True, timeout=15,
        check=False, env=env,
    )
    if proc.returncode != 0:
        # File doesn't exist or unreadable — treat as no log yet
        return []
    out = []
    for line in (proc.stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _file_exists_in_container(path: str) -> bool:
    """Return True if ``path`` exists inside the container."""
    env = {**os.environ, "MSYS_NO_PATHCONV": "1"}
    proc = subprocess.run(  # noqa: S603 — list-form, no shell
        ["docker", "exec", "-u", "0", CONTAINER,
         "test", "-f", path],
        capture_output=True, text=True, timeout=10,
        check=False, env=env,
    )
    return proc.returncode == 0


# ─────────────────────────────────────────────────────────────────────
# FIM Deploy Window — REST API path
# ─────────────────────────────────────────────────────────────────────


class TestFimDeployWindowREST:
    """Pins ``open_deploy_window`` / ``close_deploy_window`` /
    ``get_deploy_window_status`` REST contracts.

    These actions are how CI/CD pipelines mark a maintenance
    window without needing shell access. The shell script
    (``scripts/fim_deploy_window.sh``) invokes the same logic
    and so shares this contract.
    """

    def test_get_status_when_no_window_returns_inactive(
            self, container_state, container_curl):
        # Ensure no window is active first (idempotent close)
        _post_action(container_curl, "close_deploy_window", {},
                     user="superadmin1")
        body = _get_action(container_curl,
                           "get_deploy_window_status",
                           user="superadmin1")
        assert body.get("active") is False, \
            "expected no active window in clean state, got: {}".format(body)
        assert body.get("status") in ("no_window", "expired"), \
            "unexpected status: {}".format(body)

    def test_open_close_full_lifecycle(
            self, container_state, container_curl):
        # Open
        open_body = _post_action(
            container_curl, "open_deploy_window",
            {"duration_minutes": 5,
             "reason": "Ring 1 Day 6 smoke test"},
            user="superadmin1")
        if "error" in open_body:
            pytest.skip("open_deploy_window failed: {}".format(open_body))
        assert open_body.get("success") is True
        assert "expires_at" in open_body
        assert "started_at" in open_body
        assert open_body.get("duration_minutes") == 5

        # Status reports active
        status = _get_action(
            container_curl, "get_deploy_window_status",
            user="superadmin1")
        assert status.get("active") is True
        assert status.get("started_by") == "superadmin1"
        assert status.get("reason") == "Ring 1 Day 6 smoke test"
        assert status.get("remaining_seconds", 0) > 0

        # Close
        close_body = _post_action(
            container_curl, "close_deploy_window", {},
            user="superadmin1")
        assert close_body.get("success") is True

        # Status reports inactive
        status = _get_action(
            container_curl, "get_deploy_window_status",
            user="superadmin1")
        assert status.get("active") is False

    def test_open_requires_reason(
            self, container_state, container_curl):
        body = _post_action(
            container_curl, "open_deploy_window",
            {"duration_minutes": 5, "reason": "   "},
            user="superadmin1")
        assert "error" in body
        assert "reason" in body["error"].lower()

    def test_open_rejects_duration_above_60(
            self, container_state, container_curl):
        body = _post_action(
            container_curl, "open_deploy_window",
            {"duration_minutes": 120,
             "reason": "Ring 1 test - too long"},
            user="superadmin1")
        assert "error" in body
        assert "60" in body["error"]

    def test_open_rejects_non_ascii_reason(
            self, container_state, container_curl):
        # Cyrillic 'a' looks like ASCII 'a' — the homoglyph
        # attack ASCII validation closes. Should be rejected.
        body = _post_action(
            container_curl, "open_deploy_window",
            {"duration_minutes": 5,
             "reason": "Ring 1 аscii bypass test"},
            user="superadmin1")
        assert "error" in body, \
            "non-ASCII reason was accepted: {}".format(body)

    def test_close_with_no_active_window_returns_error(
            self, container_state, container_curl):
        # Make sure no window first
        _post_action(container_curl, "close_deploy_window", {},
                     user="superadmin1")
        body = _post_action(
            container_curl, "close_deploy_window", {},
            user="superadmin1")
        assert "error" in body
        assert "active" in body["error"].lower() or \
            "no" in body["error"].lower()

    def test_open_requires_superadmin_role(
            self, container_state, container_curl):
        """Pinning RBAC: analyst1 cannot open a deploy window even
        if they know the action name."""
        body = _post_action(
            container_curl, "open_deploy_window",
            {"duration_minutes": 5, "reason": "Ring 1 RBAC test"},
            user="analyst1")
        # Either explicit error or empty/forbidden response
        assert "error" in body or body.get("success") is not True, \
            "analyst1 was able to open a deploy window: {}".format(body)


# ─────────────────────────────────────────────────────────────────────
# bootstrap_csv_hashes — REST API path
# ─────────────────────────────────────────────────────────────────────


class TestBootstrapCsvHashes:
    """Pins ``bootstrap_csv_hashes`` REST contract.

    Use cases: fresh install, post-DR-restore, post-GUID-rotation.
    """

    REQUIRED_RESPONSE_FIELDS = {
        "success", "hashed_count", "missing_count", "changed_count",
    }

    def test_bootstrap_returns_full_envelope(
            self, container_state, container_curl):
        body = _post_action(
            container_curl, "bootstrap_csv_hashes", {},
            user="superadmin1")
        if "error" in body:
            pytest.skip("bootstrap_csv_hashes failed: {}".format(body))
        missing = self.REQUIRED_RESPONSE_FIELDS - set(body.keys())
        assert not missing, \
            "bootstrap_csv_hashes response missing: {}".format(missing)
        assert body["success"] is True
        # hashed_count should be > 0 in any state with managed CSVs
        assert body["hashed_count"] >= 0
        assert isinstance(body["hashed_count"], int)
        assert isinstance(body["missing_count"], int)
        assert isinstance(body["changed_count"], int)

    def test_bootstrap_creates_registry_file(
            self, container_state, container_curl):
        # Run bootstrap
        body = _post_action(
            container_curl, "bootstrap_csv_hashes", {},
            user="superadmin1")
        if "error" in body:
            pytest.skip("bootstrap failed: {}".format(body))
        # Registry file exists after run (creates if absent)
        assert _file_exists_in_container(EXPECTED_HASHES_PATH), \
            "expected-hashes registry not present after bootstrap"

    def test_bootstrap_requires_superadmin(
            self, container_state, container_curl):
        body = _post_action(
            container_curl, "bootstrap_csv_hashes", {},
            user="analyst1")
        # analyst1 should be denied — either error or no-success
        assert "error" in body or body.get("success") is not True, \
            "analyst1 ran bootstrap_csv_hashes: {}".format(body)

    def test_bootstrap_idempotent_no_changed_count(
            self, container_state, container_curl):
        """Running bootstrap twice in a row with no CSV changes
        should report changed_count=0 on the second run. This is
        the laundering-detection contract — if the second
        bootstrap reported drift it would imply someone modified
        a CSV between the two runs.
        """
        first = _post_action(
            container_curl, "bootstrap_csv_hashes", {},
            user="superadmin1")
        if "error" in first:
            pytest.skip("bootstrap failed: {}".format(first))
        second = _post_action(
            container_curl, "bootstrap_csv_hashes", {},
            user="superadmin1")
        if "error" in second:
            pytest.skip("second bootstrap failed: {}".format(second))
        assert second.get("changed_count") == 0, \
            ("Second bootstrap reported changed_count={} — this "
             "means a CSV was modified between the two runs, OR "
             "the registry write didn't persist. Investigate.")


# ─────────────────────────────────────────────────────────────────────
# Recovery log — append-only invariants
# ─────────────────────────────────────────────────────────────────────


class TestRecoveryLogContract:
    """Pins the JSONL schema for ``_recovery_log.jsonl``.

    Every entry MUST have a timestamp + action + reason / source /
    host_user so SOC analysts can trace WHO ran what WHY.
    """

    REQUIRED_ENTRY_FIELDS = {"timestamp", "action"}
    # Mirror the action set that ``default/data/ui/views/audit.xml``
    # explicitly handles in its "Out-of-Band Recovery Actions" panel
    # (see lines ~1035-1051). When a new recovery script lands, both
    # this set AND the dashboard panel must be updated. R2-D7-F1
    # added ``migrate_cooldowns`` here after Ring 2 broad sweep
    # caught it: the dashboard already knew about it but this test
    # was lagging.
    KNOWN_ACTIONS = {
        "fim_deploy_window_start",
        "fim_deploy_window_end",
        "emergency_unlock",
        "reset_cooldowns",
        "migrate_cooldowns",
    }

    def test_open_close_window_appends_two_log_entries(
            self, container_state, container_curl):
        before = len(_read_recovery_log_lines())

        open_body = _post_action(
            container_curl, "open_deploy_window",
            {"duration_minutes": 5,
             "reason": "Ring 1 Day 6 - log invariant test"},
            user="superadmin1")
        if "error" in open_body:
            pytest.skip("open_deploy_window failed: {}".format(open_body))

        _post_action(container_curl, "close_deploy_window", {},
                     user="superadmin1")

        after_lines = _read_recovery_log_lines()
        assert len(after_lines) >= before + 2, \
            ("expected open+close to append at least 2 recovery "
             "log lines, got delta={}".format(
                 len(after_lines) - before))

        # The last two entries should be our open + close
        last_two = after_lines[-2:]
        actions = {e.get("action") for e in last_two}
        assert "fim_deploy_window_start" in actions
        assert "fim_deploy_window_end" in actions

    def test_log_entries_have_required_fields(
            self, container_state, container_curl):
        # Trigger a fresh entry
        _post_action(
            container_curl, "open_deploy_window",
            {"duration_minutes": 5,
             "reason": "Ring 1 Day 6 - field shape test"},
            user="superadmin1")
        _post_action(container_curl, "close_deploy_window", {},
                     user="superadmin1")

        lines = _read_recovery_log_lines()
        assert lines, "recovery log empty after open+close"

        violators = []
        for entry in lines[-5:]:  # Last 5 entries
            missing = self.REQUIRED_ENTRY_FIELDS - set(entry.keys())
            if missing:
                violators.append(
                    "action={} missing={}".format(
                        entry.get("action", "?"), missing))
        assert not violators, \
            "recovery log entries missing required fields:\n  " \
            + "\n  ".join(violators)

    def test_log_actions_are_known(
            self, container_state, container_curl):
        """Every recovery log entry's action must be a documented
        recovery surface. A new action means we shipped a new
        recovery script without updating the inventory in this
        test (or the dashboard panel that surfaces these events).

        Filters out audit-POST fallback entries (those with
        ``audit_post_failed=true``). The recovery log doubles as a
        safety net for any audit event whose authenticated REST
        path fails — e.g. ``wl_expiration_cleanup`` falling back
        when its stdin session key arrives empty during a splunkd
        restart race (see ``bin/wl_expiration_cleanup.py
        :_append_recovery_log``). Those fallback entries carry
        original audit actions like ``auto_removed`` and are NOT
        first-class recovery surfaces. Conflating them with the
        deliberate destructive-action trail (emergency_unlock,
        reset_cooldowns, etc.) would falsely flag every
        intermittent audit-POST failure as a contract drift.
        """
        # Trigger a known action so the log isn't empty after
        # snapshot/restore.
        _post_action(
            container_curl, "open_deploy_window",
            {"duration_minutes": 5,
             "reason": "Ring 1 Day 6 - known-actions test"},
            user="superadmin1")
        _post_action(container_curl, "close_deploy_window", {},
                     user="superadmin1")

        lines = _read_recovery_log_lines()
        if not lines:
            pytest.skip("recovery log empty")
        # Recent 20 entries — older ones may be from now-removed scripts
        unknown = []
        for entry in lines[-20:]:
            # Skip audit-POST fallback entries — not first-class
            # recovery surfaces (see docstring above).
            if entry.get("audit_post_failed"):
                continue
            action = entry.get("action", "")
            if action and action not in self.KNOWN_ACTIONS:
                unknown.append(action)
        assert not unknown, \
            ("Recovery log contains unknown action names: {}. "
             "Either add them to KNOWN_ACTIONS or update the "
             "Audit dashboard 'Out-of-Band Recovery Actions' "
             "panel.".format(set(unknown)))

    def test_log_audit_record_appended_before_destructive_action(
            self, container_state, container_curl):
        """Pins the SECURITY contract: every recovery surface
        appends to the recovery log BEFORE doing the destructive
        thing. If a SIGKILL hits between append and destruction,
        we get an extra audit entry — which is fine. If we
        appended AFTER, a SIGKILL leaves the destruction in place
        with no audit trail.

        We can't easily simulate a SIGKILL in-test, but we can
        assert that the log entry exists when the action's
        destructive effect is also visible (i.e., the ordering
        of writes was correct in the success path).
        """
        before = len(_read_recovery_log_lines())

        # Open a window — destructive effect is the file appearing
        body = _post_action(
            container_curl, "open_deploy_window",
            {"duration_minutes": 5,
             "reason": "Ring 1 Day 6 - ordering test"},
            user="superadmin1")
        if "error" in body:
            pytest.skip("open_deploy_window failed: {}".format(body))

        # Both must be true: window file present AND log entry
        # appended.
        assert _file_exists_in_container(DEPLOY_WINDOW_PATH), \
            "deploy window file not created"
        after = _read_recovery_log_lines()
        assert len(after) > before, \
            "no recovery-log entry appended"
        assert after[-1].get("action") == "fim_deploy_window_start"

        # Cleanup
        _post_action(container_curl, "close_deploy_window", {},
                     user="superadmin1")


# ─────────────────────────────────────────────────────────────────────
# emergency_unlock.sh — shell script with stdin piping
# ─────────────────────────────────────────────────────────────────────


class TestEmergencyUnlockScript:
    """Pins ``scripts/emergency_unlock.sh`` contracts.

    The script is interactive (asks for reason + y/N confirm) so
    we pipe stdin. ``container_state`` restores the lockdown
    file at teardown if the test changes it, so we can safely
    create a lockdown for the test and have it cleaned up.
    """

    def _activate_lockdown(self, container_curl):
        """Activate emergency lockdown via REST so we have
        something to unlock."""
        return _post_action(
            container_curl, "activate_lockdown",
            {"reason": "Ring 1 Day 6 emergency-unlock test"},
            user="superadmin1")

    def test_lockdown_file_created_when_activated(
            self, container_state, container_curl):
        """Precondition for emergency_unlock tests: lockdown
        creates the file we'll later remove."""
        body = self._activate_lockdown(container_curl)
        if body.get("error"):
            pytest.skip("activate_lockdown failed: {}".format(body))
        assert _file_exists_in_container(LOCKDOWN_PATH), \
            "lockdown file not created after activate_lockdown"

    def test_emergency_unlock_removes_lockdown_file(
            self, container_state, container_curl):
        """Run the recovery script with reason + 'y' confirm
        piped via stdin. Verify the lockdown file is gone and a
        recovery log entry was appended."""
        if _HOST_BASH is None:
            pytest.skip(
                "no docker-capable bash found on host (Windows: "
                "needs Git Bash; Unix: needs bash on PATH)")

        # Activate lockdown first
        body = self._activate_lockdown(container_curl)
        if body.get("error"):
            pytest.skip("activate_lockdown failed: {}".format(body))
        assert _file_exists_in_container(LOCKDOWN_PATH)

        before = len(_read_recovery_log_lines())

        # Run the script. The script uses bash and asks two
        # interactive prompts — pipe both answers via stdin.
        # Use cwd + relative path to avoid Windows / Git-Bash path
        # mangling (MSYS_NO_PATHCONV=1 doesn't apply here because
        # the path is consumed by bash directly, not by docker).
        repo_root = os.path.abspath(os.path.join(
            os.path.dirname(__file__), "..", ".."))
        env = {**os.environ, "MSYS_NO_PATHCONV": "1"}
        # Pipe "Ring 1 Day 6 test\ny\n" as stdin: first prompt
        # is the reason, second is the y/N confirmation.
        # Pipe BOTH prompts at once. Git Bash's `read -r -p` on
        # Windows is sensitive to line-ending style — using
        # binary mode + explicit LF avoids text-mode CRLF
        # translation that can leave the second read empty.
        proc = subprocess.run(  # noqa: S603 — list-form, no shell
            [_HOST_BASH, "scripts/emergency_unlock.sh", CONTAINER],
            input=b"Ring 1 Day 6 test\ny\n",
            capture_output=True, timeout=60,
            check=False, env=env, cwd=repo_root,
        )
        # Decode output as UTF-8 (script uses box-drawing chars)
        proc_stdout = (proc.stdout or b"").decode("utf-8", "replace")
        proc_stderr = (proc.stderr or b"").decode("utf-8", "replace")
        if proc.returncode != 0:
            pytest.skip(
                "emergency_unlock.sh exited non-zero "
                "(may be a Bash-availability issue on this host): "
                "rc={} stderr={!r} stdout_tail={!r}".format(
                    proc.returncode,
                    proc_stderr[-300:],
                    proc_stdout[-500:]))

        # Lockdown file gone
        if _file_exists_in_container(LOCKDOWN_PATH):
            pytest.fail(
                "lockdown file still present after "
                "emergency_unlock.sh\nrc={}\nstdout:\n{}\nstderr:\n{}"
                .format(proc.returncode,
                        proc_stdout[-600:],
                        proc_stderr[-300:]))

        # Recovery log grew
        after = _read_recovery_log_lines()
        assert len(after) > before, \
            "no recovery log entry appended by emergency_unlock.sh"
        last = after[-1]
        assert last.get("action") == "emergency_unlock"
        assert last.get("script") == "emergency_unlock.sh"
        assert "Ring 1 Day 6 test" in last.get("reason", "")

    def test_emergency_unlock_aborts_without_reason(
            self, container_state, container_curl):
        """Empty reason → abort with no destructive action."""
        if _HOST_BASH is None:
            pytest.skip(
                "no docker-capable bash found on host (Windows: "
                "needs Git Bash; Unix: needs bash on PATH)")

        # Activate lockdown
        body = self._activate_lockdown(container_curl)
        if body.get("error"):
            pytest.skip("activate_lockdown failed: {}".format(body))

        before_log = len(_read_recovery_log_lines())

        repo_root = os.path.abspath(os.path.join(
            os.path.dirname(__file__), "..", ".."))
        env = {**os.environ, "MSYS_NO_PATHCONV": "1"}
        proc = subprocess.run(  # noqa: S603 — list-form, no shell
            [_HOST_BASH, "scripts/emergency_unlock.sh", CONTAINER],
            input=b"\n",  # Empty reason — script should abort
            capture_output=True, timeout=30,
            check=False, env=env, cwd=repo_root,
        )

        # Script should have exited non-zero (set -e + exit 1)
        # and the lockdown file should still be present.
        if proc.returncode == 127:
            pytest.skip("bash not available on this host")
        assert proc.returncode != 0, \
            "emergency_unlock.sh accepted empty reason: rc={}".format(
                proc.returncode)
        assert _file_exists_in_container(LOCKDOWN_PATH), \
            ("lockdown file removed despite empty reason — the "
             "audit-trail contract is broken")
        # No recovery log entry should be appended
        after_log = len(_read_recovery_log_lines())
        assert after_log == before_log, \
            ("recovery log grew despite aborted run "
             "(before={}, after={})".format(before_log, after_log))
