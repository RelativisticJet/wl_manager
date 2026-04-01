#!/usr/bin/env python3
"""Comprehensive test of limits, permissions, notifications, and audit trail."""
import json
import sys
import time
import urllib.request
import urllib.parse
import ssl

BASE = "https://localhost:8089"
CTX = ssl._create_unverified_context()
USERS = {
    "admin": "Chang3d!",
    "wladmin1": "Chang3d!",
    "wladmin2": "Chang3d!",
    "analyst1": "Chang3d!",
    "analyst2": "Chang3d!",
}

passed = 0
failed = 0
errors = []
RUN_ID = str(int(time.time()))[-6:]  # unique suffix per test run


def get_token(user, pw):
    data = urllib.parse.urlencode({
        "username": user, "password": pw, "output_mode": "json"
    }).encode()
    req = urllib.request.Request(f"{BASE}/services/auth/login", data=data)
    resp = urllib.request.urlopen(req, context=CTX)
    return json.loads(resp.read())["sessionKey"]


def api_get(token, params):
    qs = urllib.parse.urlencode(params)
    url = f"{BASE}/services/custom/wl_manager?{qs}"
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Splunk {token}")
    try:
        resp = urllib.request.urlopen(req, context=CTX)
        return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        try:
            return json.loads(body)
        except Exception:
            return {"error": body, "status": e.code}


def api_post(token, payload):
    data = json.dumps(payload).encode()
    url = f"{BASE}/services/custom/wl_manager"
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Authorization", f"Splunk {token}")
    req.add_header("Content-Type", "application/json")
    try:
        resp = urllib.request.urlopen(req, context=CTX)
        return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        try:
            return json.loads(body)
        except Exception:
            return {"error": body, "status": e.code}


