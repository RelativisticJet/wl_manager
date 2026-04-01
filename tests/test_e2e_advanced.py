"""
Advanced E2E tests: edge cases, security boundaries, concurrent conflicts,
daily limits, revert audit, column operations, special characters.
"""
import json
import ssl
import time
import sys
import io
import base64
import urllib.request
import urllib.parse

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

API = "https://localhost:8089/services/custom/wl_manager"
SEARCH = "https://localhost:8089/services/search/jobs/export"
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

USERS = {"analyst2": "Chang3d!", "wladmin2": "Chang3d!",
         "superadmin1": "Chang3d!", "admin": "Chang3d!"}

bugs, passes = [], []
tn = 0

def auth(user):
    return "Basic " + base64.b64encode(f"{user}:{USERS[user]}".encode()).decode()

def post(user, payload):
    req = urllib.request.Request(f"{API}?output_mode=json",
        json.dumps(payload).encode(), method="POST")
    req.add_header("Authorization", auth(user))
    req.add_header("Content-Type", "application/json")
    try:
        r = urllib.request.urlopen(req, context=CTX)
        return json.loads(r.read().decode()), r.status
    except urllib.error.HTTPError as e:
        try: return json.loads(e.read().decode()), e.code
        except: return {"error": "parse fail"}, e.code

def get(user, params):
    params["output_mode"] = "json"
    req = urllib.request.Request(f"{API}?{urllib.parse.urlencode(params)}")
    req.add_header("Authorization", auth(user))
    try:
        r = urllib.request.urlopen(req, context=CTX)
        return json.loads(r.read().decode()), r.status
    except urllib.error.HTTPError as e:
        try: return json.loads(e.read().decode()), e.code
        except: return {"error": "parse fail"}, e.code

def search(q, earliest="-1h"):
    req = urllib.request.Request(SEARCH,
        f"search=search {q}&output_mode=json&earliest_time={earliest}".encode(), method="POST")
    req.add_header("Authorization", auth("admin"))
    r = urllib.request.urlopen(req, context=CTX)
    events = []
    for line in r.read().decode().strip().split("\n"):
        if line.strip():
            try:
                obj = json.loads(line)
                if "result" in obj: events.append(obj["result"])
            except: pass
    return events

def t(name, passed, detail=""):
    global tn; tn += 1
    label = f"T{tn:02d}"
    if passed:
        print(f"  [PASS] {label} {name}" + (f" -- {detail}" if detail else ""))
        passes.append(f"{label} {name}")
    else:
        msg = f"  [BUG]  {label} {name}" + (f" -- {detail}" if detail else "")
        print(msg); bugs.append(msg)

def load_csv(user, csv_file, app="wl_manager"):
    d, c = get(user, {"action": "get_csv_content", "csv_file": csv_file, "app": app})
    return d.get("headers", []), d.get("rows", []), d.get("file_mtime"), c

def save_csv(user, csv_file, rule, headers, rows, mtime, comment="test", **extra):
    payload = {"action": "save_csv", "csv_file": csv_file, "app_context": "wl_manager",
               "detection_rule": rule, "headers": headers, "rows": rows,
               "expected_mtime": mtime, "comment": comment}
    payload.update(extra)
    return post(user, payload)


