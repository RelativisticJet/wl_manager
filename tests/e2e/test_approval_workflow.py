"""E2E tests for approval workflow (queue display + RBAC smokes).

Rewritten 2026-05-24 (PR #13 baseline). Old version called REST
`submit_approval` action that doesn't match the real handler's API
(real submit goes through `submit_approval` with different parameter
shapes per action type), and used UI selectors against non-existent
DOM. The full multi-user analyst→admin approval workflow is covered
by .cjs CI tests (`test_concurrent_approval_race.cjs`,
`test_concurrent_approval.cjs`).

These tests focus on what's tractable from the Python E2E layer:
- The approval queue UI renders for admin role
- The queue exposes admin actions (approve / reject)
- The REST API for `get_approval_queue` is reachable
"""
import pytest
import time
from tests.e2e.page_objects import ControlPanelPage


@pytest.mark.approval
@pytest.mark.e2e
def test_approval_queue_rest_api_reachable(rest_client):
    """The get_approval_queue REST action returns a dict — smoke."""
    queue = rest_client.get_action("get_approval_queue", {})
    assert isinstance(queue, dict), f"get_approval_queue returned non-dict: {queue!r}"
    # The dict may have `approval_queue`, `items`, or be empty —
    # all are valid responses depending on dispatch shape.


@pytest.mark.approval
@pytest.mark.e2e
def test_admin_sees_approval_queue_tab(admin_browser):
    """Admin can open the Approval Queue tab in Control Panel."""
    page = ControlPanelPage(admin_browser)
    page.goto_app()
    count = page.get_approval_queue()
    assert isinstance(count, int) and count >= 0


@pytest.mark.approval
@pytest.mark.e2e
@pytest.mark.skip(reason=(
    "Requires multi-user analyst→admin submit+approve flow. The legacy "
    "test called REST `submit_approval` with the wrong signature; rebuilding "
    "this needs a real analyst-tier user (analyst1) AND the dual-browser "
    "fixture works around state-leak issues. .cjs CI suite already covers "
    "this end-to-end (test_concurrent_approval.cjs, test_concurrent_approval_race.cjs)."
))
def test_admin_approves_request(admin_browser, rest_client):
    """Placeholder: see skip reason."""
    pass


@pytest.mark.approval
@pytest.mark.e2e
@pytest.mark.skip(reason="Same multi-user dependency as test_admin_approves_request.")
def test_admin_rejects_request(admin_browser, rest_client):
    """Placeholder: see skip reason."""
    pass


@pytest.mark.approval
@pytest.mark.e2e
@pytest.mark.skip(reason="Audit-chain check depends on the multi-user flow that's not yet ported.")
def test_approval_audit_chain(admin_browser, rest_client):
    """Placeholder: see skip reason."""
    pass


@pytest.mark.approval
@pytest.mark.e2e
@pytest.mark.skip(reason=(
    "RBAC test that requires analyst1 role (not built-in admin). The conftest "
    "`browser` fixture uses built-in admin, which has Splunk's full capability "
    "set and bypasses wl_manager's RBAC tiers — so this test would always "
    "pass for the wrong reasons. Defer to .cjs role-matrix tests "
    "(test_role_analyst.cjs)."
))
def test_analyst_limited_approval_permissions(browser, rest_client):
    """Placeholder: see skip reason."""
    pass
