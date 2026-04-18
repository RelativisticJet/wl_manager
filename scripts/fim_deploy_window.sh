#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════
# FIM Deploy Window Script
# ═══════════════════════════════════════════════════════════════════════
#
# Marks a bounded time window during which legitimate deploy-driven
# changes to watched files (default/*.conf, bin/*.py, etc.) should be
# downgraded from HIGH-severity FIM alerts to INFO-severity
# `fim_file_modified_during_deploy` events. The File Integrity Monitor
# (bin/wl_fim.py) reads the window file on every run.
#
# The window file is HMAC-signed with a key derived from the Splunk
# server GUID (same construction as the FIM baseline) so an attacker
# cannot forge a permanent suppression window. The handler ALSO
# enforces a hard 1-hour cap at read time, even if a forged file
# claims to last longer.
#
# Usage:
#
#   ./scripts/fim_deploy_window.sh start [--duration N] [--reason "..."] [container]
#   ./scripts/fim_deploy_window.sh end   [container]
#   ./scripts/fim_deploy_window.sh status [container]
#
# Arguments:
#   --duration  N    window length in minutes (default 15, max 60)
#   --reason    str  free-text reason recorded in the window file
#
# Default container: wl_manager_test
# ═══════════════════════════════════════════════════════════════════════

set -euo pipefail

SUBCMD="${1:-}"
if [ -z "$SUBCMD" ]; then
    echo "Usage: $0 {start|end|status} [--duration N] [--reason '...'] [container]"
    exit 1
fi
shift

DURATION_MIN=15
REASON=""
CONTAINER="wl_manager_test"

while [ $# -gt 0 ]; do
    case "$1" in
        --duration)
            DURATION_MIN="$2"
            shift 2
            ;;
        --reason)
            REASON="$2"
            shift 2
            ;;
        *)
            CONTAINER="$1"
            shift
            ;;
    esac
done

if ! [[ "$DURATION_MIN" =~ ^[0-9]+$ ]]; then
    echo "ERROR: --duration must be an integer (minutes)."
    exit 1
fi
if [ "$DURATION_MIN" -lt 1 ] || [ "$DURATION_MIN" -gt 60 ]; then
    echo "ERROR: --duration must be between 1 and 60 minutes."
    exit 1
fi

if ! MSYS_NO_PATHCONV=1 docker ps --format '{{.Names}}' | grep -q "^${CONTAINER}$"; then
    echo "ERROR: Container '$CONTAINER' is not running."
    exit 1
fi

WINDOW_PATH="/opt/splunk/etc/apps/wl_manager/lookups/_versions/_fim_deploy_window.json"
RECOVERY_LOG="/opt/splunk/etc/apps/wl_manager/lookups/_versions/_recovery_log.jsonl"

start_window() {
    local started_at expires_at host_user
    started_at=$(date -u +%s)
    expires_at=$((started_at + DURATION_MIN * 60))
    host_user="$(whoami 2>/dev/null || echo unknown)"

    MSYS_NO_PATHCONV=1 docker exec -u 0 \
        -e STARTED_AT="$started_at" -e EXPIRES_AT="$expires_at" \
        -e HOST_USER="$host_user" -e REASON="$REASON" \
        -e WINDOW_PATH="$WINDOW_PATH" -e RECOVERY_LOG="$RECOVERY_LOG" \
        "$CONTAINER" python3 -c '
import json, hashlib, hmac, os, sys
from datetime import datetime, timezone

# Read GUID for HMAC key
guid = ""
with open("/opt/splunk/etc/instance.cfg") as f:
    for line in f:
        line = line.strip()
        if line.startswith("guid"):
            guid = line.split("=", 1)[1].strip()
            break
if not guid:
    print("ERROR: cannot read GUID")
    sys.exit(1)
# Import FIM_HMAC_SALT from wl_constants (single source of truth)
sys.path.insert(0, "/opt/splunk/etc/apps/wl_manager/bin")
try:
    from wl_constants import FIM_HMAC_SALT
    salt = FIM_HMAC_SALT
except ImportError:
    salt = b"wl_manager_fim_integrity_v1"
    print("WARNING: using hardcoded FIM salt (wl_constants import failed)",
          file=sys.stderr)
key = hashlib.sha256(salt + guid.encode()).digest()

body = {
    "started_at":   int(os.environ["STARTED_AT"]),
    "expires_at":   int(os.environ["EXPIRES_AT"]),
    "started_by":   os.environ["HOST_USER"],
    "reason":       os.environ["REASON"][:500],
}
filtered = {k: v for k, v in body.items() if k != "_checksum"}
payload = json.dumps(filtered, sort_keys=True, default=str)
body["_checksum"] = hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()

os.makedirs(os.path.dirname(os.environ["WINDOW_PATH"]), exist_ok=True)
with open(os.environ["WINDOW_PATH"], "w") as f:
    json.dump(body, f, indent=2)
os.chmod(os.environ["WINDOW_PATH"], 0o600)

# Append recovery-log entry so the window opening is visible in
# the Audit dashboard.
rec = {
    "timestamp": body["started_at"],
    "timestamp_human": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    "action": "fim_deploy_window_start",
    "script": "fim_deploy_window.sh",
    "host_user": body["started_by"],
    "reason": body["reason"],
    "duration_min": (body["expires_at"] - body["started_at"]) // 60,
}
with open(os.environ["RECOVERY_LOG"], "a") as f:
    f.write(json.dumps(rec) + "\n")
print("Deploy window opened until " + datetime.fromtimestamp(body["expires_at"], tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"))
'
}

end_window() {
    MSYS_NO_PATHCONV=1 docker exec -u 0 \
        -e WINDOW_PATH="$WINDOW_PATH" -e RECOVERY_LOG="$RECOVERY_LOG" \
        -e HOST_USER="$(whoami 2>/dev/null || echo unknown)" \
        "$CONTAINER" python3 -c '
import json, os, time
from datetime import datetime, timezone

if not os.path.isfile(os.environ["WINDOW_PATH"]):
    print("No deploy window active.")
else:
    os.remove(os.environ["WINDOW_PATH"])
    rec = {
        "timestamp": int(time.time()),
        "timestamp_human": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "action": "fim_deploy_window_end",
        "script": "fim_deploy_window.sh",
        "host_user": os.environ["HOST_USER"],
    }
    with open(os.environ["RECOVERY_LOG"], "a") as f:
        f.write(json.dumps(rec) + "\n")
    print("Deploy window closed.")
'
}

status_window() {
    MSYS_NO_PATHCONV=1 docker exec -u 0 \
        -e WINDOW_PATH="$WINDOW_PATH" \
        "$CONTAINER" python3 -c '
import json, os, time
from datetime import datetime, timezone
p = os.environ["WINDOW_PATH"]
if not os.path.isfile(p):
    print("no_window")
else:
    with open(p) as f:
        body = json.load(f)
    now = int(time.time())
    expires = int(body.get("expires_at", 0))
    if now >= expires:
        print("expired")
    else:
        print("active until " + datetime.fromtimestamp(expires, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"))
        print("  started_by: " + str(body.get("started_by", "?")))
        print("  reason:     " + str(body.get("reason", "")))
'
}

case "$SUBCMD" in
    start)
        start_window
        ;;
    end)
        end_window
        ;;
    status)
        status_window
        ;;
    *)
        echo "Unknown subcommand: $SUBCMD"
        echo "Usage: $0 {start|end|status} ..."
        exit 1
        ;;
esac