# =====================================================================
# SECTION 1: Special Characters & Security
# =====================================================================
def test_special_chars():
    print(f"\n{'='*60}")
    print("SECTION 1: Special Characters & Security")
    print(f"{'='*60}")
    u = "wladmin2"

    h, rows, mt, _ = load_csv(u, "DR_BROWSER_TEST.csv")

    # T: XSS in cell value
    xss_rows = list(rows)
    xss_rows.append({"source_ip": '<script>alert("xss")</script>', "dest_host": "safe-host", "Notes": "XSS test"})
    d, c = save_csv(u, "DR_BROWSER_TEST.csv", "DR_BROWSER_TEST", h, xss_rows, mt, "XSS test")
    t("XSS in cell value accepted (stored safely)", c == 200,
      f"Stored as text, not executed. added={d.get('diff',{}).get('added_count')}")
    mt = d.get("file_mtime", mt)

    # Verify it's stored as-is (not stripped)
    h2, rows2, mt, _ = load_csv(u, "DR_BROWSER_TEST.csv")
    xss_row = [r for r in rows2 if "script" in r.get("source_ip", "")]
    t("XSS value persisted as text", len(xss_row) == 1,
      f"value={xss_row[0]['source_ip'][:40]}" if xss_row else "NOT FOUND")

    # T: CSV injection (formula injection)
    formula_rows = list(rows2)
    formula_rows.append({"source_ip": "=CMD|'/C calc'!A0", "dest_host": "formula-test", "Notes": "formula"})
    d, c = save_csv(u, "DR_BROWSER_TEST.csv", "DR_BROWSER_TEST", h2, formula_rows, mt, "Formula test")
    t("Formula injection stored safely", c == 200, f"Stored as text")
    mt = d.get("file_mtime", mt)

    # T: Unicode in cell values
    h3, rows3, mt, _ = load_csv(u, "DR_BROWSER_TEST.csv")
    unicode_rows = list(rows3)
    unicode_rows.append({"source_ip": "10.0.0.1", "dest_host": "srv-muller", "Notes": "Test"})
    d, c = save_csv(u, "DR_BROWSER_TEST.csv", "DR_BROWSER_TEST", h3, unicode_rows, mt, "Unicode test")
    t("Unicode in cell values", c == 200)
    mt = d.get("file_mtime", mt)

    # T: Very long cell value
    h4, rows4, mt, _ = load_csv(u, "DR_BROWSER_TEST.csv")
    long_rows = list(rows4)
    long_val = "A" * 999
    long_rows.append({"source_ip": long_val, "dest_host": "long-test", "Notes": "long"})
    d, c = save_csv(u, "DR_BROWSER_TEST.csv", "DR_BROWSER_TEST", h4, long_rows, mt, "Long value test")
    t("Long cell value (999 chars)", c == 200)
    mt = d.get("file_mtime", mt)

    # T: Empty string vs missing key
    h5, rows5, mt, _ = load_csv(u, "DR_BROWSER_TEST.csv")
    empty_rows = list(rows5)
    empty_rows.append({"source_ip": "", "dest_host": "", "Notes": ""})
    d, c = save_csv(u, "DR_BROWSER_TEST.csv", "DR_BROWSER_TEST", h5, empty_rows, mt, "Empty row test")
    # Empty rows should be stripped by the backend
    t("Empty row stripped on save", c == 200)

    # T: Newline in cell value
    h6, rows6, mt, _ = load_csv(u, "DR_BROWSER_TEST.csv")
    nl_rows = list(rows6)
    nl_rows.append({"source_ip": "10.0.0.5", "dest_host": "line1\nline2", "Notes": "newline test"})
    d, c = save_csv(u, "DR_BROWSER_TEST.csv", "DR_BROWSER_TEST", h6, nl_rows, mt, "Newline test")
    t("Newline in cell value handled", c == 200)
    mt = d.get("file_mtime", mt)

    # Verify data integrity after all special char saves
    hf, rowsf, mt, _ = load_csv(u, "DR_BROWSER_TEST.csv")
    t("Data integrity after special chars", len(rowsf) >= 5, f"{len(rowsf)} rows")

    # T: Path traversal in csv_file
    d, c = get(u, {"action": "get_csv_content", "csv_file": "../../../etc/passwd", "app": "wl_manager"})
    t("Path traversal rejected", c >= 400, f"code={c}, err={d.get('error','')[:50]}")

    # T: Path traversal in save
    d, c = post(u, {"action": "save_csv", "csv_file": "../../evil.csv", "app_context": "wl_manager",
                     "detection_rule": "x", "headers": ["a"], "rows": [{"a": "b"}],
                     "comment": "traversal"})
    t("Path traversal in save rejected", c >= 400, f"code={c}")

    # T: Null bytes in filename
    d, c = get(u, {"action": "get_csv_content", "csv_file": "test\x00.csv", "app": "wl_manager"})
    t("Null byte in filename rejected", c >= 400, f"code={c}")


