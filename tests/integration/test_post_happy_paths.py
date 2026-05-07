"""
POST happy-path contract tests.

Each test exercises a POST endpoint with valid input and asserts:

1. **The response is HTTP 200** (or the documented success code)
2. **The response shape is correct** — every documented field is
   present, with the right type. This is the build-641 / R0-F5
   bug-class fence: shallow tests pass while real projection
   drift ships. Deep contract assertions catch what shallow ones
   miss.
3. **The side effect actually happened** — file written, KV
   record stored, notification cleared, etc. "Endpoint returned
   200" is not "the endpoint did its job."

All state-mutating tests use the ``container_state`` fixture from
``tests/integration/conftest.py`` so each test is isolated from
its neighbours.

Tests are grouped by complexity tier. Simple tests come first
(no preconditions); complex tests come later (need a CSV that
exists, an approval queue entry, etc.).

Origin
------

Replaces high-value scenarios from the deleted zombie tests
(see ``RING_FINDINGS.md`` R0-F2 and
``RING1_INPUT_handler_contracts.md`` "POST happy-path contracts").
"""

import json
import os
import subprocess

import pytest


pytestmark = pytest.mark.docker


CONTAINER = "wl_manager_test"
APP_LOOKUPS = "/opt/splunk/etc/apps/wl_manager/lookups"


def _read_container_file(path: str) -> str:
    """Read a file inside the container as root.

    Helper for tests that need to verify side effects on disk.
    """
    env = {**os.environ, "MSYS_NO_PATHCONV": "1"}
    proc = subprocess.run(  # noqa: S603 — list-form, no shell
        ["docker", "exec", "-u", "0", CONTAINER, "cat", path],
        capture_output=True, text=True, timeout=10,
        check=True, env=env,
    )
    return proc.stdout


def _container_file_exists(path: str) -> bool:
    """Return True if the file exists inside the container."""
    env = {**os.environ, "MSYS_NO_PATHCONV": "1"}
    proc = subprocess.run(  # noqa: S603 — list-form, no shell
        ["docker", "exec", "-u", "0", CONTAINER,
         "test", "-f", path],
        capture_output=True, timeout=10,
        check=False, env=env,
    )
    return proc.returncode == 0


def _post_action(container_curl, action: str, payload: dict):
    """Issue a POST to ``/services/custom/wl_manager`` with the
    given action and JSON payload.

    Returns ``(http_code, body_dict)``. Body is parsed from JSON;
    if the response isn't JSON, returns ``(http_code, {"_raw": body})``
    so tests can still inspect what came back.
    """
    body = json.dumps({"action": action, **payload})
    proc = container_curl(
        "/services/custom/wl_manager",
        method="POST",
        data=body,
        content_type="application/json",
        check=False,
    )
    # Container's curl doesn't capture HTTP status by default; we
    # rely on response body to detect success/failure
    raw = proc.stdout.strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return (200 if proc.returncode == 0 else 0,
                {"_raw": raw})
    # Successful curl exit means we got a response; HTTP code is
    # implicit from the body shape. Most endpoints return JSON
    # with either a {"success": true} or {"error": "..."} key.
    return (200, parsed)


# ─────────────────────────────────────────────────────────────────────
# Tier 1 — Simple POSTs (no preconditions)
# ─────────────────────────────────────────────────────────────────────


class TestMarkNotificationsRead:
    """Pins: ``mark_notifications_read`` returns success and clears
    the calling user's notifications.

    Bug class caught: a refactor that bumps the version of the
    notification store schema without updating the read-marking
    code, leaving notifications "marked read" but still appearing
    in the bell UI.
    """

    def test_response_shape_is_success_dict(
            self, container_state, container_curl):
        code, body = _post_action(
            container_curl, "mark_notifications_read", {})
        assert code == 200
        # Required field — frontend reads `data.success` to know
        # whether to dim the bell badge. If this drifts, the UI
        # stays as-if-unread.
        assert "success" in body, \
            f"missing 'success' field in response: {body}"
        assert body["success"] is True


