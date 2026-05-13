#!/usr/bin/env bash
#
# ═══════════════════════════════════════════════════════════════════════
# Phase 2: VALIDATE — Pre-flight checks for the Whitelist Manager app
# ═══════════════════════════════════════════════════════════════════════
#
# This script performs the same checks that Splunk's AppInspect tool runs,
# plus additional sanity checks. Run this BEFORE packaging.
#
# Usage:
#   bash scripts/validate.sh
#
# Exit codes:
#   0 = all checks passed
#   1 = one or more checks failed
#

set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
APP_NAME="wl_manager"
ERRORS=0
WARNINGS=0

# ── Helpers ────────────────────────────────────────────────────────────

pass()    { echo "  [PASS]  $1"; }
fail()    { echo "  [FAIL]  $1"; ERRORS=$((ERRORS + 1)); }
warn()    { echo "  [WARN]  $1"; WARNINGS=$((WARNINGS + 1)); }
section() { echo ""; echo "── $1 ──"; }

# ── Detect Python ──────────────────────────────────────────────────────
# Try python3 first, then python, then skip Python-dependent checks.
PYTHON=""
if command -v python3 &>/dev/null && python3 --version &>/dev/null; then
    PYTHON="python3"
elif command -v python &>/dev/null && python --version &>/dev/null; then
    PYTHON="python"
fi

# ══════════════════════════════════════════════════════════════════════
section "1. Required files"
# ══════════════════════════════════════════════════════════════════════

REQUIRED_FILES=(
    "default/app.conf"
    "default/restmap.conf"
    "default/web.conf"
    "default/indexes.conf"
    "default/authorize.conf"
    "default/transforms.conf"
    "default/data/ui/nav/default.xml"
    "default/data/ui/views/whitelist_manager.xml"
    "default/data/ui/views/audit.xml"
    "metadata/default.meta"
    "bin/wl_handler.py"
    "lookups/rule_csv_map.csv"
    "appserver/static/whitelist_manager.js"
    "appserver/static/whitelist_manager.css"
    "app.manifest"
    "README.md"
)

for f in "${REQUIRED_FILES[@]}"; do
    if [[ -f "$APP_DIR/$f" ]]; then
        pass "$f exists"
    else
        fail "$f is MISSING"
    fi
done

# ══════════════════════════════════════════════════════════════════════
section "2. app.conf validation"
# ══════════════════════════════════════════════════════════════════════

if grep -q "^\[launcher\]" "$APP_DIR/default/app.conf"; then
    pass "app.conf has [launcher] stanza"
else
    fail "app.conf missing [launcher] stanza"
fi

if grep -q "^version" "$APP_DIR/default/app.conf"; then
    VERSION=$(grep "^version" "$APP_DIR/default/app.conf" | head -1 | cut -d= -f2 | tr -d ' ')
    pass "app.conf version = $VERSION"
else
    fail "app.conf missing version"
fi

# AppInspect's check_for_valid_package_id wants [id]; legacy Splunk
# apps used [package]. Both accept name/id field aliases. Accept either
# stanza here so the validator works during the transitional period
# and after Phase 0.0 (2026-05-14) which renamed [package] → [id].
if grep -qE "^\[(package|id)\]" "$APP_DIR/default/app.conf"; then
    PACKAGE_ID=$(grep -E "^(name|id)[[:space:]]*=" "$APP_DIR/default/app.conf" | head -1 | cut -d= -f2 | tr -d ' ')
    if [[ "$PACKAGE_ID" == "$APP_NAME" ]]; then
        pass "app.conf [id]/[package] name = $APP_NAME"
    else
        fail "app.conf [id]/[package] name is '$PACKAGE_ID', expected '$APP_NAME'"
    fi
else
    fail "app.conf missing [id] (or legacy [package]) stanza"
fi

# ══════════════════════════════════════════════════════════════════════
section "3. Python syntax check"
# ══════════════════════════════════════════════════════════════════════

