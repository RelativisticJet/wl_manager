"""Test approval gates and notification system."""
import json
import ssl
import urllib.request
import urllib.parse
import base64
import time

BASE = "https://localhost:8089"
SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

def api_get(user, password, action, extra_params=None):
    """GET request to wl_manager endpoint."""
    params = {"action": action, "output_mode": "json"}
    if extra_params:
        params.update(extra_params)
    url = BASE + "/servicesNS/nobody/wl_manager/custom/wl_manager?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, method="GET")
    creds = base64.b64encode(f"{user}:{password}".encode()).decode()
    req.add_header("Authorization", f"Basic {creds}")
    try:
        resp = urllib.request.urlopen(req, context=SSL_CTX, timeout=30)
        return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        try:
            return json.loads(body)
        except Exception:
            return {"error": body, "status": e.code}

def api_post(user, password, payload_dict):
    """POST request to wl_manager endpoint (JSON body like the frontend)."""
    url = BASE + "/servicesNS/nobody/wl_manager/custom/wl_manager?output_mode=json"
    body = json.dumps(payload_dict).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    creds = base64.b64encode(f"{user}:{password}".encode()).decode()
    req.add_header("Authorization", f"Basic {creds}")
    try:
        resp = urllib.request.urlopen(req, context=SSL_CTX, timeout=30)
        return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        try:
            return json.loads(body)
        except Exception:
            return {"error": body, "status": e.code}

def test(label, result, check=None):
    ok = True
    if check:
        ok = check(result)
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {label}")
    if not ok:
        print(f"  Result: {json.dumps(result, indent=2)[:500]}")
    return ok

pw = "Chang3d!"
results = []

# === 1. Config and Permissions ===
print("\n=== TEST 1: Config and Permissions ===")
r = api_get("admin", pw, "get_mapping")
perms = r.get("permissions", {})
results.append(test("Admin gets empty reason_gates",
    r, lambda r: r.get("permissions", {}).get("reason_gates", {}) == {}))
results.append(test("Admin has edit permissions",
    r, lambda r: r.get("permissions", {}).get("can_create_rules", False)))
print(f"  Permissions: {json.dumps(perms, indent=2)[:300]}")

# === 2. Submit create_csv approval (as admin, simulating analyst) ===
print("\n=== TEST 2: Submit Create CSV Approval ===")
r = api_post("admin", pw, {
    "action": "submit_approval",
    "approval_action_type": "create_csv",
    "detection_rule": "DR999_stress_test",
    "csv_file": "test_gated_csv.csv",
    "description": "Create test CSV for approval gate testing",
    "approval_reason": "Need whitelist for stress test rule",
    "comment": "Approval requested for create csv",
})
print(f"  Response: {json.dumps(r)[:300]}")
request_id_1 = r.get("request_id", "")
results.append(test("Submit returns request_id",
    r, lambda r: bool(r.get("request_id"))))

# === 3. Notifications ===
print("\n=== TEST 3: Notifications ===")
time.sleep(1)
r = api_get("admin", pw, "get_notifications")
print(f"  Admin: unread={r.get('unread_count', 0)}, total={len(r.get('notifications', []))}")
results.append(test("Admin has unread notification",
    r, lambda r: r.get("unread_count", 0) > 0))

# === 4. Approval Queue ===
print("\n=== TEST 4: Approval Queue ===")
r = api_get("admin", pw, "get_pending_approvals", {"csv_file": "test_gated_csv.csv"})
pending = r.get("pending_approvals", [])
print(f"  Pending for test_gated_csv.csv: {len(pending)}")
if pending:
    print(f"  First: {json.dumps(pending[0], indent=2)[:300]}")
results.append(test("Pending approvals found",
    r, lambda r: len(r.get("pending_approvals", [])) > 0))

# === 5. Self-approval prevention ===
print("\n=== TEST 5: Self-Approval Prevention ===")
if request_id_1:
    r = api_post("admin", pw, {
        "action": "process_approval",
        "request_id": request_id_1,
        "decision": "approve",
        "admin_comment": "Self-approving",
    })
    print(f"  Self-approval response: {json.dumps(r)[:300]}")
    results.append(test("Self-approval blocked",
        r, lambda r: "error" in r))

