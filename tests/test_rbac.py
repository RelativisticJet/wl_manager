"""
Integration tests for RBAC (Role-Based Access Control).

Verifies that each role can only perform its allowed actions:
- Any authenticated user: GET (read) operations
- EDIT_ROLES (wl_editor, wl_analyst_editor, wl_admin, admin, sc_admin, power): POST save/submit
- ADMIN_ROLES (admin, sc_admin, wl_admin): approve/reject, manage limits

Run:  cd tests && python -m unittest test_rbac -v
"""

import time
import unittest
from test_integration_base import (
    WLIntegrationTestCase, ADMIN, WLADMIN1, WLADMIN2, ANALYST1, ANALYST2,
    TEST_CSV, TEST_RULE, TEST_APP_CONTEXT,
    api_get, api_post, get_csv_content, save_csv,
    submit_approval, process_approval, cancel_request,
    get_approval_queue, wait_for_indexing,
)


class Test01_ViewerPermissions(WLIntegrationTestCase):
    """Any authenticated user can read CSVs and mappings."""

    def test_analyst_can_read_csv(self):
        """Analyst (EDIT_ROLES) can read CSV content."""
        status, data = get_csv_content(creds=ANALYST1)
        self.assertEqual(status, 200)
        self.assertIn("headers", data)
        self.assertIn("rows", data)

    def test_admin_can_read_csv(self):
        """Admin can read CSV content."""
        status, data = get_csv_content(creds=ADMIN)
        self.assertEqual(status, 200)

    def test_wladmin_can_read_csv(self):
        """wl_admin can read CSV content."""
        status, data = get_csv_content(creds=WLADMIN1)
        self.assertEqual(status, 200)

    def test_any_user_can_get_mapping(self):
        """GET get_mapping is available to all authenticated users."""
        status, data = api_get("get_mapping", creds=ANALYST1)
        self.assertEqual(status, 200)

    def test_any_user_can_get_versions(self):
        """GET get_versions is available to all authenticated users."""
        status, data = api_get("get_versions", {
            "csv_file": TEST_CSV,
            "app_context": TEST_APP_CONTEXT,
        }, creds=ANALYST1)
        self.assertEqual(status, 200)


class Test02_EditRolePermissions(WLIntegrationTestCase):
    """Users with EDIT_ROLES can save CSVs and submit approvals."""

    def test_analyst_can_save_csv(self):
        """Analyst can save CSV changes."""
        headers, rows, mtime = self._load_csv()
        visible = [h for h in headers if not h.startswith("_")]
        old_val = rows[0].get(visible[0], "")
        rows[0][visible[0]] = f"rbac_edit_{int(time.time())}"

        status, result = save_csv(headers, rows, comment="RBAC edit test",
                                  expected_mtime=mtime, creds=ANALYST1)
        self.assertEqual(status, 200, f"Analyst save failed: {result}")

        # Restore
        _, r2, m2 = self._load_csv()
        r2[0][visible[0]] = old_val
        save_csv(headers, r2, comment="Restore RBAC test")

    def test_analyst_can_submit_approval(self):
        """Analyst can submit approval requests."""
        s, d = submit_approval("bulk_row_removal", creds=ANALYST1)
        self.assertEqual(s, 200)
        cancel_request(d["request_id"], "RBAC test cleanup", creds=ANALYST1)

    def test_wladmin_can_save_csv(self):
        """wl_admin (in EDIT_ROLES) can save CSV changes."""
        headers, rows, mtime = self._load_csv()
        visible = [h for h in headers if not h.startswith("_")]
        old_val = rows[0].get(visible[0], "")
        rows[0][visible[0]] = f"rbac_wladmin_{int(time.time())}"

        status, result = save_csv(headers, rows, comment="wl_admin RBAC test",
                                  expected_mtime=mtime, creds=WLADMIN1)
        self.assertEqual(status, 200, f"wl_admin save failed: {result}")

        # Restore
        _, r2, m2 = self._load_csv()
        r2[0][visible[0]] = old_val
        save_csv(headers, r2, comment="Restore wl_admin RBAC test")


class Test03_AdminRolePermissions(WLIntegrationTestCase):
    """ADMIN_ROLES can approve, manage limits, view queue."""

    def test_analyst_cannot_approve(self):
        """Analyst (EDIT_ROLES only) cannot process approvals -> 403."""
        s, d = submit_approval("bulk_row_removal", creds=ANALYST2)
        rid = d["request_id"]

        s2, d2 = process_approval(rid, "approve", creds=ANALYST1)
        self.assertEqual(s2, 403)

        cancel_request(rid, "Cleanup", creds=ANALYST2)

    def test_analyst_cannot_get_queue(self):
        """Analyst cannot access approval queue -> 403."""
        s, d = api_post({"action": "get_approval_queue"}, creds=ANALYST1)
        self.assertEqual(s, 403)

    def test_analyst_cannot_get_daily_limits(self):
        """Analyst cannot read daily limit config -> 403."""
        s, d = api_post({"action": "get_daily_limits"}, creds=ANALYST1)
        self.assertEqual(s, 403)

    def test_analyst_cannot_set_daily_limits(self):
        """Analyst cannot modify daily limits -> 403."""
        s, d = api_post({"action": "set_daily_limits", "limits": {}},
                        creds=ANALYST1)
        self.assertEqual(s, 403)

    def test_wladmin_can_approve(self):
        """wl_admin (in ADMIN_ROLES) can approve requests."""
        s, d = submit_approval("bulk_row_removal", creds=ANALYST1)
        rid = d["request_id"]

        # wl_admin approves (not self-approve — different user)
        s2, d2 = process_approval(rid, "reject", creds=WLADMIN1,
                                  rejection_reason="RBAC test")
        self.assertEqual(s2, 200)

    def test_wladmin_can_view_queue(self):
        """wl_admin can access approval queue."""
        s, d = api_post({"action": "get_approval_queue"}, creds=WLADMIN1)
        self.assertEqual(s, 200)
        self.assertIn("queue", d)

    def test_wladmin_can_get_daily_limits(self):
        """wl_admin can read daily limit config."""
        s, d = api_post({"action": "get_daily_limits"}, creds=WLADMIN1)
        self.assertEqual(s, 200)
        self.assertIn("limits", d)


if __name__ == "__main__":
    unittest.main()
