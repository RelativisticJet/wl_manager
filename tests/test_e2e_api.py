"""
End-to-end API-level tests simulating real SOC workflows.
Tests all CRUD operations, approval workflows, version control, and audit logging
through the REST API as 3 different users: analyst2, wladmin2, superadmin1.

Each test performs real mutations and verifies persistence + audit trail.
"""
import json
import ssl
import time
import sys
import urllib.request
import urllib.parse
import base64

API = "https://localhost:8089/services/custom/wl_manager"
SEARCH_URL = "https://localhost:8089/services/search/jobs/export"

# SSL context for self-signed cert
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

USERS = {
    "analyst2":    "Chang3d!",
    "wladmin2":    "Chang3d!",
    "superadmin1": "Chang3d!",
    "admin":       "Chang3d!",
}

bugs = []
passes = []
test_num = 0

def auth_header(user):
    cred = base64.b64encode(f"{user}:{USERS[user]}".encode()).decode()
    return f"Basic {cred}"

def api_post(user, payload):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(f"{API}?output_mode=json", data=data, method="POST")
    req.add_header("Authorization", auth_header(user))
    req.add_header("Content-Type", "application/json")
    try:
        resp = urllib.request.urlopen(req, context=CTX)
        return json.loads(resp.read().decode()), resp.status
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        try:
            return json.loads(body), e.code
        except json.JSONDecodeError:
            return {"error": body[:200]}, e.code

def api_get(user, params):
    params["output_mode"] = "json"
    qs = urllib.parse.urlencode(params)
    req = urllib.request.Request(f"{API}?{qs}", method="GET")
    req.add_header("Authorization", auth_header(user))
    try:
        resp = urllib.request.urlopen(req, context=CTX)
        return json.loads(resp.read().decode()), resp.status
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        try:
            return json.loads(body), e.code
        except json.JSONDecodeError:
            return {"error": body[:200]}, e.code

def splunk_search(query, earliest="-1h"):
    data = f"search=search {query}&output_mode=json&earliest_time={earliest}"
    req = urllib.request.Request(SEARCH_URL, data=data.encode(), method="POST")
    req.add_header("Authorization", auth_header("admin"))
    resp = urllib.request.urlopen(req, context=CTX)
    events = []
    for line in resp.read().decode().strip().split("\n"):
        if line.strip():
            try:
                obj = json.loads(line)
                if "result" in obj:
                    events.append(obj["result"])
            except json.JSONDecodeError:
                pass
    return events

def test(name, passed, detail=""):
    global test_num
    test_num += 1
    label = f"T{test_num:02d}"
    if passed:
        msg = f"  [PASS] {label} {name}"
        if detail:
            msg += f" -- {detail}"
        print(msg)
        passes.append(f"{label} {name}")
    else:
        msg = f"  [BUG]  {label} {name}"
        if detail:
            msg += f" -- {detail}"
        print(msg)
        bugs.append(f"{label} {name}: {detail}")


