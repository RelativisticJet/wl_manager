#!/usr/bin/env bash
#
# ═══════════════════════════════════════════════════════════════════════
# Whitelist Manager — Quick Demo
# ═══════════════════════════════════════════════════════════════════════
#
# Spins up a standalone Splunk instance in Docker, installs the
# Whitelist Manager app from the .spl package, creates demo users
# with different roles, and seeds sample data so you can evaluate
# the full feature set including approval workflows.
#
# Usage:
#   bash demo/demo.sh              # build .spl, start Splunk, seed data
#   bash demo/demo.sh --stop       # stop and remove the demo container
#   bash demo/demo.sh --clean      # stop, remove container + data volume
#
# Requirements:
#   - Docker Desktop (running)
#   - Bash (Git Bash on Windows, or native on Linux/macOS)
#   - ~1 GB free disk space (Splunk image + data)
#
# Access after startup:
#   URL:      http://localhost:9000
#
#   Demo accounts:
#     admin    / Chang3d!   — full Splunk admin
#     analyst1 / Chang3d!   — editor (can edit whitelists)
#     viewer1  / Chang3d!   — viewer (read-only)
#     wladmin1 / Chang3d!   — WL admin (can approve/reject, configure limits)
#

set -euo pipefail

# ── Configuration ────────────────────────────────────────────────────
CONTAINER_NAME="wl_manager_demo"
SPLUNK_IMAGE="splunk/splunk:9.3.1"
SPLUNK_PASSWORD="${SPLUNK_PASSWORD:-Chang3d!}"
WEB_PORT=9000
API_PORT=9089
VOLUME_NAME="wl_manager_demo_var"
MAX_WAIT=180  # seconds to wait for Splunk startup

# Resolve project root (parent of demo/)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# ── Helpers ──────────────────────────────────────────────────────────

info()  { echo "  [INFO]  $1"; }
ok()    { echo "  [OK]    $1"; }
err()   { echo "  [ERROR] $1" >&2; }

wait_for_splunk() {
    local port="$1"
    local elapsed=0
    echo ""
    info "Waiting for Splunk to be ready (up to ${MAX_WAIT}s)..."
    while [ $elapsed -lt $MAX_WAIT ]; do
        if curl -sk -o /dev/null -w "%{http_code}" \
            -u "admin:${SPLUNK_PASSWORD}" \
            "https://localhost:${port}/services/server/info" 2>/dev/null | grep -q "200"; then
            ok "Splunk is ready! (${elapsed}s)"
            return 0
        fi
        sleep 3
        elapsed=$((elapsed + 3))
        if [ $((elapsed % 15)) -eq 0 ]; then
            info "Still waiting... (${elapsed}s)"
        fi
    done
    err "Splunk did not start within ${MAX_WAIT} seconds."
    err "Check logs: docker logs ${CONTAINER_NAME}"
    return 1
}

splunk_api() {
    # Helper: make a Splunk REST API call
    # Usage: splunk_api POST /services/authentication/users -d "name=foo&..."
    local method="$1"
    local endpoint="$2"
    shift 2
    curl -sk -X "$method" \
        -u "admin:${SPLUNK_PASSWORD}" \
        "https://localhost:${API_PORT}${endpoint}" \
        "$@" -o /dev/null -w "%{http_code}"
}

# ── Handle --stop / --clean ──────────────────────────────────────────

if [[ "${1:-}" == "--stop" ]]; then
    echo ""
    echo "Stopping demo..."
    docker stop "$CONTAINER_NAME" 2>/dev/null && ok "Container stopped." || info "Container was not running."
    docker rm "$CONTAINER_NAME" 2>/dev/null && ok "Container removed." || true
    echo ""
    exit 0
fi

if [[ "${1:-}" == "--clean" ]]; then
    echo ""
    echo "Cleaning up demo (container + data)..."
    docker stop "$CONTAINER_NAME" 2>/dev/null && ok "Container stopped." || info "Container was not running."
    docker rm "$CONTAINER_NAME" 2>/dev/null && ok "Container removed." || true
    docker volume rm "$VOLUME_NAME" 2>/dev/null && ok "Volume removed." || info "Volume did not exist."
    echo ""
    exit 0
fi

# ── Banner ───────────────────────────────────────────────────────────

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  Whitelist Manager — Quick Demo"
echo "═══════════════════════════════════════════════════════════════"
echo ""

# ── Step 1: Check Docker ────────────────────────────────────────────

echo "Step 1/7: Checking Docker..."
if ! docker info &>/dev/null; then
    err "Docker is not running. Please start Docker Desktop and try again."
    exit 1
fi
ok "Docker is running."

# ── Step 2: Find or build .spl ──────────────────────────────────────

echo ""
echo "Step 2/7: Locating .spl package..."

SPL_FILE=""
if [[ -n "${1:-}" && -f "${1:-}" ]]; then
    SPL_FILE="$1"
    ok "Using provided .spl: $SPL_FILE"
