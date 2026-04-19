#!/usr/bin/env bash
# Documentation drift guard for wl_manager.
#
# Enforces two rules against the project's top-level docs:
#   1. Every repo-relative file path mentioned in the docs (bin/..., default/...,
#      appserver/..., scripts/..., lookups/..., docs/..., tests/...) must exist
#      on disk. Catches references to deleted/renamed files.
#   2. Every `[Bb]uild NNN` mention must either match `build = N` in
#      default/app.conf, OR carry a historical-mention disambiguator on the
#      same line (a YYYY-MM-DD date, or a keyword from the allowlist, or be
#      written as a plural range like "builds 552-562"). This catches stale
#      "Current State (Build 587)" claims without flagging genuine historical
#      references to past incidents.
#
# Both checks SKIP lines inside fenced code blocks (``` ... ```), because
# those contain command examples and runtime config where verbatim values
# (like "deploy build 555") are part of the example syntax, not a claim
# about current state.
#
# Both checks SKIP content inside inline backticks when it contains the
# matched token (so `Build 587` in prose as a banned-pattern example is
# handled cleanly).
#
# Policies and rationale: see `CLAUDE.md` -> "Documentation rules".
#
# Usage:
#   scripts/pre-commit-doc-drift.sh        # runs against working tree
#   make doc-check                         # same thing, via Makefile
#
# Exit codes:
#   0  -> clean
#   1  -> drift detected (script prints what and where)

set -eu

REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
cd "$REPO_ROOT"

RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
NC='\033[0m'

# ── Docs under drift control ─────────────────────────────────────────────────
ROOT_DOCS=(
    "CLAUDE.md"
    "README.md"
    "CONTRIBUTING.md"
    "ARCHITECTURE.md"
    "INSTALLATION.md"
    "SECURITY.md"
    "CODE_OF_CONDUCT.md"
    "CHANGELOG.md"
)

DOCS=()
for f in "${ROOT_DOCS[@]}"; do
    if [ -f "$f" ]; then
        DOCS+=("$f")
    fi
done

