#!/usr/bin/env bash
#
# Regenerate the hashed Python requirements lockfiles under
# requirements/ from their .in source files. Runs pip-compile inside
# a python:3.11-slim container so the resolution matches CI exactly
# (avoids platform-specific transitive deps like pywin32 that don't
# exist in Linux CI).
#
# Usage:
#   bash scripts/regen_requirements.sh
#
# When to run: any time a requirements/*.in source file changes
# (direct-dep version bump, package addition, package removal).
# See requirements/README.md for the full workflow.

set -euo pipefail

cd "$(dirname "$0")/.."

if ! command -v docker >/dev/null 2>&1; then
  cat >&2 <<EOF
ERROR: docker is required to regenerate requirements lockfiles.

The lockfiles must be generated in a Python 3.11 Linux environment
to match CI exactly. If docker is unavailable, see the manual
fallback in requirements/README.md.
EOF
  exit 1
fi

INPUTS=("test" "docs" "pip-audit" "appinspect")

echo "Regenerating ${#INPUTS[@]} lockfile(s) in python:3.11-slim..."

# MSYS_NO_PATHCONV=1 is a no-op on Linux/macOS but prevents Git Bash
# on Windows from mangling /req inside the docker -v argument.
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd)/requirements:/req" \
  python:3.11-slim sh -c '
    set -e
    pip install --quiet pip-tools 2>/dev/null
    for f in '"${INPUTS[*]}"'; do
      echo "  compiling /req/$f.in -> /req/$f.txt"
      pip-compile --generate-hashes --strip-extras --quiet \
        --output-file=/req/$f.txt /req/$f.in
    done
  '

echo ""
echo "Done. Review the diff and commit requirements/*.txt alongside"
echo "the matching .in changes that triggered the regeneration."
