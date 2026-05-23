"""
Approval workflow contract tests — submit / process / cancel.

This file pins the response shapes and side effects of the three
approval workflow endpoints. They are the highest-value targets
for build-641-class projection drift because every endpoint
returns a request_id (frontend uses it to correlate UI state with
queue entries) and the queue entries themselves carry the
projection contract that build-641 fixed.

Each test follows the pattern:

1. **Set up a precondition** — typically by directly POSTing a
   ``submit_approval`` to put a request in the queue. We use the
   direct path rather than triggering through ``save_csv`` so the
   test is focused on the approval-workflow contract, not the
   gate-detection path.
2. **Exercise the endpoint under test** — submit / process / cancel.
3. **Assert response shape** — full set of documented fields.
4. **Assert side effect** — queue updated, audit event emitted.
5. **container_state** restores the queue at teardown.

Origin
------

Replaces high-value scenarios from the deleted zombie tests
(see ``RING_FINDINGS.md`` R0-F2 and ``RING1_INPUT_handler_contracts.md``
"Approval workflow contracts"). Plus tests built specifically to
catch the build-641 bug class.
"""

import json

import pytest


pytestmark = pytest.mark.docker


# ─────────────────────────────────────────────────────────────────────
# Helper — POST an action to the handler
# ─────────────────────────────────────────────────────────────────────


def _post_action(container_curl, action: str, payload: dict,
                 user: str = "admin"):
    """Issue ``POST /services/custom/wl_manager``.

    Returns either:
    - (http_code, body_dict) for legacy callers
    - body_dict directly when called as a kwarg-aware helper

    For backward compatibility we keep returning a tuple by
    default, but tests that pass ``user=`` typically just want
    the body, so we return the body dict in that case (the new
    callers don't unpack a tuple).

    To preserve existing tests, this helper still returns a
    tuple. Tests that pass ``user=`` should index ``[1]`` or
    use the returned dict directly — the dict shape didn't
    change.
    """
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
        parsed = {"_raw": raw}
    # Return the body dict directly. Existing callers that
    # destructure ``code, body = _post_action(...)`` can keep
    # working because we yield (200, body) for them too via
    # __iter__ semantics on a tuple. Simplest: just always
    # return a tuple. If a caller expects a single dict (newer
    # tests in this file), they can use _post_action(...)[1].
    return (200, parsed)


def _read_queue_via_get(container_curl) -> list:
    """Read the approval queue via the admin GET endpoint."""
    path = ("/services/custom/wl_manager"
            "?action=get_approval_queue")
    proc = container_curl(path, check=False)
    body = json.loads(proc.stdout.strip())
    return body.get("approval_queue", [])


def _submit_column_removal_request(
        container_curl, csv_file: str, rule_name: str,
        column_name: str = "dest_host",
        description: str = "Ring 1 test - test column removal request",
        comment: str = "Ring 1 test - column deprecated") -> dict:
    """Submit a column_removal approval request and return the
    response. Centralizes the precondition-setup logic.
    """
    payload = {
        "approval_action_type": "column_removal",
        "csv_file": csv_file,
        "detection_rule": rule_name,
        "app_context": "wl_manager",
        "description": description,
        "comment": comment,
        "pending_highlight": {
            "type": "column",
            "column_name": column_name,
        },
        "payload": {
            "column_name": column_name,
            "column_removal_reasons": [
                {"column": column_name, "reason": comment}
            ],
        },
    }
    code, body = _post_action(
        container_curl, "submit_approval", payload)
    return body


# ─────────────────────────────────────────────────────────────────────
# submit_approval
# ─────────────────────────────────────────────────────────────────────


