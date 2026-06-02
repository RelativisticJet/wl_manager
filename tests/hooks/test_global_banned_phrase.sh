#!/usr/bin/env bash
# Test: ~/.claude/hooks/banned-phrase-trigger.js (global hook)
#
# Skips if the global hook isn't installed.
#
# Verifies: each banned phrase in the assistant's last message is
# detected and a flag file is written. Clean replies don't set the flag.

REPO_ROOT=$(git rev-parse --show-toplevel)
source "$REPO_ROOT/tests/hooks/_lib.sh"

start_suite "global banned-phrase-trigger"

HOOK="$HOME/.claude/hooks/banned-phrase-trigger.js"
FLAG="$HOME/.claude/state/banned_phrase_found.flag"
skip_if_missing "$HOOK" "global banned-phrase-trigger hook missing"

SCRATCH=$(mktemp -d)
trap 'rm -rf "$SCRATCH"; rm -f "$FLAG"' EXIT

run_hook_with_assistant_text() {
    local text=$1
    rm -f "$FLAG"
    # Build a minimal transcript JSONL via python (avoids quoting issues)
    python -c "
import json, sys
text = sys.argv[1]
print(json.dumps({'type': 'user', 'message': {'role': 'user', 'content': 'q'}}))
print(json.dumps({
    'type': 'assistant',
    'message': {
        'role': 'assistant',
        'content': [{'type': 'text', 'text': text}],
    },
}))
" "$text" > "$SCRATCH/transcript.jsonl"
    # Use Windows-native path because Node on Windows can't read /tmp/...
    local wpath
    wpath=$(cygpath -m "$SCRATCH/transcript.jsonl" 2>/dev/null || echo "$SCRATCH/transcript.jsonl")
    printf '%s' "{\"transcript_path\":\"$wpath\"}" | node "$HOOK" >/dev/null 2>&1
}

# Clean reply -> no flag
run_hook_with_assistant_text "Verified by running tests/unit/x.py — 47/47 PASS."
if [ -f "$FLAG" ]; then expect_eq "clean reply -> no flag" "no flag" "FLAG SET"; else expect_eq "clean reply -> no flag" "no flag" "no flag"; fi

# Each banned phrase -> flag set
for phrase in \
    "should be fine" \
    "probably passes" \
    "theoretically correct" \
    "i think it's fixed" \
    "i fixed it, you try"; do
    run_hook_with_assistant_text "I did the change. $phrase for now."
    if [ -f "$FLAG" ]; then
        expect_eq "phrase '$phrase' caught" "caught" "caught"
    else
        expect_eq "phrase '$phrase' caught" "caught" "missed"
    fi
done

# Case insensitivity
run_hook_with_assistant_text "SHOULD BE FINE in production"
if [ -f "$FLAG" ]; then
    expect_eq "case-insensitive match" "caught" "caught"
else
    expect_eq "case-insensitive match" "caught" "missed"
fi

finish_suite
