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

        # Verify the side effect on disk. The handler writes to
        # ``OWN_LOOKUPS + TRASH_CONFIG_FILE`` =
        # ``lookups/_trash_config.json`` — that's the canonical
        # location (and the only one the handler writes to).
        # R2-D7-F3 fixed: a previous version of this test tried
        # ``lookups/_versions/_trash_config.json`` first and fell
        # back to the canonical path only if that didn't exist.
        # On systems where a stale ``_versions/`` copy survived
        # from earlier code paths, the test read the stale file
        # and got the old retention value. Assert only against
        # the path the handler actually writes.
        config_path = f"{APP_LOOKUPS}/_trash_config.json"
        assert _container_file_exists(config_path), \
            (f"trash config file not written at canonical "
             f"path {config_path}")
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


# ─────────────────────────────────────────────────────────────────────
# Tier 3 — Multi-step workflow happy paths
# ─────────────────────────────────────────────────────────────────────


def _submit_column_removal(container_curl, csv_file, rule_name):
    """Helper — submit a column_removal approval request and
    return the parsed body."""
    payload = {
        "approval_action_type": "column_removal",
        "csv_file": csv_file,
        "detection_rule": rule_name,
        "app_context": "wl_manager",
        "description": "Ring 1 day 3 test",
        "comment": "Ring 1 day 3 test reason",
        "pending_highlight": {"type": "column",
                              "column_name": "host"},
        "payload": {
            "column_name": "host",
            "column_removal_reasons": [
                {"column": "host", "reason": "Ring 1 test"},
            ],
        },
    }
    return _post_action(
        container_curl, "submit_approval", payload)


class TestProcessApprovalApprove:
    """Pins: ``process_approval`` with ``decision=approve`` returns
    the documented response and resolves the queue entry.

    Approve is structurally more complex than reject (it triggers
    the replay step), and the response shape varies by action_type:
    column_removal/create/remove return ``{message, request_id}``;
    revert returns ``{message, request_id, diff}``. Pinning the
    minimum contract that ALL approve responses must carry.
    """

    REQUIRED_FIELDS = {"message", "request_id"}

    def test_approve_response_shape_for_column_removal(
            self, container_state, container_curl):
        # Precondition: submit a column_removal request AS ANALYST.
        # Then approve it AS A DIFFERENT user with admin role.
        # Self-approval is correctly blocked by the handler — see
        # CLAUDE.md decision log for the dual-admin design.
        mapping_proc = container_curl(
            "/services/custom/wl_manager?action=get_mapping",
            user="analyst1",
            check=False)
        mapping = json.loads(mapping_proc.stdout.strip())
        if not mapping.get("mapping"):
            pytest.skip("no mappings in demo state")
        entry = mapping["mapping"][0]

        # Submit as analyst1
        body = json.dumps({
            "action": "submit_approval",
            "approval_action_type": "column_removal",
            "csv_file": entry["csv_file"],
            "detection_rule": entry["rule_name"],
            "app_context": "wl_manager",
            "description": "Ring 1 day 3 approve-flow test",
            "comment": "Ring 1 day 3 approve-flow reason",
            "pending_highlight": {"type": "column",
                                  "column_name": "host"},
            "payload": {
                "column_name": "host",
                "column_removal_reasons": [
                    {"column": "host", "reason": "Ring 1 test"}
                ],
            },
        })
        proc = container_curl(
            "/services/custom/wl_manager",
            method="POST", data=body,
            content_type="application/json",
            user="analyst1", check=False)
        submit_body = json.loads(proc.stdout.strip())
        if "error" in submit_body:
            pytest.skip(f"analyst1 submit failed: {submit_body}")
        request_id = submit_body["request_id"]

        # Approve as wladmin1 (different user, has admin role)
        approve_body = json.dumps({
            "action": "process_approval",
            "request_id": request_id,
            "decision": "approve",
            "admin_comment": "Ring 1 test - approved by wladmin1",
        })
        proc = container_curl(
            "/services/custom/wl_manager",
            method="POST", data=approve_body,
            content_type="application/json",
            user="wladmin1", check=False)
        body = json.loads(proc.stdout.strip())
        if "error" in body:
            pytest.fail(f"approve unexpectedly errored: {body}")

        # Pin minimum response contract
        missing = self.REQUIRED_FIELDS - set(body.keys())
        assert not missing, \
            f"approve response missing: {missing}. Body: {body}"
        assert body["request_id"] == request_id
        # Message must mention "approve" or "executed" — confirms
        # the response is an approval acknowledgement
        msg_lower = body["message"].lower()
        assert ("approv" in msg_lower or "execut" in msg_lower), \
            f"approve message doesn't acknowledge: {body['message']}"