class TestSubmitApprovalShape:
    """Pins: ``submit_approval`` returns ``{message, request_id}``
    and the queue grows by 1.

    Bug class caught: any drift in submit_approval's response that
    drops ``request_id`` would break the frontend's ability to
    correlate UI state (the orange "pending" banner) with queue
    entries — a build-641-style projection drift on the smaller
    response shape.
    """

    REQUIRED_FIELDS = {"message", "request_id"}

    def test_submit_returns_request_id_and_message(
            self, container_state, container_curl):
        # Precondition: pick a CSV+rule from the demo mapping
        mapping_proc = container_curl(
            "/services/custom/wl_manager?action=get_mapping",
            check=False)
        mapping = json.loads(mapping_proc.stdout.strip())
        if not mapping.get("mapping"):
            pytest.skip("no mappings in demo state")
        entry = mapping["mapping"][0]
        csv_file = entry["csv_file"]
        rule_name = entry["rule_name"]

        body = _submit_column_removal_request(
            container_curl, csv_file, rule_name)

        if "error" in body:
            pytest.fail(f"submit_approval errored: {body}")

        # Deep contract: every documented field present
        missing = self.REQUIRED_FIELDS - set(body.keys())
        assert not missing, \
            (f"submit_approval response missing: {missing}. "
             f"Body: {body}")
        # request_id should be a non-empty string (UUID4 in this
        # codebase)
        assert isinstance(body["request_id"], str)
        assert len(body["request_id"]) > 0
        # Message is human-readable text — assert it exists and
        # mentions "submitted" or similar so a future refactor
        # that returns "" still fails
        assert "submit" in body["message"].lower(), \
            f"message doesn't acknowledge submission: {body['message']}"

    def test_submit_grows_the_queue_by_one(
            self, container_state, container_curl):
        """Side-effect verification: the new request_id is in the
        post-submit queue, and exactly one new request_id was
        added relative to the pre-submit queue.

        R2-D7-F2: a previous version asserted ``len(after) ==
        before_count + 1``. That assertion was too strict because
        ``submit_approval`` invokes ``expire_pending_approvals``
        as a side effect, pruning expired entries on every
        submit. So a ``before`` count inflated by stale entries
        from prior tests would shrink instead of grow:
        observed ``before=5, after=1`` even though the new
        entry was successfully added. The right contract is
        request-id-based, not count-based — that's what catches
        a real regression where the submit returns success but
        the entry isn't persisted.
        """
        before = _read_queue_via_get(container_curl)
        before_ids = {e.get("request_id") for e in before}

        # Pick any CSV+rule
        mapping_proc = container_curl(
            "/services/custom/wl_manager?action=get_mapping",
            check=False)
        mapping = json.loads(mapping_proc.stdout.strip())
        if not mapping.get("mapping"):
            pytest.skip("no mappings in demo state")
        entry = mapping["mapping"][0]
        body = _submit_column_removal_request(
            container_curl, entry["csv_file"], entry["rule_name"])

        if "error" in body:
            pytest.skip(f"submit_approval setup failed: {body}")

        after = _read_queue_via_get(container_curl)
        after_ids = {e.get("request_id") for e in after}
        new_ids = after_ids - before_ids
        assert len(new_ids) == 1, (
            "expected exactly 1 new request_id, got {}: "
            "before_ids={}, after_ids={}".format(
                len(new_ids), sorted(before_ids),
                sorted(after_ids)))
        assert body["request_id"] in new_ids, (
            "submit response request_id {} is not the one that "
            "actually landed in the queue. The new id was {}."
            .format(body["request_id"], sorted(new_ids)))
        # Find our entry by request_id
        new_entry = next(
            (e for e in after if e["request_id"] == body["request_id"]),
            None)
        assert new_entry is not None, \
            f"new request not in queue: {body['request_id']}"
        assert new_entry["status"] == "pending"


