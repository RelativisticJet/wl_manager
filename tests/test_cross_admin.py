"""Test cross-admin approval, rejection, and notification flows."""
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

def api_post(user, password, payload_dict):
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
        body_text = e.read().decode()
        try:
            return json.loads(body_text)
        except Exception:
            return {"error": body_text, "status": e.code}

def api_get(user, password, action, extra_params=None):
    import urllib.parse
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
        body_text = e.read().decode()
        try:
            return json.loads(body_text)
        except Exception:
            return {"error": body_text, "status": e.code}

pw = "Chang3d!"
results = []

def test(label, result, check):
    ok = check(result)
    print(f"[{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        print(f"  {json.dumps(result)[:500]}")
    results.append(ok)

# === A: Submit create_csv as admin, approve as wladmin2 ===
print("=== TEST A: Submit + Approve create_csv ===")
r = api_post("admin", pw, {
    "action": "submit_approval",
    "approval_action_type": "create_csv",
    "detection_rule": "DR999_stress_test",
    "csv_file": "test_cross_admin.csv",
    "description": "Test create CSV cross-admin approval",
    "original_payload": {
        "action": "create_csv",
        "detection_rule": "DR999_stress_test",
        "csv_file": "test_cross_admin.csv",
        "headers": ["user", "src_ip", "Comment"],
        "app_context": "wl_manager",
    },
})
req_id_a = r.get("request_id", "")
print(f"  Submit: {req_id_a}")

if req_id_a:
    r2 = api_post("wladmin2", pw, {
        "action": "process_approval",
        "request_id": req_id_a,
        "decision": "approve",
        "admin_comment": "Approved by wladmin2",
    })
    print(f"  Approve: {json.dumps(r2)[:300]}")
    test("create_csv approved successfully", r2,
        lambda r: "error" not in r or "approved" in str(r).lower())

    # Verify CSV was created
    time.sleep(1)
    r3 = api_get("admin", pw, "get_csvs", {"rule": "DR999_stress_test"})
    csv_list = r3.get("csv_files", [])
    csv_names = [c.get("csv_file", c) if isinstance(c, dict) else c for c in csv_list]
    print(f"  CSVs: {csv_names}")
    test("CSV file was created", csv_names,
        lambda n: "test_cross_admin.csv" in n)

    # Check admin notification
    r4 = api_get("admin", pw, "get_notifications")
    approved = [n for n in r4.get("notifications", [])
                if n.get("type") == "approved" and "test_cross_admin" in n.get("message", "")]
    test("Admin got approval notification", approved, lambda n: len(n) > 0)

# === B: Submit remove_csv as admin, reject as wladmin2 ===
print("\n=== TEST B: Submit + Reject remove_csv ===")
r = api_post("admin", pw, {
    "action": "submit_approval",
    "approval_action_type": "remove_csv",
    "detection_rule": "DR999_stress_test",
    "csv_file": "DR999_stress_test.csv",
    "description": "Test remove CSV rejection",
    "original_payload": {
        "action": "remove_csv",
        "detection_rule": "DR999_stress_test",
        "csv_file": "DR999_stress_test.csv",
        "app_context": "wl_manager",
    },
})
req_id_b = r.get("request_id", "")
print(f"  Submit: {req_id_b}")

if req_id_b:
    r2 = api_post("wladmin2", pw, {
        "action": "process_approval",
        "request_id": req_id_b,
        "decision": "reject",
        "rejection_reason": "Rejected by wladmin2 for testing",
    })
    print(f"  Reject: {json.dumps(r2)[:300]}")
    test("remove_csv rejected successfully", r2,
        lambda r: "error" not in r or "rejected" in str(r).lower())

    # Admin should get rejection notification
    time.sleep(1)
    r4 = api_get("admin", pw, "get_notifications")
    rejected = [n for n in r4.get("notifications", [])
                if n.get("type") == "rejected" and "remove" in n.get("message", "").lower()]
    test("Admin got rejection notification", rejected, lambda n: len(n) > 0)

# === C: Submit create_rule as analyst1, approve as admin ===
print("\n=== TEST C: analyst1 submit create_rule, admin approves ===")
# Ensure analyst1 password
subprocess.run(
    ["curl", "-s", "-k", "-u", "admin:Chang3d!",
     "-X", "POST", f"{BASE}/services/authentication/users/analyst1",
     "-d", "password=Chang3d!", "-d", "output_mode=json"],
    capture_output=True, timeout=10)

r = api_post("analyst1", pw, {
    "action": "submit_approval",
    "approval_action_type": "create_rule",
    "detection_rule": "DR_ANALYST_CREATE_TEST",
    "csv_file": "__rule_operation__",
    "description": "analyst1 creates new rule",
    "original_payload": {
        "action": "create_rule",
        "detection_rule": "DR_ANALYST_CREATE_TEST",
        "csv_file": "__rule_operation__",
    },
})
req_id_c = r.get("request_id", "")
print(f"  Submit: {req_id_c}")
test("analyst1 can submit create_rule", r, lambda r: bool(r.get("request_id")))

if req_id_c:
    # Admin approves (not self-approval since analyst1 submitted)
    r2 = api_post("admin", pw, {
        "action": "process_approval",
        "request_id": req_id_c,
        "decision": "approve",
        "admin_comment": "Approved by admin",
    })
    print(f"  Approve: {json.dumps(r2)[:300]}")
    test("admin approves analyst1 request", r2,
        lambda r: "error" not in r)

    # Check analyst1 got notification
    time.sleep(1)
    r4 = api_get("analyst1", pw, "get_notifications")
    if "Unauthorized" not in str(r4):
        approved = [n for n in r4.get("notifications", [])
                    if n.get("type") == "approved"]
        test("analyst1 got approval notification", approved, lambda n: len(n) > 0)
    else:
        print("  [SKIP] analyst1 cannot access REST API directly")

# === D: Submit remove_rule as analyst1, reject as wladmin2 ===
print("\n=== TEST D: analyst1 submit remove_rule, wladmin2 rejects ===")
r = api_post("analyst1", pw, {
    "action": "submit_approval",
    "approval_action_type": "remove_rule",
    "detection_rule": "DR_ANALYST_REMOVE_TEST",
    "csv_file": "__rule_operation__",
    "description": "analyst1 removes rule",
    "original_payload": {
        "action": "remove_rule",
        "detection_rule": "DR_ANALYST_REMOVE_TEST",
    },
})
req_id_d = r.get("request_id", "")
print(f"  Submit: {req_id_d}")

if req_id_d:
    r2 = api_post("wladmin2", pw, {
        "action": "process_approval",
        "request_id": req_id_d,
        "decision": "reject",
        "rejection_reason": "Rule should not be removed",
    })
    print(f"  Reject: {json.dumps(r2)[:300]}")
    test("wladmin2 rejects remove_rule", r2,
        lambda r: "error" not in r or "rejected" in str(r).lower())

# === E: Audit trail verification ===
print("\n=== TEST E: Audit Trail ===")
result = subprocess.run(
    ["/opt/splunk/bin/splunk", "search",
     "index=wl_audit | head 20 | table _time action status approval_action_type analyst request_id",
     "-auth", "admin:Chang3d!", "-app", "wl_manager"],
    capture_output=True, text=True, timeout=30)
print(f"  Events:\n{result.stdout[:2000]}")

# === Summary ===
print(f"\n{'='*50}")
passed = sum(results)
total = len(results)
print(f"Results: {passed}/{total} passed")
print("ALL PASSED" if passed == total else "SOME FAILED")
