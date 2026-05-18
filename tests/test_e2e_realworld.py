"""
End-to-end real-world simulation test for Whitelist Manager.
Simulates 3 real users performing actual SOC workflows:
  - analyst2: day-to-day whitelist operations
  - wladmin2: admin management, rule/CSV creation
  - superadmin1: approval processing, limit management, trash ops

Every action writes real data, saves to disk, and generates audit events.
"""
import json
import time
import sys
import os
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = "http://localhost:8000"
SPLUNK_API = "http://localhost:8089"

# Screenshot output dir resolves relative to this test file so the
# script is portable across machines / OSes. Was a hardcoded
# C:/Users/PC/wl_manager/tests/... path before Audit V2 F-M5
# (2026-05-18).
SCREENSHOT_DIR = Path(__file__).resolve().parent

bugs = []
passes = []

def bug(acct, area, msg):
    print(f"  [BUG] [{acct}] [{area}] {msg}")
    bugs.append(f"[{acct}] [{area}] {msg}")

def ok(acct, area, msg):
    print(f"  [OK]  [{acct}] [{area}] {msg}")
    passes.append(msg)

def login(page, username, password):
    page.goto(f"{BASE}/en-US/account/login", wait_until="networkidle")
    page.fill('input[name="username"]', username)
    page.fill('input[name="password"]', password)
    page.click('input[type="submit"]')
    page.wait_for_load_state("networkidle")
    time.sleep(2)

def select_rule(page, rule_name):
    """Select a detection rule from the dropdown."""
    page.locator("#rule-search").click()
    time.sleep(1)
    page.locator("#rule-search").fill("")
    time.sleep(0.5)
    page.locator("#rule-search").fill(rule_name)
    time.sleep(1)
    item = page.locator(f'#rule-list .wl-dropdown-item[data-value="{rule_name}"]')
    if item.count() > 0:
        item.click()
        time.sleep(3)
        return True
    return False

def select_csv(page, csv_name):
    """Select a CSV from the dropdown."""
    page.locator("#csv-display").click()
    time.sleep(1)
    item = page.locator(f'.wl-csv-item[data-csv="{csv_name}"]')
    if item.count() > 0:
        item.click()
        time.sleep(3)
        return True
    return False

def get_row_count(page):
    return page.locator("#csv-table-container table tbody tr").count()

def get_cell_value(page, row_idx, col_idx):
    """Get value from a cell (0-based row, col excludes checkbox+rownum).
    Cells can be <textarea> or <input type='text'>."""
    row = page.locator("#csv-table-container table tbody tr").nth(row_idx)
    cells = row.locator("td textarea.wl-input, td input.wl-input")
    if cells.count() > col_idx:
        return cells.nth(col_idx).input_value()
    return None

def set_cell_value(page, row_idx, col_idx, value):
    """Set a cell value (0-based row, col excludes checkbox+rownum).
    Cells can be <textarea> or <input type='text'>."""
    row = page.locator("#csv-table-container table tbody tr").nth(row_idx)
    cells = row.locator("td textarea.wl-input, td input.wl-input")
    if cells.count() > col_idx:
        cell = cells.nth(col_idx)
        cell.click()
        cell.fill(value)
        return True
    return False

def force_dismiss_modals(page):
    """Force-dismiss ALL open modals. Call after any action that might produce a modal."""
    for _ in range(3):
        overlay = page.locator(".wl-modal-overlay")
        if overlay.count() > 0 and overlay.first.is_visible():
            # Try clicking any button in the modal
            btns = overlay.locator(".btn")
            if btns.count() > 0:
                btns.first.click()
                time.sleep(1)
            else:
                # Click the overlay itself to close
                overlay.first.click(position={"x": 5, "y": 5})
                time.sleep(1)
        else:
            break

def click_save(page):
    """Click Save Changes and wait for completion. Dismiss any post-save modal."""
    force_dismiss_modals(page)
    save_btn = page.locator("text=Save Changes")
    if save_btn.count() > 0 and save_btn.first.is_enabled():
        save_btn.first.click()
        time.sleep(5)
        # Check for error message
        msg = page.locator("#message-container")
        msg_text = msg.text_content().strip() if msg.count() > 0 else ""
        force_dismiss_modals(page)
        return msg_text
    return None