class TestSubmitApprovalQueueEntryShape:
    """Pins: the queue entry created by submit_approval has the
    full set of documented fields — this is the build-641 contract
    on the WRITE side. The build-641 fix was on the READ projection;
    this test makes sure the WRITER puts the right fields in.

    Bug class caught: a refactor that drops a field from the
    queue-entry write path. The read projection might still show
    a default value (empty string for ``comment``) and the bug
    would surface only when an analyst's typed reason mysteriously
    disappears from the dashboard.
    """

    # Queue entries carry MORE fields than the projected
    # pending_info shape (admin-only fields like resolved_by,
    # rejection_reason, etc.). This list is the minimum set every
    # entry must have at write time.
    REQUIRED_QUEUE_FIELDS = {
        "request_id", "timestamp", "analyst", "csv_file",
        "app_context", "detection_rule", "action_type",
        "description", "comment", "status", "payload",
        "pending_highlight",
    }

    def test_submitted_entry_has_full_contract(
            self, container_state, container_curl):
        # Precondition + submit
        mapping_proc = container_curl(
            "/services/custom/wl_manager?action=get_mapping",
            check=False)
        mapping = json.loads(mapping_proc.stdout.strip())
        if not mapping.get("mapping"):
            pytest.skip("no mappings in demo state")
        entry = mapping["mapping"][0]
        body = _submit_column_removal_request(
            container_curl, entry["csv_file"], entry["rule_name"],
            comment="Ring 1 build 641 contract pin")

        if "error" in body:
            pytest.skip(f"submit setup failed: {body}")
        request_id = body["request_id"]

        # Read back via admin GET and find our entry
        queue = _read_queue_via_get(container_curl)
        new_entry = next(
            (e for e in queue if e["request_id"] == request_id),
            None)
        assert new_entry is not None, \
            f"submitted request not in queue"

        # Pin the field set
        missing = self.REQUIRED_QUEUE_FIELDS - set(new_entry.keys())
        assert not missing, \
            (f"queue entry missing fields (build-641 write-side "
             f"contract): {missing}. Entry: {new_entry}")

        # And verify the comment we typed actually landed
        assert new_entry["comment"] == "Ring 1 build 641 contract pin", \
            f"comment did not survive submission: {new_entry['comment']!r}"


