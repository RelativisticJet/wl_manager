#!/usr/bin/env bash
#
# ═══════════════════════════════════════════════════════════════════════
# Whitelist Manager — Backup/Restore Smoke Test
# ═══════════════════════════════════════════════════════════════════════
#
# Verifies that the data-layer backup script roundtrips cleanly:
#   1. Inventory current state
#   2. Run scripts/backup_data.sh
#   3. Verify the archive contains every CSV + the mapping
#   4. Extract to a temp dir and verify byte-for-byte equality
#
# Does NOT actually restore over a live install (would risk damaging
# real data). For a full restore exercise, follow the runbook in
# docs/BACKUP_AND_RESTORE.md against a disposable container.
#
# Exit codes:
#   0 — backup roundtripped successfully
#   1 — inventory mismatch (something the backup should have captured
#       was missing)
#   2 — checksum / extraction failure
#   3 — preconditions failed (no container, no script)
#
# Usage:
#   bash scripts/test_backup_restore.sh [container_name]
#
# Default container: wl_manager_test

set -euo pipefail

CONTAINER="${1:-wl_manager_test}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKUP_SCRIPT="$SCRIPT_DIR/backup_data.sh"
APP_PATH="/opt/splunk/etc/apps/wl_manager"

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  Whitelist Manager — Backup/Restore Smoke Test"
echo "═══════════════════════════════════════════════════════════════"

# ── Preconditions ─────────────────────────────────────────────────────
if [[ ! -x "$BACKUP_SCRIPT" ]] && [[ ! -f "$BACKUP_SCRIPT" ]]; then
    echo "ERROR: backup_data.sh not found at $BACKUP_SCRIPT"
    exit 3
fi

if ! MSYS_NO_PATHCONV=1 docker ps --format '{{.Names}}' | grep -q "^${CONTAINER}\$"; then
    echo "ERROR: Container '$CONTAINER' is not running."
    exit 3
fi

# ── Step 1: Inventory live state ──────────────────────────────────────
echo ""
echo "Step 1/4: Inventorying live state..."
# Use a repo-local tmpdir so `docker cp` on Windows/Git-Bash gets a
# Windows-compatible path. `mktemp -d` (Linux semantics) can produce
# /tmp/... paths that Git Bash + Docker Desktop interpret as
# C:\\tmp\\... during the cp-out step.
TMPDIR_LIVE="$REPO_ROOT/.tmp_smoke_$$"
mkdir -p "$TMPDIR_LIVE"
TMPDIR_RESTORE=""
trap 'rm -rf "$TMPDIR_LIVE" "$TMPDIR_RESTORE"' EXIT

# Inventory every customer-meaningful CSV under lookups/, regardless of
# naming convention. Excludes match the backup_data.sh exclude list so
# the comparison only spans files the archive is expected to contain.
LIVE_INVENTORY="$TMPDIR_LIVE/live_inventory.txt"
MSYS_NO_PATHCONV=1 docker exec -u 0 "$CONTAINER" sh -c \
    "cd $APP_PATH/lookups && \
     find . -type f \
       ! -name '_*.json' ! -name '_*.jsonl' \
       ! -name '*.lock' ! -name '*.bak' \
       ! -name '.approval_queue.sig' \
       ! -name '.csv_expected_hashes.json' \
       ! -name '.fim_*.json' \
       ! -name '.presence.json' \
       ! -path './_versions/_*.json' ! -path './_versions/_*.jsonl' \
       ! -path './_versions/.*' \
       | sort" \
    > "$LIVE_INVENTORY"

LIVE_FILE_COUNT=$(wc -l < "$LIVE_INVENTORY" | tr -d ' ')
echo "  Live data files: $LIVE_FILE_COUNT"

# Hash each file to compare contents later.
LIVE_HASHES="$TMPDIR_LIVE/live_hashes.txt"
while IFS= read -r relpath; do
    hash=$(MSYS_NO_PATHCONV=1 docker exec -u 0 "$CONTAINER" \
        sh -c "sha256sum '$APP_PATH/lookups/$relpath' 2>/dev/null | cut -d' ' -f1" | tr -d '\r')
    echo "$hash  $relpath" >> "$LIVE_HASHES"
done < "$LIVE_INVENTORY"

