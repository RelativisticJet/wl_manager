#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════
# Mutation Testing Harness — Dockerized mutmut Runner
# ═══════════════════════════════════════════════════════════════════════
#
# Runs `mutmut` against a target Python module in a Linux Docker
# container. Avoids Windows compatibility issues (mutmut doesn't
# support Windows natively — see github.com/boxed/mutmut/issues/397).
# Same harness works locally on any host with Docker, and the
# CI workflow uses the same script for parity.
#
# Ring 3 Day 2 (2026-05-08).
#
# Usage
# -----
#
#   scripts/mutmut.sh run     [<module>]   # Mutate + test
#   scripts/mutmut.sh results              # Show survivors
#   scripts/mutmut.sh show    <id>         # Show one survivor diff
#   scripts/mutmut.sh kill                 # Stop the cache container
#   scripts/mutmut.sh mappings             # Print the module -> tests table
#
# Default <module> is bin/wl_validation.py (the security-critical
# choke point that's most worth mutating). Other useful targets:
# bin/wl_csv.py, bin/wl_versions.py, bin/wl_rbac.py, bin/wl_audit.py.
#
# Test selector auto-derivation
# -----------------------------
#
# When you set MUTATE_PATH=<module> without also setting
# TEST_RUNNER_FILES, the harness auto-selects the right test files
# from the mapping table (see ``derive_test_files_for`` below).
#
# Origin: 2026-05-18 incident — a prior run used
# MUTATE_PATH=bin/wl_csv.py with the unset TEST_RUNNER_FILES default,
# which still pointed at wl_validation tests. The "survivors" reported
# were all artifacts of test-selector / mutated-module mismatch (the
# wl_validation tests never imported wl_csv at all, so EVERY csv
# mutation trivially survived). See docs/MUTATION_TESTING.md.
#
# Mismatched config now hard-fails: if MUTATE_PATH is not in the
# mapping table AND TEST_RUNNER_FILES is not explicitly set, the
# script exits with a clear error rather than running garbage tests.
# The escape hatch is to set TEST_RUNNER_FILES manually.
#
# Why a persistent container
# --------------------------
#
# mutmut's mutation cache lives on disk (.mutmut-cache). Reusing
# the same container across `run` and `results` invocations
# preserves the cache, so re-runs are incremental. The container
# is named `wl_manager_mutmut` and stays up between commands;
# `scripts/mutmut.sh kill` tears it down when you're done.
#
# What gets mutated
# -----------------
#
# By default: bin/wl_validation.py only. Mutating bin/wl_handler.py
# (the REST handler) requires the integration test suite + a live
# Splunk container per mutation, which would take days. Stick to
# unit-tested modules where the test suite runs in seconds. The
# script's `MUTATE_PATH` env var override lets you target other
# modules without editing the script.
#
# Why we don't mutate bin/wl_handler.py
# -------------------------------------
#
# 1. Tests for it are integration tests (need live Splunk)
# 2. ~30s per test invocation × hundreds of mutations = days
# 3. The handler's logic is mostly dispatch + delegation; the
#    real validators are in wl_validation.py and friends
# 4. RBAC paths in handler are pinned by tests/integration/
#    test_rbac_matrix.py — that's exhaustive enough
#
# ═══════════════════════════════════════════════════════════════════════

set -euo pipefail

CONTAINER="wl_manager_mutmut"
# Python 3.11-slim — pytest 9.0.3 requires >= 3.10. We don't run
# Splunk in this container, just the unit tests against pure-Python
# modules, so the Splunk-bundled-3.9 constraint doesn't apply here.
IMAGE="python:3.11-slim"
MUTATE_PATH="${MUTATE_PATH:-bin/wl_validation.py}"
# mutmut wants a single directory for --tests-dir (used for change
# detection / coverage data location). Pytest runner does the actual
# scoping below — we point pytest at specific files rather than the
# whole tests/unit/ tree because unrelated tests (e.g. filelock tests
# that need fcntl semantics the slim container lacks) would fail the
# baseline and block all mutations. Per-module scoping is also ~5x
# faster: ~2-5s per mutation instead of ~15-20s.
TEST_DIR="${TEST_DIR:-tests/unit}"

