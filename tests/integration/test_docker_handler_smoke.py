"""
Docker smoke tests for all REST actions against live Splunk container.

Tests verify:
- Dispatch table routes all actions correctly
- GET actions return expected response shapes
- POST actions enforce RBAC
- Handler doesn't crash on any action

Requires: wl_manager_test Docker container running on localhost:8089
Marker: @pytest.mark.docker — auto-skipped if container unavailable
"""

import pytest
import json
import subprocess
import sys
import os

# Container config (from CLAUDE.md)
CONTAINER = "wl_manager_test"
BASE_URL = "https://localhost:8089/servicesNS/admin/wl_manager/custom/wl_manager"
CREDS = "admin:Chang3d!"


def _docker_curl(action, method="GET", payload=None):
    """Execute curl inside Docker container, return (status_code, body_dict)."""
    if method == "GET":
        cmd = (
            f'curl -s -k -u {CREDS} -o /tmp/_resp -w "%{{http_code}}" '
            f'"{BASE_URL}?action={action}&output_mode=json"'
        )
    else:
        json_payload = json.dumps(payload) if payload else "{}"
        cmd = (
            f'curl -s -k -u {CREDS} -o /tmp/_resp -w "%{{http_code}}" '
            f'-X POST "{BASE_URL}" '
            f'-H "Content-Type: application/json" '
            f"-d '{json_payload}'"
        )
    result = subprocess.run(
        ["docker", "exec", CONTAINER, "bash", "-c", cmd],
        capture_output=True, text=True, timeout=30,
        env={**os.environ, "MSYS_NO_PATHCONV": "1"},
    )
    status_code = int(result.stdout.strip()) if result.stdout.strip().isdigit() else 0
    # Read the body
    body_result = subprocess.run(
        ["docker", "exec", CONTAINER, "cat", "/tmp/_resp"],
        capture_output=True, text=True, timeout=10,
        env={**os.environ, "MSYS_NO_PATHCONV": "1"},
    )
    try:
        body = json.loads(body_result.stdout)
    except (json.JSONDecodeError, ValueError):
        body = {"raw": body_result.stdout}
    return status_code, body


@pytest.fixture(scope="session")
def docker_available():
    """Skip all Docker tests if container is not running."""
    try:
        result = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}"],
            capture_output=True, text=True, timeout=10,
        )
        if CONTAINER not in result.stdout:
            pytest.skip(f"Docker container {CONTAINER} not running")
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pytest.skip("Docker not available")


# ═══════════════════════════════════════════════════════════════════════════
# GET Action Smoke Tests
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.docker
class TestGetActions:
    """Verify all GET actions dispatch and return valid responses."""

    def test_get_rules(self, docker_available):
        code, body = _docker_curl("get_rules")
        assert code == 200
        assert "rules" in body or "registered_rules" in body

    def test_get_csvs(self, docker_available):
        code, body = _docker_curl("get_csvs")
        assert code == 200
        assert "csvs" in body or "csv_files" in body or isinstance(body, dict)

    def test_get_mapping(self, docker_available):
        code, body = _docker_curl("get_mapping")
        assert code == 200
        assert "mapping" in body

    def test_get_csv_content(self, docker_available):
        code, body = _docker_curl("get_csv_content&csv_file=DR130_priv_escalation.csv")
        assert code == 200
        assert "headers" in body or "rows" in body or "error" not in body

    def test_check_csv_status(self, docker_available):
        code, body = _docker_curl("check_csv_status&csv_file=DR130_priv_escalation.csv")
        assert code == 200

    def test_get_apps(self, docker_available):
        code, body = _docker_curl("get_apps")
        assert code == 200

    def test_get_pending_approvals(self, docker_available):
        code, body = _docker_curl("get_pending_approvals")
        assert code == 200

    def test_get_notifications(self, docker_available):
        code, body = _docker_curl("get_notifications")
        assert code == 200

    def test_unknown_action_returns_400(self, docker_available):
        code, body = _docker_curl("nonexistent_action_xyz")
        assert code == 400
        assert "error" in body


# ═══════════════════════════════════════════════════════════════════════════
# POST Action Smoke Tests
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.docker
class TestPostActions:
    """Verify POST actions dispatch correctly (RBAC may restrict execution)."""

    def test_post_requires_action(self, docker_available):
        code, body = _docker_curl("", method="POST", payload={"output_mode": "json"})
        # Should get 400 (missing action) or similar, not 500
        assert code != 500

    def test_save_csv_requires_permission(self, docker_available):
        code, body = _docker_curl("save_csv", method="POST", payload={
            "action": "save_csv",
            "csv_file": "DR130_priv_escalation.csv",
            "rows": [],
        })
        # 200 or 403 or 400 — not 500
        assert code in (200, 400, 403, 409)

    def test_log_event_dispatches(self, docker_available):
        code, body = _docker_curl("log_event", method="POST", payload={
            "action": "log_event",
            "event_type": "smoke_test",
            "event_data": "Docker smoke test",
        })
        # Should dispatch — 200 or 400 (invalid event), not 500
        assert code != 500


# ═══════════════════════════════════════════════════════════════════════════
# Backward Compatibility Tests
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.docker
class TestBackwardCompatibility:
    """Verify response shapes match expected API contract."""

    def test_get_mapping_response_shape(self, docker_available):
        """get_mapping must return {mapping: [...], registered_rules: [...], permissions: {...}}."""
        code, body = _docker_curl("get_mapping")
        assert code == 200
        assert "mapping" in body
        assert isinstance(body["mapping"], list)
        if body["mapping"]:
            entry = body["mapping"][0]
            assert "rule_name" in entry
            assert "csv_file" in entry
        assert "permissions" in body

    def test_get_csv_content_response_shape(self, docker_available):
        """get_csv_content must return {headers: [...], rows: [...]}."""
        code, body = _docker_curl("get_csv_content&csv_file=DR130_priv_escalation.csv")
        assert code == 200
        assert "headers" in body
        assert "rows" in body
        assert isinstance(body["headers"], list)
        assert isinstance(body["rows"], list)

    def test_get_pending_approvals_response_shape(self, docker_available):
        """get_pending_approvals must return {pending: [...]}."""
        code, body = _docker_curl("get_pending_approvals")
        assert code == 200
        assert "pending" in body or "pending_approvals" in body


# ═══════════════════════════════════════════════════════════════════════════
# Dispatch Table Integrity
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.docker
class TestDispatchIntegrity:
    """Verify dispatch table routes correctly under live Splunk."""

    def test_all_get_actions_dont_crash(self, docker_available):
        """Every GET action in the dispatch table should return non-500."""
        get_actions = [
            "get_rules", "get_csvs", "get_mapping", "get_csv_content&csv_file=DR130_priv_escalation.csv",
            "check_csv_status&csv_file=DR130_priv_escalation.csv", "get_apps",
            "get_pending_approvals", "get_notifications",
            "report_presence&csv_file=DR130_priv_escalation.csv",
        ]
        failures = []
        for action in get_actions:
            code, _ = _docker_curl(action)
            if code == 500:
                failures.append(f"{action.split('&')[0]}: {code}")
        assert not failures, f"Actions returned 500: {failures}"