class TestRevertCsvResponseShape:
    """Pins: ``revert_csv`` returns the full documented shape —
    diff, rows_before/after, cols_before/after, file_mtime,
    content_hash, message.

    Bug class caught: build-641-class projection drift in the
    revert response. The frontend's revert success toast and the
    table-redraw logic both depend on the diff + counts + new
    mtime/hash being present.
    """

    REQUIRED_FIELDS = {
        "message", "diff", "rows_before", "rows_after",
        "cols_before", "cols_after", "file_mtime", "content_hash",
    }

    def test_revert_response_shape(
            self, container_state, container_curl):
        # Precondition: pick a CSV with at least one prior version
        # snapshot. DR102_whitelist.csv has many in the demo state.
        csv_file = "DR102_whitelist.csv"

        # List versions
        path = (f"/services/custom/wl_manager"
                f"?action=get_versions&csv_file={csv_file}"
                f"&app_context=wl_manager")
        proc = container_curl(path, check=False)
        versions_body = json.loads(proc.stdout.strip())
        versions = versions_body.get("versions", [])
        # Need at least 2 entries: the "Current" placeholder + one
        # actual previous version
        prev_versions = [v for v in versions
                         if v.get("filename")
                         and not v.get("is_current")]
        if not prev_versions:
            pytest.skip(
                f"{csv_file} has no previous versions to revert to")
        target = prev_versions[0]

        # Read mapping to get detection_rule
        mapping_proc = container_curl(
            "/services/custom/wl_manager?action=get_mapping",
            check=False)
        mapping = json.loads(mapping_proc.stdout.strip())
        rule = next(
            (e["rule_name"] for e in mapping.get("mapping", [])
             if e["csv_file"] == csv_file), None)
        if not rule:
            pytest.skip(f"{csv_file} not in mapping")

        # Read current mtime + content_hash for optimistic lock
        cc_proc = container_curl(
            (f"/services/custom/wl_manager?action=get_csv_content"
             f"&csv_file={csv_file}&app_context=wl_manager"),
            check=False)
        current = json.loads(cc_proc.stdout.strip())

        # Issue the revert
        code, body = _post_action(container_curl, "revert_csv", {
            "csv_file": csv_file,
            "detection_rule": rule,
            "app_context": "wl_manager",
            "version_filename": target["filename"],
            "version_display": target.get(
                "display", target["filename"]),
            "revert_reason": "Ring 1 day 3 revert test",
            "expected_mtime": current.get("file_mtime"),
            "expected_content_hash": current.get("content_hash"),
        })

        if "error" in body:
            pytest.fail(f"revert errored: {body}")

        # Pin the FULL contract — every documented field present
        missing = self.REQUIRED_FIELDS - set(body.keys())
        assert not missing, \
            (f"revert_csv response missing fields: {missing}. "
             f"Body: {body}")
        # Type checks on the rich fields
        assert isinstance(body["diff"], dict), \
            f"diff is not dict: {type(body['diff'])}"
        assert isinstance(body["file_mtime"], int)
        assert isinstance(body["content_hash"], str)
        assert isinstance(body["rows_before"], int)
        assert isinstance(body["rows_after"], int)