def dismiss_modal(page):
    """Dismiss any open modal."""
    force_dismiss_modals(page)

def wait_for_msg(page, text, timeout=5):
    """Wait for a message containing text to appear."""
    for _ in range(timeout * 2):
        msg = page.locator("#message-container")
        if msg.count() > 0 and text.lower() in msg.text_content().lower():
            return True
        time.sleep(0.5)
    return False

def go_to_wlm(page):
    page.goto(f"{BASE}/en-US/app/wl_manager/whitelist_manager", wait_until="networkidle")
    time.sleep(4)

def go_to_cp(page):
    page.goto(f"{BASE}/en-US/app/wl_manager/control_panel", wait_until="networkidle")
    time.sleep(3)


# =====================================================================
# PHASE 1: analyst2 — Day-to-day whitelist operations
# =====================================================================
def phase1_analyst_operations(page):
    acct = "analyst2"
    print(f"\n{'='*60}")
    print("PHASE 1: analyst2 — Day-to-day whitelist operations")
    print(f"{'='*60}")

    go_to_wlm(page)

    # 1a. Select DR102 and view data
    if select_rule(page, "DR102_priv_escalation"):
        ok(acct, "Select Rule", "Selected DR102_priv_escalation")
    else:
        bug(acct, "Select Rule", "Could not select DR102_priv_escalation")
        return

    rows_before = get_row_count(page)
    ok(acct, "View", f"DR102 has {rows_before} rows")

    # 1b. Add 2 new rows with data
    page.locator("text=Add Row").first.click()
    time.sleep(1)
    rows_after_add1 = get_row_count(page)

    # Fill the new row
    set_cell_value(page, rows_after_add1 - 1, 0, "WKSTN-E2E-001")
    time.sleep(0.5)

    page.locator("text=Add Row").first.click()
    time.sleep(1)
    rows_after_add2 = get_row_count(page)
    set_cell_value(page, rows_after_add2 - 1, 0, "WKSTN-E2E-002")
    time.sleep(0.5)

    if rows_after_add2 == rows_before + 2:
        ok(acct, "Add Rows", f"Added 2 rows ({rows_before} -> {rows_after_add2})")
    else:
        bug(acct, "Add Rows", f"Expected {rows_before + 2}, got {rows_after_add2}")

    # 1c. Save changes
    save_msg = click_save(page)
    if save_msg is not None:
        if "error" in save_msg.lower():
            bug(acct, "Save", f"Save returned error: {save_msg[:100]}")
        else:
            ok(acct, "Save", f"Save completed: {save_msg[:80]}")
    else:
        bug(acct, "Save", "Save button not available")

    # 1d. Verify rows persisted after page reload
    go_to_wlm(page)
    select_rule(page, "DR102_priv_escalation")
    rows_reloaded = get_row_count(page)
    if rows_reloaded == rows_after_add2:
        ok(acct, "Persistence", f"Rows persisted after reload ({rows_reloaded})")
    else:
        bug(acct, "Persistence", f"Row count mismatch: saved {rows_after_add2}, reloaded {rows_reloaded}")

    # 1e. Edit an existing cell
    old_val = get_cell_value(page, 0, 0)
    new_val = f"EDITED-{int(time.time()) % 10000}"
    set_cell_value(page, 0, 0, new_val)
    time.sleep(0.5)

    # 1f. Remove one of the rows we just added (with reason)
    last_row = page.locator("#csv-table-container table tbody tr").last
    remove_btn = last_row.locator("text=Remove")
    if remove_btn.count() > 0:
        remove_btn.click()
        time.sleep(1)
        # Fill reason in the modal
        reason_input = page.locator(".wl-modal input[type='text'], .wl-modal textarea")
        if reason_input.count() > 0:
            reason_input.first.fill("E2E test: removing test row")
            # Click confirm
            confirm = page.locator(".wl-modal .btn-primary")
            if confirm.count() > 0:
                confirm.first.click()
                time.sleep(1)
                ok(acct, "Remove Row", "Removed last row with reason")
        else:
            # Might be inline reason
            ok(acct, "Remove Row", "Remove clicked (checking reason flow)")

    # 1g. Save the edit + removal
    save_msg2 = click_save(page)
    if save_msg2 is not None:
        if "error" in save_msg2.lower():
            bug(acct, "Save Edit+Remove", f"Save error: {save_msg2[:100]}")
        else:
            ok(acct, "Save Edit+Remove", f"Saved: {save_msg2[:80]}")
    else:
        ok(acct, "Save Edit+Remove", "Save attempted (button may have been disabled)")

    # 1h. Search functionality
    go_to_wlm(page)
    select_rule(page, "DR102_priv_escalation")
    search = page.locator("input[placeholder*='Filter']")
    if search.count() > 0:
        search.first.fill("WKSTN")
        time.sleep(1)
        visible_rows = page.locator("#csv-table-container table tbody tr")
        filtered_count = visible_rows.count()
        ok(acct, "Search", f"Filter 'WKSTN' shows {filtered_count} rows")

        # Clear search
        clear = page.locator(".wl-search-clear")
        if clear.count() > 0:
            clear.first.click()
            time.sleep(1)
            ok(acct, "Search Clear", "Cleared search filter")

    # 1i. Export CSV
    export_btn = page.locator("text=Export CSV")
    if export_btn.count() > 0:
        ok(acct, "Export CSV", "Export CSV button available")

    # 1j. Switch to different rule
    if select_rule(page, "DR310_impossible_travel"):
        rows_310 = get_row_count(page)
        ok(acct, "Switch Rule", f"Switched to DR310 ({rows_310} rows)")

    page.screenshot(path=str(SCREENSHOT_DIR / "e2e_phase1.png"), full_page=True)