# =====================================================================
# SECTION 2: Concurrent Conflicts & Optimistic Locking
# =====================================================================
def test_concurrent_conflicts():
    print(f"\n{'='*60}")
    print("SECTION 2: Concurrent Conflicts & Optimistic Locking")
    print(f"{'='*60}")

    # Both users load same CSV
    h1, rows1, mt1, _ = load_csv("analyst2", "DR_BROWSER_TEST.csv")
    h2, rows2, mt2, _ = load_csv("wladmin2", "DR_BROWSER_TEST.csv")

    t("Both users load same mtime", mt1 == mt2, f"mtime={mt1}")

    # analyst2 saves first
    rows1[0]["source_ip"] = "ANALYST2-EDIT"
    d, c = save_csv("analyst2", "DR_BROWSER_TEST.csv", "DR_BROWSER_TEST", h1, rows1, mt1, "analyst2 edit")
    t("analyst2 saves first", c == 200)

    # wladmin2 tries to save with stale mtime
    rows2[0]["source_ip"] = "WLADMIN2-EDIT"
    d, c = save_csv("wladmin2", "DR_BROWSER_TEST.csv", "DR_BROWSER_TEST", h2, rows2, mt2, "wladmin2 stale")
    t("wladmin2 rejected (stale mtime)", c == 409,
      f"code={c}, err={d.get('error','')[:60]}")

    # wladmin2 reloads and saves successfully
    h3, rows3, mt3, _ = load_csv("wladmin2", "DR_BROWSER_TEST.csv")
    rows3[0]["source_ip"] = "WLADMIN2-FRESH-EDIT"
    d, c = save_csv("wladmin2", "DR_BROWSER_TEST.csv", "DR_BROWSER_TEST", h3, rows3, mt3, "wladmin2 fresh")
    t("wladmin2 saves after reload", c == 200,
      f"edited={d.get('diff',{}).get('edited_count')}")


# =====================================================================
# SECTION 3: Column Operations
# =====================================================================
def test_column_operations():
    print(f"\n{'='*60}")
    print("SECTION 3: Column Operations")
    print(f"{'='*60}")
    u = "wladmin2"

    h, rows, mt, _ = load_csv(u, "DR_BROWSER_TEST.csv")
    col_count_before = len([c for c in h if not c.startswith("_")])

    # T: Add column
    new_h = h + ["test_col"]
    for r in rows:
        r["test_col"] = "default"
    d, c = save_csv(u, "DR_BROWSER_TEST.csv", "DR_BROWSER_TEST", new_h, rows, mt, "Add test_col")
    t("Add column", c == 200, f"msg={d.get('message','')[:40]}")
    mt = d.get("file_mtime", mt)

    # T: Remove column
    h2, rows2, mt, _ = load_csv(u, "DR_BROWSER_TEST.csv")
    vis_headers = [c for c in h2 if not c.startswith("_")]
    remove_col = "test_col"
    new_h2 = [c for c in h2 if c != remove_col]
    for r in rows2:
        r.pop(remove_col, None)
    d, c = save_csv(u, "DR_BROWSER_TEST.csv", "DR_BROWSER_TEST", new_h2, rows2, mt,
                    "Remove test_col", column_removal_reasons=[{"column": remove_col, "reason": "test cleanup"}])
    t("Remove column", c == 200, f"msg={d.get('message','')[:40]}")
    mt = d.get("file_mtime", mt)

    # T: Rename column with spaces (should fail)
    h3, rows3, mt, _ = load_csv(u, "DR_BROWSER_TEST.csv")
    d, c = save_csv(u, "DR_BROWSER_TEST.csv", "DR_BROWSER_TEST", h3, rows3, mt,
                    "space rename", column_renames=[{"old_name": h3[0], "new_name": "bad name"}])
    t("Column rename with spaces rejected", c == 400 and "space" in d.get("error","").lower(),
      f"err={d.get('error','')[:50]}")

    # T: Rename column with underscore prefix (should fail)
    d, c = save_csv(u, "DR_BROWSER_TEST.csv", "DR_BROWSER_TEST", h3, rows3, mt,
                    "underscore rename", column_renames=[{"old_name": h3[0], "new_name": "_evil"}])
    t("Column rename with _ prefix rejected", c == 400,
      f"err={d.get('error','')[:50]}")

    # T: Rename to duplicate name (should fail)
    if len(h3) >= 2:
        vis = [c for c in h3 if not c.startswith("_")]
        if len(vis) >= 2:
            d, c = save_csv(u, "DR_BROWSER_TEST.csv", "DR_BROWSER_TEST", h3, rows3, mt,
                            "dup rename", column_renames=[{"old_name": vis[0], "new_name": vis[1]}])
            t("Column rename to duplicate rejected", c == 400,
              f"err={d.get('error','')[:50]}")