# ── Module → test files mapping ──────────────────────────────────────
#
# Each mutated module maps to the test file(s) that actually
# exercise it. When MUTATE_PATH is set but TEST_RUNNER_FILES is
# unset, the script auto-derives the right test list. When neither
# is set we fall through to the default bin/wl_validation.py target.
#
# To add a new module: add a case branch below + a row in
# the ``mappings`` subcommand output. Update both together so the
# help text never drifts from the actual logic.
#
# Special case: bin/wl_handler.py is NOT in the mapping. Mutating
# it requires integration tests (~30s each × hundreds of mutations
# = days). The script rejects MUTATE_PATH=bin/wl_handler.py with a
# clear error pointing at this constraint.
derive_test_files_for() {
    local mutate_path="$1"
    case "$mutate_path" in
        bin/wl_handler.py)
            echo "ERROR: bin/wl_handler.py mutation is forbidden by policy." >&2
            echo "  Tests are integration-only (live Splunk required), ~30s per" >&2
            echo "  invocation. Multiplied by hundreds of mutations = multi-day" >&2
            echo "  runs. Mutate the handler's delegates (wl_validation, wl_csv," >&2
            echo "  wl_rbac, etc.) instead — they cover the real logic." >&2
            echo "  See scripts/mutmut.sh header + docs/MUTATION_TESTING.md." >&2
            return 1
            ;;
        bin/wl_validation.py)
            echo "tests/unit/test_validation.py tests/unit/test_ascii_validation.py tests/unit/test_validator_fuzz.py"
            ;;
        bin/wl_csv.py)
            echo "tests/unit/test_csv.py tests/unit/test_diff_fuzz.py"
            ;;
        bin/wl_audit.py)
            echo "tests/unit/test_audit.py tests/unit/test_view_audit_dedup.py"
            ;;
        bin/wl_approval.py)
            echo "tests/unit/test_approval.py tests/unit/test_approval_queue_state_machine.py tests/unit/test_pending_info_projection.py"
            ;;
        bin/wl_rbac.py)
            echo "tests/unit/test_rbac.py"
            ;;
        bin/wl_versions.py)
            echo "tests/unit/test_versions.py"
            ;;
        bin/wl_limits.py)
            echo "tests/unit/test_limits.py"
            ;;
        bin/wl_constants.py)
            echo "tests/unit/test_constants.py"
            ;;
        bin/wl_filelock.py)
            echo "tests/unit/test_filelock.py"
            ;;
        bin/wl_fim.py|bin/wl_fim_common.py|bin/wl_fim_watch.py)
            echo "tests/unit/test_fim_append_only.py"
            ;;
        bin/wl_hmac_key.py)
            echo "tests/unit/test_hmac_sig_fuzz.py"
            ;;
        bin/wl_logging.py)
            echo "tests/unit/test_logging.py"
            ;;
        bin/wl_notify.py)
            echo "tests/unit/test_notify.py"
            ;;
        bin/wl_presence.py)
            echo "tests/unit/test_presence.py"
            ;;
        bin/wl_ratelimit.py)
            echo "tests/unit/test_ratelimit.py"
            ;;
        bin/wl_replay.py)
            echo "tests/unit/test_replay.py"
            ;;
        bin/wl_rules.py)
            echo "tests/unit/test_rules.py"
            ;;
        bin/wl_trash.py)
            echo "tests/unit/test_trash.py"
            ;;
        *)
            echo "ERROR: no test-file mapping for MUTATE_PATH='$mutate_path'." >&2
            echo "  Either add a case branch in scripts/mutmut.sh :: derive_test_files_for," >&2
            echo "  or set TEST_RUNNER_FILES explicitly to override the auto-derivation." >&2
            echo "  Running mutmut without a matching test selector produces phantom" >&2
            echo "  survivors (see docs/MUTATION_TESTING.md for the 2026-05-18 incident)." >&2
            echo "" >&2
            echo "  Known mappings: scripts/mutmut.sh mappings" >&2
            return 1
            ;;
    esac
}

# Auto-derive TEST_RUNNER_FILES from MUTATE_PATH unless explicitly set.
# Use `${VAR:+set}` semantics: if user passed a non-empty
# TEST_RUNNER_FILES env var, honor it. Otherwise derive.
if [ -z "${TEST_RUNNER_FILES:-}" ]; then
    if ! TEST_RUNNER_FILES=$(derive_test_files_for "$MUTATE_PATH"); then
        exit 1
    fi
fi

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Posix path conversion for Windows Git Bash
export MSYS_NO_PATHCONV=1

ensure_container() {
    if docker inspect "$CONTAINER" >/dev/null 2>&1; then
        # Container exists. Make sure it's running.
        if [ "$(docker inspect -f '{{.State.Running}}' "$CONTAINER")" != "true" ]; then
            docker start "$CONTAINER" >/dev/null
        fi
        return
    fi
    echo "→ creating mutmut container ($IMAGE)..."
    docker run -d --name "$CONTAINER" \
        -v "$REPO_ROOT:/work" \
        -w /work \
        --entrypoint sleep \
        "$IMAGE" infinity >/dev/null

    echo "→ installing deps..."
    # We DON'T use --quiet here so failures are visible. mutmut
    # 2.4.4 is the last 2.x release before 3.x rewrote the API
    # incompatibly; we pin it to keep the harness stable.
    if ! docker exec "$CONTAINER" pip install \
            mutmut==2.4.4 \
            pytest==9.0.3 \
            hypothesis==6.90.0 \
            freezegun==1.5.1 \
            pytest-timeout==2.1.0; then
        echo "✖ dep install failed — see output above. removing container." >&2
        docker rm -f "$CONTAINER" >/dev/null
        exit 1
    fi
}

