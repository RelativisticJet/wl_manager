"""
Audit event schema contract tests.

For each handler action that emits to ``index=wl_audit``, this file
pins the event schema — every documented field must be present in
the indexed event with the expected type. This is the third leg
of the build-641 fence:

- ``test_pending_info_projection.py`` — build-641 read projection
- ``test_approval_workflow.py::TestSubmitApprovalQueueEntryShape``
  — build-641 write to queue contract
- This file — build-641 write to audit-index contract

A drift in any layer would break the SOC dashboards (audit panel
silently goes blank, or column shows null where data should be).

Architecture
------------

Each test:

1. Embeds a unique marker (UUID4) in the action's comment or
   description field
2. Triggers the action via ``container_curl``
3. Polls ``index=wl_audit`` via ``splunk search`` for the marker
   (Splunk indexing has a ~1-2 second lag)
4. Parses the matching event's JSON and asserts every documented
   field is present with the right type

Origin
------

Day 4 of Ring 1. Replaces the deferred audit-emission scenarios
from ``RING1_INPUT_handler_contracts.md`` with real container-
based assertions.
"""

import json
import os
import subprocess
import time
import uuid

import pytest


pytestmark = pytest.mark.docker


CONTAINER = "wl_manager_test"
SPLUNK_AUTH = ["-auth", "admin:Chang3d!"]


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────


def _splunk_search(spl: str, timeout: int = 30) -> list:
    """Run a Splunk search and return parsed events.

    Returns a list of dicts where each dict is the parsed ``_raw``
    JSON of a matching audit event. Splunk's ``-output json``
    emits a stream of JSON objects (one per result line plus a
    metadata header); we parse only the actual results.

    Note: the ``splunk search`` CLI must run as the ``splunk``
    OS user (it needs write access to splunkd's pid + log dirs).
    docker exec runs as root by default, hence the explicit
    ``-u splunk``.
    """
    env = {**os.environ, "MSYS_NO_PATHCONV": "1"}
    proc = subprocess.run(  # noqa: S603 — list-form, no shell
        ["docker", "exec", "-u", "splunk", CONTAINER,
         "/opt/splunk/bin/splunk", "search", spl,
         *SPLUNK_AUTH, "-output", "json", "-maxout", "20"],
        capture_output=True, text=True, timeout=timeout,
        check=False, env=env,
    )
    if proc.returncode != 0:
        # splunk search returns non-zero on no results too — that
        # isn't necessarily an error. Caller checks the parsed
        # list length.
        pass
    events = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            wrapper = json.loads(line)
        except json.JSONDecodeError:
            continue
        # Each result is wrapped in {"preview": false, "result":
        # {...event...}}
        result = wrapper.get("result")
        if not isinstance(result, dict):
            continue
        raw = result.get("_raw", "")
        if not raw:
            continue
        try:
            event = json.loads(raw)
            events.append(event)
        except json.JSONDecodeError:
            continue
    return events


def _wait_for_audit_event(spl: str, max_wait_s: int = 15,
                          poll_interval: float = 1.5) -> list:
    """Poll ``index=wl_audit`` until events matching ``spl``
    appear, up to ``max_wait_s`` seconds.

    Splunk indexing has a ~1-2 second lag, sometimes longer
    under load. Tests need to tolerate this without flaking.

    Returns the list of matching events (empty if none after
    timeout).
    """
    deadline = time.time() + max_wait_s
    events = []
    while time.time() < deadline:
        events = _splunk_search(spl)
        if events:
            return events
        time.sleep(poll_interval)
    return events


def _post_action(container_curl, action: str, payload: dict,
                 user: str = "admin"):
    """Wrapper for action POSTs."""
    body = json.dumps({"action": action, **payload})
    proc = container_curl(
        "/services/custom/wl_manager",
        method="POST",
        data=body,
        content_type="application/json",
        check=False,
        user=user,
    )
    raw = proc.stdout.strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return (200 if proc.returncode == 0 else 0,
                {"_raw": raw})
    return (200, parsed)


# ─────────────────────────────────────────────────────────────────────
# request_submitted (submit_approval)
# ─────────────────────────────────────────────────────────────────────