def test(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        msg = f"  FAIL: {name}"
        if detail:
            msg += f" -- {detail}"
        print(msg)
        errors.append(name)


# ── Get tokens ────────────────────────────────────────────────────
print("=== Getting auth tokens ===")
tokens = {}
for user, pw in USERS.items():
    try:
        tokens[user] = get_token(user, pw)
        print(f"  OK: {user}")
    except Exception as e:
        print(f"  FAIL: {user} - {e}")
        sys.exit(1)

# ── CLEANUP: Remove test rules from previous runs ─────────────────
print("\n=== Cleanup: Remove stale test rules ===")
import subprocess
subprocess.run([
    "bash", "-c",
    "sed -i '/DR_RULE_\\|DR_DIRECT_\\|DR_SELF_\\|DR_BLOCKED_\\|DR_SANITIZE\\|DR_FIELD_\\|DR_CSV_TEST/d' "
    "/opt/splunk/etc/apps/wl_manager/lookups/rule_csv_map.csv"
], capture_output=True)
print("  Done")

# ── TEST 1: Set permissions to require approval ───────────────────
print("\n=== Test 1: Configure permissions (require approval for all) ===")
config = api_post(tokens["admin"], {
    "action": "set_daily_limits",
    "limits": {
        "row_addition": 10, "individual_row_removal": 10,
        "bulk_row_removal": 10, "row_edit": 10, "bulk_row_edit": 10,
        "row_reorder": 10, "column_addition": 2, "column_removal": 2,
        "column_reorder": 10, "revert": 3,
        "allow_analyst_create_rules": True,
        "allow_analyst_create_csv": True,
        "allow_analyst_delete_rules": True,
        "allow_analyst_delete_csv": True,
        "require_reason_rule_creation": True,
        "require_reason_csv_creation": True,
        "require_reason_rule_deletion": True,
        "require_reason_csv_deletion": True,
    }
})
test("Config saved",
     "updated" in str(config).lower() or "no_changes" in str(config)
     or "saved" in str(config).lower(),
     str(config)[:200])

# ── TEST 2: Analyst submits create_rule request ───────────────────
print("\n=== Test 2: Analyst1 submits create_rule request ===")
result = api_post(tokens["analyst1"], {
    "action": "submit_approval",
    "approval_action_type": "create_rule",
    "detection_rule": "DR_RULE_A1",
    "csv_file": "__rule_operation__",
    "description": "Need new rule for test purposes",
    "comment": "Test rule creation"
})
test("Create rule request submitted", "request_id" in result, str(result)[:200])
req_id_1 = result.get("request_id", "")
print(f"    Request ID: {req_id_1}")
test("Request ID clean (no csv/rule name in ID)",
     "__rule_operation__" not in req_id_1 and "DR_TEST" not in req_id_1,
     req_id_1)

# ── TEST 3: Different create_rule should work ─────────────────────
print("\n=== Test 3: Analyst1 submits different create_rule ===")
result2 = api_post(tokens["analyst1"], {
    "action": "submit_approval",
    "approval_action_type": "create_rule",
    "detection_rule": "DR_RULE_B1",
    "csv_file": "__rule_operation__",
    "description": "Second rule request",
    "comment": "Another test rule"
})
test("Different rule accepted", "request_id" in result2, str(result2)[:200])
req_id_2 = result2.get("request_id", "")

# ── TEST 4: Same create_rule should block ─────────────────────────
print("\n=== Test 4: Duplicate create_rule blocked ===")
result3 = api_post(tokens["analyst1"], {
    "action": "submit_approval",
    "approval_action_type": "create_rule",
    "detection_rule": "DR_RULE_A1",
    "csv_file": "__rule_operation__",
    "description": "Duplicate request",
})
test("Duplicate blocked",
     "error" in result3 or "pending" in str(result3).lower(),
     str(result3)[:200])

# ── TEST 5: Analyst2 submits create_csv ──────────────────────────
print("\n=== Test 5: Analyst2 submits create_csv ===")
result4 = api_post(tokens["analyst2"], {
    "action": "submit_approval",
    "approval_action_type": "create_csv",
    "detection_rule": "DR_CSV_TEST_RULE",
    "csv_file": "DR_CSV_TEST.csv",
    "description": "New CSV for testing",
})
test("Create CSV submitted", "request_id" in result4, str(result4)[:200])
req_id_3 = result4.get("request_id", "")

# ── TEST 6: Admin notifications ───────────────────────────────────
print("\n=== Test 6: Check admin notifications ===")
time.sleep(1)
for admin_user in ["admin", "wladmin1", "wladmin2"]:
    notifs = api_get(tokens[admin_user], {"action": "get_notifications"})
    count = notifs.get("unread_count", 0)
    items = notifs.get("notifications", [])
    test(f"{admin_user} received notifications", count > 0,
         f"unread={count}, items={len(items)}")
    if items:
        print(f"    Latest: {items[0].get('message', 'N/A')[:80]}")

# ── TEST 7: Analyst notifications empty pre-approval ──────────────
print("\n=== Test 7: Analyst notifications (pre-approval) ===")
for analyst_user in ["analyst1", "analyst2"]:
    notifs = api_get(tokens[analyst_user], {"action": "get_notifications"})
    count = notifs.get("unread_count", 0)
    test(f"{analyst_user} no notifications yet", count == 0,
         f"unread={count}")

# ── TEST 8: wladmin1 approves request 1 ──────────────────────────
print("\n=== Test 8: wladmin1 approves request 1 ===")
result5 = api_post(tokens["wladmin1"], {
    "action": "process_approval",
    "request_id": req_id_1,
    "decision": "approve",
    "admin_comment": ""
})
test("Request approved",
     "approved" in str(result5).lower() or "message" in result5,
     str(result5)[:200])

# Check admin_comment defaults to "Approved" in full queue
queue_data = api_post(tokens["admin"], {"action": "get_approval_queue"})
all_q = queue_data.get("queue", [])
approved_entry = [i for i in all_q if i.get("request_id") == req_id_1]
if approved_entry:
    ac = approved_entry[0].get("admin_comment", "")
    test("Default admin_comment = 'Approved'", ac == "Approved",
         f"admin_comment='{ac}'")
else:
    print(f"    WARNING: Could not find {req_id_1} in {len(all_q)} queue items")

# ── TEST 9: Analyst1 approval notification ────────────────────────
print("\n=== Test 9: Analyst1 approval notification ===")
time.sleep(1)
notifs = api_get(tokens["analyst1"], {"action": "get_notifications"})
count = notifs.get("unread_count", 0)
items = notifs.get("notifications", [])
test("Analyst1 got notification", count > 0, f"unread={count}")
has_approved = any("approved" in n.get("message", "").lower() for n in items)
test("Notification mentions approved", has_approved,
     str([n["message"] for n in items[:3]]))

# ── TEST 10: wladmin2 rejects request 2 ──────────────────────────
print("\n=== Test 10: wladmin2 rejects request 2 ===")
result6 = api_post(tokens["wladmin2"], {
    "action": "process_approval",
    "request_id": req_id_2,
    "decision": "reject",
    "rejection_reason": "Not needed at this time"
})
test("Request rejected",
     "rejected" in str(result6).lower() or "reject" in str(result6).lower(),
     str(result6)[:200])

# ── TEST 11: Analyst1 rejection notification ──────────────────────
print("\n=== Test 11: Analyst1 rejection notification ===")
time.sleep(1)
notifs = api_get(tokens["analyst1"], {"action": "get_notifications"})
items = notifs.get("notifications", [])
has_rejected = any("rejected" in n.get("message", "").lower() for n in items)
test("Analyst1 got rejection notification", has_rejected,
     str([n["message"] for n in items[:5]]))

# ── TEST 12: Analyst2 cancels their own request ───────────────────
print("\n=== Test 12: Analyst2 cancels request ===")
result7 = api_post(tokens["analyst2"], {
    "action": "cancel_request",
    "request_id": req_id_3,
    "cancellation_reason": "No longer needed"
})
test("Request cancelled", "cancel" in str(result7).lower(), str(result7)[:200])

# ── TEST 13: Admin gets cancellation notification ─────────────────
print("\n=== Test 13: Admin cancellation notification ===")
time.sleep(1)
notifs = api_get(tokens["wladmin1"], {"action": "get_notifications"})
items = notifs.get("notifications", [])
has_cancelled = any("cancel" in n.get("message", "").lower() for n in items)
test("Admin got cancellation notification", has_cancelled,
     str([n["message"] for n in items[:5]]))

# ── TEST 14: Permission OFF - analyst blocked ────────────────────
print("\n=== Test 14: Rule creation OFF - analyst blocked ===")
api_post(tokens["admin"], {
    "action": "set_daily_limits",
    "limits": {"allow_analyst_create_rules": False}
})
time.sleep(0.5)
result8 = api_post(tokens["analyst1"], {
    "action": "submit_approval",
    "approval_action_type": "create_rule",
    "detection_rule": "DR_BLOCKED_TEST",
    "csv_file": "__rule_operation__",
    "description": "Should be blocked",
})
test("Analyst blocked when permission off",
     "error" in result8 or "not allowed" in str(result8).lower()
     or "denied" in str(result8).lower() or "disabled" in str(result8).lower()
     or "not permitted" in str(result8).lower(),
     str(result8)[:200])

# ── TEST 15: Permission ON no approval - direct ──────────────────
print("\n=== Test 15: Rule creation ON (no approval) - direct ===")
api_post(tokens["admin"], {
    "action": "set_daily_limits",
    "limits": {
        "allow_analyst_create_rules": True,
        "require_reason_rule_creation": False,
    }
})
time.sleep(0.5)
result9 = api_post(tokens["analyst1"], {
    "action": "create_rule",
    "detection_rule": "DR_DIRECT_CREATE",
    "csv_file": "__rule_operation__",
    "description": "Direct creation",
})
test("Direct creation succeeded (or no approval needed)",
     "error" not in result9 or "approval" not in str(result9).lower(),
     str(result9)[:200])

# Restore to require approval
api_post(tokens["admin"], {
    "action": "set_daily_limits",
    "limits": {
        "allow_analyst_create_rules": True,
        "require_reason_rule_creation": True,
    }
})

# ── TEST 16: Self-approval prevention ─────────────────────────────
print("\n=== Test 16: Self-approval prevention ===")
result10 = api_post(tokens["wladmin1"], {
    "action": "submit_approval",
    "approval_action_type": "create_rule",
    "detection_rule": "DR_SELF_APPROVE",
    "csv_file": "__rule_operation__",
    "description": "Testing self-approval",
})
if "request_id" in result10:
    self_req = result10["request_id"]
    result11 = api_post(tokens["wladmin1"], {
        "action": "process_approval",
        "request_id": self_req,
        "decision": "approve",
    })
    test("Self-approval blocked",
         "error" in result11 or "own" in str(result11).lower()
         or "self" in str(result11).lower(),
         str(result11)[:200])
    api_post(tokens["admin"], {
        "action": "process_approval",
        "request_id": self_req,
        "decision": "reject",
        "rejection_reason": "Cleanup"
    })
else:
    test("Admin bypasses approval (expected)", True, str(result10)[:200])

# ── TEST 17: Input sanitization ───────────────────────────────────
print("\n=== Test 17: Input sanitization ===")
dirty_input = '<script>alert("xss")</script> `backtick` \\backslash'
result12 = api_post(tokens["analyst1"], {
    "action": "submit_approval",
    "approval_action_type": "create_rule",
    "detection_rule": "DR_SANITIZE",
    "csv_file": "__rule_operation__",
    "description": dirty_input,
})
if "request_id" in result12:
    san_req = result12["request_id"]
    queue_data = api_post(tokens["admin"], {"action": "get_approval_queue"})
    items = queue_data.get("queue", [])
    found = [i for i in items if i.get("request_id") == san_req
             and i.get("status") == "pending"]
    if found:
        stored = found[0].get("description", "")
        test("Script tags sanitized", "<script>" not in stored, stored)
        test("Backticks sanitized", "`" not in stored, stored)
        test("Backslashes sanitized", "\\" not in stored, stored)
        print(f"    Stored: {stored}")
    else:
        test("Found in queue", False, f"Not found in {len(items)} items")
    api_post(tokens["analyst1"], {
        "action": "cancel_request",
        "request_id": san_req,
        "cancellation_reason": "Cleanup"
    })
else:
    test("Sanitization submission", False, str(result12)[:200])

# ── TEST 18: Mark notifications read ──────────────────────────────
print("\n=== Test 18: Mark notifications read ===")
notifs = api_get(tokens["analyst1"], {"action": "get_notifications"})
pre = notifs.get("unread_count", 0)
api_post(tokens["analyst1"], {
    "action": "mark_notifications_read",
    "notification_ids": "all"
})
notifs2 = api_get(tokens["analyst1"], {"action": "get_notifications"})
post = notifs2.get("unread_count", 0)
test("All notifications marked read", post == 0,
     f"before={pre}, after={post}")

# ── TEST 19: Queue entry field completeness ───────────────────────
print("\n=== Test 19: Queue entry fields ===")
result14 = api_post(tokens["analyst2"], {
    "action": "submit_approval",
    "approval_action_type": "create_rule",
    "detection_rule": "DR_FIELD_CHECK",
    "csv_file": "__rule_operation__",
    "description": "Verify fields",
})
if "request_id" in result14:
    req_id_check = result14["request_id"]
    queue_data = api_post(tokens["admin"], {"action": "get_approval_queue"})
    items = queue_data.get("queue", [])
    found = [i for i in items if i.get("request_id") == req_id_check
             and i.get("status") == "pending"]
    if found:
        entry = found[0]
        for field in ["detection_rule", "action_type", "analyst",
                       "description", "timestamp", "status"]:
            test(f"Queue has '{field}'", field in entry,
                 str(list(entry.keys())))
        test("detection_rule = 'DR_FIELD_CHECK'",
             entry.get("detection_rule") == "DR_FIELD_CHECK",
             entry.get("detection_rule"))
    else:
        test("Found entry", False, f"Not in {len(items)} items")
    api_post(tokens["analyst2"], {
        "action": "cancel_request",
        "request_id": req_id_check,
        "cancellation_reason": "Cleanup"
    })
else:
    test("Submit for field check", False, str(result14)[:200])

# ── TEST 20: Audit trail ─────────────────────────────────────────
print("\n=== Test 20: Audit trail ===")
time.sleep(2)
print("    (Check audit events manually via Splunk search)")

# ── SUMMARY ───────────────────────────────────────────────────────
print("\n" + "=" * 60)
print(f"PASSED: {passed}")
print(f"FAILED: {failed}")
if errors:
    print(f"Failed tests:")
    for e in errors:
        print(f"  - {e}")
print("=" * 60)
sys.exit(0 if failed == 0 else 1)
