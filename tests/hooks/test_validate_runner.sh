#!/usr/bin/env bash
# Test: .claude/hooks/validate-runner.js
#
# Verifies the hook fires on the right file types (default/*.conf,
# app.manifest, default/data/ui/views|nav/*.xml) and skips other
# extensions (.py, .js, .md, .csv).

REPO_ROOT=$(git rev-parse --show-toplevel)
source "$REPO_ROOT/tests/hooks/_lib.sh"

start_suite "validate-runner"

HOOK="$REPO_ROOT/scripts/hooks/validate-runner.js"
skip_if_missing "$HOOK" "validate-runner hook missing"
skip_if_missing "$REPO_ROOT/scripts/validate.sh" "scripts/validate.sh missing"

# Wrapper: returns 0 if hook produced output (ran), 1 if silent (skipped).
ran_for() {
    local fp=$1
    local out
    out=$(printf '%s' "{\"tool_input\":{\"file_path\":\"$fp\"}}" \
        | node "$HOOK" 2>&1)
    [ -n "$out" ] && return 0 || return 1
}

# Skip cases — should be silent
expect_exit "py edit skipped"     1 ran_for "$REPO_ROOT/bin/wl_handler.py"
expect_exit "js edit skipped"     1 ran_for "$REPO_ROOT/appserver/static/whitelist_manager.js"
expect_exit "md edit skipped"     1 ran_for "$REPO_ROOT/README.md"
expect_exit "csv edit skipped"    1 ran_for "$REPO_ROOT/lookups/rule_csv_map.csv"
expect_exit "empty path skipped"  1 ran_for ""

# Run cases — should produce output
expect_exit "app.conf triggers"      0 ran_for "$REPO_ROOT/default/app.conf"
expect_exit "restmap.conf triggers"  0 ran_for "$REPO_ROOT/default/restmap.conf"
expect_exit "app.manifest triggers"  0 ran_for "$REPO_ROOT/app.manifest"

# Verify the PASS line in stdout when validate.sh passes
out=$(printf '%s' "{\"tool_input\":{\"file_path\":\"$REPO_ROOT/default/app.conf\"}}" \
    | node "$HOOK" 2>&1)
expect_contains "PASS summary mentioned" "PASS" "$out"
expect_contains "summary names the triggering file" "app.conf" "$out"

finish_suite