else
    SPL_FILE=$(ls -t "$PROJECT_DIR"/dist/wl_manager-*.spl 2>/dev/null | head -1 || true)
    if [[ -n "$SPL_FILE" ]]; then
        ok "Found existing .spl: $SPL_FILE"
    else
        info "No .spl found. Building one now..."
        if bash "$PROJECT_DIR/scripts/package.sh"; then
            SPL_FILE=$(ls -t "$PROJECT_DIR"/dist/wl_manager-*.spl 2>/dev/null | head -1)
            ok "Built: $SPL_FILE"
        else
            err "Package build failed. Fix the issues above and try again."
            exit 1
        fi
    fi
fi

# ── Step 3: Start container ─────────────────────────────────────────

echo ""
echo "Step 3/7: Starting Splunk container..."

if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    info "Removing existing demo container..."
    docker stop "$CONTAINER_NAME" 2>/dev/null || true
    docker rm "$CONTAINER_NAME" 2>/dev/null || true
fi

docker run -d \
    --name "$CONTAINER_NAME" \
    --hostname splunk-demo \
    -p "${WEB_PORT}:8000" \
    -p "${API_PORT}:8089" \
    -v "${VOLUME_NAME}:/opt/splunk/var" \
    -e SPLUNK_START_ARGS="--accept-license" \
    -e SPLUNK_PASSWORD="$SPLUNK_PASSWORD" \
    "$SPLUNK_IMAGE" >/dev/null

ok "Container started: $CONTAINER_NAME"

wait_for_splunk "$API_PORT"

# ── Step 4: Install .spl ────────────────────────────────────────────

echo ""
echo "Step 4/7: Installing Whitelist Manager app..."

docker cp "$SPL_FILE" "${CONTAINER_NAME}:/tmp/wl_manager.spl"
MSYS_NO_PATHCONV=1 docker exec -u 0 "$CONTAINER_NAME" \
    chown splunk:splunk /tmp/wl_manager.spl 2>/dev/null || true

MSYS_NO_PATHCONV=1 docker exec -u splunk "$CONTAINER_NAME" \
    /opt/splunk/bin/splunk install app /tmp/wl_manager.spl \
    -auth "admin:${SPLUNK_PASSWORD}" 2>&1 | grep -v "^$" || true

ok "App installed."

info "Restarting Splunk to load the app..."
MSYS_NO_PATHCONV=1 docker exec -u splunk "$CONTAINER_NAME" \
    /opt/splunk/bin/splunk restart --answer-yes 2>&1 | tail -1 || true

wait_for_splunk "$API_PORT"

# ── Step 5: Create demo users ────────────────────────────────────────

echo ""
echo "Step 5/7: Creating demo users..."

# analyst1 — editor role (can edit whitelists, subject to daily limits and approval gates)
STATUS=$(splunk_api POST "/services/authentication/users" \
    -d "name=analyst1&password=${SPLUNK_PASSWORD}&roles=wl_analyst_editor&roles=user")
if [[ "$STATUS" == "201" || "$STATUS" == "409" ]]; then
    ok "analyst1 (editor) — can edit whitelists"
else
    info "analyst1 create returned HTTP $STATUS"
fi

# viewer1 — viewer role (read-only access to whitelists and audit trail)
STATUS=$(splunk_api POST "/services/authentication/users" \
    -d "name=viewer1&password=${SPLUNK_PASSWORD}&roles=wl_analyst_viewer&roles=user")
if [[ "$STATUS" == "201" || "$STATUS" == "409" ]]; then
    ok "viewer1  (viewer) — read-only access"
else
    info "viewer1 create returned HTTP $STATUS"
fi

# wladmin1 — WL admin (can approve/reject requests, configure limits, view usage)
STATUS=$(splunk_api POST "/services/authentication/users" \
    -d "name=wladmin1&password=${SPLUNK_PASSWORD}&roles=wl_admin&roles=user")
if [[ "$STATUS" == "201" || "$STATUS" == "409" ]]; then
    ok "wladmin1 (admin)  — approve/reject, configure limits"
else
    info "wladmin1 create returned HTTP $STATUS"
fi

# ── Step 6: Seed demo data ──────────────────────────────────────────

echo ""
echo "Step 6/7: Seeding demo data..."

APP_LOOKUPS="/opt/splunk/etc/apps/wl_manager/lookups"

# Calculate demo dates
FUTURE_7D=$(date -u -d "+7 days" "+%Y-%m-%d 00:00" 2>/dev/null || date -u -v+7d "+%Y-%m-%d 00:00" 2>/dev/null || echo "2026-04-01 00:00")
FUTURE_30D=$(date -u -d "+30 days" "+%Y-%m-%d 00:00" 2>/dev/null || date -u -v+30d "+%Y-%m-%d 00:00" 2>/dev/null || echo "2026-04-25 00:00")
FUTURE_6M=$(date -u -d "+180 days" "+%Y-%m-%d 00:00" 2>/dev/null || date -u -v+180d "+%Y-%m-%d 00:00" 2>/dev/null || echo "2026-09-20 00:00")
PAST_DATE="2025-01-15 08:00"