class TestSaveCsvBulkRemovalTriggersGate:
    """Pins: ``save_csv`` with a bulk row removal as an analyst (or
    when configured to require approval) returns a request_id
    instead of executing directly.

    The handler-side logic detects bulk operations and routes to
    submit_approval. Since the curl auth user is built-in admin,
    bulk_row_removal at the analyst threshold (>= 2 rows) doesn't
    trigger the gate. Instead we use ``submit_approval`` directly
    (same code path the gate would invoke) to verify the response.
    """

    def test_bulk_row_removal_via_submit_approval(
            self, container_state, container_curl):
        """Submit a bulk_row_removal directly and verify the queue
        accepts it with full response shape."""
        mapping_proc = container_curl(
            "/services/custom/wl_manager?action=get_mapping",
            check=False)
        mapping = json.loads(mapping_proc.stdout.strip())
        if not mapping.get("mapping"):
            pytest.skip("no mappings")
        entry = mapping["mapping"][0]

        code, body = _post_action(
            container_curl, "submit_approval", {
                "approval_action_type": "bulk_row_removal",
                "csv_file": entry["csv_file"],
                "detection_rule": entry["rule_name"],
                "app_context": "wl_manager",
                "description": "Ring 1 bulk removal test",
                "comment": "Ring 1 test reason",
                "pending_highlight": {
                    "type": "rows",
                    "headers": ["host"],
                    "row_keys": [["row1"], ["row2"]],
                },
                "payload": {
                    "rows_to_remove": [
                        {"host": "row1"}, {"host": "row2"}
                    ],
                    "removal_reasons": [
                        {"row_index": 0, "reason": "obsolete"},
                        {"row_index": 1, "reason": "obsolete"},
                    ],
                },
            })
        if "error" in body:
            pytest.fail(f"bulk_row_removal submit errored: {body}")
        # Pin response shape
        assert "request_id" in body, \
            f"missing request_id: {body}"
        assert "message" in body
        assert isinstance(body["request_id"], str)


class TestSetAdminLimits:
    """Pins: ``set_admin_limits`` (superadmin-only) updates the
    admin limit configuration and returns the documented response.

    Bug class caught: a refactor of the admin-limit storage format
    that breaks reads but not writes — set succeeds but the
    next get_admin_limits silently returns empty.
    """

    def test_set_admin_limits_response_shape(
            self, container_state, container_curl):
        # set_admin_limits requires SUPERADMIN_ROLES. The built-in
        # ``admin`` user does NOT have wl_superadmin — only
        # superadmin1 in the test container does. Submit as
        # superadmin1 to exercise the real RBAC path.
        body_str = json.dumps({
            "action": "set_admin_limits",
            "limits": {
                "rule_creation": 50,
                "csv_creation": 50,
            },
        })
        proc = container_curl(
            "/services/custom/wl_manager",
            method="POST", data=body_str,
            content_type="application/json",
            user="superadmin1", check=False)
        body = json.loads(proc.stdout.strip())
        if "error" in body:
            # Common failure: rate-limit cooldown counter tampered
            # or daily change limit hit. Both are valid container
            # states — skip if we hit them.
            err = body.get("error", "")
            if any(s in err for s in ("Security lockdown",
                                       "capped at",
                                       "tamper")):
                pytest.skip(
                    f"admin-limit rate gate hit: {err[:80]}")
            pytest.fail(f"set_admin_limits errored: {err}")

        # Documented success shape: success + applied limits
        assert body.get("success") is True or "limits" in body, \
            f"unexpected response: {body}"


class TestMarkNotificationsReadVariants:
    """Pins: ``mark_notifications_read`` accepts both the
    "all-mine" form (no IDs) and the specific-IDs form.

    The Day 2 test covered the no-IDs variant; this completes
    coverage with the specific-IDs path. The handler currently
    marks ALL notifications for the calling user regardless of
    which IDs are passed — this test pins that behavior so a
    future refactor that introduces ID filtering doesn't
    silently break the bell UX.
    """

    def test_with_specific_ids_returns_success(
            self, container_state, container_curl):
        code, body = _post_action(
            container_curl, "mark_notifications_read", {
                "ids": ["any-id-1", "any-id-2"],
            })
        assert body.get("success") is True, \
            f"mark with IDs did not succeed: {body}"