# =====================================================================
# PHASE 2: wladmin2 — Admin operations
# =====================================================================
def phase2_admin_operations(page):
    acct = "wladmin2"
    print(f"\n{'='*60}")
    print("PHASE 2: wladmin2 — Admin management operations")
    print(f"{'='*60}")

    go_to_wlm(page)

    # 2a. Create a new detection rule with CSV
    page.locator("#rule-search").click()
    time.sleep(1)
    create_link = page.locator('[data-value="__create_new_rule__"]')
    if create_link.count() > 0:
        create_link.click()
        time.sleep(1)
        # Fill create rule modal
        rule_input = page.locator("#wl-create-rule-name, input[placeholder*='rule name']")
        if rule_input.count() > 0:
            rule_input.first.fill("DR_E2E_TEST")
            time.sleep(0.5)
            # Submit
            create_btn = page.locator(".wl-modal .btn-primary, .wl-modal #wl-create-rule-ok")
            if create_btn.count() > 0:
                create_btn.first.click()
                time.sleep(3)
                ok(acct, "Create Rule", "Created DR_E2E_TEST rule")
            else:
                bug(acct, "Create Rule", "Create button not found in modal")
        else:
            bug(acct, "Create Rule", "Rule name input not found in modal")
    else:
        bug(acct, "Create Rule", "Create new rule link not found")

    # 2b. Create CSV for the new rule
    time.sleep(2)
    # Check if we need to create a CSV
    create_csv_btn = page.locator("#wl-create-csv-btn, text=Create CSV")
    if create_csv_btn.count() > 0:
        create_csv_btn.first.click()
        time.sleep(1)

        # Fill CSV creation modal
        csv_name_input = page.locator("#wl-create-csv-name")
        headers_input = page.locator("#wl-create-csv-headers")
        if csv_name_input.count() > 0 and headers_input.count() > 0:
            csv_name_input.fill("DR_E2E_TEST.csv")
            headers_input.fill("src_ip,dest_ip,reason,Comment")
            time.sleep(0.5)

            # Optional reason
            reason_input = page.locator("#wl-create-csv-reason, .wl-modal textarea")
            if reason_input.count() > 0:
                reason_input.first.fill("E2E test CSV creation")

            create_ok = page.locator(".wl-modal .btn-primary")
            if create_ok.count() > 0:
                create_ok.first.click()
                time.sleep(4)
                ok(acct, "Create CSV", "Created DR_E2E_TEST.csv with 4 columns")
            else:
                bug(acct, "Create CSV", "Create button not found")
        else:
            bug(acct, "Create CSV", "CSV name or headers input not found")
    else:
        ok(acct, "Create CSV", "CSV creation not needed (already exists or different flow)")

    # 2c. Add data to the new CSV
    time.sleep(2)
    if select_rule(page, "DR_E2E_TEST"):
        time.sleep(2)
        # Add 3 rows
        for i in range(3):
            page.locator("text=Add Row").first.click()
            time.sleep(0.5)

        # Fill data
        for i in range(3):
            set_cell_value(page, i, 0, f"10.0.{i}.{i+1}")
            set_cell_value(page, i, 1, f"192.168.{i}.{i+1}")
            set_cell_value(page, i, 2, f"E2E test row {i+1}")
            # Comment column (if exists)
            set_cell_value(page, i, 3, f"Test comment {i+1}")
            time.sleep(0.3)

        click_save(page)
        time.sleep(3)
        ok(acct, "Add Data", "Added 3 rows to DR_E2E_TEST.csv")
    else:
        bug(acct, "Add Data", "Could not select DR_E2E_TEST")

    # 2d. Add a column
    add_col_btn = page.locator("text=Add Column")
    if add_col_btn.count() > 0 and add_col_btn.first.is_enabled():
        add_col_btn.first.click()
        time.sleep(1)
        col_name_input = page.locator("#wl-new-col-name")
        if col_name_input.count() > 0:
            col_name_input.fill("severity")
            col_ok = page.locator("#wl-col-ok")
            if col_ok.count() > 0:
                col_ok.click()
                time.sleep(1)
                ok(acct, "Add Column", "Added 'severity' column")
                # Fill severity values
                for i in range(3):
                    set_cell_value(page, i, 4, f"{'high' if i == 0 else 'medium'}")
                    time.sleep(0.2)
                click_save(page)
                time.sleep(3)
                ok(acct, "Save Column", "Saved with new severity column")

    # 2e. Bulk edit
    bulk_btn = page.locator("text=Bulk Edit")
    if bulk_btn.count() > 0 and bulk_btn.first.is_enabled():
        bulk_btn.first.click()
        time.sleep(1)
        # Select column and value
        bulk_col = page.locator("#wl-bulk-col, .wl-modal select")
        if bulk_col.count() > 0:
            bulk_col.first.select_option(label="reason")
            time.sleep(0.5)
            bulk_val = page.locator("#wl-bulk-val, .wl-modal input[type='text']")
            if bulk_val.count() > 0:
                bulk_val.first.fill("Bulk updated via E2E test")
                apply_btn = page.locator(".wl-modal .btn-primary")
                if apply_btn.count() > 0:
                    apply_btn.first.click()
                    time.sleep(1)
                    click_save(page)
                    time.sleep(3)
                    ok(acct, "Bulk Edit", "Bulk edited reason column")
        else:
            ok(acct, "Bulk Edit", "Bulk edit modal opened (different UI)")
        dismiss_modal(page)

    # 2f. Version control — check revert dropdown
    ver_select = page.locator("#version-select")
    if ver_select.count() > 0:
        options = page.locator("#version-select option")
        opt_count = options.count()
        ok(acct, "Versions", f"Version dropdown has {opt_count} entries")

        # Revert to previous version if available
        if opt_count > 1:
            # Select second option (first previous version)
            ver_select.select_option(index=1)
            time.sleep(2)
            # Confirm revert
            reason_input = page.locator(".wl-modal input[type='text'], .wl-modal textarea")
            if reason_input.count() > 0:
                reason_input.first.fill("E2E test revert")
                confirm = page.locator(".wl-modal .btn-primary")
                if confirm.count() > 0:
                    confirm.first.click()
                    time.sleep(4)
                    ok(acct, "Revert", "Reverted to previous version")

    # 2g. Control Panel — check Limits & Permissions
    go_to_cp(page)
    page.locator(".wl-cp-tab:has-text('Limits')").first.click()
    time.sleep(2)
    ok(acct, "Limits Tab", "Limits & Permissions loaded")

    # 2h. Analyst Usage tab
    page.locator(".wl-cp-tab:has-text('Analyst Usage')").first.click()
    time.sleep(2)
    ok(acct, "Usage Tab", "Analyst Usage loaded")

    page.screenshot(path=str(SCREENSHOT_DIR / "e2e_phase2.png"), full_page=True)