# 1. Master mapping CSV — 3 demo rules
MSYS_NO_PATHCONV=1 docker exec -u splunk "$CONTAINER_NAME" bash -c "cat > ${APP_LOOKUPS}/rule_csv_map.csv << 'CSVEOF'
rule_name,csv_file,app_context
Brute_Force_Login,brute_force_whitelist.csv,wl_manager
Suspicious_Process,suspicious_process_whitelist.csv,wl_manager
Impossible_Travel,impossible_travel_whitelist.csv,wl_manager
CSVEOF"

# 2. Brute Force whitelist (has Expires — demonstrates expiration + approval gates)
MSYS_NO_PATHCONV=1 docker exec -u splunk "$CONTAINER_NAME" bash -c "cat > ${APP_LOOKUPS}/brute_force_whitelist.csv << CSVEOF
user,src_ip,threshold,Comment,Expires
svc_monitoring,10.1.1.50,100,Service account - high threshold expected,${FUTURE_6M}
john.doe,192.168.1.100,20,VPN reconnection issues - temporary,${FUTURE_7D}
jane.smith,10.0.0.25,50,Automated testing account,${FUTURE_30D}
legacy_scanner,172.16.0.10,200,Vulnerability scanner - approved,
old_entry,10.99.99.99,10,This entry is expired and will be auto-removed on load,${PAST_DATE}
CSVEOF"

# 3. Suspicious Process whitelist (no expiration — simpler CSV)
MSYS_NO_PATHCONV=1 docker exec -u splunk "$CONTAINER_NAME" bash -c "cat > ${APP_LOOKUPS}/suspicious_process_whitelist.csv << 'CSVEOF'
host,process_name,user,Comment
SRV-BUILD01,powershell.exe,svc_deploy,CI/CD deployment pipeline
WKSTN-SEC042,mimikatz.exe,admin.redteam,Authorized penetration testing
SRV-MONITOR,psexec.exe,svc_monitoring,Remote monitoring agent
SRV-BACKUP01,robocopy.exe,svc_backup,Nightly backup job
CSVEOF"

# 4. Impossible Travel whitelist (has Expires — demonstrates date picker)
MSYS_NO_PATHCONV=1 docker exec -u splunk "$CONTAINER_NAME" bash -c "cat > ${APP_LOOKUPS}/impossible_travel_whitelist.csv << CSVEOF
user,src_country,Comment,Expires
exec.vp,US,Executive with VPN split-tunnel,${FUTURE_6M}
contractor.ext,IN,Offshore contractor - uses VPN from India and US,${FUTURE_30D}
svc_azure,IE,Azure service account - datacenter in Ireland,
CSVEOF"

# Fix ownership
MSYS_NO_PATHCONV=1 docker exec -u 0 "$CONTAINER_NAME" \
    chown -R splunk:splunk "${APP_LOOKUPS}/" 2>/dev/null || true

ok "Demo data seeded (3 rules, 3 CSV files, 1 expired row for auto-removal demo)."

# ── Step 7: Summary ─────────────────────────────────────────────────

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  DEMO READY"
echo ""
echo "  Splunk Web:  http://localhost:${WEB_PORT}"
echo ""
echo "  Demo Accounts:"
echo "    admin    / ${SPLUNK_PASSWORD}  — full Splunk admin"
echo "    analyst1 / ${SPLUNK_PASSWORD}  — editor (edit whitelists)"
echo "    viewer1  / ${SPLUNK_PASSWORD}  — viewer (read-only)"
echo "    wladmin1 / ${SPLUNK_PASSWORD}  — WL admin (approve/reject)"
echo ""
echo "  What to try:"
echo ""
echo "  As analyst1 (editor):"
echo "    1. Apps > Whitelist Manager"
echo "    2. Select Brute_Force_Login — notice the expired row"
echo "       is auto-removed (yellow banner)"
echo "    3. Edit a cell, add a row, save with a comment"
echo "    4. Try removing 3+ rows — approval is required!"
echo "    5. Check the Audit Trail tab for change history"
echo ""
echo "  As wladmin1 (admin):"
echo "    6. Log in as wladmin1"
echo "    7. Go to the Control Panel tab"
echo "    8. Review and approve/reject analyst1's request"
echo "    9. Check Analyst Usage and Limits & Permissions tabs"
echo ""
echo "  As viewer1 (viewer):"
echo "    10. Log in as viewer1"
echo "    11. Notice you can view but NOT edit (Save is disabled)"
echo "    12. Control Panel tab is NOT visible"
echo ""
echo "  Tear down:"
echo "    bash demo/demo.sh --stop    # stop + remove container"
echo "    bash demo/demo.sh --clean   # also remove data volume"
echo "═══════════════════════════════════════════════════════════════"
echo ""
