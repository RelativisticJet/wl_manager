#!/usr/bin/env bash
# Test: scripts/install-hooks.sh
#
# Verifies the bootstrap script:
#   1. Writes .claude/settings.json from the template on a fresh tree.
#   2. Substitutes the hardcoded c:/Users/PC/wl_manager prefix with the
#      current checkout path.
#   3. Is idempotent — re-running on the same checkout is a silent
#      no-op (does NOT exit non-zero or overwrite).
#   4. Refuses to overwrite a settings.json that points at a different
#      checkout, unless --force is supplied.
#   5. --force overwrites cleanly.
#
# Runs against a temp REPO so it doesn't disturb the developer's real
# .claude/settings.json.

REPO_ROOT=$(git rev-parse --show-toplevel)
source "$REPO_ROOT/tests/hooks/_lib.sh"

start_suite "install-hooks"

SCRIPT="$REPO_ROOT/scripts/install-hooks.sh"
TEMPLATE="$REPO_ROOT/.claude/settings.example.json"
skip_if_missing "$SCRIPT" "install-hooks.sh missing"
skip_if_missing "$TEMPLATE" "settings.example.json missing"

# Build an isolated fake repo so we don't touch the real .claude/.
SCRATCH=$(mktemp -d)
trap 'rm -rf "$SCRATCH"' EXIT
mkdir -p "$SCRATCH/.claude" "$SCRATCH/scripts"
cp "$TEMPLATE" "$SCRATCH/.claude/settings.example.json"
cp "$SCRIPT" "$SCRATCH/scripts/install-hooks.sh"
(
    cd "$SCRATCH"
    git init -q
    git config user.email "test@example.com"
    git config user.name "test"
) >/dev/null

# Pre-resolve the path form the script will write (cygpath -m on
# Windows gives the same Windows-form `C:/...` that
# `git rev-parse --show-toplevel` returns in Git Bash).
SCRATCH_WIN=$(to_winpath "$SCRATCH")

# ── 1. Fresh install ───────────────────────────────────────────────
(cd "$SCRATCH" && bash scripts/install-hooks.sh) >/dev/null 2>&1
got=$?
expect_eq "fresh install exits 0" "0" "$got"
expect_eq "settings.json written" "yes" "$([ -f "$SCRATCH/.claude/settings.json" ] && echo yes || echo no)"

# ── 2. Path substitution applied ───────────────────────────────────
expect_contains "settings.json contains checkout path" "$SCRATCH_WIN" "$(cat "$SCRATCH/.claude/settings.json")"
expect_not_contains "hardcoded c:/Users/PC/wl_manager scrubbed" "c:/Users/PC/wl_manager" "$(cat "$SCRATCH/.claude/settings.json")"

# ── 3. Idempotent re-run ───────────────────────────────────────────
out=$(cd "$SCRATCH" && bash scripts/install-hooks.sh 2>&1)
got=$?
expect_eq "re-run exits 0" "0" "$got"
expect_contains "re-run reports 'already configured'" "already configured" "$out"

# ── 4. Refuse to overwrite divergent settings ──────────────────────
# Simulate a different-checkout settings.json by replacing the path
# in-place. Use a sed expression that the script's grep won't match.
sed -i "s#$SCRATCH_WIN#/tmp/some-other-checkout#g" "$SCRATCH/.claude/settings.json"
set +e
out=$(cd "$SCRATCH" && bash scripts/install-hooks.sh 2>&1)
got=$?
set -e
expect_eq "divergent settings without --force exits 2" "2" "$got"
expect_contains "diagnostic mentions different checkout" "different checkout" "$out"

# ── 5. --force overwrites cleanly ──────────────────────────────────
(cd "$SCRATCH" && bash scripts/install-hooks.sh --force) >/dev/null 2>&1
got=$?
expect_eq "--force exits 0" "0" "$got"
expect_contains "after --force, settings.json points at scratch checkout" "$SCRATCH_WIN" "$(cat "$SCRATCH/.claude/settings.json")"
expect_not_contains "after --force, old prefix scrubbed" "/tmp/some-other-checkout" "$(cat "$SCRATCH/.claude/settings.json")"

# ── 6. Missing template -> exit 1 ──────────────────────────────────
rm "$SCRATCH/.claude/settings.example.json"
set +e
out=$(cd "$SCRATCH" && bash scripts/install-hooks.sh 2>&1)
got=$?
set -e
expect_eq "missing template exits 1" "1" "$got"
expect_contains "diagnostic mentions missing template" "not found" "$out"

finish_suite