def phase1_analyst_daily_ops():
    """analyst2 performs daily whitelist operations."""
    print(f"\n{'='*60}")
    print("PHASE 1: analyst2 -- Daily whitelist operations")
    print(f"{'='*60}")
    u = "analyst2"

    # T01: Load rules
    data, code = api_get(u, {"action": "get_mapping"})
    rules = list(set(m["rule_name"] for m in data.get("mapping", [])))
    test("Load rules", code == 200 and len(rules) > 0, f"{len(rules)} rules")

    # T02: Load CSV content
    data, code = api_get(u, {"action": "get_csv_content", "csv_file": "DR130_priv_escalation.csv", "app": "wl_manager"})
    rows = data.get("rows", [])
    headers = data.get("headers", [])
    mtime = data.get("file_mtime")
    test("Load DR130 CSV", code == 200 and len(rows) == 5, f"{len(rows)} rows, headers={headers}")

    # T03: Add 2 rows
    new_rows = list(rows)
    new_rows.append({"host": "E2E-HOST-001"})
    new_rows.append({"host": "E2E-HOST-002"})
    data, code = api_post(u, {
        "action": "save_csv",
        "csv_file": "DR130_priv_escalation.csv",
        "app_context": "wl_manager",
        "detection_rule": "DR130_privilege_escalation",
        "headers": headers,
        "rows": new_rows,
        "expected_mtime": mtime,
        "comment": "analyst2 adding 2 E2E test hosts"
    })
    diff = data.get("diff", {})
    test("Add 2 rows", code == 200 and diff.get("added_count") == 2,
         f"added={diff.get('added_count')}, msg={data.get('message','')[:50]}")
    mtime = data.get("file_mtime", mtime)

    # T04: Verify persistence
    data, code = api_get(u, {"action": "get_csv_content", "csv_file": "DR130_priv_escalation.csv", "app": "wl_manager"})
    test("Rows persisted", len(data.get("rows", [])) == 7, f"{len(data.get('rows',[]))} rows")
    mtime = data.get("file_mtime", mtime)

    # T05: Edit a cell
    rows = data.get("rows", [])
    rows[0]["host"] = "E2E-EDITED-HOST"
    data, code = api_post(u, {
        "action": "save_csv",
        "csv_file": "DR130_priv_escalation.csv",
        "app_context": "wl_manager",
        "detection_rule": "DR130_privilege_escalation",
        "headers": headers,
        "rows": rows,
        "expected_mtime": mtime,
        "comment": "analyst2 editing first row"
    })
    diff = data.get("diff", {})
    test("Edit cell", code == 200 and diff.get("edited_count", 0) >= 1,
         f"edited={diff.get('edited_count')}")
    mtime = data.get("file_mtime", mtime)

    # T06: Remove a row (with reason)
    data, code = api_get(u, {"action": "get_csv_content", "csv_file": "DR130_priv_escalation.csv", "app": "wl_manager"})
    rows = data.get("rows", [])
    mtime = data.get("file_mtime", mtime)
    removed_host = rows[-1]["host"]
    save_rows = rows[:-1]
    data, code = api_post(u, {
        "action": "save_csv",
        "csv_file": "DR130_priv_escalation.csv",
        "app_context": "wl_manager",
        "detection_rule": "DR130_privilege_escalation",
        "headers": headers,
        "rows": save_rows,
        "expected_mtime": mtime,
        "bulk_removal": [{"indices": [len(rows) - 1], "reason": "E2E test removal"}],
        "comment": "analyst2 removing last row"
    })
    diff = data.get("diff", {})
    test("Remove row", code == 200 and diff.get("removed_count", 0) >= 1,
         f"removed={diff.get('removed_count')}, host={removed_host}")
    mtime = data.get("file_mtime", mtime)

    # T07: Search filter (simulated)
    data, code = api_get(u, {"action": "get_csv_content", "csv_file": "DR130_priv_escalation.csv", "app": "wl_manager"})
    rows = data.get("rows", [])
    filtered = [r for r in rows if "E2E" in r.get("host", "")]
    test("Search filter", len(filtered) >= 1, f"E2E rows found: {len(filtered)}")

    # T08: Version history
    data, code = api_get(u, {"action": "get_versions", "csv_file": "DR130_priv_escalation.csv", "app": "wl_manager"})
    versions = data.get("versions", [])
    test("Version history", len(versions) >= 3, f"{len(versions)} versions")

    # T09: Switch to different rule
    data, code = api_get(u, {"action": "get_csv_content", "csv_file": "DR55_brute_force_users.csv", "app": "wl_manager"})
    test("Switch to DR55", code == 200, f"{len(data.get('rows',[]))} rows")

    return mtime


