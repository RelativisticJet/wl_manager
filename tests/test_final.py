"""Final comprehensive test of approval gates and notification system."""
import json
import ssl
import urllib.request
import base64
import time
import subprocess

BASE = "https://localhost:8089"
SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

def api_post(user, pw, payload):
    url = BASE + "/servicesNS/nobody/wl_manager/custom/wl_manager?output_mode=json"
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", "Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode())
    try:
        resp = urllib.request.urlopen(req, context=SSL_CTX, timeout=30)
        return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode())
        except Exception:
            return {"error": str(e), "status": e.code}

def api_get(user, pw, action, extra=None):
    import urllib.parse
    params = {"action": action, "output_mode": "json"}
    if extra:
        params.update(extra)
    url = BASE + "/servicesNS/nobody/wl_manager/custom/wl_manager?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, method="GET")
    req.add_header("Authorization", "Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode())
    try:
        resp = urllib.request.urlopen(req, context=SSL_CTX, timeout=30)
        return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode())
        except Exception:
            return {"error": str(e), "status": e.code}

PW = "Chang3d!"
results = []

def t(label, ok):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    results.append(ok)

# Clear notifications for clean test
try:
    with open("/opt/splunk/etc/apps/wl_manager/lookups/_versions/_notifications.json", "w") as f:
        json.dump({}, f)
except PermissionError:
    subprocess.run(["bash", "-c",
        "echo '{}' > /opt/splunk/etc/apps/wl_manager/lookups/_versions/_notifications.json"],
        timeout=5)
    subprocess.run(["chown", "splunk:splunk",
        "/opt/splunk/etc/apps/wl_manager/lookups/_versions/_notifications.json"],
        timeout=5)

print("=" * 60)
print("COMPREHENSIVE APPROVAL GATES & NOTIFICATION TEST")
print("=" * 60)

# ── 1. Permissions check ──
print("\n1. Permissions")
r = api_get("admin", PW, "get_mapping")
perms = r.get("permissions", {})
t("Admin: empty reason_gates", perms.get("reason_gates", {}) == {})
t("Admin: can_create_rules=True", perms.get("can_create_rules") is True)
t("Admin: can_delete_csv=True", perms.get("can_delete_csv") is True)

# ── 2. Submit all 4 types (admin submits, wladmin2 approves/rejects) ──
print("\n2. Create CSV — Submit + Approve")
r = api_post("admin", PW, {
    "action": "submit_approval",
    "approval_action_type": "create_csv",
    "detection_rule": "DR130_privilege_escalation",
    "csv_file": "final_test_csv.csv",
    "description": "Final test CSV creation",
    "original_payload": {
        "action": "create_csv",
        "detection_rule": "DR130_privilege_escalation",
        "csv_file": "final_test_csv.csv",
        "headers": ["user", "src_ip", "Comment"],
        "app_context": "wl_manager",
    },
})
rid1 = r.get("request_id", "")
t("Submit returns request_id", bool(rid1))

# Self-approval blocked
r2 = api_post("admin", PW, {
    "action": "process_approval",
    "request_id": rid1,
    "decision": "approve",
})
t("Self-approval blocked", "error" in r2)

# wladmin2 approves
r3 = api_post("wladmin2", PW, {
    "action": "process_approval",
    "request_id": rid1,
    "decision": "approve",
    "admin_comment": "Approved",
})
t("wladmin2 approves", "error" not in r3)

# CSV was created
time.sleep(0.5)
r4 = api_get("admin", PW, "get_csvs", {"rule": "DR130_privilege_escalation"})
csvs = [c.get("csv_file", c) if isinstance(c, dict) else c for c in r4.get("csv_files", [])]
t("CSV file created", "final_test_csv.csv" in csvs)

# Admin got approved notification
r5 = api_get("admin", PW, "get_notifications")
t("Admin got approved notification",
    any(n.get("type") == "approved" for n in r5.get("notifications", [])))

print("\n3. Create Rule — Submit + Approve")
r = api_post("admin", PW, {
    "action": "submit_approval",
    "approval_action_type": "create_rule",
    "detection_rule": "DR_FINAL_TEST_RULE",
    "csv_file": "__rule_operation__",
    "description": "Final test rule creation",
    "original_payload": {
        "action": "create_rule",
        "detection_rule": "DR_FINAL_TEST_RULE",
    },
})
rid2 = r.get("request_id", "")
t("Submit create_rule", bool(rid2))

r3 = api_post("wladmin2", PW, {
    "action": "process_approval",
    "request_id": rid2,
    "decision": "approve",
    "admin_comment": "Approved",
})
t("wladmin2 approves create_rule", "error" not in r3)

# Rule was registered
time.sleep(0.5)
r4 = api_get("admin", PW, "get_mapping")
rules = [m.get("rule_name", "") for m in r4.get("mapping", [])]
registered = r4.get("registered_rules", [])
t("Rule registered", "DR_FINAL_TEST_RULE" in rules or "DR_FINAL_TEST_RULE" in registered)