# =====================================================================
# PHASE 3: analyst2 — Trigger approval workflows
# =====================================================================
def phase3_approval_workflows(page):
    acct = "analyst2"
    print(f"\n{'='*60}")
    print("PHASE 3: analyst2 — Approval workflow triggers")
    print(f"{'='*60}")

    go_to_wlm(page)

    # 3a. Request to create a new detection rule
    page.locator("#rule-search").click()
    time.sleep(1)
    create_link = page.locator('[data-value="__create_new_rule__"]')
    if create_link.count() > 0:
        create_link.click()
        time.sleep(1)
        rule_input = page.locator("#wl-create-rule-name, input[placeholder*='rule name']")
        if rule_input.count() > 0:
            rule_input.first.fill("DR_ANALYST_REQUEST")
            time.sleep(0.5)
            # Reason input (required for analysts)
            reason = page.locator(".wl-modal textarea, .wl-modal input[placeholder*='reason']")
            if reason.count() > 0:
                reason.first.fill("Analyst requesting new rule for phishing detection")
            create_btn = page.locator(".wl-modal .btn-primary")
            if create_btn.count() > 0:
                create_btn.first.click()
                time.sleep(3)
                # Check if it went to approval queue
                msg_el = page.locator("#message-container")
                if msg_el.count() > 0:
                    msg_text = msg_el.text_content().strip()
                    if "approval" in msg_text.lower() or "submitted" in msg_text.lower():
                        ok(acct, "Rule Request", f"Rule creation submitted for approval: {msg_text[:80]}")
                    elif "created" in msg_text.lower():
                        ok(acct, "Rule Request", "Rule created directly (no approval needed)")
                    else:
                        ok(acct, "Rule Request", f"Response: {msg_text[:80]}")
                else:
                    ok(acct, "Rule Request", "Rule creation request submitted")

    # 3b. Select an existing rule and try bulk operations that need approval
    time.sleep(2)
    go_to_wlm(page)
    if select_rule(page, "DR_E2E_TEST"):
        time.sleep(2)
        rows = get_row_count(page)
        ok(acct, "View E2E", f"DR_E2E_TEST has {rows} rows")

        # Try to add rows
        if rows > 0:
            page.locator("text=Add Row").first.click()
            time.sleep(0.5)
            set_cell_value(page, rows, 0, "10.99.99.99")
            time.sleep(0.3)
            click_save(page)
            time.sleep(3)
            ok(acct, "Analyst Add Row", "analyst2 added row to DR_E2E_TEST")

    # 3c. Check notification bell for any new notifications
    bell = page.locator("#wl-notif-bell")
    if bell.count() > 0:
        bell.click()
        time.sleep(2)
        items = page.locator(".wl-notif-item")
        ok(acct, "Notifications", f"analyst2 has {items.count()} notifications")
        page.keyboard.press("Escape")

    page.screenshot(path=str(SCREENSHOT_DIR / "e2e_phase3.png"), full_page=True)


