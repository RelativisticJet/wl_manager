#!/usr/bin/env bash
# Hook unit-test runner.
#
# Discovers all tests/hooks/test_*.sh files, runs each ONCE in a fresh
# bash subshell, aggregates pass/fail. Returns non-zero if any suite
# failed; treats SKIPPED as success.
#
# Usage:
#   bash tests/hooks/run.sh
#   make hook-tests

set -eu

REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
cd "$REPO_ROOT"

TESTS=$(ls -1 tests/hooks/test_*.sh 2>/dev/null || true)
if [ -z "$TESTS" ]; then
    echo "tests/hooks/run.sh: no test_*.sh files found"
    exit 0
fi

PASS=0
FAIL=0
SKIPPED=0
FAILED_SUITES=""

for t in $TESTS; do
    # Run once, capture both exit code and output. Double-running was
    # a bug — tests with side effects (like urlargs-sync's file mutate-
    # and-restore) would fire twice and could leave the tree dirty if
    # interrupted between runs.
    set +e
    out=$(bash "$t" 2>&1)
    rc=$?
    set -e
    echo "$out"
    if [ "$rc" -ne 0 ]; then
        FAIL=$((FAIL + 1))
        FAILED_SUITES="$FAILED_SUITES $(basename "$t")"
    else
        if printf '%s' "$out" | grep -q 'SKIPPED'; then
            SKIPPED=$((SKIPPED + 1))
        else
            PASS=$((PASS + 1))
        fi
    fi
done

echo ""
echo "════════════════════════════════════════════════════════════════"
echo "  Hook test runner: $PASS passed, $FAIL failed, $SKIPPED skipped"
if [ "$FAIL" -gt 0 ]; then
    echo "  Failed suites:$FAILED_SUITES"
    echo "════════════════════════════════════════════════════════════════"
    exit 1
fi
echo "════════════════════════════════════════════════════════════════"
exit 0