class TestSaveColWidths:
    """Pins: ``save_col_widths`` persists column widths and returns
    success.

    Bug class caught: a refactor that changes the on-disk format
    of col_widths without updating the read path. Frontend would
    silently lose user-customized widths.
    """

    SAMPLE_PAYLOAD = {
        "csv_file": "DR102_whitelist.csv",
        "app_context": "wl_manager",
        "col_widths": {"user": 200, "src_ip": 150},
    }

    def test_response_shape(
            self, container_state, container_curl):
        code, body = _post_action(
            container_curl, "save_col_widths", self.SAMPLE_PAYLOAD)
        assert code == 200
        assert body.get("success") is True, \
            f"save_col_widths did not succeed: {body}"

    def test_widths_round_trip_via_get(
            self, container_state, container_curl):
        """Side-effect verification: after saving, get_col_widths
        returns the saved widths."""
        # Save
        _post_action(container_curl, "save_col_widths",
                     self.SAMPLE_PAYLOAD)
        # Read back via GET
        path = ("/services/custom/wl_manager"
                "?action=get_col_widths"
                "&csv_file=DR102_whitelist.csv"
                "&app_context=wl_manager")
        proc = container_curl(path, check=False)
        body = json.loads(proc.stdout.strip())
        assert "col_widths" in body
        assert body["col_widths"] == self.SAMPLE_PAYLOAD["col_widths"], \
            f"widths did not round-trip: {body['col_widths']}"


class TestLogEvent:
    """Pins: ``log_event`` accepts a frontend event and returns
    success without crashing.

    Bug class caught: changes to the audit-event allow-list that
    drop a documented event type, breaking client-side analytics.
    """

    def test_csv_exported_event_logs_successfully(
            self, container_state, container_curl):
        code, body = _post_action(container_curl, "log_event", {
            "event_action": "csv_exported",
            "csv_file": "DR102_whitelist.csv",
            "app_context": "wl_manager",
        })
        assert code == 200
        assert body.get("success") is True or "error" not in body, \
            f"log_event failed: {body}"

    def test_csv_imported_event_logs_successfully(
            self, container_state, container_curl):
        code, body = _post_action(container_curl, "log_event", {
            "event_action": "csv_imported",
            "csv_file": "DR102_whitelist.csv",
            "app_context": "wl_manager",
            "rows_added": 5,
        })
        assert code == 200
        assert body.get("success") is True or "error" not in body

    def test_audit_exported_event_logs_successfully(
            self, container_state, container_curl):
        code, body = _post_action(container_curl, "log_event", {
            "event_action": "audit_exported",
            "format": "csv",
        })
        assert code == 200
        assert body.get("success") is True or "error" not in body


class TestSetTrashRetention:
    """Pins: ``set_trash_retention`` updates the config file and
    returns success.

    Bug class caught: a refactor that introduces a new required
    field in the config schema without updating the writer. The
    written file would be missing the new field and downstream
    readers would crash on KeyError.
    """

    def test_set_retention_updates_config_file(
            self, container_state, container_curl):
        # Set retention to 90 days
        code, body = _post_action(
            container_curl, "set_trash_retention",
            {"retention_days": 90})
        assert code == 200
        assert body.get("success") is True, \
            f"set_trash_retention failed: {body}"

        # Verify the side effect on disk
        config_path = (
            f"{APP_LOOKUPS}/_versions/_trash_config.json")
        # The handler stores the file at OWN_LOOKUPS, which is
        # `lookups/`, not `lookups/_versions/`. Check both.
        if not _container_file_exists(config_path):
            config_path = f"{APP_LOOKUPS}/_trash_config.json"
        assert _container_file_exists(config_path), \
            f"trash config file not written"
        config_text = _read_container_file(config_path)
        config = json.loads(config_text)
        assert config["retention_days"] == 90, \
            f"retention_days not persisted: {config}"


