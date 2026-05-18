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
echo "Step 1/6: Cleaning build artifacts..."

# Remove Python bytecode (py_compile creates these during validation)
find "$APP_DIR" -name "*.pyc" -delete 2>/dev/null || true
find "$APP_DIR" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true

# Remove OS junk files
find "$APP_DIR" -name ".DS_Store" -delete 2>/dev/null || true
find "$APP_DIR" -name "Thumbs.db" -delete 2>/dev/null || true

echo "  Done."

# ── Step 2: Run validation ────────────────────────────────────────────
echo ""
echo "Step 2/6: Running validation checks..."
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
echo "Step 3/6: Preparing dist directory..."
mkdir -p "$DIST_DIR"

# Remove old build if it exists
rm -f "$SPL_FILE" "$SPL_FILE.sha256" 2>/dev/null || true
echo "  Output: $SPL_FILE"

# ── Step 4: Build the .spl (tar.gz) ──────────────────────────────────
echo ""
echo "Step 4/6: Creating .spl archive..."

# IMPORTANT: The .spl must contain a top-level directory named after the app.
# We tar from the parent of the app directory so the structure is:
#   wl_manager/
#   wl_manager/default/
#   wl_manager/default/app.conf
#   ...
#
# Exclude files that should NOT be in the package:

# ── Step 4a: Prepare a clean rule_csv_map.csv (header-only) ──────────
# The production package ships with an empty mapping file.
# Sample lookup CSVs are for development/testing only.
STAGING_DIR=$(mktemp -d)
PROD_MAP="$STAGING_DIR/rule_csv_map.csv"
head -1 "$APP_DIR/lookups/rule_csv_map.csv" > "$PROD_MAP"

# Temporarily swap in the header-only mapping for packaging
cp "$APP_DIR/lookups/rule_csv_map.csv" "$APP_DIR/lookups/rule_csv_map.csv.bak"
cp "$PROD_MAP" "$APP_DIR/lookups/rule_csv_map.csv"

# Exclude strategy (post-2026-05-14 Phase 0.0 AppInspect findings):
#   1. `*/.*` glob catches ALL dot-prefixed paths (any depth). This is
#      defense-in-depth against denylist drift — new dev tools that
#      create `.foo` dirs are auto-excluded without script edits.
#   2. Explicit excludes for non-dot dev/runtime dirs that AppInspect
#      flags as prohibited or that would inflate package size 4-15x
#      (node_modules, htmlcov, etc.).
#   3. Step 4b below adds a post-tar sanity check that fails the build
#      if known-bad patterns appear in the tarball — backstop in case
#      a new prohibited path bypasses both layers above.
tar -czf "$SPL_FILE" \
    -C "$(dirname "$APP_DIR")" \
    --exclude='*/.*' \
    --exclude="$APP_NAME/dist" \
    --exclude="$APP_NAME/demo" \
    --exclude="$APP_NAME/scripts" \
    --exclude="$APP_NAME/tests" \
    --exclude="$APP_NAME/docs" \
    --exclude="$APP_NAME/node_modules" \
    --exclude="$APP_NAME/htmlcov" \
    --exclude="$APP_NAME/bench_results" \
    --exclude="$APP_NAME/test-results" \
    --exclude="$APP_NAME/graphify-out" \
    --exclude="$APP_NAME/docker-compose.yml" \
    --exclude="$APP_NAME/Makefile" \
    --exclude="$APP_NAME/CLAUDE.md" \
    --exclude="$APP_NAME/package.json" \
    --exclude="$APP_NAME/package-lock.json" \
    --exclude="$APP_NAME/playwright.config.*" \
    --exclude="$APP_NAME/pyproject.toml" \
    --exclude="$APP_NAME/requirements*.txt" \
    --exclude="$APP_NAME/pytest.ini" \
    --exclude="$APP_NAME/sbom.cdx.json" \
    --exclude="$APP_NAME/mkdocs.yml" \
    --exclude="$APP_NAME/__pycache__" \
    --exclude="$APP_NAME/**/__pycache__" \
    --exclude="$APP_NAME/**/*.pyc" \
    --exclude="$APP_NAME/lookups/DR*" \
    --exclude="$APP_NAME/lookups/*.bak" \
    --exclude="$APP_NAME/lookups/_versions" \
    --exclude="$APP_NAME/lookups/_*.json" \
    --exclude="$APP_NAME/lookups/_trash" \
    --exclude="$APP_NAME/metadata/local.meta" \
    --exclude="$APP_NAME/local" \
    --exclude="$APP_NAME/*.spl" \
    --exclude="$APP_NAME/*.pdf" \
    --exclude="$APP_NAME/*.png" \
    --exclude="$APP_NAME/test_*.py" \
    --exclude="$APP_NAME/*-after-*" \
    --exclude="$APP_NAME/login-check" \
    --exclude="$APP_NAME/default/data/ui/views/test_runner.xml" \
    --exclude="$APP_NAME/appserver/static/test_runner.xml" \
    --exclude="$APP_NAME/appserver/static/tests" \
    "$APP_NAME/"

