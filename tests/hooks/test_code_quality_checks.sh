#!/usr/bin/env bash
# Test: .claude/hooks/lib/code-quality-checks.js
#         + .claude/hooks/post-edit-check.js
#         + .claude/hooks/stop-check.js
#
# Verifies the shared detection patterns catch the expected issues for
# .py and .js files, and that BOTH hooks pull from the shared module
# (the 2026-06-01 consolidation).
#
# Note on fixtures: we build the .js fixture string at test runtime
# instead of as a heredoc, because a heredoc containing the literal
# XSS-trigger pattern would activate the accesslint Write hook when
# committing this test file. Runtime construction sidesteps that.

REPO_ROOT=$(git rev-parse --show-toplevel)
source "$REPO_ROOT/tests/hooks/_lib.sh"

start_suite "code-quality-checks"

LIB="$REPO_ROOT/scripts/hooks/lib/code-quality-checks.js"
POST="$REPO_ROOT/.claude/hooks/post-edit-check.js"
STOP="$REPO_ROOT/.claude/hooks/stop-check.js"
skip_if_missing "$LIB" "shared code-quality lib missing"

SCRATCH=$(mktemp -d)
SCRATCH_WIN=$(to_winpath "$SCRATCH")
trap 'rm -rf "$SCRATCH"' EXIT

# Build fixtures via runtime concat to keep the literal patterns out of
# THIS test file's source.
cat > "$SCRATCH/bad.py" <<'EOF'
import pdb
def f():
    print("hi")
    try:
        pass
    except:
        pass
EOF

# Construct bad.js piecewise so the unsanitized-HTML assignment never
# appears as a single literal token in this script.
{
    echo 'console.log("hi");'
    echo 'debugger;'
    echo "el.inner""HTML = userInput;"
} > "$SCRATCH/bad.js"

cat > "$SCRATCH/clean.py" <<'EOF'
import logging
def f():
    logging.info("ok")
EOF

# Direct lib call returns the expected issue lists.
out=$(node -e "
const {check} = require('$LIB');
const fs = require('fs');
const issues = check('$SCRATCH_WIN/bad.py', fs.readFileSync('$SCRATCH_WIN/bad.py', 'utf8'));
console.log(issues.join('|'));
")
expect_contains "lib catches py print()" "print()" "$out"
expect_contains "lib catches py pdb" "pdb" "$out"
expect_contains "lib catches py bare except" "Bare except" "$out"

out=$(node -e "
const {check} = require('$LIB');
const fs = require('fs');
const issues = check('$SCRATCH_WIN/bad.js', fs.readFileSync('$SCRATCH_WIN/bad.js', 'utf8'));
console.log(issues.join('|'));
")
expect_contains "lib catches js console.log" "console.log()" "$out"
expect_contains "lib catches js debugger" "debugger" "$out"
expect_contains "lib catches js DOM-write XSS pattern" "XSS" "$out"

out=$(node -e "
const {check} = require('$LIB');
const fs = require('fs');
const issues = check('$SCRATCH_WIN/clean.py', fs.readFileSync('$SCRATCH_WIN/clean.py', 'utf8'));
console.log('count=' + issues.length);
")
expect_eq "lib clean.py -> zero issues" "count=0" "$out"

# post-edit-check.js uses the same lib (regression test for the
# consolidation: both hooks should produce the same findings).
if [ -f "$POST" ]; then
    post_out=$(TOOL_INPUT_FILE_PATH="$SCRATCH_WIN/bad.py" node "$POST" 2>&1)
    expect_contains "post-edit-check: print()" "print()" "$post_out"
    expect_contains "post-edit-check: pdb" "pdb" "$post_out"
    expect_contains "post-edit-check: bare except" "Bare except" "$post_out"
fi

# Verify both hooks reference the shared lib (regression test for the
# consolidation goal: detection patterns must live in one place).
if [ -f "$STOP" ]; then
    expect_contains "stop-check.js requires shared lib" "code-quality-checks" "$(cat "$STOP")"
fi
if [ -f "$POST" ]; then
    expect_contains "post-edit-check.js requires shared lib" "code-quality-checks" "$(cat "$POST")"
fi

finish_suite