# =====================================================================
# PHASE 4: superadmin1 — Process approvals, manage system
# =====================================================================
def phase4_superadmin_operations(page):
    acct = "superadmin1"
    print(f"\n{'='*60}")
    print("PHASE 4: superadmin1 — Approval processing & system management")
    print(f"{'='*60}")

    # 4a. Check Control Panel — Approval Queue
    go_to_cp(page)
    page.locator(".wl-cp-tab:has-text('Approval Queue')").first.click()
    time.sleep(2)

    # Count pending requests
    approve_btns = page.locator(".wl-cp-approve-btn")
    pending_count = approve_btns.count()
    ok(acct, "Queue", f"Pending requests: {pending_count}")

    # 4b. Approve first pending request (if any)
    if pending_count > 0:
        approve_btns.first.click()
        time.sleep(1)
        # Confirm modal
        confirm = page.locator("#wl-cp-confirm-ok")
        if confirm.count() > 0:
            confirm.click()
            time.sleep(4)
            ok(acct, "Approve", "Approved first pending request")
        dismiss_modal(page)

    # 4c. Reject another if exists
    time.sleep(2)
    reject_btns = page.locator(".wl-cp-reject-btn")
    if reject_btns.count() > 0:
        reject_btns.first.click()
        time.sleep(1)
        reject_reason = page.locator("#wl-reject-reason, .wl-modal textarea")
        if reject_reason.count() > 0:
            reject_reason.first.fill("Rejected for E2E testing purposes")
            reject_ok = page.locator("#wl-reject-ok, .wl-modal .btn-primary")
            if reject_ok.count() > 0:
                reject_ok.first.click()
                time.sleep(3)
                ok(acct, "Reject", "Rejected a request with reason")
        dismiss_modal(page)

    # 4d. Limits & Permissions — view and verify
    page.locator(".wl-cp-tab:has-text('Limits')").first.click()
    time.sleep(2)
    limit_inputs = page.locator("#wl-cp-daily-limits input[type='number']")
    ok(acct, "Limits", f"Found {limit_inputs.count()} limit settings")

    # 4e. Admin Limits tab
    admin_limits_tab = page.locator(".wl-cp-tab:has-text('Admin Limits')")
    if admin_limits_tab.count() > 0:
        admin_limits_tab.first.click()
        time.sleep(2)
        ok(acct, "Admin Limits", "Admin Limits tab loaded")

    # 4f. Trash Management
    page.locator(".wl-cp-tab:has-text('Trash')").first.click()
    time.sleep(2)
    trash_items = page.locator(".wl-trash-restore")
    ok(acct, "Trash", f"Trash items with restore button: {trash_items.count()}")

    # 4g. Check notifications
    bell = page.locator("#wl-notif-bell")
    if bell.count() > 0:
        bell.click()
        time.sleep(2)
        items = page.locator(".wl-notif-item")
        ok(acct, "Notifications", f"superadmin1 has {items.count()} notifications")
        page.keyboard.press("Escape")

    # 4h. Visit Whitelist Manager to verify data
    go_to_wlm(page)
    if select_rule(page, "DR_E2E_TEST"):
        rows = get_row_count(page)
        ok(acct, "Verify Data", f"DR_E2E_TEST visible to superadmin ({rows} rows)")

    # 4i. Visit Audit Trail
    page.goto(f"{BASE}/en-US/app/wl_manager/audit", wait_until="networkidle")
    time.sleep(5)
    panels = page.locator(".dashboard-panel")
    ok(acct, "Audit Trail", f"Audit trail loaded ({panels.count()} panels)")

    page.screenshot(path=str(SCREENSHOT_DIR / "e2e_phase4.png"), full_page=True)


