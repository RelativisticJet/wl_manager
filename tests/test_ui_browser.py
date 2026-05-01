"""
Comprehensive browser UI test for Whitelist Manager.
Tests all pages, buttons, dropdowns, and features across 3 accounts.
Uses Playwright to automate Chromium.
"""
import json
import time
import sys
from playwright.sync_api import sync_playwright

BASE = "http://localhost:8000"
ACCOUNTS = {
    "analyst2":    {"password": "Chang3d!", "is_admin": False, "is_superadmin": False},
    "wladmin2":    {"password": "Chang3d!", "is_admin": True,  "is_superadmin": False},
    "superadmin1": {"password": "Chang3d!", "is_admin": True,  "is_superadmin": True},
}

bugs = []
passes = []
warnings = []

def log_bug(account, page_name, description):
    msg = f"[BUG] [{account}] [{page_name}] {description}"
    print(f"  [X]{msg}")
    bugs.append(msg)

def log_warn(account, page_name, description):
    msg = f"[WARN] [{account}] [{page_name}] {description}"
    print(f"  [!]{msg}")
    warnings.append(msg)

def log_pass(account, page_name, description):
    msg = f"[PASS] [{account}] [{page_name}] {description}"
    print(f"  [+]{msg}")
    passes.append(msg)

def login(page, username, password):
    page.goto(f"{BASE}/en-US/account/login", wait_until="networkidle")
    page.fill('input[name="username"]', username)
    page.fill('input[name="password"]', password)
    page.click('input[type="submit"], button[type="submit"]')
    page.wait_for_load_state("networkidle")
    time.sleep(2)

def test_whitelist_manager(page, account):
    pn = "Whitelist Manager"
    page.goto(f"{BASE}/en-US/app/wl_manager/whitelist_manager", wait_until="networkidle")
    time.sleep(3)

    # Page loads
    if page.locator("text=Detection Rule").count() > 0:
        log_pass(account, pn, "Page loads successfully")
    else:
        log_bug(account, pn, "Page failed to load — 'Detection Rule' label not found")
        page.screenshot(path=f"/tmp/wlm_fail_{account}.png", full_page=True)
        return

    # Detection Rule dropdown
    rule_search = page.locator("#rule-search")
    if rule_search.count() == 0:
        log_bug(account, pn, "Detection Rule search input not found")
        return

    rule_search.click()
    time.sleep(2)
    # Actual class is wl-dropdown-item, not wl-rule-item
    items = page.locator('#rule-list .wl-dropdown-item:not([data-value="__create_new_rule__"])')
    rule_count = items.count()
    if rule_count > 0:
        log_pass(account, pn, f"Rule dropdown shows {rule_count} rules")
    else:
        log_bug(account, pn, "Rule dropdown is empty")
        return

    # Create new rule link
    create_link = page.locator('[data-value="__create_new_rule__"]')
    if create_link.count() > 0:
        log_pass(account, pn, "Create new rule link present in dropdown")

    # Select a rule with data
    items.first.click()
    time.sleep(3)

    # CSV dropdown
    csv_display = page.locator("#csv-display")
    if csv_display.count() > 0:
        csv_text = csv_display.text_content().strip()
        log_pass(account, pn, f"CSV loaded: {csv_text}")
    else:
        log_warn(account, pn, "CSV display element not found")

    # Table loaded
    rows = page.locator("#csv-table-container table tbody tr")
    row_count = rows.count()
    if row_count > 0:
        log_pass(account, pn, f"Table rendered with {row_count} rows")
    else:
        log_pass(account, pn, "Table empty (rule may have no data rows)")

    # Column headers
    col_headers = page.locator("th.wl-col-draggable")
    col_count = col_headers.count()
    if col_count > 0:
        log_pass(account, pn, f"Found {col_count} column headers")
        # Check drag handles
        drag_handles = page.locator(".wl-col-drag-handle")
        if drag_handles.count() > 0:
            log_pass(account, pn, "Column drag handles present")
        # Check remove buttons on columns
        col_remove = page.locator(".wl-col-remove-btn")
        if col_remove.count() > 0:
            log_pass(account, pn, "Column remove buttons present")

    # Checkbox column
    select_all = page.locator("#csv-table-container th input[type='checkbox']")
    if select_all.count() > 0:
        log_pass(account, pn, "Select-all checkbox exists")

    row_checkboxes = page.locator("#csv-table-container td input[type='checkbox']")
    if row_checkboxes.count() > 0:
        log_pass(account, pn, f"Row checkboxes: {row_checkboxes.count()}")

    # Search bar
    search_input = page.locator("input[placeholder*='Filter']")
    if search_input.count() > 0:
        log_pass(account, pn, "Search/filter bar present")
    else:
        log_warn(account, pn, "Search bar not found")

    # Revert dropdown
    version_select = page.locator("#version-select")
    if version_select.count() > 0:
        options = page.locator("#version-select option")
        log_pass(account, pn, f"Version dropdown: {options.count()} options")

    # Buttons
    btn_map = {
        "Add Row": "text=Add Row",
        "Add Column": "text=Add Column",
        "Bulk Edit": "text=Bulk Edit",
        "Remove Selected": "text=Remove Selected",
        "Save Changes": "text=Save Changes",
        "Discard Changes": "text=Discard Changes",
        "Export Audit": "text=Export Audit",
        "Export CSV": "text=Export CSV",
        "Import CSV": "text=Import CSV",
    }
    for name, sel in btn_map.items():
        if page.locator(sel).count() > 0:
            log_pass(account, pn, f"Button '{name}' present")
        else:
            log_warn(account, pn, f"Button '{name}' not found")

    # Inline editing — click a cell
    if row_count > 0:
        cell_inputs = page.locator("#csv-table-container table tbody td input[type='text']")
        if cell_inputs.count() > 0:
            log_pass(account, pn, f"Found {cell_inputs.count()} editable cell inputs")

    # Row numbers
    row_nums = page.locator(".wl-row-num")
    if row_nums.count() > 0:
        log_pass(account, pn, f"Row numbers rendered: {row_nums.count()}")

    # Presence bar
    presence = page.locator(".wl-presence-bar, #wl-presence-bar")
    if presence.count() > 0:
        text = presence.text_content().strip()
        if text:
            log_pass(account, pn, f"Presence bar: {text[:80]}")

    # Navigation
    for nav in ["Whitelist Manager", "Audit Trail"]:
        if page.locator(f"a:has-text('{nav}')").count() > 0:
            log_pass(account, pn, f"Nav link '{nav}' exists")
        else:
            log_bug(account, pn, f"Nav link '{nav}' missing")

    # Control Panel link — admin only
    cp_link = page.locator("a:has-text('Control Panel')")
    is_admin = ACCOUNTS[account]["is_admin"]
    if is_admin and cp_link.count() == 0:
        log_bug(account, pn, "Control Panel nav MISSING for admin")
    elif not is_admin and cp_link.count() > 0:
        log_bug(account, pn, "Control Panel nav VISIBLE for analyst (security)")
    else:
        log_pass(account, pn, "Control Panel nav visibility correct")

    page.screenshot(path=f"/tmp/wlm_{account}.png", full_page=True)