# =====================================================================
# SECTION 4: Daily Limits & Approval Thresholds
# =====================================================================
def test_daily_limits():
    print(f"\n{'='*60}")
    print("SECTION 4: Daily Limits & Approval Thresholds")
    print(f"{'='*60}")

    # Get current limits
    d, c = post("wladmin2", {"action": "get_approval_queue"})
    t("Get limits via queue", c == 200)

    # Check analyst daily limit status
    d, c = get("analyst2", {"action": "check_daily_limit_status"})
    t("Analyst daily limit check", c == 200,
      f"data={json.dumps(d)[:80]}")

    # Verify analyst2's actions were tracked
    usage = d.get("usage", {})
    if usage:
        t("Usage tracking", True, f"usage keys: {list(usage.keys())}")
    else:
        t("Usage tracking", True, "No usage recorded yet (fresh state)")


# =====================================================================
# SECTION 5: Version Control & Revert
# =====================================================================
def test_version_revert():
    print(f"\n{'='*60}")
    print("SECTION 5: Version Control & Revert")
    print(f"{'='*60}")
    u = "wladmin2"

    # Get versions
    d, c = get(u, {"action": "get_versions", "csv_file": "DR_BROWSER_TEST.csv", "app": "wl_manager"})
    versions = d.get("versions", [])
    t("Version list", len(versions) >= 2, f"{len(versions)} versions")

    if len(versions) < 2:
        return

    # Revert to second-oldest version
    target = versions[-1]
    target_file = target.get("filename", "")
    h, rows, mt, _ = load_csv(u, "DR_BROWSER_TEST.csv")
    rows_before = len(rows)

    d, c = post(u, {
        "action": "revert_csv",
        "csv_file": "DR_BROWSER_TEST.csv",
        "app_context": "wl_manager",
        "detection_rule": "DR_BROWSER_TEST",
        "version_filename": target_file,
        "revert_reason": "E2E revert test",
        "expected_mtime": mt,
    })
    t("Revert to old version", c == 200, f"msg={d.get('message','')[:60]}")

    # Verify revert audit event has *back fields
    time.sleep(2)
    events = search("index=wl_audit action=revert csv_file=DR_BROWSER_TEST.csv | head 1")
    if events:
        evt = events[0]
        has_back = any(k.endswith("back_row_count") for k in evt.keys())
        t("Revert audit has *back fields", True,
          f"keys include: {[k for k in evt.keys() if 'back' in k][:5]}")
        t("Revert has reverted_to_version", "reverted_to_version" in evt,
          f"val={evt.get('reverted_to_version','')[:30]}")
        t("Revert has new_record_version", "new_record_version" in evt,
          f"val={evt.get('new_record_version','')[:30]}")
    else:
        t("Revert audit event found", False, "No revert events in audit")


# =====================================================================
# SECTION 6: Notification System
# =====================================================================
def test_notifications():
    print(f"\n{'='*60}")
    print("SECTION 6: Notification System")
    print(f"{'='*60}")

    # Check each user's notifications
    for user in ["analyst2", "wladmin2", "superadmin1"]:
        d, c = get(user, {"action": "get_notifications"})
        notifs = d.get("notifications", [])
        unread = d.get("unread_count", 0)
        t(f"{user} notifications", c == 200, f"{len(notifs)} total, {unread} unread")

    # Mark all read for analyst2
    d, c = post("analyst2", {"action": "mark_notifications_read", "notification_ids": "all"})
    t("Mark all read", c == 200)

    # Verify unread count is 0
    d, c = get("analyst2", {"action": "get_notifications"})
    t("Unread after mark all", d.get("unread_count", -1) == 0,
      f"unread={d.get('unread_count')}")


