"""
Integration tests for the Approval Workflow state machine.

Tests every state transition: submit -> approve/reject/cancel/expire,
plus guards (self-approve, duplicate, permissions, already-resolved).

Run:  cd tests && python -m unittest test_approval_workflow -v

NOTE: These tests talk to the live Splunk Docker container.
      Rate limit: 30 POSTs / 60s per user.
      Tests are grouped to minimize API calls.
      Classes are numbered to control execution order (unittest runs
      classes alphabetically).
"""

import time
import unittest
from test_integration_base import (
    WLIntegrationTestCase, ADMIN, WLADMIN1, WLADMIN2, ANALYST1, ANALYST2,
    TEST_CSV, TEST_RULE, TEST_APP_CONTEXT,
    api_post, submit_approval, process_approval, cancel_request,
    get_approval_queue, get_csv_content, save_csv, clear_approval_queue,
    search_audit, wait_for_indexing,
)


class Test01_SubmitApproval(WLIntegrationTestCase):
    """Tests for submitting approval requests.

    Runs FIRST so the queue is clean and rate limit budget is fresh.
    Consolidated to minimize POST count (30 POST / 60s per user).
    """

    def test_submit_valid_and_invalid_types(self):
        """All 6 valid action types succeed; invalid type + path traversal fail.

        POST budget: 6 submits + 6 cancels + 2 invalid = 14 (ANALYST1).
        """
        types = [
            "bulk_row_removal", "bulk_row_addition", "bulk_row_edit",
            "column_removal", "csv_import_replace", "revert",
        ]
        req_ids = []
        for atype in types:
            status, data = submit_approval(atype, description=f"Test {atype}")
            self.assertEqual(status, 200, f"Failed for {atype}: {data}")
            req_ids.append(data["request_id"])
            time.sleep(0.2)

        # Cancel all
        for rid in req_ids:
            cancel_request(rid, "Cleanup", creds=ANALYST1)
            time.sleep(0.1)

        # Invalid action type -> 400
        status, data = submit_approval("nonexistent_type")
        self.assertEqual(status, 400)
        self.assertIn("Invalid", data.get("error", ""))

        # Path traversal -> 400
        payload = {
            "action": "submit_approval",
            "approval_action_type": "bulk_row_removal",
            "csv_file": "../../etc/passwd.csv",
            "app_context": TEST_APP_CONTEXT,
            "detection_rule": TEST_RULE,
            "description": "Evil",
            "original_payload": {},
            "pending_highlight": {},
        }
        s, d = api_post(payload, creds=ANALYST1)
        self.assertEqual(s, 400)

    def test_submit_duplicate_and_multiuser(self):
        """Duplicate blocked; different types + different users allowed.

        POST budget: 5 submits + 4 cancels = 9 (split across users).
        """
        # Duplicate blocked
        s1, d1 = submit_approval("bulk_row_removal")
        self.assertEqual(s1, 200)
        rid = d1["request_id"]

        s2, d2 = submit_approval("bulk_row_removal")
        self.assertEqual(s2, 409)
        self.assertIn("already have a pending", d2.get("error", ""))
        cancel_request(rid, "Cleanup", creds=ANALYST1)

        # Different action types from same user -> both allowed
        s1, d1 = submit_approval("bulk_row_removal")
        s2, d2 = submit_approval("bulk_row_edit")
        self.assertEqual(s1, 200)
        self.assertEqual(s2, 200)
        cancel_request(d1["request_id"], "Cleanup", creds=ANALYST1)
        cancel_request(d2["request_id"], "Cleanup", creds=ANALYST1)

        # Same action type from different users -> both allowed
        s1, d1 = submit_approval("bulk_row_removal", creds=ANALYST1)
        s2, d2 = submit_approval("bulk_row_removal", creds=ANALYST2)
        self.assertEqual(s1, 200)
        self.assertEqual(s2, 200)
        cancel_request(d1["request_id"], "Cleanup", creds=ANALYST1)
        cancel_request(d2["request_id"], "Cleanup", creds=ANALYST2)

    def test_submit_description_and_audit(self):
        """Long description truncated; audit event created.

        POST budget: 2 submits + 2 cancels + 1 queue GET = 5 (ANALYST1).
        """
        # Description truncation
        long_desc = "A" * 600
        status, data = submit_approval("bulk_row_removal", description=long_desc)
        self.assertEqual(status, 200)
        rid_trunc = data["request_id"]

        _, queue = get_approval_queue()
        pending = queue.get("pending", [])
        match = [p for p in pending if p["request_id"] == rid_trunc]
        self.assertTrue(match)
        self.assertEqual(len(match[0]["description"]), 500)
        cancel_request(rid_trunc, "Cleanup", creds=ANALYST1)

        # Audit event
        status, data = submit_approval(
            "bulk_row_removal", description="Audit test")
        self.assertEqual(status, 200)
        rid_audit = data["request_id"]

        events = self._get_latest_audit("request_submitted")
        matching = [e for e in events if e.get("request_id") == rid_audit]
        self.assertGreaterEqual(len(matching), 1,
                                "No request_submitted audit event found")
        self.assertEqual(matching[0].get("approval_action_type"),
                         "bulk_row_removal")
        cancel_request(rid_audit, "Cleanup", creds=ANALYST1)


