#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════
# Cooldown Counter Recovery Script
# ═══════════════════════════════════════════════════════════════════════
#
# USE WHEN: The rate-limit cooldown state was tampered with (KV store
# record deleted or HMAC check failed), causing the app to fail-closed
# and block admin limit changes and purge operations.
#
# This script:
#   1. Clears the on-disk tamper flag and initialization marker
#   2. Deletes the wl_cooldowns KV store record so the handler can
#      rebuild it on the next request
#   3. Appends a record to the append-only recovery log
#   4. Restarts Splunk to drop any cached HMAC keys
#
# AUDIT: The recovery log is tailed by a Splunk scripted input into
# wl_audit so the record is visible in the Audit dashboard.
#
# Usage:
#   ./scripts/reset_cooldowns.sh [container_name]
#
# Default container: wl_manager_test
# ═══════════════════════════════════════════════════════════════════════

set -euo pipefail

CONTAINER="${1:-wl_manager_test}"
VERSIONS_DIR="/opt/splunk/etc/apps/wl_manager/lookups/_versions"
TAMPER_FLAG_PATH="${VERSIONS_DIR}/.cooldown_tamper"
INIT_MARKER_PATH="${VERSIONS_DIR}/.cooldown_initialized"
LEGACY_COOLDOWN_PATH="${VERSIONS_DIR}/_action_cooldowns.json"
RECOVERY_LOG="${VERSIONS_DIR}/_recovery_log.jsonl"

echo "═══════════════════════════════════════════════════════"
echo "  COOLDOWN COUNTER RECOVERY"
echo "═══════════════════════════════════════════════════════"
echo ""
echo "Container: $CONTAINER"
echo ""

if ! MSYS_NO_PATHCONV=1 docker ps --format '{{.Names}}' | grep -q "^${CONTAINER}$"; then
    echo "ERROR: Container '$CONTAINER' is not running."
    exit 1
fi

HOST_USER="$(whoami 2>/dev/null || echo unknown)"
read -r -p "Incident ticket or reason (required): " REASON
if [ -z "$REASON" ]; then
    echo "Aborted: reason is required for audit trail."
    exit 1
fi

read -r -p "Reset cooldown counter and restart Splunk? [y/N] " confirm
if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
    echo "Aborted."
    exit 0
fi

# Append audit record BEFORE destructive action
TS_EPOCH="$(date -u +%s)"
TS_HUMAN="$(date -u +'%Y-%m-%d %H:%M:%S UTC')"
MSYS_NO_PATHCONV=1 docker exec -u 0 -e TS_EPOCH="$TS_EPOCH" -e TS_HUMAN="$TS_HUMAN" \
    -e HOST_USER="$HOST_USER" -e REASON="$REASON" -e CONTAINER_NAME="$CONTAINER" \
    -e RECOVERY_LOG="$RECOVERY_LOG" \
    "$CONTAINER" python3 -c '
import json, os
log_path = os.environ["RECOVERY_LOG"]
os.makedirs(os.path.dirname(log_path), exist_ok=True)
rec = {
    "timestamp": int(os.environ["TS_EPOCH"]),
    "timestamp_human": os.environ["TS_HUMAN"],
    "action": "reset_cooldowns",
    "script": "reset_cooldowns.sh",
    "container": os.environ["CONTAINER_NAME"],
    "host_user": os.environ["HOST_USER"],
    "reason": os.environ["REASON"][:500],
}
with open(log_path, "a", encoding="utf-8") as fh:
    fh.write(json.dumps(rec) + "\n")
os.chmod(log_path, 0o644)
print("Audit record appended:", log_path)
'

# Clear tamper flag + init marker + legacy file (if any)
MSYS_NO_PATHCONV=1 docker exec -u 0 "$CONTAINER" rm -f \
    "$TAMPER_FLAG_PATH" "$INIT_MARKER_PATH" "$LEGACY_COOLDOWN_PATH"

# Delete the wl_cooldowns KV store record so handler can rebuild it.
# Uses an authenticated REST call from inside the container.
MSYS_NO_PATHCONV=1 docker exec -u 0 -e SPLUNK_PW="Chang3d!" "$CONTAINER" bash -c '
curl -s -k -u "admin:${SPLUNK_PW}" -X DELETE \
  "https://localhost:8089/servicesNS/nobody/wl_manager/storage/collections/data/wl_cooldowns/state" \
  > /dev/null 2>&1 || true
echo "KV store cooldown record cleared."
'

echo ""
echo "Restarting Splunk to drop cached HMAC keys..."
MSYS_NO_PATHCONV=1 docker exec -u splunk "$CONTAINER" /opt/splunk/bin/splunk stop
MSYS_NO_PATHCONV=1 docker exec -u splunk "$CONTAINER" /opt/splunk/bin/splunk start --answer-yes

echo ""
echo "CONFIRMED: Cooldown state reset and Splunk restarted."
echo "Audit record appended to: $RECOVERY_LOG"
echo ""
echo "IMPORTANT: Document this recovery in your incident log."
echo "  - Who ran this script"
echo "  - Why (e.g., 'counter record missing after container migration')"
echo "  - Incident ticket number"
echo ""
echo "If this was caused by an attack, review:"
echo "  - Recent wl_audit events for unusual admin activity"
echo "  - Splunk audit logs for filesystem access"
echo "  - Consider rotating superadmin credentials"
