#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════
# Emergency Lockdown Recovery Script
# ═══════════════════════════════════════════════════════════════════════
#
# USE ONLY WHEN: Both superadmin accounts are compromised or unavailable,
# and the app is locked down with no way to deactivate via the UI.
#
# This script directly removes the lockdown state file from the Splunk
# container, bypassing the dual-approval requirement.
#
# AUDIT: This bypass is written to an append-only recovery log inside
# the container at:
#   /opt/splunk/etc/apps/wl_manager/lookups/_versions/_recovery_log.jsonl
# A Splunk scripted input tails that file into the wl_audit index so
# the record is visible in the Audit dashboard.
#
# Usage:
#   ./scripts/emergency_unlock.sh [container_name]
#
# Default container: wl_manager_test
# ═══════════════════════════════════════════════════════════════════════

set -euo pipefail

CONTAINER="${1:-wl_manager_test}"
LOCKDOWN_PATH="/opt/splunk/etc/apps/wl_manager/lookups/_versions/_emergency_lockdown.json"
RECOVERY_LOG="/opt/splunk/etc/apps/wl_manager/lookups/_versions/_recovery_log.jsonl"

echo "═══════════════════════════════════════════════════════"
echo "  EMERGENCY LOCKDOWN RECOVERY"
echo "═══════════════════════════════════════════════════════"
echo ""
echo "Container: $CONTAINER"
echo "Target:    $LOCKDOWN_PATH"
echo ""

if ! MSYS_NO_PATHCONV=1 docker ps --format '{{.Names}}' | grep -q "^${CONTAINER}$"; then
    echo "ERROR: Container '$CONTAINER' is not running."
    exit 1
fi

echo "Current lockdown state:"
MSYS_NO_PATHCONV=1 docker exec -u 0 "$CONTAINER" cat "$LOCKDOWN_PATH" 2>/dev/null || echo "  (no lockdown file found — lockdown is not active)"
echo ""

HOST_USER="$(whoami 2>/dev/null || echo unknown)"
read -r -p "Incident ticket or reason (required): " REASON
if [ -z "$REASON" ]; then
    echo "Aborted: reason is required for audit trail."
    exit 1
fi

read -r -p "Remove lockdown file and restore write operations? [y/N] " confirm
if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
    echo "Aborted."
    exit 0
fi

# Append audit record BEFORE destructive action (attacker cannot skip
# the audit by killing the script mid-run)
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
    "action": "emergency_unlock",
    "script": "emergency_unlock.sh",
    "container": os.environ["CONTAINER_NAME"],
    "host_user": os.environ["HOST_USER"],
    "reason": os.environ["REASON"][:500],
}
with open(log_path, "a", encoding="utf-8") as fh:
    fh.write(json.dumps(rec) + "\n")
os.chmod(log_path, 0o644)
print("Audit record appended:", log_path)
'

MSYS_NO_PATHCONV=1 docker exec -u 0 "$CONTAINER" rm -f "$LOCKDOWN_PATH"
echo ""
echo "Lockdown file removed."
echo ""

if MSYS_NO_PATHCONV=1 docker exec -u 0 "$CONTAINER" test -f "$LOCKDOWN_PATH" 2>/dev/null; then
    echo "WARNING: File still exists. Manual intervention needed."
    exit 1
else
    echo "CONFIRMED: Lockdown deactivated. Write operations restored."
    echo "Audit record appended to: $RECOVERY_LOG"
    echo ""
    echo "IMPORTANT: Document this emergency unlock in your incident log."
    echo "  - Who ran this script"
    echo "  - Why the UI deactivation was not possible"
    echo "  - Incident ticket number"
    echo ""
    echo "Consider rotating superadmin credentials if accounts were"
    echo "compromised."
fi