class Test02_ApproveReject(WLIntegrationTestCase):
    """Tests for approving and rejecting requests."""

    def _submit_with_real_csv_data(self, action_type="bulk_row_removal",
                                    creds=ANALYST1):
        """Submit an approval request with real CSV row data so approve replay
        succeeds. Returns (request_id, first_row_key, visible_headers)."""
        headers, rows, _ = self._load_csv()
        visible = [h for h in headers if not h.startswith("_")]
        if not rows:
            self.skipTest("No rows in test CSV")
        first_key = [rows[0].get(h, "") for h in visible]

        s, d = submit_approval(
            action_type, creds=creds,
            pending_highlight={
                "type": "rows",
                "headers": visible,
                "row_keys": [first_key],
            },
            original_payload={
                "removal_reasons": [{"reason": "Test removal"}],
            },
        )
        self.assertEqual(s, 200, f"Submit failed: {d}")
        return d["request_id"], first_key, visible

    def _restore_removed_row(self, visible, first_key):
        """Re-add a row that was removed by an approve replay."""
        h2, r2, _ = self._load_csv()
        restored = {h: v for h, v in zip(visible, first_key)}
        r2.append(restored)
        save_csv(h2, r2, comment="Restore row after approve test")

    def test_approve_request_and_verify_queue(self):
        """Approve -> request moves from pending to resolved as 'approved'."""
        rid, first_key, visible = self._submit_with_real_csv_data()

        # Verify pending
        _, queue = get_approval_queue()
        pending_ids = [p["request_id"] for p in queue.get("pending", [])]
        self.assertIn(rid, pending_ids)

        # Approve
        s2, d2 = process_approval(rid, "approve", creds=WLADMIN1)
        self.assertEqual(s2, 200, f"Approve failed: {d2}")

        # Verify resolved
        _, queue = get_approval_queue()
        pending_ids = [p["request_id"] for p in queue.get("pending", [])]
        resolved = queue.get("resolved", [])
        self.assertNotIn(rid, pending_ids)
        match = [r for r in resolved if r["request_id"] == rid]
        self.assertTrue(match)
        self.assertEqual(match[0]["status"], "approved")

        # Restore row
        self._restore_removed_row(visible, first_key)

    def test_reject_request_with_reason(self):
        """Reject -> resolved with reason, resolved_by set."""
        s, d = submit_approval("bulk_row_edit", creds=ANALYST2)
        rid = d["request_id"]

        s2, d2 = process_approval(
            rid, "reject", creds=WLADMIN1,
            rejection_reason="Policy violation")
        self.assertEqual(s2, 200)

        _, queue = get_approval_queue()
        resolved = queue.get("resolved", [])
        match = [r for r in resolved if r["request_id"] == rid]
        self.assertTrue(match)
        self.assertEqual(match[0]["status"], "rejected")
        self.assertEqual(match[0]["rejection_reason"], "Policy violation")
        self.assertEqual(match[0]["resolved_by"], "wladmin1")

    def test_reject_requires_reason(self):
        """Rejection without reason -> 400."""
        s, d = submit_approval("bulk_row_removal", creds=ANALYST2)
        rid = d["request_id"]

        s2, d2 = process_approval(rid, "reject", creds=WLADMIN1,
                                  rejection_reason="")
        self.assertEqual(s2, 400)
        self.assertIn("reason is required", d2.get("error", ""))

        cancel_request(rid, "Cleanup", creds=ANALYST2)

    def test_self_approve_blocked(self):
        """wl_admin cannot approve their own request -> 403."""
        s, d = submit_approval("bulk_row_removal", creds=WLADMIN1)
        rid = d["request_id"]

        s2, d2 = process_approval(rid, "approve", creds=WLADMIN1)
        self.assertEqual(s2, 403)
        self.assertIn("cannot approve your own", d2.get("error", ""))

        # Verify still pending
        _, queue = get_approval_queue()
        match = [p for p in queue["pending"] if p["request_id"] == rid]
        self.assertTrue(match, "Request should still be pending after 403")

        cancel_request(rid, "Cleanup", creds=WLADMIN1)

    def test_approve_already_rejected(self):
        """Cannot approve an already-rejected request -> 409."""
        s, d = submit_approval("bulk_row_removal", creds=ANALYST2)
        rid = d["request_id"]

        process_approval(rid, "reject", creds=WLADMIN1,
                         rejection_reason="First")
        s2, d2 = process_approval(rid, "approve", creds=ADMIN)
        self.assertEqual(s2, 409)

    def test_reject_already_approved(self):
        """Cannot reject an already-approved request -> 409.

        Uses real CSV data so the approve replay succeeds.
        """
        rid, first_key, visible = self._submit_with_real_csv_data(
            creds=ANALYST2)

        s_approve, _ = process_approval(rid, "approve", creds=WLADMIN1)
        self.assertEqual(s_approve, 200, "Approve should succeed with real data")

        s2, d2 = process_approval(rid, "reject", creds=ADMIN,
                                  rejection_reason="Late")
        self.assertEqual(s2, 409)

        # Restore the row removed by the approve replay
        self._restore_removed_row(visible, first_key)

    def test_nonexistent_request_id(self):
        """Approving nonexistent request -> 404."""
        s, d = process_approval("fake-id-12345", "approve")
        self.assertEqual(s, 404)

    def test_invalid_decision(self):
        """Decision 'maybe' -> 400."""
        s, d = submit_approval("bulk_row_removal", creds=ANALYST2)
        rid = d["request_id"]

        payload = {
            "action": "process_approval",
            "request_id": rid,
            "decision": "maybe",
        }
        s2, d2 = api_post(payload, creds=WLADMIN1)
        self.assertEqual(s2, 400)

        cancel_request(rid, "Cleanup", creds=ANALYST2)

    def test_non_admin_cannot_process(self):
        """Analyst (EDIT_ROLES only) cannot approve/reject -> 403.

        Uses ANALYST2 as submitter. ANALYST1 tries to approve (also non-admin).
        """
        s, d = submit_approval("bulk_row_removal", creds=ANALYST2)
        rid = d["request_id"]

        s2, d2 = process_approval(rid, "approve", creds=ANALYST1)
        self.assertEqual(s2, 403)

        cancel_request(rid, "Cleanup", creds=ANALYST2)

    def test_approve_audit_event(self):
        """Approval creates request_approved audit event.

        Uses real CSV data so the approve replay succeeds and generates
        a real audit event.
        """
        rid, first_key, visible = self._submit_with_real_csv_data()
        s_approve, d_approve = process_approval(rid, "approve", creds=WLADMIN1)
        self.assertEqual(s_approve, 200,
                         f"Approve failed (no audit event without success): {d_approve}")

        events = self._get_latest_audit("request_approved")
        matching = [e for e in events if e.get("request_id") == rid]
        self.assertGreaterEqual(len(matching), 1,
                                "No request_approved audit event found")
        self.assertEqual(matching[0].get("status"), "approved")

        # Restore the row removed by approve replay
        self._restore_removed_row(visible, first_key)

    def test_reject_audit_event(self):
        """Rejection creates request_rejected audit event."""
        s, d = submit_approval("bulk_row_removal", creds=ANALYST2)
        rid = d["request_id"]
        process_approval(rid, "reject", creds=WLADMIN1,
                         rejection_reason="Test rejection")

        events = self._get_latest_audit("request_rejected")
        matching = [e for e in events if e.get("request_id") == rid]
        self.assertGreaterEqual(len(matching), 1)
        self.assertEqual(matching[0].get("rejection_reason"), "Test rejection")