# ── Step 2: Run the backup script ────────────────────────────────────
echo ""
echo "Step 2/4: Running backup_data.sh..."
BACKUP_OUTPUT_DIR="$TMPDIR_LIVE/backups"
mkdir -p "$BACKUP_OUTPUT_DIR"
bash "$BACKUP_SCRIPT" "$CONTAINER" "$BACKUP_OUTPUT_DIR" >/dev/null 2>&1 || {
    echo "ERROR: backup_data.sh failed."
    exit 2
}

ARCHIVE=$(ls "$BACKUP_OUTPUT_DIR"/*.tar.gz 2>/dev/null | head -1)
if [[ -z "$ARCHIVE" ]]; then
    echo "ERROR: backup script ran but produced no archive."
    exit 2
fi
echo "  Archive: $(basename "$ARCHIVE")"

# ── Step 3: Verify checksum ──────────────────────────────────────────
echo ""
echo "Step 3/4: Verifying checksum..."
if [[ -f "${ARCHIVE}.sha256" ]]; then
    if command -v sha256sum >/dev/null 2>&1; then
        cd "$BACKUP_OUTPUT_DIR" && sha256sum -c "$(basename "${ARCHIVE}.sha256")" >/dev/null 2>&1 || {
            echo "ERROR: checksum verification failed."
            exit 2
        }
    elif command -v shasum >/dev/null 2>&1; then
        cd "$BACKUP_OUTPUT_DIR" && shasum -a 256 -c "$(basename "${ARCHIVE}.sha256")" >/dev/null 2>&1 || {
            echo "ERROR: checksum verification failed."
            exit 2
        }
    fi
    echo "  Checksum OK."
else
    echo "  No checksum file (sha256sum/shasum not installed?) — skipping."
fi

# ── Step 4: Extract + compare ─────────────────────────────────────────
echo ""
echo "Step 4/4: Extracting archive + comparing contents..."
TMPDIR_RESTORE="$REPO_ROOT/.tmp_restore_$$"
mkdir -p "$TMPDIR_RESTORE"
tar -xzf "$ARCHIVE" -C "$TMPDIR_RESTORE"

RESTORED_INVENTORY="$TMPDIR_LIVE/restored_inventory.txt"
(cd "$TMPDIR_RESTORE" && find . -type f \
   ! -name '_*.json' ! -name '_*.jsonl' \
   ! -name '*.lock' ! -name '*.bak' \
   ! -name '.approval_queue.sig' \
   ! -name '.csv_expected_hashes.json' \
   ! -name '.fim_*.json' \
   ! -name '.presence.json' \
   ! -path './_versions/_*.json' ! -path './_versions/_*.jsonl' \
   ! -path './_versions/.*' \
   | sort) \
    > "$RESTORED_INVENTORY"

if ! diff -q "$LIVE_INVENTORY" "$RESTORED_INVENTORY" >/dev/null 2>&1; then
    echo "FAIL: file inventory differs between live and backup."
    echo "Live (first 5):"
    head -5 "$LIVE_INVENTORY" | sed 's/^/  /'
    echo "Restored (first 5):"
    head -5 "$RESTORED_INVENTORY" | sed 's/^/  /'
    exit 1
fi

# Compare each file's hash.
MISMATCHES=0
while IFS=' ' read -r expected_hash relpath; do
    relpath_clean="${relpath#  }"
    relpath_clean="${relpath_clean#./}"
    actual_hash=$(sha256sum "$TMPDIR_RESTORE/$relpath_clean" 2>/dev/null \
        | cut -d' ' -f1 || echo "missing")
    if [[ "$expected_hash" != "$actual_hash" ]]; then
        echo "  MISMATCH: $relpath_clean"
        echo "    live:     $expected_hash"
        echo "    restored: $actual_hash"
        MISMATCHES=$((MISMATCHES + 1))
    fi
done < "$LIVE_HASHES"

if [[ $MISMATCHES -gt 0 ]]; then
    echo ""
    echo "FAIL: $MISMATCHES file(s) hashed differently after restore."
    exit 1
fi

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  PASS — backup roundtripped cleanly"
echo ""
echo "  Files compared:   $LIVE_FILE_COUNT"
echo "  Hash mismatches:  0"
echo "  Archive size:     $(du -h "$ARCHIVE" | cut -f1)"
echo "═══════════════════════════════════════════════════════════════"
