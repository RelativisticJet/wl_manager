#!/usr/bin/env bash
# Shared test helpers for tests/hooks/test_*.sh.
#
# Conventions:
#   - Each test script sources this file at the top, calls start_suite,
#     runs a series of expect_* checks, ends with finish_suite.
#   - finish_suite prints a summary line and `exit 1` if any check failed.
#   - The test runner (tests/hooks/run.sh) aggregates per-suite results.
#
# Output protocol:
#   - Each PASS prints `  PASS: <desc>`.
#   - Each FAIL prints `  FAIL: <desc>` followed by a diff/diagnostic.
#   - finish_suite prints `<suite-name>: <pass>/<total> PASS` or
#     `<suite-name>: <pass>/<total> PASS (FAIL)`.

set -eu

_SUITE_NAME=""
_PASS=0
_FAIL=0

start_suite() {
    _SUITE_NAME="$1"
    _PASS=0
    _FAIL=0
    echo ""
    echo "── $_SUITE_NAME ──"
}

expect_eq() {
    # expect_eq <description> <expected> <got>
    local desc=$1 want=$2 got=$3
    if [ "$want" = "$got" ]; then
        _PASS=$((_PASS + 1))
        echo "  PASS: $desc"
    else
        _FAIL=$((_FAIL + 1))
        echo "  FAIL: $desc"
        echo "    want: $want"
        echo "    got : $got"
    fi
}

expect_exit() {
    # expect_exit <description> <expected_code> <cmd...>
    local desc=$1 want=$2
    shift 2
    local got
    "$@" >/dev/null 2>&1 && got=0 || got=$?
    expect_eq "$desc" "$want" "$got"
}

expect_contains() {
    # expect_contains <description> <needle> <haystack>
    local desc=$1 needle=$2 hay=$3
    case "$hay" in
        *"$needle"*)
            _PASS=$((_PASS + 1))
            echo "  PASS: $desc"
            ;;
        *)
            _FAIL=$((_FAIL + 1))
            echo "  FAIL: $desc"
            echo "    needle: $needle"
            echo "    got   : $hay"
            ;;
    esac
}

expect_not_contains() {
    # expect_not_contains <description> <needle> <haystack>
    local desc=$1 needle=$2 hay=$3
    case "$hay" in
        *"$needle"*)
            _FAIL=$((_FAIL + 1))
            echo "  FAIL: $desc (unwanted needle found)"
            echo "    needle: $needle"
            ;;
        *)
            _PASS=$((_PASS + 1))
            echo "  PASS: $desc"
            ;;
    esac
}

to_winpath() {
    # Convert a POSIX-form path (e.g. /tmp/x or /c/Users/x) to a form
    # Node-on-Windows can resolve (e.g. C:/tmp/x or C:/Users/x). On
    # non-Windows systems this is a no-op. Safe for paths that already
    # look like C:/... too.
    local p=$1
    if command -v cygpath >/dev/null 2>&1; then
        cygpath -m "$p"
    else
        printf '%s' "$p"
    fi
}

skip_if_missing() {
    # skip_if_missing <path> <reason>  -> exits the whole suite with PASS=skipped
    local target=$1 reason=$2
    if [ ! -e "$target" ]; then
        echo "  SKIP: $reason ($target missing)"
        # Treat skip as success for the runner; print a sentinel.
        echo "$_SUITE_NAME: SKIPPED"
        exit 0
    fi
}

finish_suite() {
    local total=$((_PASS + _FAIL))
    if [ "$_FAIL" -eq 0 ]; then
        echo "$_SUITE_NAME: $_PASS/$total PASS"
        exit 0
    fi
    echo "$_SUITE_NAME: $_PASS/$total PASS ($_FAIL FAIL)"
    exit 1
}
