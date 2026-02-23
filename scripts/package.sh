#!/usr/bin/env bash
#
# ═══════════════════════════════════════════════════════════════════════
# Phase 4: PACKAGE — Build a .spl file from the wl_manager app
# ═══════════════════════════════════════════════════════════════════════
#
# What is a .spl file?
#   A .spl file is simply a .tar.gz archive with a .spl extension.
#   Inside it, the top-level directory must be the app name (wl_manager/).
#   Splunk expects this exact structure when you install via:
#     - Splunk Web → "Install app from file"
#     - CLI:  splunk install app wl_manager-1.0.0.spl
#
# Usage:
#   bash scripts/package.sh              # builds with version from app.conf
#   bash scripts/package.sh 2.1.0        # override version
#
# Output:
#   dist/wl_manager-<version>.spl
#   dist/wl_manager-<version>.spl.sha256
#

set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
APP_NAME="wl_manager"
DIST_DIR="$APP_DIR/dist"

# ── Determine version ─────────────────────────────────────────────────
if [[ -n "${1:-}" ]]; then
    VERSION="$1"
else
    VERSION=$(grep "^version" "$APP_DIR/default/app.conf" | head -1 | cut -d= -f2 | tr -d ' ')
fi

if [[ -z "$VERSION" ]]; then
    echo "ERROR: Could not determine version. Pass it as an argument or set it in app.conf."
    exit 1
fi

SPL_FILE="$DIST_DIR/${APP_NAME}-${VERSION}.spl"

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  Packaging: $APP_NAME v$VERSION"
echo "═══════════════════════════════════════════════════════════════"
echo ""

# ── Step 1: Clean up build artifacts ──────────────────────────────────
echo "Step 1/5: Cleaning build artifacts..."

# Remove Python bytecode (py_compile creates these during validation)
find "$APP_DIR" -name "*.pyc" -delete 2>/dev/null || true
find "$APP_DIR" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true

# Remove OS junk files
find "$APP_DIR" -name ".DS_Store" -delete 2>/dev/null || true
find "$APP_DIR" -name "Thumbs.db" -delete 2>/dev/null || true

echo "  Done."

# ── Step 2: Run validation ────────────────────────────────────────────
echo ""
echo "Step 2/5: Running validation checks..."
if bash "$APP_DIR/scripts/validate.sh"; then
    echo ""
    echo "  Validation passed. Proceeding to package."
else
    echo ""
    echo "  ERROR: Validation failed. Fix issues before packaging."
    exit 1
fi

echo "  Done."

# ── Step 3: Create dist directory ─────────────────────────────────────
echo ""
echo "Step 3/5: Preparing dist directory..."
mkdir -p "$DIST_DIR"

# Remove old build if it exists
rm -f "$SPL_FILE" "$SPL_FILE.sha256" 2>/dev/null || true
echo "  Output: $SPL_FILE"

# ── Step 4: Build the .spl (tar.gz) ──────────────────────────────────
echo ""
echo "Step 4/5: Creating .spl archive..."

# IMPORTANT: The .spl must contain a top-level directory named after the app.
# We tar from the parent of the app directory so the structure is:
#   wl_manager/
#   wl_manager/default/
#   wl_manager/default/app.conf
#   ...
#
# Exclude files that should NOT be in the package:

tar -czf "$SPL_FILE" \
    -C "$(dirname "$APP_DIR")" \
    --exclude="$APP_NAME/.git" \
    --exclude="$APP_NAME/.github" \
    --exclude="$APP_NAME/.docker" \
    --exclude="$APP_NAME/dist" \
    --exclude="$APP_NAME/scripts" \
    --exclude="$APP_NAME/tests" \
    --exclude="$APP_NAME/docker-compose.yml" \
    --exclude="$APP_NAME/.dockerignore" \
    --exclude="$APP_NAME/.gitignore" \
    --exclude="$APP_NAME/Makefile" \
    --exclude="$APP_NAME/__pycache__" \
    --exclude="$APP_NAME/**/__pycache__" \
    --exclude="$APP_NAME/**/*.pyc" \
    --exclude="$APP_NAME/.DS_Store" \
    "$APP_NAME/"

echo "  Archive created."

# ── Step 5: Generate checksum ─────────────────────────────────────────
echo ""
echo "Step 5/5: Generating SHA-256 checksum..."

# Use sha256sum if available, otherwise fall back to shasum or openssl
if command -v sha256sum &>/dev/null; then
    sha256sum "$SPL_FILE" > "$SPL_FILE.sha256"
elif command -v shasum &>/dev/null; then
    shasum -a 256 "$SPL_FILE" > "$SPL_FILE.sha256"
elif command -v openssl &>/dev/null; then
    openssl dgst -sha256 "$SPL_FILE" > "$SPL_FILE.sha256"
else
    echo "  WARNING: No sha256 tool found — skipping checksum."
fi

if [[ -f "$SPL_FILE.sha256" ]]; then
    echo "  Checksum: $(cat "$SPL_FILE.sha256")"
fi

# ── Summary ───────────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  BUILD SUCCESSFUL"
echo ""
echo "  Package:  $SPL_FILE"
FILE_SIZE=$(du -h "$SPL_FILE" | cut -f1)
echo "  Size:     $FILE_SIZE"
echo "  Version:  $VERSION"
echo ""
echo "  To verify contents:"
echo "    tar -tzf $SPL_FILE"
echo ""
echo "  To install on Splunk:"
echo "    # Option A — Splunk CLI:"
echo "    \$SPLUNK_HOME/bin/splunk install app $SPL_FILE"
echo ""
echo "    # Option B — Splunk Web:"
echo "    Apps > Manage Apps > Install app from file > Upload $SPL_FILE"
echo ""
echo "    # Option C — Manual copy:"
echo "    tar -xzf $SPL_FILE -C \$SPLUNK_HOME/etc/apps/"
echo "    \$SPLUNK_HOME/bin/splunk restart"
echo "═══════════════════════════════════════════════════════════════"