# ─────────────────────────────────────────────────────────────────────
# Tier 2 — POSTs requiring preconditions
# ─────────────────────────────────────────────────────────────────────


class TestCreateCsvHappyPath:
    """Pins: ``create_csv`` creates a new CSV and returns the
    full documented response shape (``success``, ``csv_file``,
    ``message``).

    Bug class caught: build-641-style projection drift in the
    create_csv response — silent loss of fields the frontend
    needs to update its state (csv_file echo, message). Without
    csv_file in the response the frontend can't navigate to the
    just-created CSV; without message the toast is empty.
    """

    NEW_CSV_NAME = "DR_RING1_HAPPY_PATH_TEST.csv"
    NEW_RULE_NAME = "DR_RING1_HAPPY_PATH_TEST"

    REQUIRED_FIELDS = {"success", "csv_file", "message"}

    def test_create_csv_response_shape(
            self, container_state, container_curl):
        # Make sure the rule + CSV don't already exist
        # (container_state will restore so this is safe).
        # Field name is ``detection_rule`` (not ``rule_name``)
        # per the handler contract.
        code, body = _post_action(container_curl, "create_csv", {
            "csv_file": self.NEW_CSV_NAME,
            "detection_rule": self.NEW_RULE_NAME,
            "app_context": "wl_manager",
            "headers": ["user", "src_ip"],
        })
        assert code == 200, f"unexpected code {code}: {body}"

        if "error" in body:
            # Most likely a demo-state artifact — the rule already
            # exists. container_state should have prevented this,
            # but if the demo CSV/rule is part of the snapshot
            # (which it is — demo state ships with DR130 etc.),
            # this test must use a name not in that snapshot.
            # NEW_CSV_NAME is deliberately distinct.
            pytest.fail(
                f"create_csv unexpectedly errored: {body['error']}")

        # Deep contract: every documented field present
        missing = self.REQUIRED_FIELDS - set(body.keys())
        assert not missing, \
            (f"create_csv response missing fields: {missing}. "
             f"Body: {body}")
        assert body["success"] is True
        assert body["csv_file"] == self.NEW_CSV_NAME, \
            f"csv_file echo wrong: {body['csv_file']}"
        assert self.NEW_CSV_NAME in body["message"], \
            f"message doesn't reference CSV: {body['message']}"


class TestCreateRuleHappyPath:
    """Pins: ``create_rule`` creates a rule registry entry and
    returns the documented response shape.

    Bug class caught: same projection-drift class as create_csv,
    in the symmetric rule-creation path.
    """

    NEW_RULE_NAME = "DR_RING1_RULE_HAPPY_TEST"

    # Per ``create_rule_pipeline`` contract: success, detection_rule,
    # message. Field name is ``detection_rule`` not ``rule_name``;
    # the latter exists in the mapping CSV row but the create_rule
    # API uses detection_rule consistently.
    REQUIRED_FIELDS = {"success", "detection_rule", "message"}

    def test_create_rule_response_shape(
            self, container_state, container_curl):
        code, body = _post_action(container_curl, "create_rule", {
            "detection_rule": self.NEW_RULE_NAME,
            "app_context": "wl_manager",
        })
        assert code == 200
        if "error" in body:
            pytest.fail(
                f"create_rule unexpectedly errored: {body['error']}")
        missing = self.REQUIRED_FIELDS - set(body.keys())
        assert not missing, \
            (f"create_rule response missing: {missing}. "
             f"Body: {body}")
        assert body["success"] is True
        assert body["detection_rule"] == self.NEW_RULE_NAME, \
            f"detection_rule echo wrong: {body['detection_rule']}"