# docs/ — exclude dated snapshots and archive subdirs.
if [ -d "docs" ]; then
    while IFS= read -r -d '' f; do
        base=$(basename "$f")
        case "$base" in
            *20[0-9][0-9]-[0-9][0-9]-[0-9][0-9]*.md) continue ;;
            *-archive.md|archive-*.md) continue ;;
        esac
        case "$f" in
            */archive/*|*/archived/*) continue ;;
        esac
        DOCS+=("$f")
    done < <(find docs -name '*.md' -type f -print0 2>/dev/null)
fi

if [ "${#DOCS[@]}" -eq 0 ]; then
    echo -e "${YELLOW}doc-drift: no tracked docs found — nothing to check.${NC}"
    exit 0
fi

# ── Preprocess docs: strip fenced code blocks ────────────────────────────────
# We build a version of each doc with every ``` ... ``` block replaced by
# blank lines (preserving line numbers so error messages stay accurate).
# The awk state-machine flips `in_fence` each time a line starts with ``` .

strip_fences() {
    awk '
        /^[[:space:]]*```/ {
            in_fence = !in_fence
            print ""
            next
        }
        { if (in_fence) print ""; else print $0 }
    ' "$1"
}

# Write one temp file per doc with fences stripped.
TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

STRIPPED=()
for f in "${DOCS[@]}"; do
    out="$TMPDIR/$(echo "$f" | tr '/' '_')"
    strip_fences "$f" > "$out"
    STRIPPED+=("$out")
done

# Helper: given a stripped-index into STRIPPED[], return the original doc path.
orig_of() {
    idx=$1
    echo "${DOCS[$idx]}"
}

ERRORS=0

# ── Check 1: file-path references exist on disk ──────────────────────────────
echo -e "${GREEN}[doc-drift 1/2]${NC} verifying file-path references exist..."

# Collect candidate paths from STRIPPED docs (fenced blocks already gone).
# Anchor on known top-level directories. Trailing punctuation (., ), ,, ;)
# is trimmed because prose often writes `see foo/bar.py.`
RAW_PATHS=$(
    grep -ohE '(bin|appserver|default|scripts|lookups|docs|tests)/[A-Za-z0-9_./-]+\.(py|js|conf|xml|sh|csv|md|yaml|yml|json|jsonl)' "${STRIPPED[@]}" 2>/dev/null | \
    sort -u || true
)

# Runtime-only path patterns — these are produced by the running Splunk app
# and are documented for operational clarity, not as repo files.
is_runtime_path() {
    case "$1" in
        lookups/_versions/_*.json|lookups/_versions/_*.jsonl) return 0 ;;
        lookups/_versions/.fim_*) return 0 ;;
        lookups/_versions/.csv_*) return 0 ;;
        *) return 1 ;;
    esac
}

MISSING=()
for p in $RAW_PATHS; do
    # Skip wildcards, placeholders, absolute paths.
    case "$p" in
        *\**) continue ;;
        *\$*) continue ;;
        *\<*\>*) continue ;;
        /opt/splunk/*) continue ;;
    esac
    if is_runtime_path "$p"; then
        continue
    fi
    if [ ! -e "$p" ]; then
        MISSING+=("$p")
    fi
done

if [ "${#MISSING[@]}" -gt 0 ]; then
    echo -e "${RED}doc-drift: file-path references that do not exist:${NC}"
    for p in "${MISSING[@]}"; do
        # Map back to originals for the "mentioned in" list (search in the
        # un-stripped docs since that's what the user sees).
        hits=$(grep -l -F -- "$p" "${DOCS[@]}" 2>/dev/null | tr '\n' ' ' || true)
        echo "  $p    (mentioned in: ${hits:-unknown})"
    done
    echo ""
    echo "Fix: either restore the file, update the doc to a real path, or"
    echo "     remove the reference if the feature was deleted."
    echo "     Runtime-only paths (files the app creates at runtime) should"
    echo "     match a pattern in is_runtime_path() inside this script."
    ERRORS=$((ERRORS + 1))
fi

# ── Check 2: build-number consistency ────────────────────────────────────────
echo -e "${GREEN}[doc-drift 2/2]${NC} verifying build numbers match default/app.conf..."

CURRENT_BUILD=$(grep -oE '^build[[:space:]]*=[[:space:]]*[0-9]+' default/app.conf 2>/dev/null | grep -oE '[0-9]+' | head -1 || true)
if [ -z "$CURRENT_BUILD" ]; then
    echo -e "${RED}doc-drift: cannot read build number from default/app.conf${NC}"
    exit 1
fi

# Disambiguator keywords — keep in sync with CLAUDE.md rule #2.
ALLOW_RE='\b([0-9]{4}-[0-9]{2}-[0-9]{2}|incident|incidents|shipped|caused|introduced|historical|origin|rounds?|hardening|was|were|originally|previously|ago|past)\b'
PLURAL_RE='\bbuilds?[[:space:]]+[0-9]+[[:space:]]*[-–—to]+[[:space:]]*[0-9]+\b'

MISMATCHES=()
for i in "${!DOCS[@]}"; do
    f="${DOCS[$i]}"
    stripped="${STRIPPED[$i]}"

    # Each build mention from the fence-stripped version (so fenced code
    # blocks are already excluded). Line numbers still map to originals
    # because stripping preserves line numbering.
    while IFS= read -r match_line; do
        lineno=$(echo "$match_line" | cut -d: -f1)
        content=$(echo "$match_line" | cut -d: -f2-)

        # Skip if the build mention is inside an inline backtick span.
        if echo "$content" | grep -qE '`[^`]*[Bb]uild[[:space:]]+[0-9]+[^`]*`'; then
            continue
        fi
        # Skip if the line carries any disambiguator.
        if echo "$content" | grep -qE "$ALLOW_RE"; then
            continue
        fi
        if echo "$content" | grep -qE "$PLURAL_RE"; then
            continue
        fi

        extracted=$(echo "$content" | grep -oE '[Bb]uild[[:space:]]+[0-9]+' | head -1 | grep -oE '[0-9]+' || true)
        if [ -n "$extracted" ] && [ "$extracted" != "$CURRENT_BUILD" ]; then
            MISMATCHES+=("$f:$lineno  claims build $extracted (app.conf is $CURRENT_BUILD)")
            MISMATCHES+=("    $(echo "$content" | sed 's/^[[:space:]]*//' | cut -c1-120)")
        fi
    done < <(grep -nE '[Bb]uild[[:space:]]+[0-9]+' "$stripped" 2>/dev/null || true)
done

if [ "${#MISMATCHES[@]}" -gt 0 ]; then
    echo -e "${RED}doc-drift: stale build-number claims:${NC}"
    for line in "${MISMATCHES[@]}"; do
        echo "  $line"
    done
    echo ""
    echo "Fix: either update the number, remove the sentence (the actual build"
    echo "     lives in default/app.conf — do not duplicate), or add a"
    echo "     disambiguator to mark it historical:"
    echo "       - a date  (e.g. 'build 585 (2026-04-14) shipped a bug')"
    echo "       - a keyword (incident, shipped, caused, introduced, historical,"
    echo "         origin, rounds, hardening, was, originally, previously, ago)"
    echo "       - a plural range ('builds 552-562')"
    ERRORS=$((ERRORS + 1))
fi

# ── Result ───────────────────────────────────────────────────────────────────
if [ "$ERRORS" -gt 0 ]; then
    echo ""
    echo -e "${RED}doc-drift check failed with $ERRORS issue group(s).${NC}"
    echo "Run 'make doc-check' after fixing to re-verify."
    exit 1
fi

echo -e "${GREEN}doc-drift: OK${NC} (checked ${#DOCS[@]} docs against build $CURRENT_BUILD)"
exit 0
