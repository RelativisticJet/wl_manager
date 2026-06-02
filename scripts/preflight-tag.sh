#!/usr/bin/env bash
# Version-tag consistency pre-flight (RELEASE_CHECKLIST.md §3.5).
#
# Verifies that the four sources-of-truth for the app version agree
# with the intended tag BEFORE `git tag` / `gh release create` runs.
#
# Sources checked:
#   1. default/app.conf [launcher].version
#   2. default/app.conf [id].version
#   3. app.manifest info.id.version
#   4. default/app.conf [package].id == [id].name  (AppInspect 4.2.0
#      check_for_valid_package_id)
#
# Usage:
#   scripts/preflight-tag.sh <intended-tag>      # e.g. v1.0.1
#   scripts/preflight-tag.sh                     # uses $INTENDED_TAG env var
#
# Exit codes:
#   0  -> all four sources match the intended version (leading `v` stripped)
#   1  -> drift detected (script prints what)
#   2  -> usage error (no tag supplied)
#
# This file is the canonical implementation of §3.5. The release-tag
# PreToolUse guard at .claude/hooks/preflight-tag-guard.js invokes
# this script — if you change the check logic, update §3.5 too.

set -eu

INTENDED_TAG="${1:-${INTENDED_TAG:-}}"
if [ -z "${INTENDED_TAG}" ]; then
    echo "preflight-tag: usage: $0 <intended-tag>  (e.g. v1.0.1)" >&2
    exit 2
fi

REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
cd "$REPO_ROOT"

INTENDED_VERSION="${INTENDED_TAG#v}"

LAUNCHER_VER=$(awk -F= '/^\[launcher\]/{flag=1; next} /^\[/{flag=0} flag && /^version/{gsub(/[[:space:]]/,""); print $2}' default/app.conf)
ID_VER=$(awk -F= '/^\[id\]/{flag=1; next} /^\[/{flag=0} flag && /^version/{gsub(/[[:space:]]/,""); print $2}' default/app.conf)
ID_NAME=$(awk -F= '/^\[id\]/{flag=1; next} /^\[/{flag=0} flag && /^name/{gsub(/[[:space:]]/,""); print $2}' default/app.conf)
PKG_ID=$(awk -F= '/^\[package\]/{flag=1; next} /^\[/{flag=0} flag && /^id/{gsub(/[[:space:]]/,""); print $2}' default/app.conf)

if command -v python3 >/dev/null 2>&1; then
    MANIFEST_VER=$(python3 -c "import json; print(json.load(open('app.manifest'))['info']['id']['version'])")
elif command -v python >/dev/null 2>&1; then
    MANIFEST_VER=$(python -c "import json; print(json.load(open('app.manifest'))['info']['id']['version'])")
else
    # Last-resort grep — works because app.manifest is hand-edited JSON
    # with one-version-field-per-line.
    MANIFEST_VER=$(grep -A2 '"id"' app.manifest | grep '"version"' | head -1 | sed -E 's/.*"version"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/')
fi

FAIL=0

if [ "$LAUNCHER_VER" != "$INTENDED_VERSION" ] || [ "$ID_VER" != "$INTENDED_VERSION" ]; then
    echo "VERSION DRIFT: tag=$INTENDED_TAG app.conf[launcher]=$LAUNCHER_VER app.conf[id]=$ID_VER" >&2
    echo "Fix app.conf before cutting the tag." >&2
    FAIL=1
fi

if [ "$MANIFEST_VER" != "$INTENDED_VERSION" ]; then
    echo "VERSION DRIFT: tag=$INTENDED_TAG app.manifest.info.id.version=$MANIFEST_VER" >&2
    echo "AppInspect's check_version_is_valid_semver requires this to match app.conf." >&2
    echo "Fix app.manifest before cutting the tag." >&2
    FAIL=1
fi

if [ "$ID_NAME" != "$PKG_ID" ]; then
    echo "ID DRIFT: app.conf[id].name=$ID_NAME app.conf[package].id=$PKG_ID" >&2
    echo "AppInspect 4.2.0 (check_for_valid_package_id) requires these to match." >&2
    FAIL=1
fi

if [ "$FAIL" -ne 0 ]; then
    exit 1
fi

echo "preflight-tag: OK ($INTENDED_TAG; launcher=$LAUNCHER_VER, id=$ID_VER, manifest=$MANIFEST_VER, package.id=$PKG_ID)"
exit 0