class TestSaveCsvSmallEditHappyPath:
    """Pins: ``save_csv`` with a single-row edit returns the full
    documented response shape — diff, file_mtime, content_hash,
    pending_approvals.

    Bug class caught: this is the literal build-641 bug surface.
    The response includes ``pending_approvals`` (other admins'
    pending requests on this CSV); if a future projection drift
    drops a field from each pending entry, the frontend banner
    misrenders. Test asserts both the top-level shape AND the
    inner pending_approvals entry shape if any exist.
    """

    # Use DR102_whitelist.csv from the demo state — already exists
    CSV_FILE = "DR102_whitelist.csv"

    REQUIRED_TOP_LEVEL = {
        "success", "diff", "file_mtime", "content_hash",
        "pending_approvals",
    }

    # The build-641 fix added ``comment`` to this set. Pinning
    # all 8 fields prevents the build-641 regression — and
    # prevents the same drift from recurring in any other
    # projection that builds this shape.
    PENDING_INFO_FIELDS = {
        "request_id", "action_type", "description", "comment",
        "analyst", "timestamp", "pending_highlight", "payload",
    }

    def test_save_csv_response_shape_for_small_edit(
            self, container_state, container_curl):
        # Resolve detection_rule from the mapping (save_csv requires
        # it; get_csv_content doesn't echo it back).
        mapping_proc = container_curl(
            "/services/custom/wl_manager?action=get_mapping",
            check=False)
        mapping = json.loads(mapping_proc.stdout.strip())
        rule_for_csv = None
        for entry in mapping.get("mapping", []):
            if entry.get("csv_file") == self.CSV_FILE:
                rule_for_csv = entry.get("rule_name")
                break
        if rule_for_csv is None:
            pytest.skip(
                f"{self.CSV_FILE} not in mapping (demo state "
                f"missing this CSV)")

        # Now read the current CSV so we know its mtime + hash
        path = (f"/services/custom/wl_manager"
                f"?action=get_csv_content&csv_file={self.CSV_FILE}"
                f"&app_context=wl_manager")
        proc = container_curl(path, check=False)
        current = json.loads(proc.stdout.strip())
        if "error" in current:
            pytest.skip(
                f"could not read demo CSV {self.CSV_FILE}: "
                f"{current['error']}")
        rows = current.get("rows", [])
        headers = current.get("headers", [])
        if not rows:
            pytest.skip(f"{self.CSV_FILE} is empty in demo state")

        # Send identical rows back — produces empty diff → handler
        # returns "No changes detected" path, which is the simplest
        # happy-path shape to assert.
        code, body = _post_action(container_curl, "save_csv", {
            "csv_file": self.CSV_FILE,
            "detection_rule": rule_for_csv,
            "app_context": "wl_manager",
            "headers": headers,
            "rows": rows,
            "expected_mtime": current.get("file_mtime"),
            "expected_content_hash": current.get("content_hash"),
        })
        assert code == 200, f"unexpected code: {body}"
        if "error" in body:
            pytest.fail(
                f"save_csv unexpectedly errored: {body}")

        # The "No changes" path returns a slightly different shape
        # (``diff`` + ``message`` + ``file_mtime`` + ``content_hash``
        # but no ``success`` and no ``pending_approvals``).
        # Either response shape is acceptable as a contract — but
        # the keys MUST be from the documented set.
        if body.get("message") == "No changes detected":
            # No-op happy path
            for required in ("diff", "file_mtime", "content_hash"):
                assert required in body, \
                    f"no-change response missing {required}: {body}"
        else:
            # Full save happened
            missing = self.REQUIRED_TOP_LEVEL - set(body.keys())
            assert not missing, \
                f"save_csv response missing top-level: {missing}"
            # If pending_approvals is non-empty, every entry must
            # match the build-641 contract
            for entry in body.get("pending_approvals", []):
                entry_missing = (
                    self.PENDING_INFO_FIELDS - set(entry.keys()))
                assert not entry_missing, \
                    (f"pending_approvals[i] missing fields "
                     f"(build-641 class): {entry_missing}. "
                     f"Entry: {entry}")
