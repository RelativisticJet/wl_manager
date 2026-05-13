#!/usr/bin/env bash
#
# ═══════════════════════════════════════════════════════════════════════
# AppInspect Validation Wrapper — Docker-based, JSON-parsed
# ═══════════════════════════════════════════════════════════════════════
#
# This script:
#   1. Builds the .spl file (via package.sh) if missing
#   2. Builds the wl-appinspect Docker image (one-time, ~30s) if missing
#   3. Runs splunk-appinspect inside the container with the chosen profile
#   4. Parses JSON output and reports counts per result class
#   5. Exits non-zero if any error/failure/future_failure is found
#
# Usage:
#   bash scripts/verify_appinspect.sh                # default: both profiles
#   bash scripts/verify_appinspect.sh --standalone   # on-prem (Standalone) cert
#   bash scripts/verify_appinspect.sh --cloud        # Splunk Cloud cert
#   bash scripts/verify_appinspect.sh --both         # both (default)
#
# Tag-set names:
#   "standalone" maps to the local CLI's default (no included-tags filter,
#   ~249 checks). This is the AppInspect Cloud API's
#   `splunk_platform_standalone` profile — the local CLI just doesn't
#   expose that exact tag name.
#
# Exit codes:
#   0  = All checks passed (0 errors + 0 failures + 0 future_failures)
#   1  = One or more errors/failures/future_failures found
#   2  = Setup error (Docker not running, .spl build failed, etc.)
#
# Migration note (2026-05-14):
#   Replaced previous native-binary path that broke on Python 3.14
#   (no pre-built wheels for pillow/lxml transitive deps). The Docker
#   image at .planning/appinspect/Dockerfile pins Python 3.11 + libmagic1
#   and works portably across dev machines.

set -euo pipefail

# ── Configuration ─────────────────────────────────────────────────────
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
APP_NAME="wl_manager"
DIST_DIR="$APP_DIR/dist"
DOCKER_IMAGE="wl-appinspect:latest"
DOCKERFILE_DIR="$APP_DIR/.planning/appinspect"
OUTPUT_DIR="$APP_DIR/.planning/appinspect"

# ── Parse arguments ───────────────────────────────────────────────────
PROFILES="both"
if [[ $# -gt 0 ]]; then
    case "$1" in
        --standalone|standalone) PROFILES="standalone" ;;
        --cloud|cloud)           PROFILES="cloud" ;;
        --both|both)             PROFILES="both" ;;
        # Back-compat with older --standard flag (alias for --standalone).
        --standard|standard)     PROFILES="standalone" ;;
        -h|--help)
            sed -n '4,32p' "$0"
            exit 0
            ;;
        *)
            echo "ERROR: unknown argument: $1"
            echo "Usage: $0 [--standalone | --cloud | --both]"
            exit 2
            ;;
    esac
fi

# ── Helpers ───────────────────────────────────────────────────────────
require_docker() {
    if ! command -v docker &>/dev/null; then
        echo "ERROR: docker is not on PATH. Install Docker Desktop or equivalent."
        exit 2
    fi
    if ! docker info &>/dev/null; then
        echo "ERROR: docker daemon is not responding."
        echo "  Start Docker Desktop (or 'systemctl start docker') and retry."
        exit 2
    fi
}

ensure_image() {
    if docker image inspect "$DOCKER_IMAGE" &>/dev/null; then
        return 0
    fi
    echo "Building Docker image $DOCKER_IMAGE (one-time, ~30s)..."
    MSYS_NO_PATHCONV=1 docker build -t "$DOCKER_IMAGE" "$DOCKERFILE_DIR"
    echo "  Image ready."
}

build_spl_if_missing() {
    if [[ ! -f "$SPL_FILE" ]]; then
        echo "Building .spl file via scripts/package.sh..."
        if ! bash "$APP_DIR/scripts/package.sh"; then
            echo "ERROR: scripts/package.sh failed. Fix errors above and retry."
            exit 2
        fi
    fi
    if [[ ! -f "$SPL_FILE" ]]; then
        echo "ERROR: .spl file not found at $SPL_FILE after package.sh"
        exit 2
    fi
}