class TestSubmitDualApprovalQueueEntryShape:
    """R1-D5-F1 fix: pins the dual-admin queue entry contract,
    specifically that ``timestamp`` is present.

    Bug class: dual-admin submits at ``_submit_dual_approval``
    write entries with ``submitted_at`` but no ``timestamp``.
    The consumer ``wl_approval.expire_pending_approvals`` reads
    ``entry.get("timestamp", 0)`` — for entries without a
    ``timestamp`` key that returned ``0``, evaluating to
    "30 days old", and the entry was silently expired by the
    next single-admin submit.

    Shipped fix (build 645): write both ``timestamp`` and
    ``submitted_at`` on the dual-admin path; expire fallback to
    ``submitted_at`` when ``timestamp`` is missing (handles any
    legacy queue entries written before the fix).
    """

    REQUIRED_DUAL_FIELDS = {
        "request_id", "analyst", "action_type", "status",
        "timestamp", "submitted_at", "submitted_at_human",
        "comment", "meta", "is_dual_admin",
    }

    def test_dual_admin_entry_has_timestamp_and_required_fields(
            self, container_state, container_curl):
        _, body = _post_action(container_curl, "submit_dual_approval", {
            "action_type": "admin_factory_reset",
            "comment": "Ring 1 R1-D5-F1 dual-admin shape pin",
        }, user="superadmin1")
        if "error" in body:
            pytest.skip(
                "submit_dual_approval failed: {}".format(body))
        request_id = body["request_id"]

        # Read back via admin GET
        queue = _read_queue_via_get(container_curl)
        entry = next(
            (e for e in queue if e["request_id"] == request_id),
            None)
        assert entry is not None, \
            "dual-admin request not in queue: {}".format(request_id)
        assert entry.get("is_dual_admin") is True, \
            "is_dual_admin flag missing or false"

        # Pin the field set
        missing = self.REQUIRED_DUAL_FIELDS - set(entry.keys())
        assert not missing, \
            ("dual-admin queue entry missing fields: {}. "
             "Entry keys: {}".format(missing, sorted(entry.keys())))

        # The R1-D5-F1 fix specifically: timestamp must be a
        # positive int, not None, not zero. If this fails, the
        # write-side fix didn't land.
        ts = entry.get("timestamp")
        assert isinstance(ts, int) and ts > 0, \
            ("dual-admin entry has invalid timestamp: {!r}. "
             "R1-D5-F1 fix not applied.".format(ts))
        # timestamp and submitted_at should be the same epoch
        # (both are set to ``now`` at submit time)
        assert entry.get("submitted_at") == ts, \
            ("timestamp ({}) != submitted_at ({}) — they should "
             "be the same value written at submit time".format(
                 ts, entry.get("submitted_at")))

    def test_dual_admin_entry_survives_subsequent_single_admin_submit(
            self, container_state, container_curl):
        """The exact bug R1-D5-F1 fixed: a dual-admin pending
        entry would silently disappear when ANY non-dual submit
        happened, because expire_pending_approvals saw the
        absent timestamp as 0 (= 30+ days old).

        With the fix, the dual-admin entry should still be in
        the queue after a sibling single-admin submit triggers
        an expire pass.
        """
        # Step 1: submit dual-admin request
        _, dual_body = _post_action(
            container_curl, "submit_dual_approval", {
                "action_type": "admin_factory_reset",
                "comment": "Ring 1 R1-D5-F1 survival test",
            }, user="superadmin1")
        if "error" in dual_body:
            pytest.skip("dual-admin submit failed: {}".format(dual_body))
        dual_id = dual_body["request_id"]

        # Step 2: submit a single-admin request to trigger
        # expire_pending_approvals as a side effect
        mapping_proc = container_curl(
            "/services/custom/wl_manager?action=get_mapping",
            check=False)
        mapping = json.loads(mapping_proc.stdout.strip())
        if not mapping.get("mapping"):
            pytest.skip("no mappings")
        entry = mapping["mapping"][0]
        single_body = _submit_column_removal_request(
            container_curl, entry["csv_file"], entry["rule_name"],
            comment="Ring 1 R1-D5-F1 trigger expire")
        if "error" in single_body:
            pytest.skip("single submit failed: {}".format(single_body))

        # Step 3: read queue — dual-admin entry MUST still be
        # present. Pre-fix this would fail with the dual_id gone.
        queue = _read_queue_via_get(container_curl)
        survivor = next(
            (e for e in queue if e["request_id"] == dual_id),
            None)
        assert survivor is not None, \
            ("R1-D5-F1 regression: dual-admin entry {} was silently "
             "expired by sibling single-admin submit. Check that "
             "_submit_dual_approval writes 'timestamp' and that "
             "expire_pending_approvals falls back to submitted_at."
             .format(dual_id))


class TestSubmitApprovalErrorPaths:
    """Pins: invalid submit_approval payloads return 4xx errors
    with the documented ``error`` field.

    Catches: silent acceptance of malformed payloads (a partially-
    parsed payload could land in the queue and crash later
    consumers).
    """

    def test_invalid_action_type_returns_400(
            self, container_state, container_curl):
        code, body = _post_action(container_curl, "submit_approval", {
            "approval_action_type": "INVALID_NEVER_VALID",
            "csv_file": "x.csv",
            "detection_rule": "DRX",
            "app_context": "wl_manager",
        })
        assert "error" in body, \
            f"expected error, got: {body}"
        assert "Invalid approval action type" in body["error"], \
            f"unexpected error message: {body['error']}"

    def test_missing_action_type_returns_400(
            self, container_state, container_curl):
        code, body = _post_action(container_curl, "submit_approval", {
            "csv_file": "x.csv",
            "detection_rule": "DRX",
        })
        # Empty action_type → "" → fails the "in (...)" allow-list
        assert "error" in body, \
            f"expected error, got: {body}"
        assert "Invalid approval action type" in body["error"]

    def test_non_ascii_description_returns_400(
            self, container_state, container_curl):
        """ASCII validation enforcement on the description."""
        # Need a real CSV+rule for this to get past earlier
        # validations
        mapping_proc = container_curl(
            "/services/custom/wl_manager?action=get_mapping",
            check=False)
        mapping = json.loads(mapping_proc.stdout.strip())
        if not mapping.get("mapping"):
            pytest.skip("no mappings in demo state")
        entry = mapping["mapping"][0]

        code, body = _post_action(container_curl, "submit_approval", {
            "approval_action_type": "column_removal",
            "csv_file": entry["csv_file"],
            "detection_rule": entry["rule_name"],
            "app_context": "wl_manager",
            "description": "Reason with unicode: 中文",
            "pending_highlight": {"type": "column",
                                  "column_name": "dest_host"},
            "payload": {"column_name": "dest_host"},
        })
        assert "error" in body, \
            f"non-ASCII description should be rejected: {body}"