class Test03_CancelRequest(WLIntegrationTestCase):
    """Tests for cancelling approval requests."""

    def test_cancel_own_request(self):
        """Analyst cancels their own pending request."""
        s, d = submit_approval("bulk_row_removal", creds=ANALYST1)
        rid = d["request_id"]

        s2, d2 = cancel_request(rid, "Changed my mind", creds=ANALYST1)
        self.assertEqual(s2, 200)

        _, queue = get_approval_queue()
        resolved = queue.get("resolved", [])
        match = [r for r in resolved if r["request_id"] == rid]
        self.assertTrue(match)
        self.assertEqual(match[0]["status"], "cancelled")
        self.assertEqual(match[0]["cancellation_reason"], "Changed my mind")

    def test_cancel_requires_reason(self):
        """Cancel without reason -> 400."""
        s, d = submit_approval("bulk_row_removal", creds=ANALYST1)
        rid = d["request_id"]

        s2, d2 = cancel_request(rid, "", creds=ANALYST1)
        self.assertEqual(s2, 400)
        self.assertIn("reason is required", d2.get("error", ""))

        cancel_request(rid, "Cleanup", creds=ANALYST1)

    def test_cancel_other_users_request_blocked(self):
        """Analyst cannot cancel another's request -> 403."""
        s, d = submit_approval("bulk_row_removal", creds=ANALYST1)
        rid = d["request_id"]

        s2, d2 = cancel_request(rid, "I want to cancel", creds=ANALYST2)
        self.assertEqual(s2, 403)
        self.assertIn("original requester", d2.get("error", ""))

        cancel_request(rid, "Cleanup", creds=ANALYST1)

    def test_cancel_already_resolved_states(self):
        """Cannot cancel approved, rejected, or already-cancelled requests."""
        # Cancel after approve (use real CSV data for successful approve)
        headers, rows, _ = self._load_csv()
        visible = [h for h in headers if not h.startswith("_")]
        first_key = [rows[0].get(h, "") for h in visible] if rows else []

        s, d = submit_approval(
            "bulk_row_removal", creds=ANALYST1,
            pending_highlight={
                "type": "rows", "headers": visible, "row_keys": [first_key],
            },
            original_payload={
                "removal_reasons": [{"reason": "Resolved state test"}],
            },
        )
        rid1 = d["request_id"]
        process_approval(rid1, "approve", creds=WLADMIN1)
        s2, _ = cancel_request(rid1, "Too late", creds=ANALYST1)
        self.assertEqual(s2, 409)

        # Restore removed row
        h2, r2, _ = self._load_csv()
        restored = {h: v for h, v in zip(visible, first_key)}
        r2.append(restored)
        save_csv(h2, r2, comment="Restore after resolved state test")

        # Cancel after reject
        s, d = submit_approval("bulk_row_edit", creds=ANALYST1)
        rid2 = d["request_id"]
        process_approval(rid2, "reject", creds=WLADMIN1,
                         rejection_reason="Nope")
        s2, _ = cancel_request(rid2, "Too late", creds=ANALYST1)
        self.assertEqual(s2, 409)

        # Double-cancel
        s, d = submit_approval("column_removal", creds=ANALYST1)
        rid3 = d["request_id"]
        cancel_request(rid3, "First", creds=ANALYST1)
        s2, _ = cancel_request(rid3, "Second", creds=ANALYST1)
        self.assertEqual(s2, 409)

    def test_cancel_nonexistent(self):
        """Cancel nonexistent request -> 404."""
        s, d = cancel_request("fake-id-99999", "Doesn't exist", creds=ANALYST1)
        self.assertEqual(s, 404)

    def test_cancel_audit_event(self):
        """Cancellation creates request_cancelled audit event."""
        s, d = submit_approval("bulk_row_removal", creds=ANALYST1)
        rid = d["request_id"]
        cancel_request(rid, "Test cancel reason", creds=ANALYST1)

        events = self._get_latest_audit("request_cancelled")
        matching = [e for e in events if e.get("request_id") == rid]
        self.assertGreaterEqual(len(matching), 1)
        self.assertEqual(matching[0].get("cancellation_reason"),
                         "Test cancel reason")

    def test_wladmin_cancel_own_request(self):
        """wl_admin can cancel their own request."""
        s, d = submit_approval("bulk_row_removal", creds=WLADMIN1)
        rid = d["request_id"]

        s2, d2 = cancel_request(rid, "Admin cancels own", creds=WLADMIN1)
        self.assertEqual(s2, 200)