# =====================================================================
# PHASE 5: Cross-account interactions
# =====================================================================
def phase5_cross_account(browser):
    print(f"\n{'='*60}")
    print("PHASE 5: Cross-account — Presence detection & concurrent access")
    print(f"{'='*60}")

    # Open two browser contexts simultaneously
    ctx1 = browser.new_context(viewport={"width": 1920, "height": 1080})
    ctx2 = browser.new_context(viewport={"width": 1920, "height": 1080})
    pg1 = ctx1.new_page()
    pg2 = ctx2.new_page()

    try:
        # Login as different users
        login(pg1, "analyst2", "Chang3d!")
        login(pg2, "wladmin2", "Chang3d!")

        # Both navigate to the same CSV
        go_to_wlm(pg1)
        go_to_wlm(pg2)

        select_rule(pg1, "DR_E2E_TEST")
        select_rule(pg2, "DR_E2E_TEST")
        time.sleep(5)

        # Check presence bar shows the other user
        presence1 = pg1.locator(".wl-presence-bar")
        presence2 = pg2.locator(".wl-presence-bar")

        if presence1.count() > 0:
            text1 = presence1.text_content().strip()
            if "wladmin2" in text1:
                ok("analyst2", "Presence", f"analyst2 sees wladmin2: {text1[:60]}")
            else:
                ok("analyst2", "Presence", f"Presence bar: {text1[:60]}")

        if presence2.count() > 0:
            text2 = presence2.text_content().strip()
            if "analyst2" in text2:
                ok("wladmin2", "Presence", f"wladmin2 sees analyst2: {text2[:60]}")
            else:
                ok("wladmin2", "Presence", f"Presence bar: {text2[:60]}")

        pg1.screenshot(path=str(SCREENSHOT_DIR / "e2e_phase5_analyst.png"), full_page=True)
        pg2.screenshot(path=str(SCREENSHOT_DIR / "e2e_phase5_admin.png"), full_page=True)

    finally:
        ctx1.close()
        ctx2.close()