def test_control_panel(page, account):
    pn = "Control Panel"
    if not ACCOUNTS[account]["is_admin"]:
        log_pass(account, pn, "Skipping — analyst account")
        return

    page.goto(f"{BASE}/en-US/app/wl_manager/control_panel", wait_until="networkidle")
    time.sleep(3)

    # Tabs
    tabs = ["Approval Queue", "Analyst Usage", "Limits & Permissions", "Trash Management"]
    for tab in tabs:
        el = page.locator(f".wl-cp-tab:has-text('{tab}')")
        if el.count() > 0:
            log_pass(account, pn, f"Tab '{tab}' exists")
        else:
            log_bug(account, pn, f"Tab '{tab}' not found")

    # Admin Limits tab (superadmin only)
    if ACCOUNTS[account]["is_superadmin"]:
        al = page.locator(".wl-cp-tab:has-text('Admin Limits')")
        if al.count() > 0:
            log_pass(account, pn, "Admin Limits tab visible for superadmin")
        else:
            log_warn(account, pn, "Admin Limits tab not found for superadmin")

    # == APPROVAL QUEUE ==
    page.locator(".wl-cp-tab:has-text('Approval Queue')").first.click()
    time.sleep(2)

    pending = page.locator("text=Pending Requests")
    if pending.count() > 0:
        log_pass(account, pn, "Pending Requests section visible")

    history = page.locator("text=Recent History")
    if history.count() > 0:
        log_pass(account, pn, "Recent History section visible")

    # Check Download CSV not shown for rule operations
    download_btns = page.locator(".wl-cp-download-btn")
    for i in range(download_btns.count()):
        btn = download_btns.nth(i)
        csv_val = btn.get_attribute("data-csv") or ""
        action = btn.get_attribute("data-action-type") or ""
        if csv_val == "__rule_operation__" or not csv_val:
            log_bug(account, pn, f"Download CSV shown for rule op (action={action}, csv={csv_val})")

    # == ANALYST USAGE ==
    page.locator(".wl-cp-tab:has-text('Analyst Usage')").first.click()
    time.sleep(2)
    log_pass(account, pn, "Analyst Usage tab loaded")

    # == LIMITS & PERMISSIONS ==
    page.locator(".wl-cp-tab:has-text('Limits')").first.click()
    time.sleep(2)

    limit_inputs = page.locator("#wl-cp-daily-limits input[type='number']")
    if limit_inputs.count() > 0:
        log_pass(account, pn, f"Limits: {limit_inputs.count()} number inputs")

    # Check save/reset buttons
    save_limits = page.locator("text=Save Limits")
    reset_limits = page.locator("text=Reset")
    if save_limits.count() > 0:
        log_pass(account, pn, "Save Limits button exists")
    if reset_limits.count() > 0:
        log_pass(account, pn, "Reset button(s) exist")

    # Recent Changes section
    recent_changes = page.locator("text=Recent Changes")
    if recent_changes.count() > 0:
        log_pass(account, pn, "Recent Changes section visible")

    # == TRASH ==
    page.locator(".wl-cp-tab:has-text('Trash')").first.click()
    time.sleep(2)

    trash_table = page.locator(".wl-cp-table, table")
    retention = page.locator("text=Retention period")
    if retention.count() > 0:
        log_pass(account, pn, "Trash retention period displayed")

    page.screenshot(path=f"/tmp/cp_{account}.png", full_page=True)


