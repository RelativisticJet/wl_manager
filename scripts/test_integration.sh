#!/usr/bin/env bash
#
# ═══════════════════════════════════════════════════════════════════════
# Phase 3: TEST — Integration tests against the containerized Splunk
# ═══════════════════════════════════════════════════════════════════════
#
# Prerequisites:
#   1. Docker must be running
#   2. Run: docker compose up -d
#   3. Wait for Splunk to be ready (~60-90 seconds)
#   4. Then run this script: bash scripts/test_integration.sh
#
# What it tests:
#   - Splunk is reachable
#   - The wl_manager app is installed and visible
#   - The REST endpoint responds
#   - GET actions work (get_rules, get_csv_content)
#   - POST save_csv works and produces an audit event
#   - The wl_audit index receives events
#   - Dashboards are accessible
#

set -euo pipefail

SPLUNK_URL="https://localhost:8089"
SPLUNK_WEB="http://localhost:8000"
SPLUNK_USER="admin"
SPLUNK_PASS="Chang3d!"
CURL_OPTS="-sk"  # silent + insecure (self-signed cert)

TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0

# ── Helpers ────────────────────────────────────────────────────────────

run_test() {
    local name="$1"
    TESTS_RUN=$((TESTS_RUN + 1))
    echo -n "  [$TESTS_RUN] $name ... "
}

pass() {
    TESTS_PASSED=$((TESTS_PASSED + 1))
    echo "PASS"
}

fail() {
    TESTS_FAILED=$((TESTS_FAILED + 1))
    echo "FAIL — $1"
}

splunk_rest() {
    # Make an authenticated REST call to Splunk's management API
    local method="$1"
    local endpoint="$2"
    shift 2
    curl $CURL_OPTS -X "$method" \
        -u "$SPLUNK_USER:$SPLUNK_PASS" \
        "$SPLUNK_URL$endpoint" \
        "$@"
}

splunk_custom() {
    # Call our custom REST endpoint
    local method="$1"
    shift
    if [[ "$method" == "GET" ]]; then
        # Use -G so -d params become query string (not request body)
        curl $CURL_OPTS -G -X GET \
            -u "$SPLUNK_USER:$SPLUNK_PASS" \
            "$SPLUNK_URL/services/custom/wl_manager" \
            "$@"
    else
        curl $CURL_OPTS -X "$method" \
            -u "$SPLUNK_USER:$SPLUNK_PASS" \
            "$SPLUNK_URL/services/custom/wl_manager" \
            "$@"
    fi
}

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  Integration Tests — Whitelist Manager"
echo "═══════════════════════════════════════════════════════════════"
echo ""

# ══════════════════════════════════════════════════════════════════════
echo "── Connectivity ──"
# ══════════════════════════════════════════════════════════════════════

run_test "Splunk management API is reachable"
RESP=$(curl $CURL_OPTS -o /dev/null -w "%{http_code}" "$SPLUNK_URL/services/server/info" -u "$SPLUNK_USER:$SPLUNK_PASS" 2>/dev/null)
if [[ "$RESP" == "200" ]]; then
    pass
else
    fail "HTTP $RESP (is Splunk running? try: docker compose up -d)"
    echo ""
    echo "  Cannot proceed without Splunk. Exiting."
    exit 1
fi

run_test "Splunk Web is reachable"
RESP=$(curl -sk -o /dev/null -w "%{http_code}" "$SPLUNK_WEB" 2>/dev/null)
if [[ "$RESP" == "200" ]] || [[ "$RESP" == "303" ]]; then
    pass
else
    fail "HTTP $RESP"
fi

# ══════════════════════════════════════════════════════════════════════
echo ""
echo "── App Installation ──"
# ══════════════════════════════════════════════════════════════════════

run_test "wl_manager app is installed"
RESP=$(splunk_rest GET "/services/apps/local/wl_manager" -o /dev/null -w "%{http_code}" 2>/dev/null)
if [[ "$RESP" == "200" ]]; then
    pass
else
    fail "App not found (HTTP $RESP)"
fi

run_test "wl_audit index exists"
RESP=$(splunk_rest GET "/services/data/indexes/wl_audit" -o /dev/null -w "%{http_code}" 2>/dev/null)
if [[ "$RESP" == "200" ]]; then
    pass
else
    fail "Index not found (HTTP $RESP) — may need a Splunk restart"
fi

# ══════════════════════════════════════════════════════════════════════
echo ""
echo "── REST Endpoint — GET ──"
# ══════════════════════════════════════════════════════════════════════

run_test "GET get_rules returns rules"
BODY=$(splunk_custom GET -d "action=get_rules" 2>/dev/null)
if echo "$BODY" | python3 -c "import sys,json; d=json.load(sys.stdin); assert 'rules' in d" 2>/dev/null; then
    pass
else
    fail "Unexpected response: $BODY"
fi

run_test "GET get_mapping returns mapping"
BODY=$(splunk_custom GET -d "action=get_mapping" 2>/dev/null)
if echo "$BODY" | python3 -c "import sys,json; d=json.load(sys.stdin); assert 'mapping' in d" 2>/dev/null; then
    pass