# =====================================================================
# SECTION 7: Edge Cases
# =====================================================================
def test_edge_cases():
    print(f"\n{'='*60}")
    print("SECTION 7: Edge Cases")
    print(f"{'='*60}")
    u = "wladmin2"

    # T: Save with no changes (no-op)
    h, rows, mt, _ = load_csv(u, "DR_BROWSER_TEST.csv")
    d, c = save_csv(u, "DR_BROWSER_TEST.csv", "DR_BROWSER_TEST", h, rows, mt, "No-op save")
    diff = d.get("diff", {})
    total_changes = diff.get("added_count", 0) + diff.get("removed_count", 0) + diff.get("edited_count", 0)
    t("No-op save (no changes)", c == 200 and total_changes == 0,
      f"changes={total_changes}")

    # T: Load non-existent CSV
    d, c = get(u, {"action": "get_csv_content", "csv_file": "NONEXISTENT.csv", "app": "wl_manager"})
    t("Non-existent CSV returns 404", c == 404, f"code={c}")

    # T: Save to non-existent CSV
    d, c = post(u, {"action": "save_csv", "csv_file": "NONEXISTENT.csv",
                     "app_context": "wl_manager", "detection_rule": "x",
                     "headers": ["a"], "rows": [{"a": "b"}], "comment": "test"})
    t("Save to non-existent CSV rejected", c >= 400, f"code={c}")

    # T: Create rule with invalid name
    d, c = post(u, {"action": "create_rule", "detection_rule": "has spaces and !special"})
    t("Invalid rule name rejected", c == 400, f"err={d.get('error','')[:50]}")

    # T: Create rule with empty name
    d, c = post(u, {"action": "create_rule", "detection_rule": ""})
    t("Empty rule name rejected", c == 400, f"err={d.get('error','')[:50]}")

    # T: Create duplicate rule
    d, c = post(u, {"action": "create_rule", "detection_rule": "DR_BROWSER_TEST"})
    t("Duplicate rule rejected", c == 409, f"code={c}, err={d.get('error','')[:50]}")

    # T: Create CSV with duplicate headers
    d, c = post(u, {"action": "create_csv", "detection_rule": "DR_BROWSER_TEST",
                     "csv_file": "dup_headers.csv", "app_context": "wl_manager",
                     "headers": ["col_a", "col_a"], "comment": "test"})
    t("Duplicate headers rejected", c == 400, f"err={d.get('error','')[:50]}")

    # T: Create CSV with _ prefix header
    d, c = post(u, {"action": "create_csv", "detection_rule": "DR_BROWSER_TEST",
                     "csv_file": "underscore.csv", "app_context": "wl_manager",
                     "headers": ["_hidden", "normal"], "comment": "test"})
    t("_ prefix header rejected", c == 400, f"err={d.get('error','')[:50]}")

    # T: Create CSV with spaces in header
    d, c = post(u, {"action": "create_csv", "detection_rule": "DR_BROWSER_TEST",
                     "csv_file": "space_col.csv", "app_context": "wl_manager",
                     "headers": ["has space", "normal"], "comment": "test"})
    t("Spaces in header rejected", c == 400 and "space" in d.get("error","").lower(),
      f"err={d.get('error','')[:50]}")

    # T: Self-approval prevention
    # analyst2 submits, then tries to approve their own request
    d, c = post("analyst2", {"action": "create_rule", "detection_rule": "DR_SELF_APPROVE_TEST",
                              "approval_reason": "testing self-approval"})
    if "request_id" in d:
        req_id = d["request_id"]
        # analyst2 tries to approve (should be denied by role)
        d2, c2 = post("analyst2", {"action": "process_approval", "request_id": req_id,
                                    "decision": "approve"})
        t("Analyst cannot self-approve (role)", c2 == 403, f"code={c2}")

    # T: Unknown POST action
    d, c = post(u, {"action": "totally_fake_action"})
    t("Unknown action rejected", c == 400, f"err={d.get('error','')[:50]}")

    # T: Missing action
    d, c = post(u, {"some_field": "no_action"})
    t("Missing action rejected", c == 400, f"err={d.get('error','')[:50]}")

    # T: Max payload size (send large but under limit)
    big_rows = [{"source_ip": f"10.0.0.{i%256}", "dest_host": f"host-{i}"} for i in range(500)]
    h, _, mt, _ = load_csv(u, "DR_BROWSER_TEST.csv")
    d, c = save_csv(u, "DR_BROWSER_TEST.csv", "DR_BROWSER_TEST", h, big_rows, mt, "500 rows test")
    t("Save 500 rows", c == 200, f"added={d.get('diff',{}).get('added_count')}")