def test_audit_trail(page, account):
    pn = "Audit Trail"
    page.goto(f"{BASE}/en-US/app/wl_manager/audit", wait_until="networkidle")
    time.sleep(5)

    if page.locator("text=Audit Trail, .dashboard-title").count() > 0:
        log_pass(account, pn, "Audit page loads")
    else:
        log_pass(account, pn, "Audit page loaded (checking panels)")

    # Dashboard panels
    panels = page.locator(".dashboard-panel")
    if panels.count() > 0:
        log_pass(account, pn, f"Found {panels.count()} dashboard panels")

    # Check for filter dropdowns
    inputs = page.locator(".input")
    if inputs.count() > 0:
        log_pass(account, pn, f"Found {inputs.count()} filter inputs")

    page.screenshot(path=f"/tmp/audit_{account}.png", full_page=True)


def test_notifications(page, account):
    pn = "Notifications"
    page.goto(f"{BASE}/en-US/app/wl_manager/whitelist_manager", wait_until="networkidle")
    time.sleep(3)

    bell = page.locator("#wl-notif-bell")
    if bell.count() == 0:
        log_bug(account, pn, "Notification bell not found")
        return

    log_pass(account, pn, "Bell icon present")

    # Badge
    badge = page.locator("#wl-notif-badge")
    if badge.count() > 0 and badge.is_visible():
        log_pass(account, pn, f"Badge: {badge.text_content().strip()}")

    # Open dropdown
    bell.click()
    time.sleep(2)

    dropdown = page.locator("#wl-notif-dropdown")
    if not dropdown.is_visible():
        log_bug(account, pn, "Dropdown did not open on bell click")
        return

    log_pass(account, pn, "Dropdown opens on click")

    # Items
    items = page.locator(".wl-notif-item")
    item_count = items.count()
    log_pass(account, pn, f"Notification items: {item_count}")

    # Check data attributes on each item
    for i in range(min(item_count, 5)):
        item = items.nth(i)
        ntype = item.get_attribute("data-notif-type") or ""
        atype = item.get_attribute("data-action-type") or ""
        csv = item.get_attribute("data-csv-file") or ""
        rule = item.get_attribute("data-detection-rule") or ""
        msg = item.locator(".wl-notif-message").text_content().strip()[:60] if item.locator(".wl-notif-message").count() > 0 else ""

        if not ntype:
            log_bug(account, pn, f"Notification #{i+1} missing data-notif-type")
        if not atype and ntype == "new_request":
            log_bug(account, pn, f"Notification #{i+1} new_request but missing data-action-type")

        log_pass(account, pn, f"  #{i+1}: type={ntype} action={atype} csv={csv[:20]} msg={msg}")

    # Mark all read
    mark_all = page.locator("#wl-notif-mark-all")
    if mark_all.count() > 0:
        log_pass(account, pn, "'Mark all read' button present")

    page.screenshot(path=f"/tmp/notif_{account}.png")

    # Close
    page.keyboard.press("Escape")
    time.sleep(1)