run_profile() {
    # $1: profile name ("standalone" or "cloud")
    # $2: extra args to pass to splunk-appinspect (e.g. "--included-tags cloud")
    local profile="$1"
    local extra_args="$2"
    local out_file="$OUTPUT_DIR/appinspect-${profile}.json"

    echo ""
    echo "── Running profile: $profile ──"
    # shellcheck disable=SC2086
    MSYS_NO_PATHCONV=1 docker run --rm \
        -v "$DIST_DIR:/spl:ro" \
        -v "$OUTPUT_DIR:/out" \
        "$DOCKER_IMAGE" inspect "/spl/$(basename "$SPL_FILE")" \
            --mode test --data-format json \
            --output-file "/out/appinspect-${profile}.json" \
            $extra_args 2>&1 | tail -12
    echo "Report: $out_file"
}

parse_and_report() {
    # $1: profile name; emits per-class counts, returns 1 if any
    # error/failure/future_failure is found.
    local profile="$1"
    local out_file="$OUTPUT_DIR/appinspect-${profile}.json"
    if [[ ! -f "$out_file" ]]; then
        echo "ERROR: report file missing: $out_file"
        return 1
    fi
    # Use the same Docker image's Python to parse — guarantees the script
    # works even if the host has no python3 (or a too-new Python like 3.14).
    MSYS_NO_PATHCONV=1 docker run --rm \
        -v "$OUTPUT_DIR:/out:ro" \
        --entrypoint python \
        "$DOCKER_IMAGE" -c "
import json,sys
d = json.load(open('/out/appinspect-${profile}.json'))
s = d.get('summary', {})
err  = s.get('error', 0)
fail = s.get('failure', 0)
ff   = s.get('future_failure', 0)
warn = s.get('warning', 0)
ok   = s.get('success', 0)
na   = s.get('not_applicable', 0)
sk   = s.get('skipped', 0)
print('  errors:         {}'.format(err))
print('  failures:       {}'.format(fail))
print('  future_failures:{}'.format(ff))
print('  warnings:       {}'.format(warn))
print('  success:        {}'.format(ok))
print('  not_applicable: {}'.format(na))
print('  skipped:        {}'.format(sk))
blocking = err + fail + ff
sys.exit(1 if blocking > 0 else 0)
"
}

# ── Main ──────────────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════════════════"
echo "  AppInspect Validation (profile: $PROFILES)"
echo "═══════════════════════════════════════════════════════════════════"

VERSION=$(grep "^version" "$APP_DIR/default/app.conf" | head -1 | cut -d= -f2 | tr -d ' ')
SPL_FILE="$DIST_DIR/${APP_NAME}-${VERSION}.spl"

require_docker
ensure_image
mkdir -p "$OUTPUT_DIR"
build_spl_if_missing
echo "  .spl: $SPL_FILE"

OVERALL_RC=0

run_one() {
    # $1: profile name; $2: extra appinspect args
    run_profile "$1" "$2"
    echo ""
    echo "Summary ($1):"
    if ! parse_and_report "$1"; then
        OVERALL_RC=1
        echo "  Status: FAIL (one or more error/failure/future_failure)"
    else
        echo "  Status: PASS"
    fi
}

if [[ "$PROFILES" == "standalone" || "$PROFILES" == "both" ]]; then
    run_one "standalone" ""
fi

if [[ "$PROFILES" == "cloud" || "$PROFILES" == "both" ]]; then
    run_one "cloud" "--included-tags cloud"
fi

echo ""
if [[ "$OVERALL_RC" -eq 0 ]]; then
    echo "AppInspect: PASS (no errors, failures, or future_failures)"
else
    echo "AppInspect: FAIL — see the per-profile JSON reports in"
    echo "  $OUTPUT_DIR for details."
fi
exit "$OVERALL_RC"