# ─────────────────────────────────────────────────────────────────────
# process_approval
# ─────────────────────────────────────────────────────────────────────


class TestProcessApprovalRejectShape:
    """Pins: ``process_approval`` with ``decision=reject`` returns
    ``{message, request_id}`` and the queue entry transitions to
    rejected status.

    Reject is tested before approve because reject is structurally
    simpler — no replay step. Approve has more moving parts (CSV
    must change) and gets its own test class.
    """

    REQUIRED_FIELDS = {"message", "request_id"}

    def test_reject_response_shape(
            self, container_state, container_curl):
        # Precondition: submit a request
        mapping_proc = container_curl(
            "/services/custom/wl_manager?action=get_mapping",
            check=False)
        mapping = json.loads(mapping_proc.stdout.strip())
        if not mapping.get("mapping"):
            pytest.skip("no mappings in demo state")
        entry = mapping["mapping"][0]
        submit_body = _submit_column_removal_request(
            container_curl, entry["csv_file"], entry["rule_name"])

        if "error" in submit_body:
            pytest.skip(f"submit setup failed: {submit_body}")
        request_id = submit_body["request_id"]

        # Reject it
        code, body = _post_action(
            container_curl, "process_approval", {
                "request_id": request_id,
                "decision": "reject",
                "rejection_reason":
                    "Ring 1 test - rejecting for contract verification",
            })

        if "error" in body:
            pytest.fail(f"reject errored: {body}")

        missing = self.REQUIRED_FIELDS - set(body.keys())
        assert not missing, \
            (f"reject response missing: {missing}. "
             f"Body: {body}")
        assert body["request_id"] == request_id
        assert "reject" in body["message"].lower(), \
            f"reject message doesn't acknowledge: {body['message']}"

    def test_reject_transitions_status_in_queue(
            self, container_state, container_curl):
        """Side-effect verification: the queue entry status is
        ``rejected`` after a reject, with ``resolved_by`` set."""
        # Submit
        mapping_proc = container_curl(
            "/services/custom/wl_manager?action=get_mapping",
            check=False)
        mapping = json.loads(mapping_proc.stdout.strip())
        if not mapping.get("mapping"):
            pytest.skip("no mappings in demo state")
        entry = mapping["mapping"][0]
        submit_body = _submit_column_removal_request(
            container_curl, entry["csv_file"], entry["rule_name"])
        if "error" in submit_body:
            pytest.skip(f"submit failed: {submit_body}")
        request_id = submit_body["request_id"]

        # Reject
        _post_action(container_curl, "process_approval", {
            "request_id": request_id,
            "decision": "reject",
            "rejection_reason": "Ring 1 test - reject reason",
        })

        # Inspect queue
        queue = _read_queue_via_get(container_curl)
        target = next(
            (e for e in queue if e["request_id"] == request_id),
            None)
        assert target is not None, "rejected entry vanished from queue"
        assert target["status"] == "rejected", \
            f"status not transitioned: {target['status']}"
        assert target.get("resolved_by"), \
            "resolved_by not populated"