if [[ -n "$PYTHON" ]]; then
    for pyfile in "$APP_DIR"/bin/*.py; do
        # Convert path for Windows Python if cygpath is available (Git Bash / MSYS2)
        if command -v cygpath &>/dev/null; then
            CHECK_PATH="$(cygpath -w "$pyfile")"
        else
            CHECK_PATH="$pyfile"
        fi
        if $PYTHON -c "import sys; compile(open(sys.argv[1], encoding='utf-8').read(), sys.argv[1], 'exec')" "$CHECK_PATH" 2>/dev/null; then
            pass "$(basename "$pyfile") — syntax OK"
        else
            fail "$(basename "$pyfile") — syntax ERROR"
        fi
    done
    # Clean up any .pyc files that may have been created
    find "$APP_DIR" -name "*.pyc" -delete 2>/dev/null || true
    find "$APP_DIR" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
else
    warn "Python not found — skipping syntax check (will be validated inside Docker)"
fi

# ══════════════════════════════════════════════════════════════════════
section "4. XML well-formedness"
# ══════════════════════════════════════════════════════════════════════

if [[ -n "$PYTHON" ]]; then
    for xmlfile in "$APP_DIR"/default/data/ui/views/*.xml "$APP_DIR"/default/data/ui/nav/*.xml; do
        if command -v cygpath &>/dev/null; then
            CHECK_PATH="$(cygpath -w "$xmlfile")"
        else
            CHECK_PATH="$xmlfile"
        fi
        if $PYTHON -c "import sys; import xml.etree.ElementTree as ET; ET.parse(sys.argv[1])" "$CHECK_PATH" 2>/dev/null; then
            pass "$(basename "$xmlfile") — valid XML"
        else
            fail "$(basename "$xmlfile") — invalid XML"
        fi
    done
else
    warn "Python not found — skipping XML validation (will be validated inside Docker)"
fi

# ══════════════════════════════════════════════════════════════════════
section "5. Security checks"
# ══════════════════════════════════════════════════════════════════════

# Check for hardcoded passwords or tokens
if grep -rn "password\s*=" "$APP_DIR/default/" 2>/dev/null | grep -vi "requireAuthentication"; then
    fail "Possible hardcoded password found in conf files"
else
    pass "No hardcoded passwords in conf files"
fi

if grep -rn "token\s*=" "$APP_DIR/bin/" 2>/dev/null | grep -v "token=" | grep -v "authtoken" | grep -v "session_key" | grep -v "b64encode" | grep -q .; then
    fail "Possible hardcoded token in Python files"
else
    pass "No hardcoded tokens in Python files"
fi

# Check that REST endpoint requires authentication
if grep -q "requireAuthentication\s*=\s*true" "$APP_DIR/default/restmap.conf"; then
    pass "REST endpoint requires authentication"
else
    fail "REST endpoint does NOT require authentication — security risk!"
fi

# ══════════════════════════════════════════════════════════════════════
section "6. CSV validation"
# ══════════════════════════════════════════════════════════════════════

for csvfile in "$APP_DIR"/lookups/*.csv; do
    # Check it's valid CSV with headers
    HEADER=$(head -1 "$csvfile")
    if [[ -n "$HEADER" ]]; then
        pass "$(basename "$csvfile") — has header: $HEADER"
    else
        fail "$(basename "$csvfile") — empty or missing header"
    fi
done

# ══════════════════════════════════════════════════════════════════════
section "7. Dangerous patterns"
# ══════════════════════════════════════════════════════════════════════

# No eval() or exec() in Python (security risk)
if grep -rn "eval\s*(" "$APP_DIR/bin/"*.py 2>/dev/null; then
    fail "eval() found in Python code — security risk"
else
    pass "No eval() in Python code"
fi

if grep -rn "exec\s*(" "$APP_DIR/bin/"*.py 2>/dev/null | grep -v "exec()" | grep -v "extrasaction"; then
    warn "exec() found in Python code — review manually"
else
    pass "No exec() in Python code"
fi

# No os.system() calls
if grep -rn "os\.system\s*(" "$APP_DIR/bin/"*.py 2>/dev/null; then
    fail "os.system() found — use subprocess instead"
else
    pass "No os.system() calls"
fi

# ══════════════════════════════════════════════════════════════════════
section "8. AppInspect pre-flight checks"
# ══════════════════════════════════════════════════════════════════════

# Check for bare except clauses (AppInspect: avoid bare except)
if grep -rn "except:" "$APP_DIR/bin/"*.py 2>/dev/null; then
    fail "Bare except clause found — use specific exception type instead"
else
    pass "No bare except clauses"
fi

# Check for direct print() statements in production code (not docstrings)
# This is a simple heuristic: grep for print( but exclude docstrings and comments
if grep -rn "print(" "$APP_DIR/bin/"*.py 2>/dev/null | grep -v "^\s*#" | grep -v '"""' | grep -v "'''" | grep -q .; then
    warn "print() statement found — verify it's not in production code"
else
    pass "No production print() statements detected"
fi

# Check for module-level Splunk SDK imports (should be lazy-loaded)
if grep -rn "^from splunk\|^import splunk" "$APP_DIR/bin/"*.py 2>/dev/null | grep -v "PersistentServerConnectionApplication" | grep -q .; then
    warn "Module-level Splunk SDK import found (except PersistentServerConnectionApplication which is required)"
else
    pass "Splunk SDK imports are lazy-loaded (or only at required entry point)"
fi

# ══════════════════════════════════════════════════════════════════════
section "9. Forbidden files (AppInspect rules)"
# ══════════════════════════════════════════════════════════════════════

# .pyc files should not be packaged
if find "$APP_DIR" -name "*.pyc" 2>/dev/null | grep -q .; then
    fail "Compiled .pyc files found — remove before packaging"
else
    pass "No .pyc files"
fi

# __pycache__ directories
if find "$APP_DIR" -name "__pycache__" -type d 2>/dev/null | grep -q .; then
    fail "__pycache__ directories found — remove before packaging"
else
    pass "No __pycache__ directories"
fi

# .git directory should not be in the package
if [[ -d "$APP_DIR/.git" ]]; then
    warn ".git directory exists (will be excluded from .spl package)"
else
    pass "No .git directory"
fi

# ══════════════════════════════════════════════════════════════════════
# Summary
# ══════════════════════════════════════════════════════════════════════

echo ""
echo "════════════════════════════════════════════════════════════════"
if [[ $ERRORS -eq 0 ]]; then
    echo "  RESULT: ALL CHECKS PASSED ($WARNINGS warning(s))"
    echo "  Ready to package!"
    echo "════════════════════════════════════════════════════════════════"
    exit 0
else
    echo "  RESULT: $ERRORS FAILED check(s), $WARNINGS warning(s)"
    echo "  Fix the failures above before packaging."
    echo "════════════════════════════════════════════════════════════════"
    exit 1
fi