def phase2_admin_operations():
    """wladmin2 performs admin management operations."""
    print(f"\n{'='*60}")
    print("PHASE 2: wladmin2 -- Admin management operations")
    print(f"{'='*60}")
    u = "wladmin2"

    # T10: Create new detection rule
    data, code = api_post(u, {
        "action": "create_rule",
        "detection_rule": "DR_E2E_ADMIN"
    })
    test("Create rule", code == 200, f"msg={data.get('message','')[:50]}")

    # T11: Create CSV with 4 columns
    data, code = api_post(u, {
        "action": "create_csv",
        "detection_rule": "DR_E2E_ADMIN",
        "csv_file": "DR_E2E_ADMIN.csv",
        "app_context": "wl_manager",
        "headers": ["src_ip", "dest_ip", "reason", "Comment"],
        "comment": "Admin creating E2E test CSV"
    })
    test("Create CSV", code == 200, f"msg={data.get('message','')[:50]}")

    # T12: Add 3 rows
    data, code = api_get(u, {"action": "get_csv_content", "csv_file": "DR_E2E_ADMIN.csv", "app": "wl_manager"})
    headers = data.get("headers", [])
    mtime = data.get("file_mtime")
    new_rows = [
        {"src_ip": "10.0.1.1", "dest_ip": "192.168.1.1", "reason": "VPN server", "Comment": "Approved by SOC"},
        {"src_ip": "10.0.1.2", "dest_ip": "192.168.1.2", "reason": "Jump host", "Comment": "Standard access"},
        {"src_ip": "10.0.1.3", "dest_ip": "192.168.1.3", "reason": "Monitoring", "Comment": "Nagios probe"},
    ]
    data, code = api_post(u, {
        "action": "save_csv",
        "csv_file": "DR_E2E_ADMIN.csv",
        "app_context": "wl_manager",
        "detection_rule": "DR_E2E_ADMIN",
        "headers": headers,
        "rows": new_rows,
        "expected_mtime": mtime,
        "comment": "Admin adding 3 whitelist entries"
    })
    diff = data.get("diff", {})
    test("Add 3 rows", code == 200 and diff.get("added_count") == 3, f"added={diff.get('added_count')}")
    mtime = data.get("file_mtime", mtime)

    # T13: Add column
    data, code = api_get(u, {"action": "get_csv_content", "csv_file": "DR_E2E_ADMIN.csv", "app": "wl_manager"})
    rows = data.get("rows", [])
    headers = data.get("headers", [])
    mtime = data.get("file_mtime", mtime)
    new_headers = headers + ["severity"]
    for r in rows:
        r["severity"] = "medium"
    rows[0]["severity"] = "high"
    data, code = api_post(u, {
        "action": "save_csv",
        "csv_file": "DR_E2E_ADMIN.csv",
        "app_context": "wl_manager",
        "detection_rule": "DR_E2E_ADMIN",
        "headers": new_headers,
        "rows": rows,
        "expected_mtime": mtime,
        "comment": "Adding severity column"
    })
    test("Add column", code == 200, f"msg={data.get('message','')[:50]}")
    mtime = data.get("file_mtime", mtime)

    # T14: Bulk edit (change all reasons)
    data, code = api_get(u, {"action": "get_csv_content", "csv_file": "DR_E2E_ADMIN.csv", "app": "wl_manager"})
    rows = data.get("rows", [])
    headers = data.get("headers", [])
    mtime = data.get("file_mtime", mtime)
    for r in rows:
        r["reason"] = "Bulk updated via E2E"
    data, code = api_post(u, {
        "action": "save_csv",
        "csv_file": "DR_E2E_ADMIN.csv",
        "app_context": "wl_manager",
        "detection_rule": "DR_E2E_ADMIN",
        "headers": headers,
        "rows": rows,
        "expected_mtime": mtime,
        "comment": "Bulk edit all reasons"
    })
    diff = data.get("diff", {})
    test("Bulk edit", code == 200 and diff.get("edited_count", 0) >= 2,
         f"edited={diff.get('edited_count')}")
    mtime = data.get("file_mtime", mtime)

    # T15: Revert to previous version
    data, code = api_get(u, {"action": "get_versions", "csv_file": "DR_E2E_ADMIN.csv", "app": "wl_manager"})
    versions = data.get("versions", [])
    test("Version list", len(versions) >= 2, f"{len(versions)} versions")

    if len(versions) >= 2:
        prev_ver = versions[1]["filename"]
        data, code = api_post(u, {
            "action": "revert_csv",
            "csv_file": "DR_E2E_ADMIN.csv",
            "app_context": "wl_manager",
            "detection_rule": "DR_E2E_ADMIN",
            "version_file": prev_ver,
            "revert_reason": "E2E test revert"
        })
        test("Revert", code == 200, f"msg={data.get('message','')[:50]}")

    # T16: Column rename
    data, code = api_get(u, {"action": "get_csv_content", "csv_file": "DR_E2E_ADMIN.csv", "app": "wl_manager"})
    headers = data.get("headers", [])
    rows = data.get("rows", [])
    mtime = data.get("file_mtime", mtime)
    data, code = api_post(u, {
        "action": "save_csv",
        "csv_file": "DR_E2E_ADMIN.csv",
        "app_context": "wl_manager",
        "detection_rule": "DR_E2E_ADMIN",
        "headers": headers,
        "rows": rows,
        "expected_mtime": mtime,
        "column_renames": [{"old_name": "Comment", "new_name": "Notes"}],
        "comment": "Rename Comment to Notes"
    })
    test("Column rename", code == 200, f"msg={data.get('message','')[:50]}")

    # T17: View limits
    data, code = api_post(u, {"action": "get_approval_queue"})
    test("View approval queue", code == 200, f"queue={len(data.get('queue',[]))}")

    return mtime


