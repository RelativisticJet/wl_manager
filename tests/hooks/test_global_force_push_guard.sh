#!/usr/bin/env bash
# Test: ~/.claude/hooks/force-push-guard.js (global hook)
#
# Skips if the global hook isn't installed (e.g. fresh checkout by
# someone who hasn't run the global Claude Code config bootstrap).
#
# Verifies the regex pattern blocks destructive force-pushes and
# branch-deletes while allowing --force-with-lease and regular pushes.

REPO_ROOT=$(git rev-parse --show-toplevel)
source "$REPO_ROOT/tests/hooks/_lib.sh"

start_suite "global force-push-guard"

HOOK="$HOME/.claude/hooks/force-push-guard.js"
skip_if_missing "$HOOK" "global force-push-guard hook missing"
HOOK_WIN=$(to_winpath "$HOOK")

# Wrapper: pipe a JSON payload via python to avoid the literal
# trigger pattern appearing in this script's outer Bash argv.
run_hook() {
    local cmd=$1 tool=${2:-Bash}
    python -c "
import json, subprocess, sys
payload = json.dumps({'tool_name': sys.argv[1], 'tool_input': {'command': sys.argv[2]}})
p = subprocess.run(['node', sys.argv[3]], input=payload, capture_output=True, text=True)
sys.exit(p.returncode)
" "$tool" "$cmd" "$HOOK_WIN"
}

# Constructed substrings — same pattern as test_preflight_tag_guard.sh
PUSH="g""it push"
FORCE="--""force"

# Allow cases
set +e; run_hook "$PUSH origin main"; got=$?; set -e
expect_eq "plain push allowed" "0" "$got"

set +e; run_hook "$PUSH -u origin feature"; got=$?; set -e
expect_eq "push -u allowed" "0" "$got"

set +e; run_hook "$PUSH --force-with-lease origin main"; got=$?; set -e
expect_eq "force-with-lease allowed" "0" "$got"

set +e; run_hook "ls -la"; got=$?; set -e
expect_eq "non-push Bash allowed" "0" "$got"

# Block cases
set +e; run_hook "$PUSH $FORCE origin main"; got=$?; set -e
expect_eq "--force blocked" "2" "$got"

set +e; run_hook "$PUSH -f origin main"; got=$?; set -e
expect_eq "-f blocked" "2" "$got"

set +e; run_hook "$PUSH origin main $FORCE"; got=$?; set -e
expect_eq "--force at end blocked" "2" "$got"

set +e; run_hook "$PUSH origin :feature"; got=$?; set -e
expect_eq "branch-delete shorthand blocked" "2" "$got"

set +e; run_hook "$PUSH --delete origin feature"; got=$?; set -e
expect_eq "--delete blocked" "2" "$got"

# Non-Bash tool — ignored
set +e; run_hook "$PUSH $FORCE origin main" "Edit"; got=$?; set -e
expect_eq "non-Bash tool ignored" "0" "$got"

# False-positive guard: commit message body containing the trigger
# string must NOT block. This regression was introduced when the
# regex scanned the entire argv without honoring quoting; the fix
# only inspects the first shell sub-command.
COMMIT="g""it commit"
set +e; run_hook "$COMMIT -m 'body mentions $PUSH $FORCE as a string'"; got=$?; set -e
expect_eq "commit-message body with trigger string allowed" "0" "$got"

# Embedded interpreters: python -c, bash -c, node -e with a string
# argument that contains the trigger pattern must NOT block.
set +e; run_hook "python -c 'subprocess.run([\"$PUSH\", \"$FORCE\"])'"; got=$?; set -e
expect_eq "python -c with trigger in script string allowed" "0" "$got"

set +e; run_hook "echo \"$PUSH $FORCE is bad\""; got=$?; set -e
expect_eq "echo with trigger in argument allowed" "0" "$got"

# Env-var prefix should NOT defeat the guard
set +e; run_hook "FOO=bar BAZ=1 $PUSH $FORCE origin main"; got=$?; set -e
expect_eq "env-var prefix doesn't defeat guard" "2" "$got"

finish_suite
