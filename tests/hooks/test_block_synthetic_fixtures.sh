#!/usr/bin/env bash
# Test: scripts/hooks/block-synthetic-fixtures.js
#
# Backfilled 2026-06-02 — the hook has been in place since 2026-04-23
# but had no unit test (called out as Item 2 in the Additional Thoughts
# of the 2026-06-02 hook-system rollout). Covers the four behavior
# classes the hook enforces:
#
#   1. Write/Edit to BLOCKED_FILE_PATTERNS (queue JSON, FIM baseline,
#      KV-state files) → block (exit 2).
#   2. Write/Edit under tests/unit/ → allow (UNIT_TEST_EXCEPTION).
#   3. Bash with WRITE_INDICATORS pointing at a blocked path → block.
#   4. Bash with `# JUSTIFIED: <reason>` marker → allow (the override
#      documented in CLAUDE.md "Synthetic Fixtures — Banned").
#   5. Bash GET against a KV collection → allow (read-only).
#   6. Bash POST/PUT/DELETE against a KV collection → block.

REPO_ROOT=$(git rev-parse --show-toplevel)
source "$REPO_ROOT/tests/hooks/_lib.sh"

start_suite "block-synthetic-fixtures"

HOOK="$REPO_ROOT/scripts/hooks/block-synthetic-fixtures.js"
skip_if_missing "$HOOK" "block-synthetic-fixtures hook missing"

# Wrapper: invoke hook via env-var contract (the contract this hook
# actually uses — TOOL_NAME + TOOL_INPUT_*). Returns exit code.
run_write() {
    local fpath=$1
    TOOL_NAME=Write TOOL_INPUT_file_path="$fpath" \
        node "$HOOK" >/dev/null 2>&1
}

run_bash() {
    local cmd=$1
    TOOL_NAME=Bash TOOL_INPUT_command="$cmd" \
        node "$HOOK" >/dev/null 2>&1
}

# ── 1. Write blocks on protected paths ──────────────────────────────
expect_exit "write to _approval_queue.json blocked" \
    2 run_write "lookups/_versions/_approval_queue.json"

expect_exit "write to .fim_baseline.json blocked" \
    2 run_write "lookups/_versions/.fim_baseline.json"

expect_exit "write to .csv_expected_hashes.json blocked" \
    2 run_write "lookups/_versions/.csv_expected_hashes.json"

expect_exit "write to synthetic test fixture blocked" \
    2 run_write "tests/test_approval_fixture_helper.py"

# ── 2. Unit-test exception ─────────────────────────────────────────
expect_exit "write under tests/unit/ allowed" \
    0 run_write "tests/unit/test_approval.py"

expect_exit "write to README.md allowed" \
    0 run_write "README.md"

expect_exit "write to bin/wl_handler.py allowed" \
    0 run_write "bin/wl_handler.py"

# ── 3. Bash with WRITE_INDICATORS blocks ───────────────────────────
expect_exit "bash redirect to queue file blocked" \
    2 run_bash 'echo "{}" > lookups/_versions/_approval_queue.json'

expect_exit "bash cp to queue file blocked" \
    2 run_bash "cp scratch.json lookups/_versions/_approval_queue.json"

expect_exit "bash docker cp to queue file blocked" \
    2 run_bash "docker cp scratch.json wl_manager_test:/opt/splunk/etc/apps/wl_manager/lookups/_versions/_approval_queue.json"

# ── 4. JUSTIFIED marker overrides Bash blocking ────────────────────
expect_exit "bash with # JUSTIFIED marker allowed" \
    0 run_bash 'echo "{}" > lookups/_versions/.fim_baseline.json  # JUSTIFIED: first-install bootstrap'

# Generic "for testing" should NOT pass — the marker requires a
# concrete reason. The hook treats any non-empty token after the
# colon as a reason. (The CLAUDE.md prose rule says it must be
# specific, but enforcement is on the marker presence, not its
# semantics.) Document this gap as a known limitation rather than
# pretending the hook is stricter than it is.
expect_exit "bash with # JUSTIFIED: anything allowed (semantic gap)" \
    0 run_bash 'echo "{}" > lookups/_versions/.fim_baseline.json  # JUSTIFIED: testing'

# ── 5. Bash GET (read-only) against KV collection allowed ──────────
expect_exit "GET against wl_cooldowns KV allowed" \
    0 run_bash "curl -sk -u admin:Pw -X GET https://localhost:8089/servicesNS/nobody/wl_manager/storage/collections/data/wl_cooldowns"

expect_exit "default curl (no -X) against KV allowed" \
    0 run_bash "curl -sk -u admin:Pw https://localhost:8089/servicesNS/nobody/wl_manager/storage/collections/data/wl_fim_baseline"

# ── 6. Bash mutating KV collection blocked ─────────────────────────
expect_exit "POST to wl_cooldowns KV blocked" \
    2 run_bash "curl -sk -u admin:Pw -X POST https://localhost:8089/servicesNS/nobody/wl_manager/storage/collections/data/wl_cooldowns -d '{}'"

expect_exit "DELETE on wl_fim_baseline KV blocked" \
    2 run_bash "curl -sk -u admin:Pw -X DELETE https://localhost:8089/servicesNS/nobody/wl_manager/storage/collections/data/wl_fim_baseline"

expect_exit "PATCH on wl_presence KV blocked" \
    2 run_bash "curl -sk -u admin:Pw -X PATCH https://localhost:8089/servicesNS/nobody/wl_manager/storage/collections/data/wl_presence -d '{}'"

# ── 7. Non-blocked bash (read paths) allowed ───────────────────────
expect_exit "bash cat of queue file allowed (read-only)" \
    0 run_bash "cat lookups/_versions/_approval_queue.json"

expect_exit "bash grep on baseline allowed (read-only)" \
    0 run_bash "grep mtime lookups/_versions/.fim_baseline.json"

finish_suite
