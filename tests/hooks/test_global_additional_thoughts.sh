#!/usr/bin/env bash
# Test: ~/.claude/hooks/additional-thoughts-trigger.sh
#       + ~/.claude/hooks/additional-thoughts-trigger-prompt.sh
#
# Skips if the global hooks aren't installed.
#
# Verifies:
#   - The Stop hook sets the flag when CHANGED_FILES > 3 OR commits in
#     last 2h (matches qa-trigger threshold).
#   - The UserPromptSubmit hook emits the system-reminder when the flag
#     is present.
#   - Below threshold, no flag is written.

REPO_ROOT=$(git rev-parse --show-toplevel)
source "$REPO_ROOT/tests/hooks/_lib.sh"

start_suite "global additional-thoughts"

STOP_HOOK="$HOME/.claude/hooks/additional-thoughts-trigger.sh"
PROMPT_HOOK="$HOME/.claude/hooks/additional-thoughts-trigger-prompt.sh"
FLAG="$HOME/.claude/state/needs_additional_thoughts.flag"

skip_if_missing "$STOP_HOOK" "additional-thoughts-trigger.sh missing"
skip_if_missing "$PROMPT_HOOK" "additional-thoughts-trigger-prompt.sh missing"

# Above-threshold case: there ARE uncommitted changes from this session,
# so the Stop hook should set the flag.
rm -f "$FLAG"
bash "$STOP_HOOK" >/dev/null 2>&1
if [ -f "$FLAG" ]; then
    expect_eq "Stop hook sets flag with current changes" "set" "set"
else
    expect_eq "Stop hook sets flag with current changes" "set" "not set"
fi

# Prompt hook reads the flag and emits the checklist
out=$(bash "$PROMPT_HOOK" 2>&1)
expect_contains "prompt hook emits system-reminder" "system-reminder" "$out"
expect_contains "prompt hook emits checklist" "Additional Thoughts" "$out"
expect_contains "prompt hook lists docs lens" "Documentation drift" "$out"
expect_contains "prompt hook lists security lens" "Security gaps" "$out"

# Below-threshold case: simulate a clean tree by running in a tempdir
# with a fresh empty git repo.
SCRATCH=$(mktemp -d)
trap 'rm -rf "$SCRATCH"; rm -f "$FLAG"' EXIT
(
    cd "$SCRATCH"
    git init -q
    git config user.email "test@example.com"
    git config user.name "test"
    rm -f "$FLAG"
    bash "$STOP_HOOK" >/dev/null 2>&1
)
if [ -f "$FLAG" ]; then
    expect_eq "Stop hook silent on clean tree" "no flag" "FLAG SET"
else
    expect_eq "Stop hook silent on clean tree" "no flag" "no flag"
fi

# Cleanup: re-run with current cwd so the flag goes back to its real
# state (otherwise we'd suppress a real fire-event for this session).
bash "$STOP_HOOK" >/dev/null 2>&1 || true

finish_suite