# Restore the original mapping file
mv "$APP_DIR/lookups/rule_csv_map.csv.bak" "$APP_DIR/lookups/rule_csv_map.csv"
rm -rf "$STAGING_DIR"

echo "  Archive created."

# ── Step 4b: Sanity-check the .spl for prohibited content ─────────────
# AppInspect's `check_that_extracted_splunk_app_does_not_contain_prohibited_*`
# checks fail if a .spl ships dev artifacts. This local check catches the
# same patterns before the .spl ever reaches AppInspect — fail fast.
echo ""
echo "Step 4b: Sanity-checking .spl contents..."
PROHIBITED_REGEX='(/\.[^/]+(/|$)|/node_modules/|/htmlcov/|/bench_results/|/test-results/|/graphify-out/|/lookups/_trash/|/lookups/_versions/|/lookups/_[^/]+\.json$|/__pycache__/|\.pyc$|/local/|\.bak$|/sbom\.cdx\.json$|\.spl$|\.pdf$|/CLAUDE\.md$|/Makefile$|/docker-compose\.yml$|/package(-lock)?\.json$|/pyproject\.toml$|/pytest\.ini$|/requirements[^/]*\.txt$|/playwright\.config\.[^/]+$|/test_[^/]+\.py$|-after-)'
BAD_HITS="$(tar -tzf "$SPL_FILE" | grep -E "$PROHIBITED_REGEX" || true)"
if [[ -n "$BAD_HITS" ]]; then
    echo "  ERROR: .spl contains prohibited paths:"
    echo "$BAD_HITS" | head -20 | sed 's/^/    /'
    HIT_COUNT="$(echo "$BAD_HITS" | wc -l | tr -d ' ')"
    if [[ "$HIT_COUNT" -gt 20 ]]; then
        echo "    ... and $((HIT_COUNT - 20)) more"
    fi
    echo ""
    echo "  Fix: add an --exclude flag in scripts/package.sh."
    rm -f "$SPL_FILE"
    exit 1
fi
echo "  No prohibited paths in archive."

# ── Step 5: Generate checksum ─────────────────────────────────────────
echo ""
echo "Step 5/6: Generating SHA-256 checksum..."

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

# ── Step 6: Generate per-release SBOM ─────────────────────────────────
# Round 8 (2026-04-29). Replaces the static `sbom.cdx.json` baseline
# with a per-release SBOM that matches the .spl byte-for-byte. Uses
# the system Python; the helper has zero third-party deps.
echo ""
echo "Step 6/6: Generating CycloneDX SBOM..."
SBOM_FILE="$SPL_FILE.cdx.json"
PYTHON_BIN="$(command -v python3 || command -v python || echo '')"
if [[ -n "$PYTHON_BIN" ]]; then
    if "$PYTHON_BIN" "$APP_DIR/scripts/generate_sbom.py" \
            "$SPL_FILE" "$SBOM_FILE"; then
        echo "  SBOM:     $SBOM_FILE"
    else
        echo "  WARNING: SBOM generation failed — continuing anyway."
        rm -f "$SBOM_FILE" 2>/dev/null || true
    fi
else
    echo "  WARNING: No python3/python found — skipping SBOM."
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