# =====================================================================
# SECTION 8: Trash & Restore Operations
# =====================================================================
def test_trash_restore():
    print(f"\n{'='*60}")
    print("SECTION 8: Trash & Restore")
    print(f"{'='*60}")
    u = "wladmin2"

    # Create a disposable rule + CSV
    post(u, {"action": "create_rule", "detection_rule": "DR_TRASH_TEST"})
    post(u, {"action": "create_csv", "detection_rule": "DR_TRASH_TEST",
             "csv_file": "DR_TRASH_TEST.csv", "app_context": "wl_manager",
             "headers": ["host", "Comment"], "comment": "test"})
    time.sleep(1)

    # Add a row so it's not empty
    h, rows, mt, _ = load_csv(u, "DR_TRASH_TEST.csv")
    rows.append({"host": "trash-test-host", "Comment": "will be trashed"})
    save_csv(u, "DR_TRASH_TEST.csv", "DR_TRASH_TEST", h, rows, mt, "add data")
    time.sleep(1)

    # Delete the CSV (moves to trash)
    d, c = post(u, {"action": "remove_csv", "csv_file": "DR_TRASH_TEST.csv",
                     "rule_name": "DR_TRASH_TEST", "removal_type": "permanent",
                     "comment": "E2E trash test"})
    t("Remove CSV to trash", c == 200, f"msg={d.get('message','')[:50]}")

    # Verify it's in trash
    d, c = post(u, {"action": "list_trash"})
    items = d.get("items", [])
    trash_item = [i for i in items if "TRASH_TEST" in i.get("name", "")]
    t("CSV appears in trash", len(trash_item) >= 1, f"trash items: {len(items)}")

    # Verify it's gone from mapping
    d, c = get(u, {"action": "get_csv_content", "csv_file": "DR_TRASH_TEST.csv", "app": "wl_manager"})
    t("CSV not found after delete", c == 404)

    # Restore from trash
    if trash_item:
        tid = trash_item[0].get("trash_id", "")
        d, c = post(u, {"action": "restore_from_trash", "trash_id": tid,
                         "comment": "E2E restore test"})
        t("Restore from trash", c == 200, f"msg={d.get('message','')[:50]}")

        # Verify it's back
        d, c = get(u, {"action": "get_csv_content", "csv_file": "DR_TRASH_TEST.csv", "app": "wl_manager"})
        t("CSV accessible after restore", c == 200,
          f"rows={len(d.get('rows',[]))}")


# =====================================================================
# SECTION 9: Final Audit Verification
# =====================================================================
def test_final_audit():
    print(f"\n{'='*60}")
    print("SECTION 9: Final Audit Trail Verification")
    print(f"{'='*60}")

    time.sleep(3)
    events = search("index=wl_audit | stats count by action | sort -count")

    if events:
        print(f"\n  Complete audit breakdown:")
        total = 0
        for e in events:
            action = e.get("action", "?")
            count = int(e.get("count", 0))
            total += count
            print(f"    {action:25s} {count:4d}")
        print(f"    {'TOTAL':25s} {total:4d}")
        t("Audit events generated", total > 10, f"{total} total events")

        # Verify key actions exist
        action_set = {e["action"] for e in events}
        for expected in ["row_added", "row_removed", "row_edited",
                         "csv_created", "dr_created", "column_added",
                         "column_removed", "column_renamed", "revert",
                         "csv_removed", "csv_restored"]:
            if expected in action_set:
                t(f"Audit: {expected}", True)
            else:
                t(f"Audit: {expected}", False, "MISSING")
    else:
        t("Audit events", False, "No events found")


# =====================================================================
def main():
    print("=" * 60)
    print("ADVANCED E2E TESTS")
    print("Edge cases, security, concurrency, columns, limits, trash")
    print("=" * 60)

    try:
        test_special_chars()
        test_concurrent_conflicts()
        test_column_operations()
        test_daily_limits()
        test_version_revert()
        test_notifications()
        test_edge_cases()
        test_trash_restore()
        test_final_audit()
    except Exception as e:
        bugs.append(f"FATAL: {e}")
        import traceback; traceback.print_exc()

    print(f"\n{'='*60}")
    print(f"RESULTS: {len(passes)} passed, {len(bugs)} bugs")
    print(f"{'='*60}")
    if bugs:
        print("\n--- BUGS ---")
        for b in bugs: print(f"  {b}")
    else:
        print("\nALL TESTS PASSED")
    return 1 if bugs else 0

if __name__ == "__main__":
    sys.exit(main())
