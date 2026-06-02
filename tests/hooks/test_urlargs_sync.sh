#!/usr/bin/env bash
# Test: .claude/hooks/urlargs-sync.js
#
# Verifies:
#   1. No-op when JS _b= already matches app.conf [install].build.
#   2. Auto-fixes JS when build > _b= (and reports the change).
#   3. Auto-fixes JS when build < _b= (downgrade case).
#   4. Ignores edits to non-app.conf files.
#   5. Always restores both files to original state (idempotent test).

REPO_ROOT=$(git rev-parse --show-toplevel)
source "$REPO_ROOT/tests/hooks/_lib.sh"

start_suite "urlargs-sync"

HOOK="$REPO_ROOT/scripts/hooks/urlargs-sync.js"
APP_CONF="$REPO_ROOT/default/app.conf"
JS_FILE="$REPO_ROOT/appserver/static/whitelist_manager.js"

skip_if_missing "$HOOK" "urlargs-sync hook missing"
skip_if_missing "$APP_CONF" "default/app.conf missing"
skip_if_missing "$JS_FILE" "whitelist_manager.js missing"

# Snapshot both files so we can restore even on test failure
SCRATCH=$(mktemp -d)
cp "$APP_CONF" "$SCRATCH/app.conf.orig"
cp "$JS_FILE" "$SCRATCH/whitelist_manager.js.orig"

restore() {
    cp "$SCRATCH/app.conf.orig" "$APP_CONF"
    cp "$SCRATCH/whitelist_manager.js.orig" "$JS_FILE"
}
trap 'restore; rm -rf "$SCRATCH"' EXIT

# Capture starting build
START_BUILD=$(grep -E '^build\s*=\s*[0-9]+' "$APP_CONF" | head -1 | grep -oE '[0-9]+')
START_URLARGS=$(grep -oE '_b=[0-9]+' "$JS_FILE" | head -1 | grep -oE '[0-9]+')

expect_eq "fixture pre-condition: build == _b=" "$START_BUILD" "$START_URLARGS"

# Case 1: no drift, hook should be silent
out=$(printf '%s' "{\"tool_input\":{\"file_path\":\"$APP_CONF\"}}" | node "$HOOK" 2>&1 || true)
expect_eq "case 1: silent when in sync" "" "$out"

# Case 2: simulate JS drift down by one
sed -i "s/_b=$START_URLARGS/_b=$((START_URLARGS - 1))/" "$JS_FILE"
out=$(printf '%s' "{\"tool_input\":{\"file_path\":\"$APP_CONF\"}}" | node "$HOOK" 2>&1 || true)
expect_contains "case 2: reports the bump" "bumped" "$out"
NEW_URLARGS=$(grep -oE '_b=[0-9]+' "$JS_FILE" | head -1 | grep -oE '[0-9]+')
expect_eq "case 2: JS now matches build" "$START_BUILD" "$NEW_URLARGS"

# Case 3: simulate JS ahead (downgrade case)
sed -i "s/_b=$START_BUILD/_b=$((START_BUILD + 5))/" "$JS_FILE"
out=$(printf '%s' "{\"tool_input\":{\"file_path\":\"$APP_CONF\"}}" | node "$HOOK" 2>&1 || true)
expect_contains "case 3: reports the downgrade" "bumped" "$out"
NEW_URLARGS=$(grep -oE '_b=[0-9]+' "$JS_FILE" | head -1 | grep -oE '[0-9]+')
expect_eq "case 3: JS now matches build (after downgrade)" "$START_BUILD" "$NEW_URLARGS"

# Case 4: non-app.conf file -> hook is a no-op (no JS change)
restore   # bring both back to pristine
out=$(printf '%s' "{\"tool_input\":{\"file_path\":\"$REPO_ROOT/README.md\"}}" | node "$HOOK" 2>&1 || true)
expect_eq "case 4: silent on README edit" "" "$out"
FINAL_URLARGS=$(grep -oE '_b=[0-9]+' "$JS_FILE" | head -1 | grep -oE '[0-9]+')
expect_eq "case 4: JS unchanged after non-app.conf edit" "$START_URLARGS" "$FINAL_URLARGS"

# Case 5: multi-match defensive path — synthesize a 2nd urlArgs line
# in the JS (e.g. simulating a future refactor that ships a second
# require.config block) and confirm the hook warns AND syncs both.
restore
# Inject a duplicate urlArgs line with a stale value below the real one
awk -v stale="$((START_URLARGS - 99))" '
    /urlArgs:.*_b=/ && !done {
        print
        # Append a 2nd urlArgs line right after the existing one
        printf "require.config({ urlArgs: \"_b=%s\" });\n", stale
        done = 1
        next
    }
    { print }
' "$JS_FILE" > "$SCRATCH/wm.dual.js"
cp "$SCRATCH/wm.dual.js" "$JS_FILE"
DUAL_COUNT=$(grep -cE '_b=[0-9]+' "$JS_FILE")
expect_eq "case 5: fixture has 2 _b= occurrences" "2" "$DUAL_COUNT"

out=$(printf '%s' "{\"tool_input\":{\"file_path\":\"$APP_CONF\"}}" | node "$HOOK" 2>&1 || true)
expect_contains "case 5: warns about multiple occurrences" "WARNING" "$out"
expect_contains "case 5: reports occurrence count" "2 occurrence" "$out"

# Both occurrences should now equal the build number
DISTINCT_AFTER=$(grep -oE '_b=[0-9]+' "$JS_FILE" | sort -u | wc -l | tr -d '[:space:]')
expect_eq "case 5: all urlArgs values converged" "1" "$DISTINCT_AFTER"
FINAL_VAL=$(grep -oE '_b=[0-9]+' "$JS_FILE" | head -1 | grep -oE '[0-9]+')
expect_eq "case 5: converged value equals build" "$START_BUILD" "$FINAL_VAL"

finish_suite