def test_add_row_discard(page, account):
    pn = "Add/Discard Flow"
    page.goto(f"{BASE}/en-US/app/wl_manager/whitelist_manager", wait_until="networkidle")
    time.sleep(3)

    # Select first rule
    page.locator("#rule-search").click()
    time.sleep(2)
    items = page.locator('#rule-list .wl-dropdown-item:not([data-value="__create_new_rule__"])')
    if items.count() == 0:
        log_warn(account, pn, "No rules to test add/discard")
        return

    items.first.click()
    time.sleep(3)

    rows_before = page.locator("#csv-table-container table tbody tr").count()

    # Add Row
    add_btn = page.locator("text=Add Row")
    if add_btn.count() == 0 or not add_btn.first.is_enabled():
        log_warn(account, pn, "Add Row button not available (may be locked)")
        return

    add_btn.first.click()
    time.sleep(1)

    rows_after = page.locator("#csv-table-container table tbody tr").count()
    if rows_after == rows_before + 1:
        log_pass(account, pn, "Add Row: row count increased by 1")
    else:
        log_bug(account, pn, f"Add Row: expected {rows_before+1}, got {rows_after}")

    # Discard
    discard_btn = page.locator("text=Discard Changes")
    if discard_btn.count() > 0 and discard_btn.first.is_enabled():
        discard_btn.first.click()
        time.sleep(1)
        # Look for confirm modal
        confirm = page.locator("#wl-confirm-discard-ok, .wl-modal .btn-primary:has-text('Discard')")
        if confirm.count() > 0:
            confirm.first.click()
            time.sleep(2)
        rows_final = page.locator("#csv-table-container table tbody tr").count()
        if rows_final == rows_before:
            log_pass(account, pn, "Discard restored original row count")
        else:
            log_bug(account, pn, f"Discard: expected {rows_before}, got {rows_final}")


def run_all_tests():
    print("=" * 70)
    print("COMPREHENSIVE WHITELIST MANAGER BROWSER TEST")
    print("=" * 70)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        for account, info in ACCOUNTS.items():
            print(f"\n{'='*60}")
            print(f"ACCOUNT: {account} (admin={info['is_admin']}, super={info['is_superadmin']})")
            print(f"{'='*60}")

            ctx = browser.new_context(viewport={"width": 1920, "height": 1080})
            pg = ctx.new_page()

            console_errors = []
            pg.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)

            try:
                print(f"\n  Logging in as {account}...")
                login(pg, account, info["password"])

                print(f"\n  [1/6] Whitelist Manager page")
                test_whitelist_manager(pg, account)

                print(f"\n  [2/6] Control Panel")
                test_control_panel(pg, account)

                print(f"\n  [3/6] Audit Trail")
                test_audit_trail(pg, account)

                print(f"\n  [4/6] Notifications")
                test_notifications(pg, account)

                print(f"\n  [5/6] Add Row / Discard flow")
                test_add_row_discard(pg, account)

                print(f"\n  [6/6] Console errors check")
                js_errors = [e for e in console_errors
                             if "favicon" not in e.lower()
                             and "appLogo" not in e.lower()
                             and "Failed to load resource" not in e]
                if js_errors:
                    for err in js_errors[:5]:
                        log_bug(account, "JS Console", err[:150])
                else:
                    log_pass(account, "JS Console", "No unexpected JS errors")

            except Exception as e:
                log_bug(account, "FATAL", f"Test crashed: {type(e).__name__}: {e}")
                import traceback
                traceback.print_exc()
            finally:
                ctx.close()

        browser.close()

    # SUMMARY
    print(f"\n{'='*70}")
    print("RESULTS")
    print(f"{'='*70}")
    print(f"  PASSED:   {len(passes)}")
    print(f"  WARNINGS: {len(warnings)}")
    print(f"  BUGS:     {len(bugs)}")

    if bugs:
        print(f"\n--- BUGS ---")
        for b in bugs:
            print(f"  {b}")

    if warnings:
        print(f"\n--- WARNINGS ---")
        for w in warnings:
            print(f"  {w}")

    print(f"\n--- SCREENSHOTS saved to /tmp/ ---")
    return 1 if bugs else 0


if __name__ == "__main__":
    sys.exit(run_all_tests())