class TestRequestSubmittedAuditSchema:
    """Pins the audit event emitted when a user submits an approval
    request. The dashboard's "Pending Requests" panel and the
    "Recent Activity" panel both consume this event; a missing
    field renders blanks in the UI.
    """

    REQUIRED_FIELDS = {
        "action", "timestamp", "analyst", "detection_rule",
        "csv_file", "app_context", "request_id",
        "approval_action_type", "description", "status",
    }

    def test_request_submitted_event_has_full_schema(
            self, container_state, container_curl):
        """Submit a request, wait for the audit event, assert
        every documented field is present."""
        # Get a CSV+rule from mapping
        proc = container_curl(
            "/services/custom/wl_manager?action=get_mapping",
            check=False, user="analyst1")
        mapping = json.loads(proc.stdout.strip())
        if not mapping.get("mapping"):
            pytest.skip("no mappings in demo state")
        entry = mapping["mapping"][0]

        # Unique marker so we can find OUR event among many
        marker = uuid.uuid4().hex[:12]
        description = f"Ring1audit_test_{marker}"

        # Submit
        code, body = _post_action(
            container_curl, "submit_approval", {
                "approval_action_type": "column_removal",
                "csv_file": entry["csv_file"],
                "detection_rule": entry["rule_name"],
                "app_context": "wl_manager",
                "description": description,
                "comment": f"Audit schema test {marker}",
                "pending_highlight": {"type": "column",
                                      "column_name": "dest_host"},
                "payload": {"column_name": "dest_host"},
            }, user="analyst1")

        if "error" in body:
            pytest.skip(f"submit failed: {body}")

        # Search for the event
        spl = (f'index=wl_audit action=request_submitted '
               f'"{marker}" earliest=-5m')
        events = _wait_for_audit_event(spl)
        assert events, \
            (f"no request_submitted event found within 15s. "
             f"Marker: {marker}, request_id: {body.get('request_id')}")

        evt = events[0]

        # Pin the schema
        missing = self.REQUIRED_FIELDS - set(evt.keys())
        assert not missing, \
            (f"request_submitted event missing fields: {missing}. "
             f"Event: {evt}")

        # Type / value spot-checks
        assert evt["action"] == "request_submitted"
        assert evt["status"] == "pending"
        assert evt["analyst"] == "analyst1"
        assert evt["approval_action_type"] == "column_removal"
        assert evt["request_id"] == body["request_id"]
        assert evt["description"] == description


# ─────────────────────────────────────────────────────────────────────
# request_rejected (process_approval reject)
# ─────────────────────────────────────────────────────────────────────


class TestRequestRejectedAuditSchema:
    """Pins the audit event emitted when an admin rejects a
    pending request. The dashboard's audit drilldown depends on
    rejection_reason being present.
    """

    REQUIRED_FIELDS = {
        "action", "timestamp", "analyst", "detection_rule",
        "csv_file", "app_context", "request_id",
        "approval_action_type", "rejection_reason", "status",
    }

    def test_request_rejected_event_has_full_schema(
            self, container_state, container_curl):
        # Get mapping, submit as analyst1
        proc = container_curl(
            "/services/custom/wl_manager?action=get_mapping",
            check=False, user="analyst1")
        mapping = json.loads(proc.stdout.strip())
        if not mapping.get("mapping"):
            pytest.skip("no mappings")
        entry = mapping["mapping"][0]

        marker = uuid.uuid4().hex[:12]
        code, submit_body = _post_action(
            container_curl, "submit_approval", {
                "approval_action_type": "column_removal",
                "csv_file": entry["csv_file"],
                "detection_rule": entry["rule_name"],
                "app_context": "wl_manager",
                "description": f"Ring1reject_{marker}",
                "comment": "test",
                "pending_highlight": {"type": "column",
                                      "column_name": "dest_host"},
                "payload": {"column_name": "dest_host"},
            }, user="analyst1")
        if "error" in submit_body:
            pytest.skip(f"submit failed: {submit_body}")
        request_id = submit_body["request_id"]

        # Reject as wladmin1 with a unique rejection reason
        rejection_marker = f"Ring1rej_{marker}"
        code, _ = _post_action(
            container_curl, "process_approval", {
                "request_id": request_id,
                "decision": "reject",
                "rejection_reason": rejection_marker,
            }, user="wladmin1")

        # Search by rejection_reason marker
        spl = (f'index=wl_audit action=request_rejected '
               f'"{rejection_marker}" earliest=-5m')
        events = _wait_for_audit_event(spl)
        assert events, \
            f"no request_rejected event for {request_id}"
        evt = events[0]

        missing = self.REQUIRED_FIELDS - set(evt.keys())
        assert not missing, \
            (f"request_rejected event missing fields: {missing}. "
             f"Event: {evt}")

        assert evt["status"] == "rejected"
        assert evt["analyst"] == "wladmin1"
        assert evt["request_id"] == request_id
        assert rejection_marker in evt["rejection_reason"]