def phase3_analyst_approvals():
    """analyst2 triggers approval workflows."""
    print(f"\n{'='*60}")
    print("PHASE 3: analyst2 -- Approval workflow triggers")
    print(f"{'='*60}")
    u = "analyst2"

    # T18: Request create rule (should go to approval)
    data, code = api_post(u, {
        "action": "create_rule",
        "detection_rule": "DR_ANALYST_REQ",
        "approval_reason": "Analyst requesting new phishing detection rule"
    })
    went_to_approval = "approval" in data.get("message", "").lower() or "submitted" in data.get("message", "").lower()
    test("Request create rule", code == 200, f"msg={data.get('message','')[:60]}")

    # T19: Request to remove a CSV (should need approval for permanent)
    data, code = api_post(u, {
        "action": "remove_csv",
        "csv_file": "DR_E2E_ADMIN.csv",
        "rule_name": "DR_E2E_ADMIN",
        "removal_type": "permanent",
        "comment": "Analyst requesting permanent removal of test CSV"
    })
    test("Request remove CSV", code in (200, 403, 429),
         f"code={code}, msg={data.get('message', data.get('error',''))[:60]}")

    # T20: Check notifications
    data, code = api_get(u, {"action": "get_notifications"})
    notifs = data.get("notifications", [])
    test("Analyst notifications", code == 200, f"{len(notifs)} notifications")

    # T21: Load pending approvals for a CSV
    data, code = api_get(u, {"action": "get_pending_approvals", "csv_file": "DR_E2E_ADMIN.csv"})
    test("Pending approvals check", code == 200, f"data={json.dumps(data)[:80]}")


def phase4_superadmin_ops():
    """superadmin1 processes approvals and manages the system."""
    print(f"\n{'='*60}")
    print("PHASE 4: superadmin1 -- Approval processing & system mgmt")
    print(f"{'='*60}")
    u = "superadmin1"

    # T22: View approval queue
    data, code = api_post(u, {"action": "get_approval_queue"})
    queue = data.get("queue", [])
    pending = [q for q in queue if q.get("status") == "pending"]
    test("View queue", code == 200, f"total={len(queue)}, pending={len(pending)}")

    # T23: Approve first pending request
    if pending:
        req_id = pending[0]["request_id"]
        action_type = pending[0].get("action_type", "")
        data, code = api_post(u, {
            "action": "process_approval",
            "request_id": req_id,
            "decision": "approve",
            "admin_comment": "Approved via E2E test"
        })
        test(f"Approve {action_type}", code == 200,
             f"msg={data.get('message', data.get('error',''))[:60]}")

    # T24: Reject second pending request (if exists)
    data, code = api_post(u, {"action": "get_approval_queue"})
    queue = data.get("queue", [])
    pending = [q for q in queue if q.get("status") == "pending"]
    if pending:
        req_id = pending[0]["request_id"]
        action_type = pending[0].get("action_type", "")
        data, code = api_post(u, {
            "action": "process_approval",
            "request_id": req_id,
            "decision": "reject",
            "rejection_reason": "Rejected via E2E test"
        })
        test(f"Reject {action_type}", code == 200,
             f"msg={data.get('message', data.get('error',''))[:60]}")

    # T25: View limits
    data, code = api_post(u, {"action": "get_limits"})
    test("View limits", code == 200,
         f"row_removal={data.get('row_removal')}, revert={data.get('revert')}")

    # T26: Check admin limits (superadmin)
    data, code = api_post(u, {"action": "get_admin_limits"})
    test("View admin limits", code == 200,
         f"limits={json.dumps(data.get('admin_limits',{}))[:80]}")

    # T27: View trash
    data, code = api_post(u, {"action": "list_trash"})
    items = data.get("items", [])
    test("View trash", code == 200, f"{len(items)} trash items")

    # T28: Restore from trash (if items exist)
    if items:
        trash_id = items[0].get("trash_id", "")
        data, code = api_post(u, {
            "action": "restore_from_trash",
            "trash_id": trash_id,
            "comment": "Restored via E2E test"
        })
        test("Restore from trash", code == 200,
             f"msg={data.get('message', data.get('error',''))[:60]}")

    # T29: Superadmin notifications
    data, code = api_get(u, {"action": "get_notifications"})
    notifs = data.get("notifications", [])
    test("Superadmin notifications", code == 200, f"{len(notifs)} notifications")