# === 6. Approve via wladmin2 ===
print("\n=== TEST 6: Approval by Different Admin ===")
if request_id_1:
    r = api_post("wladmin2", pw, {
        "action": "process_approval",
        "request_id": request_id_1,
        "decision": "approve",
        "admin_comment": "Approved by wladmin2 for testing",
    })
    print(f"  wladmin2 approval: {json.dumps(r)[:300]}")
    if "Unauthorized" in str(r) or r.get("status") == 401:
        print("  [SKIP] wladmin2 lacks REST API access")
    else:
        results.append(test("Approval succeeds",
            r, lambda r: "error" not in r or r.get("status") in ("approved",)))

# === 7. Submit create_rule and cancel ===
print("\n=== TEST 7: Submit and Cancel ===")
r = api_post("admin", pw, {
    "action": "submit_approval",
    "approval_action_type": "create_rule",
    "detection_rule": "DR_TEST_CANCEL",
    "csv_file": "__rule_operation__",
    "description": "Create rule DR_TEST_CANCEL",
    "approval_reason": "Testing cancel flow",
    "comment": "Approval requested for create rule",
})
request_id_2 = r.get("request_id", "")
print(f"  Submit: request_id={request_id_2}")

if request_id_2:
    r = api_post("admin", pw, {
        "action": "cancel_request",
        "request_id": request_id_2,
        "cancellation_reason": "Testing cancel flow",
    })
    print(f"  Cancel: {json.dumps(r)[:200]}")
    results.append(test("Cancel succeeds",
        r, lambda r: r.get("status") == "cancelled" or "cancelled" in str(r).lower()))

# === 8. Submit remove_csv and reject ===
print("\n=== TEST 8: Submit and Reject ===")
r = api_post("admin", pw, {
    "action": "submit_approval",
    "approval_action_type": "remove_csv",
    "detection_rule": "DR999_stress_test",
    "csv_file": "DR999_stress_test.csv",
    "description": "Remove DR999_stress_test.csv",
    "approval_reason": "Testing rejection flow",
    "comment": "Approval requested for remove csv",
})
request_id_3 = r.get("request_id", "")
print(f"  Submit: request_id={request_id_3}")

if request_id_3:
    r = api_post("wladmin2", pw, {
        "action": "process_approval",
        "request_id": request_id_3,
        "decision": "reject",
        "admin_comment": "Rejected for testing",
    })
    print(f"  Reject: {json.dumps(r)[:300]}")
    if "Unauthorized" in str(r) or r.get("status") == 401:
        print("  [SKIP] wladmin2 lacks REST API access")
    else:
        results.append(test("Rejection succeeds",
            r, lambda r: r.get("status") == "rejected" or "rejected" in str(r).lower()))

# === 9. Mark notifications read ===
print("\n=== TEST 9: Mark Notifications Read ===")
r = api_get("admin", pw, "get_notifications")
notifs = r.get("notifications", [])
unread = [n for n in notifs if not n.get("read")]
print(f"  Total: {len(notifs)}, Unread: {len(unread)}")

if unread:
    mark_ids = [unread[0].get("id")]
    r = api_post("admin", pw, {
        "action": "mark_notifications_read",
        "notification_ids": mark_ids,
    })
    print(f"  Mark read: {json.dumps(r)[:200]}")
    r2 = api_get("admin", pw, "get_notifications")
    new_unread = r2.get("unread_count", 0)
    results.append(test(f"Unread decreased ({len(unread)} -> {new_unread})",
        r2, lambda r: r.get("unread_count", len(unread)) < len(unread)))

# === 10. Verify audit trail ===
print("\n=== TEST 10: Audit Trail ===")
# Use SPL search to check audit events
import subprocess
cmd = [
    "/opt/splunk/bin/splunk", "search",
    "index=wl_audit | head 20 | table _time action status request_id approval_action_type",
    "-auth", "admin:Chang3d!",
    "-app", "wl_manager",
]
try:
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    print(f"  Audit events:\n{result.stdout[:1000]}")
except Exception as e:
    print(f"  Could not query audit: {e}")

# === Summary ===
print(f"\n{'='*50}")
passed = sum(1 for r in results if r)
total = len(results)
print(f"Results: {passed}/{total} passed")
if passed < total:
    print("SOME TESTS FAILED — review output above")
else:
    print("ALL TESTS PASSED")