else
    fail "Unexpected response: $BODY"
fi

# ══════════════════════════════════════════════════════════════════════
echo ""
echo "── REST Endpoint — POST (save + audit) ──"
# ══════════════════════════════════════════════════════════════════════

# Create a test CSV directly inside the container's lookups folder
echo "  (Setting up test CSV in container...)"
MSYS_NO_PATHCONV=1 docker exec -u splunk wl_manager_test bash -c 'printf "host,user,CommandLine,Comment\nWKSTN-001,bob,whoami,Legacy entry\nWKSTN-042,alice,net use,Approved\n" > /opt/splunk/etc/apps/wl_manager/lookups/TEST_whitelist.csv' 2>/dev/null || true

# Fetch the current content_hash — save_csv enforces optimistic locking
# (a security control added in hardening round 6). Without expected_content_hash
# the save returns HTTP 409 Conflict.
EXPECTED_HASH=$(splunk_custom GET -d "action=get_csv_content&csv_file=TEST_whitelist.csv" 2>/dev/null \
    | python3 -c "import sys,json; print(json.load(sys.stdin).get('content_hash',''))" 2>/dev/null)

run_test "POST save_csv writes CSV and returns diff"
SAVE_BODY=$(splunk_custom POST \
    -H "Content-Type: application/json" \
    -d '{
        "action": "save_csv",
        "csv_file": "TEST_whitelist.csv",
        "app_context": "",
        "detection_rule": "TEST_rule",
        "expected_content_hash": "'"$EXPECTED_HASH"'",
        "headers": ["host","user","CommandLine","Comment"],
        "rows": [
            {"host":"WKSTN-042","user":"alice","CommandLine":"net use","Comment":"Approved"},
            {"host":"SRV-NEW","user":"svc_test","CommandLine":"whoami","Comment":"Integration test"}
        ],
        "comment": "Integration test save"
    }' 2>/dev/null)

if echo "$SAVE_BODY" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert d.get('message') == 'CSV saved successfully', f'Unexpected message: {d}'
assert 'diff' in d, 'No diff in response'
" 2>/dev/null; then
    pass
else
    fail "Save failed: $SAVE_BODY"
fi

run_test "Saved CSV has correct content"
VERIFY=$(splunk_custom GET -d "action=get_csv_content&csv_file=TEST_whitelist.csv" 2>/dev/null)
if echo "$VERIFY" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert d['row_count'] == 2, f'Expected 2 rows, got {d[\"row_count\"]}'
" 2>/dev/null; then
    pass
else
    fail "CSV content incorrect: $VERIFY"
fi

# Wait for the audit event to be indexed
sleep 8

run_test "Audit event appeared in wl_audit index"
SEARCH_RESP=$(splunk_rest POST "/services/search/jobs/export" \
    -d "search=search index=wl_audit sourcetype=wl_audit detection_rule=TEST_rule | head 1" \
    -d "output_mode=json" \
    -d "earliest_time=-5m" \
    2>/dev/null)

if echo "$SEARCH_RESP" | grep -q "TEST_rule"; then
    pass
else
    fail "Audit event not found in index (may need more time to index)"
fi

# ══════════════════════════════════════════════════════════════════════
echo ""
echo "── Dashboards ──"
# ══════════════════════════════════════════════════════════════════════

run_test "Whitelist Manager dashboard exists"
RESP=$(splunk_rest GET "/servicesNS/nobody/wl_manager/data/ui/views/whitelist_manager" -o /dev/null -w "%{http_code}" 2>/dev/null)
if [[ "$RESP" == "200" ]]; then
    pass
else
    fail "Dashboard not found (HTTP $RESP)"
fi

run_test "Audit dashboard exists"
RESP=$(splunk_rest GET "/servicesNS/nobody/wl_manager/data/ui/views/audit" -o /dev/null -w "%{http_code}" 2>/dev/null)
if [[ "$RESP" == "200" ]]; then
    pass
else
    fail "Dashboard not found (HTTP $RESP)"
fi

# ══════════════════════════════════════════════════════════════════════
echo ""
echo "── Cleanup ──"
# ══════════════════════════════════════════════════════════════════════

# Remove the test CSV
MSYS_NO_PATHCONV=1 docker exec -u splunk wl_manager_test rm -f /opt/splunk/etc/apps/wl_manager/lookups/TEST_whitelist.csv 2>/dev/null || true
echo "  Test CSV removed."

# ══════════════════════════════════════════════════════════════════════
# Summary
# ══════════════════════════════════════════════════════════════════════

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  RESULTS: $TESTS_PASSED/$TESTS_RUN passed, $TESTS_FAILED failed"
echo "═══════════════════════════════════════════════════════════════"

if [[ $TESTS_FAILED -eq 0 ]]; then
    echo "  All tests passed! The app is ready for packaging."
    exit 0
else
    echo "  Some tests failed. Review the output above."
    exit 1
fi
