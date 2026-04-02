#!/usr/bin/env bash
#
# ═══════════════════════════════════════════════════════════════════════
# AppInspect Validation Wrapper — Standard + Cloud Tag Sets
# ═══════════════════════════════════════════════════════════════════════
#
# This script:
#   1. Builds the .spl file (via package.sh)
#   2. Runs splunk-appinspect with configurable tag sets
#   3. Parses output for high/critical/warning counts
#   4. Reports status and exits appropriately
#
# Usage:
#   bash scripts/verify_appinspect.sh                # default: standard tag set
#   bash scripts/verify_appinspect.sh --standard     # explicit standard
#   bash scripts/verify_appinspect.sh --cloud        # cloud-only tag set
#   bash scripts/verify_appinspect.sh --both         # standard + cloud (exhaustive)
#
# Exit codes:
#   0  = All checks passed (high + critical = 0)
#   1  = Found high or critical issues, or appinspect not installed
#

set -euo pipefail

# ── Configuration ─────────────────────────────────────────────────────
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
APP_NAME="wl_manager"
DIST_DIR="$APP_DIR/dist"

# Parse command-line arguments
TAG_SET="${1:-standard}"
case "$TAG_SET" in
    standard|--standard)
        TAG_SET="standard"
        ;;
    cloud|--cloud)
        TAG_SET="cloud"
        ;;
    both|--both)
        TAG_SET="both"
        ;;
    *)
        echo "ERROR: Unknown tag set: $TAG_SET"
        echo "Usage: $0 [standard|cloud|both]"
        exit 1
        ;;
esac

# ── Helper Functions ──────────────────────────────────────────────────

check_appinspect_installed() {
    if ! command -v splunk-appinspect &>/dev/null; then
        echo "ERROR: splunk-appinspect is not installed."
        echo ""
        echo "Install it with:"
        echo "  pip install splunk-appinspect"
        echo ""
        echo "Or install from source:"
        echo "  https://github.com/splunk/app-inspect"
        return 1
    fi
    return 0
}

run_appinspect() {
    local spl_file="$1"
    local tags="$2"
    local output_file="$3"

    # Run appinspect with specified tag set
    if [[ "$tags" == "standard" ]]; then
        splunk-appinspect inspect "$spl_file" \
            --tag-blacklist other,splunk_appinspect \
            > "$output_file" 2>&1 || true
    elif [[ "$tags" == "cloud" ]]; then
        splunk-appinspect inspect "$spl_file" \
            --included-tags cloud \
            --tag-blacklist other,splunk_appinspect \
            > "$output_file" 2>&1 || true
    fi
}

parse_appinspect_output() {
    local output_file="$1"

    # Extract counts from output
    local high_count=0
    local critical_count=0
    local warning_count=0

    # Parse output for issue counts
    # AppInspect output format varies, but typically:
    # - Lines with "high" issues start with "high:"
    # - Lines with "critical" issues start with "critical:"
    # - Lines with "warning" issues start with "warning:"

    if grep -q "^high:" "$output_file" 2>/dev/null; then
        high_count=$(grep "^high:" "$output_file" | wc -l)
    fi

    if grep -q "^critical:" "$output_file" 2>/dev/null; then
        critical_count=$(grep "^critical:" "$output_file" | wc -l)
    fi

    if grep -q "^warning:" "$output_file" 2>/dev/null; then
        warning_count=$(grep "^warning:" "$output_file" | wc -l)
    fi

    echo "$high_count:$critical_count:$warning_count"
}

format_report() {
    local spl_file="$1"
    local tag_set="$2"
    local high="$3"
    local critical="$4"
    local warning="$5"
    local output_file="$6"

    echo ""
    echo "=== AppInspect Validation ($tag_set) ==="
    echo "File: $spl_file"
    echo "High: $high, Critical: $critical, Warnings: $warning"

    if [[ $((high + critical)) -eq 0 ]]; then
        echo "Status: PASS"
    else
        echo "Status: FAIL"
        echo ""
        echo "Issues found (see details below):"
        cat "$output_file" | grep -E "^(high|critical):" || true
    fi
    echo ""
}

# ── Main Execution ────────────────────────────────────────────────────

echo ""
echo "═══════════════════════════════════════════════════════════════════"
echo "  AppInspect Validation ($TAG_SET tag set)"
echo "═══════════════════════════════════════════════════════════════════"
echo ""

