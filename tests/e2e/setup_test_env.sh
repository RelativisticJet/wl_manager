#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════
# Test Environment Setup — Idempotent User/Role Creation
# ═══════════════════════════════════════════════════════════════════════
#
# Creates the test users and roles required by the E2E test suite.
# Safe to run multiple times — Splunk returns 409 for existing
# entities and the script ignores those.
#
# Required BEFORE running any E2E tests on a fresh container.
#
# Usage:
#   ./tests/e2e/setup_test_env.sh [container_name]
#
# Default container: wl_manager_test
# ═══════════════════════════════════════════════════════════════════════

set -euo pipefail

CONTAINER="${1:-wl_manager_test}"
ADMIN_USER="admin"
ADMIN_PASS="Chang3d!"
BASE_URL="https://localhost:8089"

echo "=== Test Environment Setup (container: $CONTAINER) ==="

# Wait for Splunk REST API to be ready
echo -n "Waiting for Splunk REST API..."
for i in $(seq 1 30); do
    status=$(MSYS_NO_PATHCONV=1 docker exec "$CONTAINER" \
        curl -sk -o /dev/null -w "%{http_code}" \
        -u "$ADMIN_USER:$ADMIN_PASS" \
        "$BASE_URL/services/server/info" 2>/dev/null || echo "000")
    if [ "$status" = "200" ]; then
        echo " ready."
        break
    fi
    echo -n "."
    sleep 5
done
if [ "$status" != "200" ]; then
    echo " TIMEOUT — Splunk not responding after 150s."
    exit 1
fi

# Wait for KV store to be ready
echo -n "Waiting for KV store..."
for i in $(seq 1 12); do
    kv_status=$(MSYS_NO_PATHCONV=1 docker exec "$CONTAINER" \
        curl -sk -u "$ADMIN_USER:$ADMIN_PASS" \
        "$BASE_URL/services/kvstore/status?output_mode=json" 2>/dev/null \
        | python3 -c "import json,sys; print(json.load(sys.stdin)['entry'][0]['content']['current']['status'])" 2>/dev/null || echo "unknown")
    if [ "$kv_status" = "ready" ]; then
        echo " ready."
        break
    fi
    echo -n "."
    sleep 5
done
if [ "$kv_status" != "ready" ]; then
    echo " TIMEOUT — KV store not ready after 60s."
    exit 1
fi

# Helper: create role (ignore 409 = already exists)
create_role() {
    local name="$1"
    shift
    local result
    result=$(MSYS_NO_PATHCONV=1 docker exec "$CONTAINER" \
        curl -sk -o /dev/null -w "%{http_code}" \
        -u "$ADMIN_USER:$ADMIN_PASS" \
        -X POST "$BASE_URL/services/authorization/roles" \
        -d "name=$name" "$@" 2>/dev/null)
    if [ "$result" = "201" ]; then
        echo "  Created role: $name"
    elif [ "$result" = "409" ]; then
        echo "  Role exists:  $name (ok)"
    else
        echo "  Role $name: HTTP $result (unexpected)"
    fi
}

# Helper: create user (ignore 409 = already exists)
create_user() {
    local name="$1"
    shift
    local result
    result=$(MSYS_NO_PATHCONV=1 docker exec "$CONTAINER" \
        curl -sk -o /dev/null -w "%{http_code}" \
        -u "$ADMIN_USER:$ADMIN_PASS" \
        -X POST "$BASE_URL/services/authentication/users" \
        -d "name=$name" -d "password=$ADMIN_PASS" "$@" 2>/dev/null)
    if [ "$result" = "201" ]; then
        echo "  Created user: $name"
    elif [ "$result" = "409" ]; then
        # User exists — update roles to ensure they match
        MSYS_NO_PATHCONV=1 docker exec "$CONTAINER" \
            curl -sk -o /dev/null \
            -u "$ADMIN_USER:$ADMIN_PASS" \
            -X POST "$BASE_URL/services/authentication/users/$name" \
            "$@" 2>/dev/null
        echo "  User exists:  $name (roles updated)"
    else
        echo "  User $name: HTTP $result (unexpected)"
    fi
}

echo ""
echo "--- Creating roles ---"
create_role "wl_editor"     -d "imported_roles=user"
create_role "wl_viewer"     -d "imported_roles=user"
create_role "wl_admin"      -d "imported_roles=admin"
create_role "wl_superadmin" -d "imported_roles=admin"
create_role "sc_admin"      -d "imported_roles=admin"

echo ""
echo "--- Creating test users ---"
echo ""
echo "  analyst1 / analyst2         — roles: user, wl_editor"
echo "  wladmin1 / wladmin2         — roles: admin, wl_editor, wl_admin"
echo "  superadmin1 / superadmin2   — roles: admin, sc_admin, wl_editor, wl_superadmin"
echo ""
echo "  Note: *2 accounts are required for dual-admin/dual-superadmin/dual-analyst"
echo "  approval flows (a user cannot approve their own dual-approval request)."
echo ""
create_user "analyst1"     -d "roles=user"      -d "roles=wl_editor"
create_user "analyst2"     -d "roles=user"      -d "roles=wl_editor"
create_user "wladmin1"     -d "roles=admin"     -d "roles=wl_editor" -d "roles=wl_admin"
create_user "wladmin2"     -d "roles=admin"     -d "roles=wl_editor" -d "roles=wl_admin"
create_user "superadmin1"  -d "roles=admin"     -d "roles=sc_admin"  -d "roles=wl_editor" -d "roles=wl_superadmin"
create_user "superadmin2"  -d "roles=admin"     -d "roles=sc_admin"  -d "roles=wl_editor" -d "roles=wl_superadmin"

echo ""
echo "--- Verifying ---"
MSYS_NO_PATHCONV=1 docker exec "$CONTAINER" \
    curl -sk -u "$ADMIN_USER:$ADMIN_PASS" \
    "$BASE_URL/services/authentication/users?output_mode=json" 2>/dev/null \
    | python3 -c "
import json, sys
d = json.load(sys.stdin)
for e in d['entry']:
    print('  {} -> {}'.format(e['name'], e['content']['roles']))
"

echo ""
echo "=== Setup complete ==="