print("\n4. Remove CSV — Submit + Reject")
r = api_post("admin", PW, {
    "action": "submit_approval",
    "approval_action_type": "remove_csv",
    "detection_rule": "DR130_privilege_escalation",
    "csv_file": "final_test_csv.csv",
    "description": "Final test CSV removal",
    "original_payload": {
        "action": "remove_csv",
        "detection_rule": "DR130_privilege_escalation",
        "csv_file": "final_test_csv.csv",
        "app_context": "wl_manager",
    },
})
rid3 = r.get("request_id", "")
t("Submit remove_csv", bool(rid3))

r3 = api_post("wladmin2", PW, {
    "action": "process_approval",
    "request_id": rid3,
    "decision": "reject",
    "rejection_reason": "CSV should not be removed yet",
})
t("wladmin2 rejects remove_csv", "error" not in r3)

# Admin got rejection notification
time.sleep(0.5)
r5 = api_get("admin", PW, "get_notifications")
t("Admin got rejected notification",
    any(n.get("type") == "rejected" for n in r5.get("notifications", [])))

print("\n5. Remove Rule — Submit + Cancel")
r = api_post("admin", PW, {
    "action": "submit_approval",
    "approval_action_type": "remove_rule",
    "detection_rule": "DR_FINAL_TEST_RULE",
    "csv_file": "__rule_operation__",
    "description": "Final test rule removal",
    "original_payload": {
        "action": "remove_rule",
        "detection_rule": "DR_FINAL_TEST_RULE",
    },
})
rid4 = r.get("request_id", "")
t("Submit remove_rule", bool(rid4))

r3 = api_post("admin", PW, {
    "action": "cancel_request",
    "request_id": rid4,
    "cancellation_reason": "Changed my mind",
})
t("Cancel remove_rule", r3.get("status") == "cancelled" or "cancelled" in str(r3).lower())

print("\n6. Notifications — Mark Read")
r = api_get("admin", PW, "get_notifications")
total = len(r.get("notifications", []))
unread = r.get("unread_count", 0)
print(f"  Admin: {total} total, {unread} unread")

# Mark first unread as read
notifs = r.get("notifications", [])
unread_ids = [n["id"] for n in notifs if not n.get("read")]
if unread_ids:
    r2 = api_post("admin", PW, {
        "action": "mark_notifications_read",
        "notification_ids": unread_ids[:2],
    })
    t("Mark read succeeds", r2.get("success") is True)
    r3 = api_get("admin", PW, "get_notifications")
    t("Unread count decreased", r3.get("unread_count", unread) < unread)

print("\n7. wladmin2 Notifications")
r = api_get("wladmin2", PW, "get_notifications")
wl2_total = len(r.get("notifications", []))
wl2_new_req = sum(1 for n in r.get("notifications", []) if n.get("type") == "new_request")
print(f"  wladmin2: {wl2_total} total, {wl2_new_req} new_request")
t("wladmin2 received new_request notifications", wl2_new_req >= 4)

print("\n8. Duplicate Request Prevention")
r = api_post("admin", PW, {
    "action": "submit_approval",
    "approval_action_type": "remove_csv",
    "detection_rule": "DR999_stress_test",
    "csv_file": "DR999_stress_test.csv",
    "description": "Duplicate test 1",
    "original_payload": {"action": "remove_csv", "csv_file": "DR999_stress_test.csv"},
})
rid5 = r.get("request_id", "")
t("First submit succeeds", bool(rid5))

r2 = api_post("admin", PW, {
    "action": "submit_approval",
    "approval_action_type": "remove_csv",
    "detection_rule": "DR999_stress_test",
    "csv_file": "DR999_stress_test.csv",
    "description": "Duplicate test 2",
    "original_payload": {"action": "remove_csv", "csv_file": "DR999_stress_test.csv"},
})
t("Duplicate submit blocked", "error" in r2 and "already" in r2.get("error", "").lower())

# Clean up
if rid5:
    api_post("admin", PW, {
        "action": "cancel_request",
        "request_id": rid5,
        "cancellation_reason": "Cleanup",
    })

print("\n9. Audit Trail")
result = subprocess.run(
    ["/opt/splunk/bin/splunk", "search",
     "index=wl_audit earliest=-5m | head 30 | table _time action status approval_action_type analyst",
     "-auth", "admin:Chang3d!", "-app", "wl_manager"],
    capture_output=True, text=True, timeout=30)
print(result.stdout[:2000])

# === SUMMARY ===
print("=" * 60)
passed = sum(results)
total_tests = len(results)
print(f"FINAL RESULTS: {passed}/{total_tests} passed")
if passed == total_tests:
    print("ALL TESTS PASSED!")
else:
    print(f"{total_tests - passed} TESTS FAILED")
print("=" * 60)
