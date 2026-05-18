#!/usr/bin/env python3
"""
seed-demo-state.py — populate the wl_manager dev container with realistic
demo data for screenshot capture.

Runs against a CLEAN container (audit index empty, queue empty,
counters empty). Hits production REST endpoints exactly as a real
analyst / admin would, so the resulting state is schema-correct.

Run from inside the wl_manager_test container, OR from the host with
SPLUNK_BASE_URL pointed at the container.

NOT a test fixture. NOT for replay. See tests/fixtures/demo-state/README.md.
"""
import json
import os
import ssl
import sys
import time
import urllib.request
import urllib.parse
import urllib.error
import base64

BASE = os.environ.get("SPLUNK_BASE_URL", "https://localhost:8089")
SCTX = ssl._create_unverified_context()

CREDS = {
    "analyst1":    "Chang3d!",
    "wladmin1":    "Chang3d!",
    "superadmin1": "Chang3d!",
}


def req(user: str, method: str, path: str, body=None, query=None) -> dict:
    """Make an authenticated REST call. Returns parsed JSON."""
    url = f"{BASE}{path}"
    if query:
        url += "?" + urllib.parse.urlencode(query)
    auth = base64.b64encode(f"{user}:{CREDS[user]}".encode()).decode()
    headers = {
        "Authorization": f"Basic {auth}",
        "Content-Type": "application/json",
    }
    data = json.dumps(body).encode() if body else None
    r = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, context=SCTX, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return {"_http_error": e.code, "_body": e.read().decode()[:500]}


def get_hash(rule: str, csv: str) -> str:
    r = req("analyst1", "GET", "/services/custom/wl_manager",
            query={"action": "get_csv_content",
                   "detection_rule": rule,
                   "csv_file": csv,
                   "app_context": "wl_manager"})
    return r.get("content_hash", "")


def save_csv(user: str, rule: str, csv: str, rows: list, comment: str) -> dict:
    return req(user, "POST", "/services/custom/wl_manager", body={
        "action": "save_csv",
        "detection_rule": rule,
        "csv_file": csv,
        "app_context": "wl_manager",
        "rows": rows,
        "expected_content_hash": get_hash(rule, csv),
        "comment": comment,
    })


def submit_approval(user: str, action_type: str, **kwargs) -> dict:
    body = {"action": "submit_approval",
            "approval_action_type": action_type}
    body.update(kwargs)
    return req(user, "POST", "/services/custom/wl_manager", body=body)


def banner(msg: str) -> None:
    print(f"\n=== {msg} ===")


def step(label: str, resp: dict) -> None:
    short = json.dumps(resp)[:140]
    print(f"  - {label}: {short}")


# ─────────────────────────────────────────────────────────────────────
# Step 1: realistic edits as analyst1 — populate audit trail
# ─────────────────────────────────────────────────────────────────────

banner("Step 1: realistic row additions by analyst1")

# DR55_brute_force_users — edit one threshold value
step("DR55 increase threshold",
     save_csv("analyst1", "DR55_brute_force_login", "DR55_brute_force_users.csv",
              [
                  {"user": "svc_patch",   "src_ip": "10.2.0.39",
                   "dest_host": "ADFS02",   "threshold": "30",
                   "auth_method": "ntlm",        "Comment": "ServiceNow API polling - bumped threshold",
                   "Expires": "2026-10-18"},
                  {"user": "p.anderson",  "src_ip": "10.100.0.104",
                   "dest_host": "RADIUS09", "threshold": "100",
                   "auth_method": "password",    "Comment": "Splunk forwarder reconnections",
                   "Expires": "2026-06-17"},
                  {"user": "h.brown",     "src_ip": "10.2.0.14",
                   "dest_host": "LDAP01",   "threshold": "30",
                   "auth_method": "password",    "Comment": "Night shift operator account",
                   "Expires": ""},
                  {"user": "k.wong",      "src_ip": "172.16.20.93",
                   "dest_host": "VPN-GW02", "threshold": "30",
                   "auth_method": "certificate", "Comment": "Compliance scan account",
                   "Expires": "2026-05-08"},
              ],
              "Bump svc_patch threshold to match new ServiceNow baseline"))


# ─────────────────────────────────────────────────────────────────────
# Step 2: pending approval requests by analyst1
# ─────────────────────────────────────────────────────────────────────

banner("Step 2: pending approval requests")

# 2a. Submit a column removal request (will be approved in Step 3).
# All fields are ASCII-only — no em-dashes / curly quotes / etc.
step("submit_approval column_removal DR55 auth_method",
     submit_approval("analyst1",
                     "column_removal",
                     detection_rule="DR55_brute_force_login",
                     csv_file="DR55_brute_force_users.csv",
                     app_context="wl_manager",
                     column_name="auth_method",
                     comment="Field deprecated - moving to centralized auth catalog"))

time.sleep(1)

# 2b. Submit a column removal request (will be rejected in Step 3).
step("submit_approval column_removal DR130 ticket_id",
     submit_approval("analyst1",
                     "column_removal",
                     detection_rule="DR130_privilege_escalation",
                     csv_file="DR130_priv_escalation.csv",
                     app_context="wl_manager",
                     column_name="ticket_id",
                     comment="Field deprecated by GRC team"))

time.sleep(1)

# 2c. Submit a column removal request (will stay pending after Step 3).
step("submit_approval column_removal DR55 src_host",
     submit_approval("analyst1",
                     "column_removal",
                     detection_rule="DR55_brute_force_login",
                     csv_file="DR55_brute_force_src.csv",
                     app_context="wl_manager",
                     column_name="src_host",
                     comment="Hostname column redundant - src_ip already canonical"))


# ─────────────────────────────────────────────────────────────────────
# Step 3: resolved history by wladmin1 — approve / reject some
# ─────────────────────────────────────────────────────────────────────

banner("Step 3: resolved approval history (wladmin1)")

# Get the current pending queue
q = req("wladmin1", "GET", "/services/custom/wl_manager",
        query={"action": "get_approval_queue"}).get("approval_queue", [])
pending = [e for e in q if e.get("status") == "pending"]
print(f"  pending queue size: {len(pending)}")

# Approve the FIRST pending; reject the SECOND if present; leave
# the remaining 1+ pending so the screenshot has both buckets
if len(pending) >= 1:
    rid = pending[-1]["request_id"]   # oldest first in queue list
    step(f"approve {rid[:12]}",
         req("wladmin1", "POST", "/services/custom/wl_manager", body={
             "action": "process_approval",
             "request_id": rid,
             "decision": "approve",
             "admin_comment": "Approved - auth catalog migration scheduled"}))
    time.sleep(0.5)

if len(pending) >= 2:
    rid = pending[-2]["request_id"]
    step(f"reject {rid[:12]}",
         req("wladmin1", "POST", "/services/custom/wl_manager", body={
             "action": "process_approval",
             "request_id": rid,
             "decision": "reject",
             "rejection_reason": "Hold for GRC sign-off - see ticket SEC-2412"}))


banner("DONE")
print("Final state:")
q2 = req("superadmin1", "GET", "/services/custom/wl_manager",
         query={"action": "get_approval_queue"}).get("approval_queue", [])
states = {}
for e in q2:
    states[e.get("status", "?")] = states.get(e.get("status", "?"), 0) + 1
print(f"  queue: {states}  (total: {len(q2)})")
