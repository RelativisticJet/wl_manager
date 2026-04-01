"""
Base helper for Whitelist Manager integration tests.

Talks to the live Splunk instance in the Docker container via REST API
at https://localhost:8089/services/custom/wl_manager.

Requirements:
    - Docker container 'wl_manager_test' running Splunk 9.3.1
    - Accounts: admin/Chang3d!, wladmin1/WlAdmin123, analyst1/Analyst123, analyst2/Analyst2
"""

import json
import time
import urllib.request
import urllib.parse
import urllib.error
import ssl
import csv
import io
import os
import unittest

# ── Connection settings ──────────────────────────────────────────────────────
SPLUNK_HOST = "localhost"
SPLUNK_PORT = 8089
BASE_URL = f"https://{SPLUNK_HOST}:{SPLUNK_PORT}"
WL_ENDPOINT = f"{BASE_URL}/services/custom/wl_manager"

# Test accounts
ADMIN = ("admin", "Chang3d!")
WLADMIN1 = ("wladmin1", "WlAdmin123")
WLADMIN2 = ("wladmin2", "WlAdmin123")
ANALYST1 = ("analyst1", "Analyst123")
ANALYST2 = ("analyst2", "Analyst2")

# Test CSV — use DR999_stress_test.csv as it's designated for testing
TEST_CSV = "DR999_stress_test.csv"
TEST_RULE = "DR999 - Stress Test"
TEST_APP_CONTEXT = "wl_manager"

# SSL context that skips cert verification (self-signed cert in container)
SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE


def api_get(action, params=None, creds=ADMIN):
    """Make a GET request to the WL Manager REST endpoint."""
    url_params = {"action": action, "output_mode": "json"}
    if params:
        url_params.update(params)
    url = f"{WL_ENDPOINT}?{urllib.parse.urlencode(url_params)}"
    req = urllib.request.Request(url)
    auth_str = f"{creds[0]}:{creds[1]}"
    import base64
    req.add_header("Authorization",
                   "Basic " + base64.b64encode(auth_str.encode()).decode())
    try:
        resp = urllib.request.urlopen(req, context=SSL_CTX, timeout=30)
        body = resp.read().decode("utf-8")
        return resp.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        try:
            return e.code, json.loads(body)
        except json.JSONDecodeError:
            return e.code, {"raw": body}


def api_post(payload, creds=ADMIN):
    """Make a POST request to the WL Manager REST endpoint.

    Sends the payload as a raw JSON body (matching the frontend's
    contentType: 'application/json' + JSON.stringify approach).
    Splunk's passPayload=true puts the raw body into request["payload"].
    """
    url = f"{WL_ENDPOINT}?output_mode=json"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    auth_str = f"{creds[0]}:{creds[1]}"
    import base64
    req.add_header("Authorization",
                   "Basic " + base64.b64encode(auth_str.encode()).decode())
    req.add_header("Content-Type", "application/json")
    try:
        resp = urllib.request.urlopen(req, context=SSL_CTX, timeout=30)
        body = resp.read().decode("utf-8")
        return resp.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        try:
            return e.code, json.loads(body)
        except json.JSONDecodeError:
            return e.code, {"raw": body}


def search_audit(query_filter="", max_results=50, earliest="-5m", creds=ADMIN):
    """Run a Splunk search against wl_audit and return results."""
    spl = (f'search index=wl_audit sourcetype=wl_audit {query_filter} '
           f'| head {max_results} | sort -_time')
    url = f"{BASE_URL}/services/search/jobs/export"
    data = urllib.parse.urlencode({
        "search": spl,
        "output_mode": "json",
        "earliest_time": earliest,
        "latest_time": "now",
    }).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    auth_str = f"{creds[0]}:{creds[1]}"
    import base64
    req.add_header("Authorization",
                   "Basic " + base64.b64encode(auth_str.encode()).decode())
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        resp = urllib.request.urlopen(req, context=SSL_CTX, timeout=30)
        body = resp.read().decode("utf-8")
        results = []
        for line in body.strip().split("\n"):
            if not line.strip():
                continue
            obj = json.loads(line)
            if "result" in obj:
                result = obj["result"]
                # Parse _raw JSON to extract audit fields
                raw = result.get("_raw", "")
                if raw:
                    try:
                        parsed = json.loads(raw)
                        parsed.update({k: v for k, v in result.items()
                                       if k.startswith("_")})
                        result = parsed
                    except json.JSONDecodeError:
                        pass
                results.append(result)
        return results
    except Exception as e:
        print(f"Audit search error: {e}")
        return []


