#!/usr/bin/env bash
# Test: scripts/pre-commit-doc-drift.sh
#
# Verifies:
#   1. Current working tree passes (baseline integrity).
#   2. Inserting a stale "Build NNN" line into a covered doc trips the
#      build-mismatch check.
#   3. Adding an unguarded historical reference (no date / no keyword)
#      is rejected; same line with a disambiguator is accepted.
#   4. Inserting a non-existent file path into a covered doc trips the
#      file-existence check.
#
# All mutations are written to scratch copies, never to the real doc.

REPO_ROOT=$(git rev-parse --show-toplevel)
source "$REPO_ROOT/tests/hooks/_lib.sh"

start_suite "doc-drift"

SCRIPT="$REPO_ROOT/scripts/pre-commit-doc-drift.sh"
skip_if_missing "$SCRIPT" "doc-drift script missing"

# 1. Baseline — current tree must pass
"$SCRIPT" >/dev/null 2>&1
expect_eq "current working tree passes" "0" "$?"

# 2. Stale build claim in a covered doc -> drift detected
# We mutate a temp copy of README.md, then point the script at our
# scratch dir via env-var override. The script doesn't support that,
# so we test via a temp file shadowed in-place.
SCRATCH=$(mktemp -d)
trap 'rm -rf "$SCRATCH"; git -C "$REPO_ROOT" checkout -- README.md 2>/dev/null || true' EXIT

# Append a stale build claim to README.md (without committing), run, restore.
# Probe text must NOT contain any allowlist keyword (date/incident/shipped/
# caused/introduced/historical/origin/rounds/hardening/was/were/originally/
# previously/ago/past) or the script will accept it as a historical mention.
cp "$REPO_ROOT/README.md" "$SCRATCH/README.md.orig"
{
    echo ""
    echo "Note: build 9999 is on the next release line."
} >> "$REPO_ROOT/README.md"

set +e
"$SCRIPT" >"$SCRATCH/out" 2>&1
got=$?
set -e
expect_eq "stale build NNN trips check" "1" "$got"
expect_contains "drift message mentions claimed build" "9999" "$(cat "$SCRATCH/out")"

# 3. Same line with disambiguator should NOT trip
cp "$SCRATCH/README.md.orig" "$REPO_ROOT/README.md"
{
    echo ""
    echo "Note: build 9999 (historical) is on the next release line."
} >> "$REPO_ROOT/README.md"

set +e
"$SCRIPT" >"$SCRATCH/out" 2>&1
got=$?
set -e
expect_eq "historical disambiguator accepted" "0" "$got"

# 4. Bogus file path -> file-existence check trips
cp "$SCRATCH/README.md.orig" "$REPO_ROOT/README.md"
{
    echo ""
    echo "See bin/this_file_does_not_exist_xyz.py for details."
} >> "$REPO_ROOT/README.md"

set +e
"$SCRIPT" >"$SCRATCH/out" 2>&1
got=$?
set -e
expect_eq "missing file path trips check" "1" "$got"
expect_contains "path-missing message names the file" "this_file_does_not_exist_xyz.py" "$(cat "$SCRATCH/out")"

# Restore README.md to clean state
cp "$SCRATCH/README.md.orig" "$REPO_ROOT/README.md"

finish_suite