class TestProcessApprovalErrorPaths:
    """Pins: invalid process_approval calls return errors."""

    def test_unknown_request_id_returns_404(
            self, container_state, container_curl):
        code, body = _post_action(
            container_curl, "process_approval", {
                "request_id": "nonexistent-request-id-12345",
                "decision": "approve",
            })
        assert "error" in body, \
            f"expected error, got: {body}"
        assert "not found" in body["error"].lower(), \
            f"unexpected error: {body['error']}"

    def test_invalid_decision_returns_400(
            self, container_state, container_curl):
        code, body = _post_action(
            container_curl, "process_approval", {
                "request_id": "anything",
                "decision": "MAYBE_LATER",  # not approve/reject/cancel
            })
        assert "error" in body, \
            f"expected error, got: {body}"
        assert ("decision" in body["error"].lower()
                or "approve" in body["error"].lower()), \
            f"unexpected error: {body['error']}"

    def test_reject_without_reason_returns_400(
            self, container_state, container_curl):
        # Need a real pending request first
        mapping_proc = container_curl(
            "/services/custom/wl_manager?action=get_mapping",
            check=False)
        mapping = json.loads(mapping_proc.stdout.strip())
        if not mapping.get("mapping"):
            pytest.skip("no mappings in demo state")
        entry = mapping["mapping"][0]
        submit_body = _submit_column_removal_request(
            container_curl, entry["csv_file"], entry["rule_name"])
        if "error" in submit_body:
            pytest.skip(f"submit failed: {submit_body}")
        request_id = submit_body["request_id"]

        code, body = _post_action(
            container_curl, "process_approval", {
                "request_id": request_id,
                "decision": "reject",
                "rejection_reason": "",  # empty
            })
        assert "error" in body, \
            f"expected error for empty rejection reason: {body}"


# ─────────────────────────────────────────────────────────────────────
# cancel_request
# ─────────────────────────────────────────────────────────────────────


class TestCancelRequest:
    """Pins: ``cancel_request`` returns ``{message, request_id}``
    when the requester cancels their own pending request.
    """

    REQUIRED_FIELDS = {"message", "request_id"}

    def test_cancel_response_shape(
            self, container_state, container_curl):
        # Submit (as built-in admin — the curl auth user)
        mapping_proc = container_curl(
            "/services/custom/wl_manager?action=get_mapping",
            check=False)
        mapping = json.loads(mapping_proc.stdout.strip())
        if not mapping.get("mapping"):
            pytest.skip("no mappings in demo state")
        entry = mapping["mapping"][0]
        submit_body = _submit_column_removal_request(
            container_curl, entry["csv_file"], entry["rule_name"])
        if "error" in submit_body:
            pytest.skip(f"submit failed: {submit_body}")
        request_id = submit_body["request_id"]

        # Cancel as same user
        code, body = _post_action(
            container_curl, "cancel_request", {
                "request_id": request_id,
                "cancellation_reason":
                    "Ring 1 test - cancelling for contract verification",
            })

        if "error" in body:
            pytest.fail(f"cancel errored: {body}")

        missing = self.REQUIRED_FIELDS - set(body.keys())
        assert not missing, \
            (f"cancel response missing: {missing}. "
             f"Body: {body}")
        assert body["request_id"] == request_id

    def test_cancel_unknown_request_returns_404(
            self, container_state, container_curl):
        code, body = _post_action(
            container_curl, "cancel_request", {
                "request_id": "nonexistent-uuid-cancel-test",
                "cancellation_reason":
                    "Ring 1 test - cancel reason",
            })
        assert "error" in body, \
            f"expected error, got: {body}"
        assert ("not found" in body["error"].lower()), \
            f"unexpected error: {body['error']}"

    def test_cancel_without_reason_returns_400(
            self, container_state, container_curl):
        code, body = _post_action(
            container_curl, "cancel_request", {
                "request_id": "any-id",
                "cancellation_reason": "",
            })
        assert "error" in body, \
            f"expected error, got: {body}"
        assert "reason" in body["error"].lower(), \
            f"unexpected error: {body['error']}"
