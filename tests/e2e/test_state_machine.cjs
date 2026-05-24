/**
 * Approval State Machine Test
 *
 * Enumerates valid and invalid transitions on the approval queue:
 *   pending → approved  ✓
 *   pending → rejected  ✓
 *   pending → cancelled ✓
 *   approved → anything ✗ (must return 409)
 *   rejected → anything ✗ (must return 409)
 *   cancelled → anything ✗ (must return 409)
 *   unknown_id → anything ✗ (must return 404)
 *
 * Also covers input validation:
 *   - Missing/invalid decision
 *   - Decision="reject" with no rejection_reason
 *   - Decision="cancel" with no cancellation_reason
 *   - Self-approval (submitter == admin) → 403
 *   - Cancel by unrelated analyst → 403
 *
 * Why it matters: state machine bugs are where "the UI works" but the
 * backend lets two admins approve the same request, or lets a rejected
 * request get re-approved. These bugs hide between the test-pass-rate
 * and the bug-reported-in-production gap.
 */
const H = require("./lib_helpers.cjs");

// We use bulk_row_removal — it's a no-op approval type for our purposes
// (we never call the approval's replay). It needs a valid csv_file and
// a minimal payload that satisfies submit_approval.
function buildSubmitPayload(ruleTag) {
    return {
        action: "submit_approval",
        approval_action_type: "bulk_row_removal",
        detection_rule: "DR55_brute_force_login",
        csv_file: "DR55_brute_force_users.csv",
        reason: `state_machine_test_${ruleTag}`,
        payload: {
            removed_keys: ["sm_test_row_key_1", "sm_test_row_key_2"],
            rows: [],
            remove_reason: `state_machine_test_${ruleTag}`,
        },
    };
}

// Clean up any leftover pending requests for our test CSV
async function cleanupStaleRequests(page) {
    const q = await H.restCall(page, "GET", { action: "get_approval_queue" });
    const items = q.approval_queue || q.queue || [];
    for (const item of items) {
        if (item.status === "pending" &&
            item.detection_rule === "DR55_brute_force_login" &&
            item.reason && item.reason.startsWith("state_machine_test_")) {
            await H.restCall(page, "POST", {
                action: "process_approval",
                request_id: item.request_id,
                decision: "cancel",
                cancellation_reason: "state_machine_test_cleanup",
            });
        }
    }
}