def get_csv_content(csv_file=TEST_CSV, app_context=TEST_APP_CONTEXT, creds=ADMIN):
    """GET the CSV content (headers + rows)."""
    status, data = api_get("get_csv_content", {
        "csv_file": csv_file,
        "app_context": app_context,
    }, creds=creds)
    return status, data


def save_csv(headers, rows, csv_file=TEST_CSV, app_context=TEST_APP_CONTEXT,
             comment="Integration test", expected_mtime=None, creds=ADMIN,
             extra_payload=None):
    """POST to save CSV content."""
    payload = {
        "action": "save_csv",
        "csv_file": csv_file,
        "app_context": app_context,
        "headers": headers,
        "rows": rows,
        "comment": comment,
    }
    if expected_mtime:
        payload["expected_mtime"] = expected_mtime
    if extra_payload:
        payload.update(extra_payload)
    return api_post(payload, creds=creds)


def submit_approval(action_type, csv_file=TEST_CSV, creds=ANALYST1,
                    description="Test approval", original_payload=None,
                    pending_highlight=None, detection_rule=TEST_RULE,
                    app_context=TEST_APP_CONTEXT, selected_count=1):
    """Submit an approval request."""
    payload = {
        "action": "submit_approval",
        "approval_action_type": action_type,
        "csv_file": csv_file,
        "app_context": app_context,
        "detection_rule": detection_rule,
        "description": description,
        "selected_count": selected_count,
        "original_payload": original_payload or {},
        "pending_highlight": pending_highlight or {},
    }
    return api_post(payload, creds=creds)


def process_approval(request_id, decision, creds=WLADMIN1,
                     rejection_reason=""):
    """Approve or reject a request."""
    payload = {
        "action": "process_approval",
        "request_id": request_id,
        "decision": decision,
    }
    if rejection_reason:
        payload["rejection_reason"] = rejection_reason
    return api_post(payload, creds=creds)


def cancel_request(request_id, reason, creds=ANALYST1):
    """Cancel an approval request."""
    payload = {
        "action": "cancel_request",
        "request_id": request_id,
        "cancellation_reason": reason,
    }
    return api_post(payload, creds=creds)


def get_approval_queue(creds=WLADMIN1):
    """Get the full approval queue, normalized into pending/resolved lists."""
    status, raw = api_post({"action": "get_approval_queue"}, creds=creds)
    if status != 200:
        return status, raw
    # API returns {"queue": [...]}, normalize to {"pending": [...], "resolved": [...]}
    queue = raw.get("queue", [])
    pending = [i for i in queue if i.get("status") == "pending"]
    resolved = [i for i in queue if i.get("status") != "pending"]
    return status, {"pending": pending, "resolved": resolved, "queue": queue}


def clear_approval_queue(creds=ADMIN):
    """Cancel/reject all pending requests to clean up. Returns count cleared.

    Uses cancel (as the owner) when possible to avoid admin rate limits,
    falls back to reject (as admin) for requests from unknown users.
    """
    status, data = get_approval_queue(creds=creds)
    if status != 200:
        return 0
    pending = data.get("pending", [])
    cleared = 0
    user_creds_map = {
        "analyst1": ANALYST1, "analyst2": ANALYST2,
        "wladmin1": WLADMIN1, "wladmin2": WLADMIN2,
        "admin": ADMIN,
    }
    for item in pending:
        owner = item.get("analyst", "")
        owner_creds = user_creds_map.get(owner)
        if owner_creds:
            s, _ = cancel_request(item["request_id"], "Test cleanup",
                                  creds=owner_creds)
        else:
            s, _ = process_approval(
                item["request_id"], "reject", creds=creds,
                rejection_reason="Cleanup for integration tests")
        if s == 200:
            cleared += 1
    return cleared