class Test04_CSVLocking(WLIntegrationTestCase):
    """Tests for CSV locking while approval is pending."""

    def test_csv_locked_and_unlocked_lifecycle(self):
        """CSV locked while pending, unlocked after approval/rejection/cancel."""
        s, d = submit_approval("bulk_row_removal", creds=ANALYST1)
        rid = d["request_id"]

        s2, data = get_csv_content()
        self.assertEqual(s2, 200)
        self.assertTrue(data.get("pending_approvals"),
                        "Expected pending_approvals while request is pending")

        cancel_request(rid, "Unlock test", creds=ANALYST1)

        s3, data = get_csv_content()
        self.assertFalse(data.get("pending_approvals"),
                         "CSV should be unlocked after cancellation")

    def test_save_blocked_while_locked(self):
        """Cannot save CSV while approval is pending -> 409."""
        s, d = submit_approval("bulk_row_removal", creds=ANALYST1)
        rid = d["request_id"]

        headers, rows, mtime = self._load_csv()
        visible = [h for h in headers if not h.startswith("_")]
        if rows:
            rows[0][visible[0]] = "lock_test_value"
        s2, d2 = save_csv(headers, rows, comment="Should fail",
                          expected_mtime=mtime)
        self.assertIn(s2, (409, 403),
                      f"Expected 409/403 when CSV locked, got {s2}: {d2}")

        cancel_request(rid, "Cleanup", creds=ANALYST1)