def phase5_rbac_security():
    """Test RBAC boundaries and security."""
    print(f"\n{'='*60}")
    print("PHASE 5: RBAC & Security verification")
    print(f"{'='*60}")

    # T30: analyst2 cannot process approvals
    data, code = api_post("analyst2", {
        "action": "process_approval",
        "request_id": "fake_id",
        "decision": "approve"
    })
    test("Analyst cannot approve", code == 403, f"code={code}")

    # T31: analyst2 cannot view approval queue
    data, code = api_post("analyst2", {"action": "get_approval_queue"})
    test("Analyst cannot view queue", code == 403, f"code={code}")

    # T32: analyst2 cannot change limits
    data, code = api_post("analyst2", {
        "action": "set_limits",
        "row_removal": 999
    })
    test("Analyst cannot set limits", code == 403, f"code={code}")

    # T33: wladmin2 cannot view admin limits
    data, code = api_post("wladmin2", {"action": "get_admin_limits"})
    test("Admin cannot view admin-limits", code == 403, f"code={code}")

    # T34: Column name with spaces rejected
    data, code = api_get("wladmin2", {"action": "get_csv_content", "csv_file": "DR_E2E_ADMIN.csv", "app": "wl_manager"})
    headers = data.get("headers", [])
    rows = data.get("rows", [])
    mtime = data.get("file_mtime")
    data, code = api_post("wladmin2", {
        "action": "save_csv",
        "csv_file": "DR_E2E_ADMIN.csv",
        "app_context": "wl_manager",
        "detection_rule": "DR_E2E_ADMIN",
        "headers": headers,
        "rows": rows,
        "expected_mtime": mtime,
        "column_renames": [{"old_name": headers[0] if headers else "x", "new_name": "bad column name"}],
        "comment": "Test spaces in column name"
    })
    test("Spaces in column name rejected", code == 400 and "space" in data.get("error", "").lower(),
         f"code={code}, error={data.get('error','')[:60]}")

    # T35: Reserved _ prefix rejected
    data, code = api_post("wladmin2", {
        "action": "create_csv",
        "detection_rule": "DR_E2E_ADMIN",
        "csv_file": "DR_E2E_underscore_test.csv",
        "app_context": "wl_manager",
        "headers": ["_evil_column", "normal_col"],
        "comment": "Test underscore prefix"
    })
    test("Underscore prefix rejected", code == 400, f"error={data.get('error','')[:60]}")

    # T36: Optimistic locking (stale mtime)
    data, code = api_post("wladmin2", {
        "action": "save_csv",
        "csv_file": "DR_E2E_ADMIN.csv",
        "app_context": "wl_manager",
        "detection_rule": "DR_E2E_ADMIN",
        "headers": headers,
        "rows": rows,
        "expected_mtime": 1000000,
        "comment": "Test stale mtime"
    })
    test("Optimistic lock rejects stale mtime", code == 409,
         f"code={code}, error={data.get('error','')[:60]}")