def reset_daily_limits(creds=ADMIN):
    """Reset daily limits to factory defaults (unlimited)."""
    api_post({"action": "reset_factory_defaults"}, creds=creds)
    api_post({"action": "reset_daily_usage"}, creds=creds)


def set_approval_thresholds(thresholds, creds=ADMIN):
    """Set specific daily limit / threshold values."""
    payload = {"action": "set_daily_limits"}
    payload.update(thresholds)
    return api_post(payload, creds=creds)


def wait_for_indexing(seconds=4):
    """Wait for Splunk to index audit events."""
    time.sleep(seconds)


class WLIntegrationTestCase(unittest.TestCase):
    """Base class for WL Manager integration tests.

    Cleanup runs once per class (not per test) to stay within rate limits.
    Each test should clean up its own approval requests if it creates them.
    """

    @classmethod
    def setUpClass(cls):
        """Verify Splunk is reachable and clean up queue once per class."""
        try:
            status, _ = api_get("get_rules")
            if status != 200:
                raise unittest.SkipTest(
                    f"Splunk API returned {status} — is the container running?")
        except Exception as e:
            raise unittest.SkipTest(f"Cannot reach Splunk: {e}")
        # Wait for rate limit window to reset between test classes
        # (30 POST per 60s per user — need to budget carefully)
        time.sleep(20)
        # One-time cleanup per test class
        clear_approval_queue()
        reset_daily_limits()
        time.sleep(1)

    def setUp(self):
        """Light per-test delay for rate limiting.

        Individual tests handle their own cleanup. The setUpClass does
        one-time cleanup. No per-test cleanup to conserve rate limit budget.
        """
        time.sleep(0.5)

    def _load_csv(self, creds=ADMIN):
        """Load test CSV, return (headers, rows, mtime)."""
        status, data = get_csv_content(creds=creds)
        self.assertEqual(status, 200, f"Failed to load CSV: {data}")
        return data["headers"], data["rows"], data.get("file_mtime")

    def _save_and_reload(self, headers, rows, comment="test", creds=ADMIN,
                         expected_mtime=None, extra_payload=None):
        """Save CSV and reload, return (save_result, headers, rows, mtime)."""
        status, result = save_csv(
            headers, rows, comment=comment, creds=creds,
            expected_mtime=expected_mtime, extra_payload=extra_payload)
        self.assertEqual(status, 200, f"Save failed: {result}")
        h, r, m = self._load_csv(creds=creds)
        return result, h, r, m

    def _get_latest_audit(self, action=None, count=5):
        """Get latest audit events, optionally filtered by action."""
        wait_for_indexing()
        flt = f'action="{action}"' if action else ""
        return search_audit(flt, max_results=count)

    def _submit_and_get_id(self, action_type="bulk_row_removal", creds=ANALYST1,
                           **kwargs):
        """Submit an approval request and return the request_id."""
        status, data = submit_approval(action_type, creds=creds, **kwargs)
        self.assertEqual(status, 200, f"Submit failed: {data}")
        self.assertIn("request_id", data)
        return data["request_id"]


# Column names that are treated as expiration dates — mirrors backend EXPIRE_COLUMN_NAMES
_EXPIRE_COL_NAMES = {
    "expires", "expire", "expiration", "expiration_date",
    "expiry", "termination", "termination_date",
}


def make_row(visible_headers, prefix, index=None):
    """Build a test row dict that uses empty strings for expiration columns.

    This avoids triggering backend date-format validation with placeholder text.
    """
    tag = f"{prefix}_{index}" if index is not None else prefix
    return {
        h: ("" if h.lower() in _EXPIRE_COL_NAMES else f"{tag}_{h}")
        for h in visible_headers
    }


def make_rows(visible_headers, prefix, count):
    """Build multiple test rows with valid expiration column values."""
    return [make_row(visible_headers, prefix, i) for i in range(count)]