cmd_run() {
    ensure_container
    echo "→ mutating $MUTATE_PATH"
    echo "→ tests-dir: $TEST_DIR (mutmut change-detection scope)"
    echo "→ runner: pytest $TEST_RUNNER_FILES"
    # --use-coverage requires .coverage from a prior run. We don't
    # use it here because the per-module scoped runner doesn't import
    # every line in the file anyway, and false-survivor count from
    # uncovered lines is information we WANT (it surfaces dead code).
    docker exec "$CONTAINER" mutmut run \
        --paths-to-mutate="$MUTATE_PATH" \
        --tests-dir="$TEST_DIR" \
        --runner="python -m pytest -x -q --tb=no $TEST_RUNNER_FILES" \
        || true
    docker exec "$CONTAINER" mutmut results || true
}

cmd_results() {
    ensure_container
    docker exec "$CONTAINER" mutmut results
}

cmd_show() {
    local id="${1:-}"
    if [ -z "$id" ]; then
        echo "usage: mutmut.sh show <mutation-id>" >&2
        exit 1
    fi
    ensure_container
    docker exec "$CONTAINER" mutmut show "$id"
}

cmd_kill() {
    if docker inspect "$CONTAINER" >/dev/null 2>&1; then
        echo "→ removing $CONTAINER"
        docker rm -f "$CONTAINER" >/dev/null
    else
        echo "(no container to kill)"
    fi
}

cmd_mappings() {
    # Print the module-to-test mapping table. Kept hand-maintained
    # to mirror derive_test_files_for above. If you add a module
    # there, add a row here too.
    cat <<'EOF'
Module → test files mapping (used when MUTATE_PATH is set but
TEST_RUNNER_FILES is not):

  bin/wl_validation.py    tests/unit/test_validation.py
                          tests/unit/test_ascii_validation.py
                          tests/unit/test_validator_fuzz.py
  bin/wl_csv.py           tests/unit/test_csv.py
                          tests/unit/test_diff_fuzz.py
  bin/wl_audit.py         tests/unit/test_audit.py
                          tests/unit/test_view_audit_dedup.py
  bin/wl_approval.py      tests/unit/test_approval.py
                          tests/unit/test_approval_queue_state_machine.py
                          tests/unit/test_pending_info_projection.py
  bin/wl_rbac.py          tests/unit/test_rbac.py
  bin/wl_versions.py      tests/unit/test_versions.py
  bin/wl_limits.py        tests/unit/test_limits.py
  bin/wl_constants.py     tests/unit/test_constants.py
  bin/wl_filelock.py      tests/unit/test_filelock.py
  bin/wl_fim.py           tests/unit/test_fim_append_only.py
  bin/wl_fim_common.py    tests/unit/test_fim_append_only.py
  bin/wl_fim_watch.py     tests/unit/test_fim_append_only.py
  bin/wl_hmac_key.py      tests/unit/test_hmac_sig_fuzz.py
  bin/wl_logging.py       tests/unit/test_logging.py
  bin/wl_notify.py        tests/unit/test_notify.py
  bin/wl_presence.py      tests/unit/test_presence.py
  bin/wl_ratelimit.py     tests/unit/test_ratelimit.py
  bin/wl_replay.py        tests/unit/test_replay.py
  bin/wl_rules.py         tests/unit/test_rules.py
  bin/wl_trash.py         tests/unit/test_trash.py

FORBIDDEN:
  bin/wl_handler.py       (integration tests only — multi-day runs)

To override: set TEST_RUNNER_FILES env var explicitly.
EOF
}

cmd="${1:-run}"
shift || true

case "$cmd" in
    run)      cmd_run "$@" ;;
    results)  cmd_results "$@" ;;
    show)     cmd_show "$@" ;;
    kill)     cmd_kill "$@" ;;
    mappings) cmd_mappings "$@" ;;
    *)
        echo "usage: scripts/mutmut.sh {run|results|show <id>|kill|mappings}" >&2
        echo "  MUTATE_PATH=<file>            select module (auto-derives tests)" >&2
        echo "  TEST_RUNNER_FILES='<files>'   explicit test list (overrides auto)" >&2
        echo "  TEST_DIR=<dir>                mutmut --tests-dir override" >&2
        exit 1
        ;;
esac