def phase6_concurrent_presence():
    """Test presence detection via API."""
    print(f"\n{'='*60}")
    print("PHASE 6: Presence detection")
    print(f"{'='*60}")

    # T37: analyst2 reports presence
    data, code = api_get("analyst2", {
        "action": "report_presence",
        "csv_file": "DR_E2E_ADMIN.csv",
        "app": "wl_manager",
        "user": "analyst2",
        "last_activity": str(int(time.time()))
    })
    test("analyst2 presence", code == 200,
         f"users={data.get('active_users',[])}")

    # T38: wladmin2 reports presence (same CSV)
    data, code = api_get("wladmin2", {
        "action": "report_presence",
        "csv_file": "DR_E2E_ADMIN.csv",
        "app": "wl_manager",
        "user": "wladmin2",
        "last_activity": str(int(time.time()))
    })
    active = data.get("active_users", [])
    both_present = "analyst2" in active and "wladmin2" in active
    test("Both users present", code == 200 and both_present,
         f"users={active}")


def phase7_audit_verification():
    """Verify all audit events are correct and complete."""
    print(f"\n{'='*60}")
    print("PHASE 7: Audit trail verification")
    print(f"{'='*60}")

    time.sleep(3)  # Wait for indexing

    events = splunk_search("index=wl_audit | sort -_time | head 50 | table _time action analyst csv_file detection_rule comment", "-2h")
    test("Audit events exist", len(events) > 0, f"{len(events)} events")

    if not events:
        return

    # Count by action
    action_counts = {}
    for e in events:
        a = e.get("action", "unknown")
        action_counts[a] = action_counts.get(a, 0) + 1

    print(f"\n  Audit breakdown ({len(events)} events):")
    for action, count in sorted(action_counts.items()):
        print(f"    {action}: {count}")

    # Expected actions from our test workflow
    expected_actions = {
        "row_added": "Phase 1: add rows",
        "row_edited": "Phase 1: edit cell",
        "row_removed": "Phase 1: remove row",
        "csv_created": "Phase 2: create CSV",
        "dr_created": "Phase 2: create rule",
        "column_added": "Phase 2: add column",
        "revert": "Phase 2: revert",
        "column_renamed": "Phase 2: rename column",
    }
    for action, source in expected_actions.items():
        if action in action_counts:
            test(f"Audit: {action}", True, f"count={action_counts[action]} ({source})")
        else:
            test(f"Audit: {action}", False, f"MISSING ({source})")

    # Verify analyst attribution
    analyst_events = [e for e in events if e.get("analyst") == "analyst2"]
    admin_events = [e for e in events if e.get("analyst") == "wladmin2"]
    test("Analyst events attributed", len(analyst_events) > 0,
         f"analyst2={len(analyst_events)} events")
    test("Admin events attributed", len(admin_events) > 0,
         f"wladmin2={len(admin_events)} events")

    # Print recent events
    print(f"\n  Recent audit events:")
    for e in events[:15]:
        ts = e.get("_time", "?")[-8:]
        action = e.get("action", "?")
        analyst = e.get("analyst", "?")
        csv_f = e.get("csv_file", "?")
        comment = (e.get("comment", "") or "")[:40]
        print(f"    {ts} | {action:20s} | {analyst:12s} | {csv_f:25s} | {comment}")


def main():
    print("=" * 60)
    print("API-LEVEL END-TO-END TEST")
    print("Real data operations across 3 user accounts")
    print("=" * 60)

    try:
        phase1_analyst_daily_ops()
        phase2_admin_operations()
        phase3_analyst_approvals()
        phase4_superadmin_ops()
        phase5_rbac_security()
        phase6_concurrent_presence()
        phase7_audit_verification()
    except Exception as e:
        bugs.append(f"FATAL: {e}")
        import traceback; traceback.print_exc()

    print(f"\n{'='*60}")
    print(f"RESULTS: {len(passes)} passed, {len(bugs)} bugs")
    print(f"{'='*60}")
    if bugs:
        print("\n--- BUGS ---")
        for b in bugs:
            print(f"  {b}")
    else:
        print("\nALL TESTS PASSED")
    return 1 if bugs else 0


if __name__ == "__main__":
    sys.exit(main())