(async () => {
    H.log("\u{1F504}", `=== APPROVAL STATE MACHINE TEST ===`);

    const analyst = await H.createSession("analyst1", "Chang3d!");
    const admin   = await H.createSession("wladmin1",  "Chang3d!");
    const admin2  = await H.createSession("wladmin2",  "Chang3d!");

    await cleanupStaleRequests(admin.page);

    // ── Pure negative cases (no request needed) ──

    await H.test("SM01 process_approval with unknown request_id \u2192 404", async () => {
        const r = await H.restCall(admin.page, "POST", {
            action: "process_approval",
            request_id: "sm_fake_id_does_not_exist",
            decision: "approve",
        });
        if (!r.error || !/not found/i.test(r.error)) {
            throw new Error(`Expected 'not found' error, got: ${JSON.stringify(r)}`);
        }
    });

    await H.test("SM02 process_approval with invalid decision \u2192 400", async () => {
        const r = await H.restCall(admin.page, "POST", {
            action: "process_approval",
            request_id: "anything",
            decision: "maybe",
        });
        if (!r.error || !/approve, reject, or cancel/i.test(r.error)) {
            throw new Error(`Expected validation error, got: ${JSON.stringify(r)}`);
        }
    });

    await H.test("SM03 reject without rejection_reason \u2192 400", async () => {
        const r = await H.restCall(admin.page, "POST", {
            action: "process_approval",
            request_id: "anything",
            decision: "reject",
        });
        if (!r.error || !/rejection reason/i.test(r.error)) {
            throw new Error(`Expected rejection reason error, got: ${JSON.stringify(r)}`);
        }
    });

    await H.test("SM04 cancel without cancellation_reason \u2192 400", async () => {
        const r = await H.restCall(admin.page, "POST", {
            action: "process_approval",
            request_id: "anything",
            decision: "cancel",
        });
        if (!r.error || !/cancellation reason/i.test(r.error)) {
            throw new Error(`Expected cancellation reason error, got: ${JSON.stringify(r)}`);
        }
    });

    await H.test("SM05 submit_approval with invalid action_type \u2192 400", async () => {
        const r = await H.restCall(analyst.page, "POST", {
            action: "submit_approval",
            approval_action_type: "no_such_thing",
            detection_rule: "DR55_brute_force_login",
            csv_file: "DR55_brute_force_users.csv",
            reason: "sm05_test",
            payload: {},
        });
        if (!r.error || !/invalid approval action type/i.test(r.error)) {
            throw new Error(`Expected invalid type error, got: ${JSON.stringify(r)}`);
        }
    });

    // ── Lifecycle: pending \u2192 approved, then try more transitions ──

    let approvedReqId = null;
    await H.test("SM06 analyst submits request \u2192 pending", async () => {
        const r = await H.restCall(analyst.page, "POST", buildSubmitPayload("lifecycle_approve"));
        if (r.error) throw new Error(`Submit failed: ${r.error}`);
        if (!r.request_id) throw new Error(`No request_id in response: ${JSON.stringify(r)}`);
        approvedReqId = r.request_id;
    });

    await H.test("SM07 admin approves the request \u2192 success", async () => {
        const r = await H.restCall(admin.page, "POST", {
            action: "process_approval",
            request_id: approvedReqId,
            decision: "approve",
            admin_comment: "sm07_approve",
        });
        // Approval replay MAY fail at the replay stage (no real rows to
        // remove for our fake keys) — that's OK. The state transition
        // to "approved" or "failed" is what matters; "pending" would
        // indicate a bug.
        const q = await H.restCall(admin.page, "GET", { action: "get_approval_queue" });
        const items = q.approval_queue || q.queue || [];
        const me = items.find(i => i.request_id === approvedReqId);
        if (!me) throw new Error("Request vanished from queue");
        if (me.status === "pending") {
            throw new Error(`Status should have changed from pending, still pending: ${JSON.stringify(me).slice(0, 200)}`);
        }
    });

    await H.test("SM08 re-approve already-processed request \u2192 409 'already'", async () => {
        const r = await H.restCall(admin.page, "POST", {
            action: "process_approval",
            request_id: approvedReqId,
            decision: "approve",
            admin_comment: "sm08_re_approve",
        });
        if (!r.error || !/already/i.test(r.error)) {
            throw new Error(`Expected 'already processed' error, got: ${JSON.stringify(r)}`);
        }
    });

    await H.test("SM09 reject already-processed request \u2192 409", async () => {
        const r = await H.restCall(admin.page, "POST", {
            action: "process_approval",
            request_id: approvedReqId,
            decision: "reject",
            rejection_reason: "sm09_late_reject",
        });
        if (!r.error || !/already/i.test(r.error)) {
            throw new Error(`Expected 'already processed' error, got: ${JSON.stringify(r)}`);
        }
    });

    await H.test("SM10 cancel already-processed request \u2192 409", async () => {
        const r = await H.restCall(admin.page, "POST", {
            action: "process_approval",
            request_id: approvedReqId,
            decision: "cancel",
            cancellation_reason: "sm10_late_cancel",
        });
        if (!r.error || !/already/i.test(r.error)) {
            throw new Error(`Expected 'already processed' error, got: ${JSON.stringify(r)}`);
        }
    });

    // ── Lifecycle: pending \u2192 rejected ──

    let rejectedReqId = null;
    await cleanupStaleRequests(admin.page);

    await H.test("SM11 analyst submits + admin rejects \u2192 rejected", async () => {
        const sub = await H.restCall(analyst.page, "POST", buildSubmitPayload("lifecycle_reject"));
        if (sub.error) throw new Error(`Submit failed: ${sub.error}`);
        rejectedReqId = sub.request_id;

        const r = await H.restCall(admin.page, "POST", {
            action: "process_approval",
            request_id: rejectedReqId,
            decision: "reject",
            rejection_reason: "sm11_reject",
        });
        if (r.error) throw new Error(`Reject failed: ${r.error}`);
    });

    await H.test("SM12 cannot approve a rejected request \u2192 409", async () => {
        const r = await H.restCall(admin.page, "POST", {
            action: "process_approval",
            request_id: rejectedReqId,
            decision: "approve",
        });
        if (!r.error || !/already/i.test(r.error)) {
            throw new Error(`Expected 'already rejected' error, got: ${JSON.stringify(r)}`);
        }
    });

    // ── Self-approval blocked ──

    // Rate-limit budget refresh: SM01-SM12 plus the prior test_security_bypass
    // suite consume wladmin1's RATE_MAX_WRITES=30/60s budget. Without a
    // window-slide pause here, SM13's `process_approval` call returns
    // 429 "Rate limit exceeded" instead of the expected 403 self-approval
    // block, and SM14/SM15 inherit the leftover lock from SM13's
    // unprocessed request. Pause 65s (one full rate-limit window + 5s
    // buffer) so wladmin1 has a fresh budget for the final 3 sub-tests.
    // See docs/V1_RC_RETRO.md (run 26351850079 evidence).
    H.log("\u23f1\ufe0f", `  Waiting 65s for rate-limit window slide before SM13-SM15...`);
    await new Promise(r => setTimeout(r, 65000));

    await cleanupStaleRequests(admin.page);

    await H.test("SM13 submitter cannot approve their own request \u2192 403", async () => {
        // wladmin1 submits as both analyst and admin (has EDIT_ROLES)
        const sub = await H.restCall(admin.page, "POST", buildSubmitPayload("self_approve"));
        if (sub.error) {
            // If admin-submitting is blocked at submit time, skip test
            H.log("\u2139\uFE0F", `  Admin submit blocked: ${sub.error} \u2014 skipping self-approve`);
            return;
        }
        const r = await H.restCall(admin.page, "POST", {
            action: "process_approval",
            request_id: sub.request_id,
            decision: "approve",
        });
        if (!r.error || !/cannot approve your own|self/i.test(r.error)) {
            throw new Error(`Expected self-approval block, got: ${JSON.stringify(r)}`);
        }
        // cleanup
        await H.restCall(admin2.page, "POST", {
            action: "process_approval",
            request_id: sub.request_id,
            decision: "cancel",
            cancellation_reason: "sm13_cleanup",
        });
    });

    // ── Cross-analyst cancellation ──

    await cleanupStaleRequests(admin.page);

    await H.test("SM14 unrelated analyst cannot cancel another's request \u2192 403", async () => {
        const sub = await H.restCall(analyst.page, "POST", buildSubmitPayload("cross_cancel"));
        if (sub.error) throw new Error(`Submit failed: ${sub.error}`);

        const analyst2 = await H.createSession("analyst2", "Chang3d!");
        try {
            const r = await H.restCall(analyst2.page, "POST", {
                action: "cancel_request",
                request_id: sub.request_id,
                cancellation_reason: "sm14_hijack_attempt",
            });
            // cancel_request allows any authenticated user to try, but
            // should refuse if the caller isn't the original submitter
            // or an admin. Look for permission-style error.
            if (!r.error) {
                throw new Error(`Expected permission error, got success: ${JSON.stringify(r)}`);
            }
            if (!/original requester|admin can cancel|permission|not allowed/i.test(r.error)) {
                throw new Error(`Expected permission-style error, got: ${r.error}`);
            }
        } finally {
            await analyst2.browser.close();
            // cleanup
            await H.restCall(admin.page, "POST", {
                action: "process_approval",
                request_id: sub.request_id,
                decision: "cancel",
                cancellation_reason: "sm14_cleanup",
            });
        }
    });

    // ── Duplicate submission lock ──

    await cleanupStaleRequests(admin.page);

    await H.test("SM15 same CSV locked by pending request \u2192 2nd submit rejected", async () => {
        const first = await H.restCall(analyst.page, "POST", buildSubmitPayload("lock_first"));
        if (first.error) throw new Error(`First submit failed: ${first.error}`);

        try {
            const second = await H.restCall(analyst.page, "POST", buildSubmitPayload("lock_second"));
            if (!second.error) {
                throw new Error(`Second submit should have been blocked, got: ${JSON.stringify(second)}`);
            }
            if (!/pending|locked|already have/i.test(second.error)) {
                throw new Error(`Expected lock error, got: ${second.error}`);
            }
        } finally {
            await H.restCall(admin.page, "POST", {
                action: "process_approval",
                request_id: first.request_id,
                decision: "cancel",
                cancellation_reason: "sm15_cleanup",
            });
        }
    });

    await cleanupStaleRequests(admin.page);
    await analyst.browser.close();
    await admin.browser.close();
    await admin2.browser.close();

    H.summary("State Machine Test Results");
    process.exit(H.results.some(r => r.status === "FAIL") ? 1 : 0);
})();