# Step 1: Check if appinspect is installed
echo "Checking for splunk-appinspect..."
if ! check_appinspect_installed; then
    exit 1
fi
echo "  Found: $(splunk-appinspect --version 2>/dev/null || echo 'unknown version')"
echo ""

# Step 2: Get version from app.conf
VERSION=$(grep "^version" "$APP_DIR/default/app.conf" | head -1 | cut -d= -f2 | tr -d ' ')
SPL_FILE="$DIST_DIR/${APP_NAME}-${VERSION}.spl"

# Step 3: Build the .spl file (if needed)
if [[ ! -f "$SPL_FILE" ]]; then
    echo "Building .spl file..."
    if ! bash "$APP_DIR/scripts/package.sh"; then
        echo "ERROR: Failed to package app. Fix errors and try again."
        exit 1
    fi
    echo ""
fi

if [[ ! -f "$SPL_FILE" ]]; then
    echo "ERROR: .spl file not found at $SPL_FILE"
    exit 1
fi

# Step 4: Run appinspect validation
echo "Running AppInspect validation..."
echo ""

if [[ "$TAG_SET" == "both" ]]; then
    # Run both standard and cloud tag sets
    TEMP_STANDARD=$(mktemp)
    TEMP_CLOUD=$(mktemp)

    trap "rm -f '$TEMP_STANDARD' '$TEMP_CLOUD'" EXIT

    # Standard tag set
    echo "Step 1/2: Running standard tag set..."
    run_appinspect "$SPL_FILE" "standard" "$TEMP_STANDARD"
    COUNTS_STANDARD=$(parse_appinspect_output "$TEMP_STANDARD")
    IFS=":" read -r STANDARD_HIGH STANDARD_CRITICAL STANDARD_WARNING <<<"$COUNTS_STANDARD"

    echo ""
    format_report "$SPL_FILE" "standard" "$STANDARD_HIGH" "$STANDARD_CRITICAL" "$STANDARD_WARNING" "$TEMP_STANDARD"

    # Cloud tag set
    echo "Step 2/2: Running cloud tag set..."
    run_appinspect "$SPL_FILE" "cloud" "$TEMP_CLOUD"
    COUNTS_CLOUD=$(parse_appinspect_output "$TEMP_CLOUD")
    IFS=":" read -r CLOUD_HIGH CLOUD_CRITICAL CLOUD_WARNING <<<"$COUNTS_CLOUD"

    echo ""
    format_report "$SPL_FILE" "cloud" "$CLOUD_HIGH" "$CLOUD_CRITICAL" "$CLOUD_WARNING" "$TEMP_CLOUD"

    # Overall status
    echo "═══════════════════════════════════════════════════════════════"
    if [[ $((STANDARD_HIGH + STANDARD_CRITICAL)) -eq 0 ]]; then
        echo "OVERALL STATUS: PASS (standard tag set clean)"
    else
        echo "OVERALL STATUS: FAIL (standard tag set has issues)"
    fi
    echo "═══════════════════════════════════════════════════════════════"
    echo ""

    # Exit with failure if standard tag set has issues
    [[ $((STANDARD_HIGH + STANDARD_CRITICAL)) -eq 0 ]]
    exit $?

else
    # Run single tag set (standard or cloud)
    TEMP_OUTPUT=$(mktemp)
    trap "rm -f '$TEMP_OUTPUT'" EXIT

    run_appinspect "$SPL_FILE" "$TAG_SET" "$TEMP_OUTPUT"
    COUNTS=$(parse_appinspect_output "$TEMP_OUTPUT")
    IFS=":" read -r HIGH CRITICAL WARNING <<<"$COUNTS"

    format_report "$SPL_FILE" "$TAG_SET" "$HIGH" "$CRITICAL" "$WARNING" "$TEMP_OUTPUT"

    echo "═══════════════════════════════════════════════════════════════"
    if [[ $((HIGH + CRITICAL)) -eq 0 ]]; then
        echo "OVERALL STATUS: PASS"
    else
        echo "OVERALL STATUS: FAIL"
    fi
    echo "═══════════════════════════════════════════════════════════════"
    echo ""

    # Exit with failure if issues found
    [[ $((HIGH + CRITICAL)) -eq 0 ]]
    exit $?
fi