# ─────────────────────────────────────────────────────────────────────
# dr_created (create_rule)
# ─────────────────────────────────────────────────────────────────────


class TestRuleCreatedAuditSchema:
    """Pins the audit event for ``create_rule``. The Audit
    dashboard's "Rule lifecycle" panel reads ``action=dr_created``.
    """

    REQUIRED_FIELDS = {
        "action", "timestamp", "analyst", "detection_rule",
        "csv_file", "app_context", "status",
    }

    def test_dr_created_event_has_full_schema(
            self, container_state, container_curl):
        marker = uuid.uuid4().hex[:8]
        rule_name = f"DR_RING1_AUDIT_{marker}"

        code, body = _post_action(
            container_curl, "create_rule", {
                "detection_rule": rule_name,
                "app_context": "wl_manager",
            })
        if "error" in body:
            pytest.skip(f"create_rule failed: {body}")

        # Search for the event by detection_rule field
        spl = (f'index=wl_audit action=dr_created '
               f'detection_rule="{rule_name}" earliest=-5m')
        events = _wait_for_audit_event(spl)
        assert events, \
            f"no dr_created event for {rule_name}"
        evt = events[0]

        missing = self.REQUIRED_FIELDS - set(evt.keys())
        assert not missing, \
            (f"dr_created event missing fields: {missing}. "
             f"Event: {evt}")
        assert evt["action"] == "dr_created"
        assert evt["detection_rule"] == rule_name
        assert evt["status"] == "created"


# ─────────────────────────────────────────────────────────────────────
# Common-fields invariant across all events
# ─────────────────────────────────────────────────────────────────────


class TestCommonAuditFieldsInvariant:
    """Pins: every audit event has the 6 common fields documented
    in CLAUDE.md ("Audit Event Structure"):

        timestamp, action, analyst, detection_rule, csv_file,
        app_context

    Plus the ``comment`` field which has a default of "" but must
    always be present (the audit dashboard reads it directly).

    Scope: ``sourcetype=wl_audit`` only — handler-emitted events.
    FIM events (``sourcetype=wl_fim``, from ``wl_fim.py`` and
    ``wl_fim_watch.py`` scripted inputs) are machine alerts with a
    different documented schema and a different dashboard panel.
    They go through their own emit path (Python ``print`` → Splunk
    scripted-input pipeline), not ``_index_audit`` — so the
    chokepoint backfill in ``WhitelistHandler._index_audit`` does
    not (and should not) reach them. CLAUDE.md "CSV Integrity
    Monitoring" describes their schema separately.
    """

    COMMON_FIELDS = {
        "timestamp", "action", "analyst", "detection_rule",
        "csv_file", "app_context", "comment",
    }

    def test_recent_audit_events_carry_common_fields(self):
        """Sample the 20 most recent handler-emitted audit events
        and assert ALL of them have the 7 common fields. Catches a
        regression where a new action emits to wl_audit without
        the common envelope (e.g., a contributor adds an event
        without going through ``build_audit_event`` AND the
        ``_index_audit`` chokepoint somehow misses it).

        Time window: ``earliest=-5m``. Tighter than the 1-day
        default because events from prior CI runs (or local
        mutation-test sessions that intentionally polluted the
        index) shouldn't fail this test indefinitely. Five
        minutes is short enough that any post-mutation event is
        outside the window quickly, and long enough that an
        in-progress run can find the events it just emitted.
        """
        events = _splunk_search(
            "index=wl_audit sourcetype=wl_audit earliest=-5m "
            "| head 20")
        if not events:
            pytest.skip(
                "no recent audit events to sample (no events in "
                "last 5 minutes)")

        violators = []
        for evt in events:
            missing = self.COMMON_FIELDS - set(evt.keys())
            if missing:
                violators.append(
                    f"action={evt.get('action', '?')} "
                    f"missing={missing}")

        assert not violators, \
            (f"audit events missing common fields:\n  "
             + "\n  ".join(violators[:10]))
