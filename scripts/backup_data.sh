#!/usr/bin/env bash
#
# ═══════════════════════════════════════════════════════════════════════
# Whitelist Manager — Backup the DATA layer
# ═══════════════════════════════════════════════════════════════════════
#
# Captures the customer-meaningful state that survives a Splunk
# rebuild: detection-rule CSVs + rule↔CSV mapping. Does NOT capture
# state that is HMAC-bound to the Splunk server GUID (cooldowns, FIM
# baseline, etc.) — those rebuild cleanly via the post-restore steps
# in `docs/BACKUP_AND_RESTORE.md` and would fail HMAC verification on
# any host other than the original.
#
# What gets backed up:
#   - lookups/DR*.csv                    (active whitelist CSVs)
#   - lookups/rule_csv_map.csv           (rule↔CSV mapping)
#   - lookups/_versions/*.csv            (version snapshots)
#   - lookups/_versions/*_versions.json  (version manifests)
#
# What does NOT get backed up (rebuild on restore):
#   - HMAC-signed state (`_action_cooldowns.json`, `wl_cooldowns` KV)
#   - FIM baselines (`.fim_baseline.json`, `wl_fim_baseline` KV)
#   - Hash registry (`.csv_expected_hashes.json`) — re-bootstrap
#   - Lockdown / presence / deploy-window files
#   - Recovery log (it's append-only; archive separately if needed)
#
# What this script does NOT capture (out of scope):
#   - The `wl_audit` Splunk index — back up via Splunk's standard
#     index backup procedure, not this script
#   - The `wl_manager` app code (`bin/`, `appserver/`, `default/`) —
#     ship as the .spl artifact instead
#
# Usage:
#   bash scripts/backup_data.sh [container_name] [output_dir]
#
# Defaults:
#   container_name = wl_manager_test
#   output_dir     = ./backups
#

set -euo pipefail

CONTAINER="${1:-wl_manager_test}"
OUTPUT_DIR="${2:-$(cd "$(dirname "$0")/.." && pwd)/backups}"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP_NAME="wl_manager_data_${TIMESTAMP}"
BACKUP_PATH="${OUTPUT_DIR}/${BACKUP_NAME}.tar.gz"

APP_PATH="/opt/splunk/etc/apps/wl_manager"

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  Whitelist Manager — Backup Data Layer"
echo "═══════════════════════════════════════════════════════════════"
echo ""
echo "  Container:  $CONTAINER"
echo "  Output:     $BACKUP_PATH"
echo ""

# ── Verify container is running ───────────────────────────────────────
if ! MSYS_NO_PATHCONV=1 docker ps --format '{{.Names}}' | grep -q "^${CONTAINER}\$"; then
    echo "ERROR: Container '$CONTAINER' is not running."
    echo "       Start it first or pass a different container name."
    exit 1
fi

mkdir -p "$OUTPUT_DIR"

# ── Step 1: Inventory ─────────────────────────────────────────────────
echo "Step 1/4: Inventorying lookups..."
CSV_COUNT=$(MSYS_NO_PATHCONV=1 docker exec -u 0 "$CONTAINER" \
    sh -c "ls $APP_PATH/lookups/DR*.csv 2>/dev/null | wc -l" | tr -d '\r')
VERSION_COUNT=$(MSYS_NO_PATHCONV=1 docker exec -u 0 "$CONTAINER" \
    sh -c "ls $APP_PATH/lookups/_versions/*.csv 2>/dev/null | wc -l" | tr -d '\r')
echo "  CSVs:               $CSV_COUNT"
echo "  Version snapshots:  $VERSION_COUNT"
echo "  Mapping file:       rule_csv_map.csv"

# ── Step 2: Tar inside the container ─────────────────────────────────
echo ""
echo "Step 2/4: Creating archive inside container..."
TMP_INSIDE="/tmp/${BACKUP_NAME}.tar.gz"
MSYS_NO_PATHCONV=1 docker exec -u 0 "$CONTAINER" \
    tar -czf "$TMP_INSIDE" \
    -C "$APP_PATH/lookups" \
    --exclude='_versions/.*' \
    --exclude='_versions/_*.json' \
    --exclude='_versions/_*.jsonl' \
    --exclude='*.bak' \
    .

# ── Step 3: Copy out + checksum ──────────────────────────────────────
echo ""
echo "Step 3/4: Copying archive out..."
# On Git Bash + Docker Desktop the host-side destination of `docker
# cp` must be Windows-shaped or MSYS double-converts it. Convert
# `/c/Users/PC/...` → `C:/Users/PC/...` defensively (no-op on Linux).
HOST_DEST="$BACKUP_PATH"
if command -v cygpath >/dev/null 2>&1; then
    HOST_DEST=$(cygpath -m "$BACKUP_PATH")
fi
MSYS_NO_PATHCONV=1 docker cp "${CONTAINER}:${TMP_INSIDE}" "$HOST_DEST"
MSYS_NO_PATHCONV=1 docker exec -u 0 "$CONTAINER" rm -f "$TMP_INSIDE"

if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$BACKUP_PATH" > "${BACKUP_PATH}.sha256"
elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$BACKUP_PATH" > "${BACKUP_PATH}.sha256"
fi

# ── Step 4: Manifest ──────────────────────────────────────────────────
echo ""
echo "Step 4/4: Writing manifest..."
cat > "${BACKUP_PATH}.manifest.json" <<EOF
{
    "backup_name": "${BACKUP_NAME}",
    "timestamp_utc": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
    "container": "${CONTAINER}",
    "csv_count": ${CSV_COUNT:-0},
    "version_count": ${VERSION_COUNT:-0},
    "wl_manager_build": "$(MSYS_NO_PATHCONV=1 docker exec -u 0 "$CONTAINER" grep '^build' $APP_PATH/default/app.conf | cut -d= -f2 | tr -d ' \r')",
    "scope": "data_layer_only",
    "excludes": [
        "HMAC-signed state files",
        "FIM baselines",
        "wl_audit index",
        "app code"
    ],
    "restore_runbook": "docs/BACKUP_AND_RESTORE.md"
}
EOF

ARCHIVE_SIZE=$(du -h "$BACKUP_PATH" | cut -f1)
echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  BACKUP COMPLETE"
echo ""
echo "  Archive:    $BACKUP_PATH"
echo "  Size:       $ARCHIVE_SIZE"
echo "  Manifest:   ${BACKUP_PATH}.manifest.json"
if [[ -f "${BACKUP_PATH}.sha256" ]]; then
    echo "  Checksum:   $(cat "${BACKUP_PATH}.sha256" | cut -d' ' -f1)"
fi
echo ""
echo "  To restore: see docs/BACKUP_AND_RESTORE.md"
echo "═══════════════════════════════════════════════════════════════"
