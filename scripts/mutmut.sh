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
#
# Default <module> is bin/wl_validation.py (the security-critical
# choke point that's most worth mutating). Other useful targets:
# bin/wl_csv.py, bin/wl_versions.py, bin/wl_rbac.py, bin/wl_audit.py.
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
TEST_RUNNER_FILES="${TEST_RUNNER_FILES:-tests/unit/test_validation.py tests/unit/test_ascii_validation.py tests/unit/test_validator_fuzz.py}"
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

cmd="${1:-run}"
shift || true

case "$cmd" in
    run)     cmd_run "$@" ;;
    results) cmd_results "$@" ;;
    show)    cmd_show "$@" ;;
    kill)    cmd_kill "$@" ;;
    *)
        echo "usage: scripts/mutmut.sh {run|results|show <id>|kill}" >&2
        echo "  MUTATE_PATH=<file> TEST_PATH=<dir> overrides defaults" >&2
        exit 1
        ;;
esac
