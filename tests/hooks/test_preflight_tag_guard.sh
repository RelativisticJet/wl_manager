#!/usr/bin/env bash
# Test: scripts/preflight-tag.sh + .claude/hooks/preflight-tag-guard.js
#
# Verifies:
#   1. preflight-tag.sh exits 0 when the intended tag matches the four
#      sources of truth (app.conf [launcher].version, app.conf [id].version,
#      app.manifest info.id.version, app.conf [package].id == [id].name).
#   2. preflight-tag.sh exits 1 when any source disagrees with the tag.
#   3. The PreToolUse guard hook:
#       - allows non-tag Bash commands
#       - allows `git tag <semver>` matching current version
#       - blocks `git tag <semver>` for a mismatched version
#       - allows `gh release create <matching>`
#       - blocks `gh release create <mismatched>`
#       - ignores non-Bash tool invocations
#
# Uses python to construct JSON payloads so the test's own bash argv
# doesn't contain the trigger pattern (avoids self-blocking when the
# tests are run via the Claude Code Bash tool — see CASE 5 in
# C:/Users/PC/AppData/Local/Temp/preflight_test.py for the rationale).

REPO_ROOT=$(git rev-parse --show-toplevel)
source "$REPO_ROOT/tests/hooks/_lib.sh"

start_suite "preflight-tag-guard"

PREFLIGHT="$REPO_ROOT/scripts/preflight-tag.sh"
HOOK="$REPO_ROOT/scripts/hooks/preflight-tag-guard.js"
skip_if_missing "$PREFLIGHT" "preflight script missing"
skip_if_missing "$HOOK" "preflight-tag-guard hook missing"
HOOK_WIN=$(to_winpath "$HOOK")

# Discover the current app.conf version (the one tag-cuts must agree with).
CURRENT_VER=$(awk -F= '/^\[launcher\]/{flag=1; next} /^\[/{flag=0} flag && /^version/{gsub(/[[:space:]]/,""); print $2}' "$REPO_ROOT/default/app.conf")
[ -z "$CURRENT_VER" ] && { echo "  could not read current version from app.conf"; exit 1; }

CURRENT_TAG="v$CURRENT_VER"
DRIFT_TAG="v0.0.0-drift"

# 1. Direct script — matching tag
set +e
bash "$PREFLIGHT" "$CURRENT_TAG" >/dev/null 2>&1
got=$?
set -e
expect_eq "preflight-tag.sh accepts matching tag $CURRENT_TAG" "0" "$got"

# 2. Direct script — drift
set +e
bash "$PREFLIGHT" "$DRIFT_TAG" >/dev/null 2>&1
got=$?
set -e
expect_eq "preflight-tag.sh rejects drift tag $DRIFT_TAG" "1" "$got"

# 3. Hook — pipe JSON via python helper (keeps the trigger substring
# out of the outer bash invocation's argv so this test doesn't block
# itself when run inside Claude Code).
run_hook() {
    local cmd=$1
    local tool=${2:-Bash}
    python -c "
import json, subprocess, sys
payload = json.dumps({'tool_name': sys.argv[1], 'tool_input': {'command': sys.argv[2]}})
p = subprocess.run(['node', sys.argv[3]], input=payload, capture_output=True, text=True)
sys.exit(p.returncode)
" "$tool" "$cmd" "$HOOK_WIN"
}

# Use a constructed string to avoid the substring appearing in this
# script's argv. The hook reads its OWN stdin, not our argv, but the
# script's content is read from disk by bash without splitting into argv
# tokens for the surrounding tool call.
GIT="g""it"
TAG="t""ag"
GH="g""h release create"

set +e
run_hook "git status"; got=$?
set -e
expect_eq "hook allows non-tag Bash command" "0" "$got"

set +e
run_hook "$GIT $TAG $CURRENT_TAG"; got=$?
set -e
expect_eq "hook allows $TAG matching current" "0" "$got"

set +e
run_hook "$GIT $TAG $DRIFT_TAG"; got=$?
set -e
expect_eq "hook blocks $TAG drift" "2" "$got"

set +e
run_hook "$GIT $TAG -a $DRIFT_TAG -m 'note'"; got=$?
set -e
expect_eq "hook blocks annotated $TAG drift" "2" "$got"

set +e
run_hook "$GIT $TAG my-feature-branch"; got=$?
set -e
expect_eq "hook ignores non-semver tag names" "0" "$got"

set +e
run_hook "$GH $CURRENT_TAG --notes 'x'"; got=$?
set -e
expect_eq "hook allows $GH matching" "0" "$got"

set +e
run_hook "$GH $DRIFT_TAG --notes 'x'"; got=$?
set -e
expect_eq "hook blocks $GH drift" "2" "$got"

set +e
run_hook "$GIT $TAG $DRIFT_TAG" "Edit"; got=$?
set -e
expect_eq "hook ignores non-Bash tool" "0" "$got"

finish_suite
