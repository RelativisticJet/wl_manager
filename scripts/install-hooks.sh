#!/usr/bin/env bash
# Bootstrap the project's Claude Code hook configuration for a new
# collaborator.
#
# The tracked TEMPLATE at .claude/settings.example.json uses absolute
# paths (Claude Code does not expand ${workspaceFolder} in hook
# commands today). This script reads the template, rewrites the
# hardcoded `c:/Users/PC/wl_manager` prefix to the current checkout
# path, and writes the result to .claude/settings.json (the actual
# per-developer config, gitignored).
#
# Usage:
#   bash scripts/install-hooks.sh            # interactive (asks before overwrite)
#   bash scripts/install-hooks.sh --force    # overwrite without prompting
#
# Exit codes:
#   0 = wrote .claude/settings.json successfully (or already in sync)
#   1 = template missing or write failed
#   2 = .claude/settings.json exists and --force not supplied

set -euo pipefail

REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
cd "$REPO_ROOT"

TEMPLATE=".claude/settings.example.json"
TARGET=".claude/settings.json"
HARDCODED_PREFIX="c:/Users/PC/wl_manager"

FORCE=0
for arg in "$@"; do
    case "$arg" in
        -f|--force) FORCE=1 ;;
        -h|--help)
            sed -n '2,/^set -euo/p' "$0" | sed -n 's/^# \{0,1\}//p'
            exit 0
            ;;
    esac
done

if [ ! -f "$TEMPLATE" ]; then
    echo "install-hooks: template $TEMPLATE not found" >&2
    echo "  (the wl_manager repo ships .claude/settings.example.json — your checkout may be stale)" >&2
    exit 1
fi

# Resolve REPO_ROOT to forward-slash form Claude Code understands on
# Windows (e.g. C:/Users/you/wl_manager) and POSIX hosts (e.g.
# /home/you/wl_manager).
CHECKOUT=$(printf '%s' "$REPO_ROOT" | sed 's#\\#/#g')

if [ -f "$TARGET" ] && [ "$FORCE" -ne 1 ]; then
    # If the target already points at THIS checkout, treat as no-op
    # rather than asking — that's the steady-state for a developer
    # who already ran this script.
    if grep -q -F "$CHECKOUT/scripts/hooks/" "$TARGET" 2>/dev/null; then
        echo "install-hooks: $TARGET already configured for $CHECKOUT — nothing to do"
        exit 0
    fi
    cat >&2 <<EOF
install-hooks: $TARGET already exists and points at a different checkout (or has manual edits).

  Current target prefix(es):
$(grep -oE "(c:/[A-Za-z0-9_./-]+|/[A-Za-z0-9_./-]+)/(scripts|\.claude)/hooks/" "$TARGET" | sort -u | sed 's/^/    /')

  Re-run with --force to overwrite, or edit $TARGET by hand. If you
  rely on personal customizations there, copy them somewhere safe
  before forcing.
EOF
    exit 2
fi

# sed -i differs between BSD (macOS) and GNU — use a portable form.
TMP=$(mktemp)
sed "s#$HARDCODED_PREFIX#$CHECKOUT#g" "$TEMPLATE" > "$TMP"
mv "$TMP" "$TARGET"

echo "install-hooks: wrote $TARGET"
echo "  checkout prefix: $CHECKOUT"
echo ""
echo "Hook config installed. To verify:"
echo "  make hook-tests   # runs tests/hooks/run.sh"
echo ""
echo "If you want the global hooks too (force-push-guard, banned-phrase,"
echo "additional-thoughts), see ~/.claude/settings.json — those live"
echo "outside this repo and are documented in scripts/hooks/README.md."
exit 0