class Test05_FullLifecycleAuditTrail(WLIntegrationTestCase):
    """End-to-end audit trail verification for the full lifecycle."""

    def test_submit_approve_audit_trail(self):
        """Full: submit -> approve -> both audit events with matching fields.

        Uses real CSV data so the approve replay succeeds.
        """
        # Get real row data
        headers, rows, _ = self._load_csv()
        visible = [h for h in headers if not h.startswith("_")]
        if not rows:
            self.skipTest("No rows in test CSV")
        first_key = [rows[0].get(h, "") for h in visible]

        s, d = submit_approval(
            "bulk_row_removal", creds=ANALYST1,
            description="Full lifecycle test",
            pending_highlight={
                "type": "rows", "headers": visible, "row_keys": [first_key],
            },
            original_payload={
                "removal_reasons": [{"reason": "Lifecycle approve test"}],
            },
        )
        self.assertEqual(s, 200)
        rid = d["request_id"]
        wait_for_indexing()

        s2, d2 = process_approval(rid, "approve", creds=WLADMIN1)
        self.assertEqual(s2, 200, f"Approve failed: {d2}")
        wait_for_indexing()

        submit_events = search_audit(
            f'request_id="{rid}" action="request_submitted"')
        approve_events = search_audit(
            f'request_id="{rid}" action="request_approved"')

        self.assertGreaterEqual(len(submit_events), 1,
                                "Missing request_submitted event")
        self.assertGreaterEqual(len(approve_events), 1,
                                "Missing request_approved event")

        # Verify consistent fields
        self.assertEqual(submit_events[0].get("approval_action_type"),
                         "bulk_row_removal")
        self.assertEqual(approve_events[0].get("approval_action_type"),
                         "bulk_row_removal")
        self.assertEqual(approve_events[0].get("csv_file"), TEST_CSV)

        # Restore removed row
        h2, r2, _ = self._load_csv()
        restored = {h: v for h, v in zip(visible, first_key)}
        r2.append(restored)
        save_csv(h2, r2, comment="Restore after lifecycle test")

    def test_submit_cancel_audit_trail(self):
        """Full: submit -> cancel -> both audit events present."""
        s, d = submit_approval("bulk_row_edit", creds=ANALYST1)
        self.assertEqual(s, 200, f"Submit failed: {d}")
        rid = d["request_id"]
        wait_for_indexing()

        cancel_request(rid, "Lifecycle cancel test", creds=ANALYST1)
        wait_for_indexing()

        submit_events = search_audit(
            f'request_id="{rid}" action="request_submitted"')
        cancel_events = search_audit(
            f'request_id="{rid}" action="request_cancelled"')

        self.assertGreaterEqual(len(submit_events), 1)
        self.assertGreaterEqual(len(cancel_events), 1)
        self.assertEqual(cancel_events[0].get("cancellation_reason"),
                         "Lifecycle cancel test")


if __name__ == "__main__":
    unittest.main()