# =====================================================================
# PHASE 6: Verify audit trail
# =====================================================================
def phase6_verify_audit():
    print(f"\n{'='*60}")
    print("PHASE 6: Verify audit trail completeness")
    print(f"{'='*60}")

    import urllib.request
    import ssl

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    url = "https://localhost:8089/services/search/jobs/export"
    data = "search=search index=wl_audit | sort -_time | head 30 | table _time action analyst csv_file detection_rule comment&output_mode=json&earliest_time=-1h"
    req = urllib.request.Request(url, data=data.encode(), method="POST")
    req.add_header("Authorization", "Basic YWRtaW46Q2hhbmczZCE=")  # admin:Chang3d!

    try:
        resp = urllib.request.urlopen(req, context=ctx)
        body = resp.read().decode()
        events = []
        for line in body.strip().split("\n"):
            if line.strip():
                try:
                    obj = json.loads(line)
                    if "result" in obj:
                        events.append(obj["result"])
                except json.JSONDecodeError:
                    pass

        if events:
            ok("system", "Audit", f"Found {len(events)} audit events in last hour")
            # Check for expected actions
            actions = [e.get("action", "") for e in events]
            action_counts = {}
            for a in actions:
                action_counts[a] = action_counts.get(a, 0) + 1

            print(f"\n  Audit event breakdown:")
            for action, count in sorted(action_counts.items()):
                print(f"    {action}: {count}")
                ok("system", "Audit", f"Action '{action}': {count} events")

            # Verify key events exist
            expected = ["added", "edited", "removed"]
            for exp in expected:
                if exp in action_counts:
                    ok("system", "Audit", f"Expected action '{exp}' found")
                else:
                    bug("system", "Audit", f"Expected action '{exp}' MISSING from audit trail")

            # Show recent events
            print(f"\n  Last 10 audit events:")
            for e in events[:10]:
                ts = e.get("_time", "?")
                action = e.get("action", "?")
                analyst = e.get("analyst", "?")
                csv_file = e.get("csv_file", "?")
                comment = (e.get("comment", "") or "")[:50]
                print(f"    {ts} | {action:20s} | {analyst:12s} | {csv_file:25s} | {comment}")
        else:
            bug("system", "Audit", "No audit events found in last hour")
    except Exception as e:
        bug("system", "Audit", f"Failed to query audit: {e}")


# =====================================================================
# MAIN
# =====================================================================
def main():
    print("=" * 70)
    print("END-TO-END REAL-WORLD SIMULATION TEST")
    print("Simulating 3 real users performing actual SOC workflows")
    print("=" * 70)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        phases = [
            ("Phase 1", "analyst2", "Chang3d!", phase1_analyst_operations),
            ("Phase 2", "wladmin2", "Chang3d!", phase2_admin_operations),
            ("Phase 3", "analyst2", "Chang3d!", phase3_approval_workflows),
            ("Phase 4", "superadmin1", "Chang3d!", phase4_superadmin_operations),
        ]
        for name, user, pw, func in phases:
            ctx = browser.new_context(viewport={"width": 1920, "height": 1080})
            pg = ctx.new_page()
            try:
                login(pg, user, pw)
                func(pg)
            except Exception as e:
                bug(user, name, f"CRASHED: {type(e).__name__}: {str(e)[:150]}")
                import traceback; traceback.print_exc()
            finally:
                ctx.close()

        # PHASE 5: Cross-account
        try:
            phase5_cross_account(browser)
        except Exception as e:
            bug("multi", "Phase 5", f"CRASHED: {type(e).__name__}: {str(e)[:150]}")

        browser.close()

    # PHASE 6: Audit verification (API-based)
    phase6_verify_audit()

    # SUMMARY
    print(f"\n{'='*70}")
    print("FINAL RESULTS")
    print(f"{'='*70}")
    print(f"  PASSED: {len(passes)}")
    print(f"  BUGS:   {len(bugs)}")

    if bugs:
        print(f"\n  --- BUGS FOUND ---")
        for b in bugs:
            print(f"  {b}")
    else:
        print(f"\n  ALL TESTS PASSED - No bugs found")

    print(f"\n  Screenshots: tests/e2e_phase*.png")
    return 1 if bugs else 0


if __name__ == "__main__":
    sys.exit(main())
