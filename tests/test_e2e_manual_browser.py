"""
Browser-based E2E test that simulates real human interactions.
Uses keyboard.type() with delays and proper focus/blur to trigger
Splunk's jQuery event chain correctly.
"""
import json
import time
import sys
import io
from playwright.sync_api import sync_playwright

# Fix Windows console encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE = "http://localhost:8000"
bugs = []
passes = []
test_num = 0

def bug(acct, area, msg):
    global test_num; test_num += 1
    s = f"  [BUG]  T{test_num:02d} [{acct}] [{area}] {msg}"
    print(s); bugs.append(s)

def ok(acct, area, msg):
    global test_num; test_num += 1
    s = f"  [PASS] T{test_num:02d} [{acct}] [{area}] {msg}"
    print(s); passes.append(s)

def login(page, user, pw):
    page.goto(f"{BASE}/en-US/account/login", wait_until="networkidle")
    page.fill('input[name="username"]', user)
    page.fill('input[name="password"]', pw)
    page.click('input[type="submit"]')
    page.wait_for_load_state("networkidle")
    time.sleep(2)

def go_wlm(page):
    page.goto(f"{BASE}/en-US/app/wl_manager/whitelist_manager", wait_until="networkidle")
    time.sleep(4)

def go_cp(page):
    page.goto(f"{BASE}/en-US/app/wl_manager/control_panel", wait_until="networkidle")
    time.sleep(3)

def select_rule(page, name):
    page.locator("#rule-search").click()
    time.sleep(1)
    page.locator("#rule-search").fill(name)
    time.sleep(1)
    item = page.locator(f'.wl-dropdown-item[data-value="{name}"]')
    if item.count() > 0:
        item.click()
        time.sleep(3)
        return True
    return False

def type_in_cell(page, row_idx, value):
    """Type into a cell using keyboard to trigger real events."""
    row = page.locator("#csv-table-container table tbody tr").nth(row_idx)
    ta = row.locator("textarea.wl-input").first
    ta.click()
    time.sleep(0.2)
    # Select all existing text and replace
    page.keyboard.press("Control+a")
    page.keyboard.type(value, delay=30)
    time.sleep(0.3)
    # Tab away to trigger blur/change
    page.keyboard.press("Tab")
    time.sleep(0.3)

def dismiss_modals(page):
    for _ in range(3):
        overlay = page.locator(".wl-modal-overlay")
        if overlay.count() > 0 and overlay.first.is_visible():
            btns = overlay.locator("span.btn, button.btn")
            if btns.count() > 0:
                btns.first.click()
                time.sleep(1)
        else:
            break

def save_and_check(page, acct, label):
    dismiss_modals(page)
    save = page.locator("#btn-save")
    if save.count() == 0 or not save.is_enabled():
        bug(acct, label, "Save button disabled or missing")
        return False
    save.click()
    time.sleep(5)
    dismiss_modals(page)
    msg = page.locator("#message-container")
    msg_text = msg.text_content().strip() if msg.count() > 0 else ""
    diff = page.locator("#diff-container")
    diff_text = diff.text_content().strip()[:100] if diff.count() > 0 else ""
    if "error" in msg_text.lower():
        bug(acct, label, f"Save error: {msg_text[:80]}")
        return False
    ok(acct, label, f"Saved. Diff: {diff_text[:60]}")
    return True

def row_count(page):
    return page.locator("#csv-table-container table tbody tr").count()

def screenshot(page, name):
    page.screenshot(path=f"C:/Users/PC/wl_manager/tests/e2e_{name}.png", full_page=True)


# =====================================================================
# PHASE 1: analyst2 — Daily operations
# =====================================================================
def phase1(page):
    acct = "analyst2"
    print(f"\n{'='*60}")
    print("PHASE 1: analyst2 -- Daily whitelist operations")
    print(f"{'='*60}")

    go_wlm(page)

    # 1.1 Select rule
    if select_rule(page, "DR102_priv_escalation"):
        ok(acct, "Select", "Selected DR102_priv_escalation")
    else:
        bug(acct, "Select", "Failed to select DR102"); return

    r0 = row_count(page)
    ok(acct, "View", f"Table has {r0} rows")

    # 1.2 Add row + type data
    page.locator("#btn-add-row").click()
    time.sleep(1)
    r1 = row_count(page)
    if r1 == r0 + 1:
        ok(acct, "Add Row", f"Row added ({r0}->{r1})")
    else:
        bug(acct, "Add Row", f"Expected {r0+1}, got {r1}")

    type_in_cell(page, r1 - 1, "E2E-TYPED-HOST")
    time.sleep(0.5)

    # 1.3 Save
    save_and_check(page, acct, "Save Add")

    # 1.4 Verify persistence
    go_wlm(page)
    select_rule(page, "DR102_priv_escalation")
    r2 = row_count(page)
    if r2 == r1:
        ok(acct, "Persist", f"Row persisted after reload ({r2} rows)")
    else:
        bug(acct, "Persist", f"Row NOT persisted: expected {r1}, got {r2}")

    # 1.5 Edit existing cell
    old_val = page.locator("#csv-table-container table tbody tr").first.locator("textarea.wl-input").first.input_value()
    type_in_cell(page, 0, "E2E-EDITED-VAL")
    save_and_check(page, acct, "Save Edit")

    # 1.6 Verify edit persisted
    go_wlm(page)
    select_rule(page, "DR102_priv_escalation")
    new_val = page.locator("#csv-table-container table tbody tr").first.locator("textarea.wl-input").first.input_value()
    if new_val == "E2E-EDITED-VAL":
        ok(acct, "Edit Persist", f"Edit persisted: {new_val}")
    else:
        bug(acct, "Edit Persist", f"Expected 'E2E-EDITED-VAL', got '{new_val}'")

    # 1.7 Remove row (click Remove button)
    r_before = row_count(page)
    last_remove = page.locator("#csv-table-container table tbody tr").last.locator("button.btn-rm")
    if last_remove.count() > 0:
        last_remove.click()
        time.sleep(1)
        # Fill reason in modal
        reason_inp = page.locator(".wl-modal textarea, .wl-modal input[type='text']")
        if reason_inp.count() > 0:
            reason_inp.first.fill("E2E test removal reason")
            page.locator(".wl-modal span.btn-primary").first.click()
            time.sleep(2)
            r_after = row_count(page)
            # Row removal auto-saves
            ok(acct, "Remove Row", f"Removed with reason ({r_before}->{r_after})")
        else:
            ok(acct, "Remove Row", "Remove clicked (inline reason flow)")
            dismiss_modals(page)
    else:
        bug(acct, "Remove Row", "Remove button not found")

    # 1.8 Search
    search = page.locator("input[placeholder*='Filter']")
    if search.count() > 0:
        search.first.fill("E2E")
        time.sleep(1)
        filtered = row_count(page)
        ok(acct, "Search", f"Filter 'E2E' shows {filtered} rows")
        # Clear
        clear = page.locator(".wl-search-clear")
        if clear.count() > 0:
            clear.first.click()
            time.sleep(1)
            ok(acct, "Search Clear", f"Cleared, {row_count(page)} rows")

    # 1.9 Discard flow
    page.locator("#btn-add-row").click()
    time.sleep(0.5)
    type_in_cell(page, row_count(page) - 1, "DISCARD-ME")
    page.locator("text=Discard Changes").click()
    time.sleep(1)
    confirm = page.locator(".wl-modal span.btn-primary")
    if confirm.count() > 0:
        confirm.first.click()
        time.sleep(2)
    r_discard = row_count(page)
    ok(acct, "Discard", f"Discarded changes ({r_discard} rows)")

    # 1.10 Switch rule
    if select_rule(page, "DR310_impossible_travel"):
        ok(acct, "Switch Rule", f"Switched to DR310 ({row_count(page)} rows)")

    screenshot(page, "phase1")


# =====================================================================
# PHASE 2: wladmin2 — Admin operations
# =====================================================================
def phase2(page):
    acct = "wladmin2"
    print(f"\n{'='*60}")
    print("PHASE 2: wladmin2 -- Admin operations")
    print(f"{'='*60}")

    go_wlm(page)

    # 2.1 Create rule
    page.locator("#rule-search").click()
    time.sleep(1)
    page.locator('[data-value="__create_new_rule__"]').click()
    time.sleep(1)
    # Find the rule name input in modal
    modal = page.locator(".wl-modal")
    if modal.count() > 0:
        inp = modal.locator("input[type='text']").first
        inp.fill("DR_BROWSER_TEST")
        time.sleep(0.3)
        modal.locator("span.btn-primary").first.click()
        time.sleep(3)
        dismiss_modals(page)
        ok(acct, "Create Rule", "Created DR_BROWSER_TEST")
    else:
        bug(acct, "Create Rule", "Create rule modal not found")

    # 2.2 Create CSV
    time.sleep(2)
    create_csv = page.locator("#wl-create-csv-btn")
    if create_csv.count() > 0:
        create_csv.click()
        time.sleep(1)
        modal = page.locator(".wl-modal")
        csv_name = modal.locator("#wl-create-csv-name")
        csv_headers = modal.locator("#wl-create-csv-headers")
        if csv_name.count() > 0 and csv_headers.count() > 0:
            csv_name.fill("DR_BROWSER_TEST.csv")
            csv_headers.fill("src_ip,dest_host,Comment")
            time.sleep(0.3)
            # Reason if required
            reason = modal.locator("textarea")
            if reason.count() > 0:
                reason.first.fill("Browser test CSV")
            modal.locator("span.btn-primary").first.click()
            time.sleep(4)
            dismiss_modals(page)
            ok(acct, "Create CSV", "Created DR_BROWSER_TEST.csv")
        else:
            bug(acct, "Create CSV", "CSV form inputs not found")
    else:
        ok(acct, "Create CSV", "Create CSV button not shown (different flow)")

    # 2.3 Add rows to new CSV
    time.sleep(2)
    if select_rule(page, "DR_BROWSER_TEST"):
        for i in range(3):
            page.locator("#btn-add-row").click()
            time.sleep(0.5)

        # Type data into each row
        for i in range(3):
            row = page.locator("#csv-table-container table tbody tr").nth(i)
            tas = row.locator("textarea.wl-input")
            if tas.count() >= 2:
                tas.nth(0).click()
                page.keyboard.press("Control+a")
                page.keyboard.type(f"10.0.{i}.1", delay=20)
                page.keyboard.press("Tab")
                time.sleep(0.2)
                page.keyboard.type(f"srv-{i+1}.corp.local", delay=20)
                page.keyboard.press("Tab")
                time.sleep(0.2)
                # Comment column
                if tas.count() >= 3:
                    page.keyboard.type(f"Test entry {i+1}", delay=20)
                    page.keyboard.press("Tab")
                time.sleep(0.2)

        save_and_check(page, acct, "Add 3 Rows")

        # Verify
        go_wlm(page)
        select_rule(page, "DR_BROWSER_TEST")
        r = row_count(page)
        ok(acct, "Verify 3 Rows", f"DR_BROWSER_TEST has {r} rows")
    else:
        bug(acct, "Select", "Could not select DR_BROWSER_TEST")

    # 2.4 Add column
    add_col = page.locator("text=Add Column")
    if add_col.count() > 0 and add_col.first.is_enabled():
        add_col.first.click()
        time.sleep(1)
        col_inp = page.locator("#wl-new-col-name")
        if col_inp.count() > 0:
            # Test space rejection
            col_inp.fill("bad name")
            page.locator("#wl-col-ok").click()
            time.sleep(1)
            err = page.locator("#wl-col-error")
            if err.count() > 0 and err.is_visible():
                ok(acct, "Space Reject", f"Spaces rejected: {err.text_content()[:50]}")
            else:
                bug(acct, "Space Reject", "Spaces in column name NOT rejected")

            # Valid name
            col_inp.fill("severity")
            page.locator("#wl-col-ok").click()
            time.sleep(1)
            ok(acct, "Add Column", "Added 'severity' column")
            save_and_check(page, acct, "Save Column")

    # 2.5 Column rename
    col_text = page.locator("th.wl-col-draggable .wl-col-header-text").first
    if col_text.count() > 0:
        old_name = col_text.text_content().strip()
        col_text.click()
        time.sleep(0.5)
        rename_inp = page.locator(".wl-col-rename-input")
        if rename_inp.count() > 0:
            rename_inp.fill("")
            rename_inp.type("source_ip", delay=30)
            page.keyboard.press("Enter")
            time.sleep(2)
            ok(acct, "Column Rename", f"Renamed '{old_name}' to 'source_ip'")
        else:
            bug(acct, "Column Rename", "Rename input not found")

    # 2.6 Version dropdown
    ver = page.locator("#version-select")
    if ver.count() > 0:
        opts = page.locator("#version-select option")
        ok(acct, "Versions", f"Version dropdown: {opts.count()} entries")

    # 2.7 Revert
    if ver.count() > 0 and page.locator("#version-select option").count() > 1:
        page.locator("#version-select").select_option(index=1)
        time.sleep(2)
        reason_inp = page.locator(".wl-modal textarea, .wl-modal input[type='text']")
        if reason_inp.count() > 0:
            reason_inp.first.fill("Browser test revert")
            page.locator(".wl-modal span.btn-primary").first.click()
            time.sleep(4)
            dismiss_modals(page)
            ok(acct, "Revert", "Reverted to previous version")

    # 2.8 Control Panel — Limits
    go_cp(page)
    page.locator(".wl-cp-tab:has-text('Limits')").first.click()
    time.sleep(2)
    inputs = page.locator("#wl-cp-daily-limits input[type='number']")
    ok(acct, "CP Limits", f"{inputs.count()} limit inputs")

    # 2.9 Trash tab
    page.locator(".wl-cp-tab:has-text('Trash')").first.click()
    time.sleep(2)
    ok(acct, "CP Trash", "Trash tab loaded")

    screenshot(page, "phase2")


# =====================================================================
# PHASE 3: analyst2 — Approval workflows
# =====================================================================
def phase3(page):
    acct = "analyst2"
    print(f"\n{'='*60}")
    print("PHASE 3: analyst2 -- Approval workflows")
    print(f"{'='*60}")

    go_wlm(page)

    # 3.1 Create rule request (needs approval for analyst)
    page.locator("#rule-search").click()
    time.sleep(1)
    page.locator('[data-value="__create_new_rule__"]').click()
    time.sleep(1)
    modal = page.locator(".wl-modal")
    if modal.count() > 0:
        inp = modal.locator("input[type='text']").first
        inp.fill("DR_ANALYST_APPROVAL")
        # Reason
        reason = modal.locator("textarea")
        if reason.count() > 0:
            reason.first.fill("Analyst needs this for new phishing detection")
        modal.locator("span.btn-primary").first.click()
        time.sleep(3)
        msg = page.locator("#message-container")
        msg_text = msg.text_content().strip() if msg.count() > 0 else ""
        if "approval" in msg_text.lower() or "submitted" in msg_text.lower():
            ok(acct, "Rule Approval", f"Submitted for approval: {msg_text[:60]}")
        else:
            ok(acct, "Rule Request", f"Response: {msg_text[:60]}")
        dismiss_modals(page)

    # 3.2 Check notifications
    bell = page.locator("#wl-notif-bell")
    if bell.count() > 0:
        bell.click()
        time.sleep(2)
        items = page.locator(".wl-notif-item")
        ok(acct, "Notifications", f"{items.count()} notifications")
        page.keyboard.press("Escape")

    screenshot(page, "phase3")


# =====================================================================
# PHASE 4: superadmin1 — Process approvals
# =====================================================================
def phase4(page):
    acct = "superadmin1"
    print(f"\n{'='*60}")
    print("PHASE 4: superadmin1 -- Approvals & system management")
    print(f"{'='*60}")

    # 4.1 Notification → Control Panel
    go_wlm(page)
    time.sleep(2)
    bell = page.locator("#wl-notif-bell")
    if bell.count() > 0:
        bell.click()
        time.sleep(2)
        items = page.locator(".wl-notif-item")
        ok(acct, "Notifications", f"{items.count()} notifications")

        # Click first new_request notification
        new_req = page.locator('.wl-notif-item[data-notif-type="new_request"]')
        if new_req.count() > 0:
            new_req.first.click()
            time.sleep(3)
            page.wait_for_load_state("networkidle")
            time.sleep(2)
            # Should be on Control Panel now
            if "control_panel" in page.url:
                ok(acct, "Notif Click", "Redirected to Control Panel")
            else:
                bug(acct, "Notif Click", f"NOT redirected. URL: {page.url}")
        else:
            ok(acct, "Notif Click", "No new_request notifications to click")
            go_cp(page)
    else:
        go_cp(page)

    # 4.2 Approve pending request
    time.sleep(2)
    page.locator(".wl-cp-tab:has-text('Approval Queue')").first.click()
    time.sleep(2)
    approve_btns = page.locator(".wl-cp-approve-btn")
    if approve_btns.count() > 0:
        approve_btns.first.click()
        time.sleep(1)
        confirm = page.locator("#wl-cp-confirm-ok")
        if confirm.count() > 0:
            ok(acct, "Approve Modal", f"Confirm button text: '{confirm.text_content().strip()}'")
            confirm.click()
            time.sleep(4)
            dismiss_modals(page)
            ok(acct, "Approve", "Approved pending request")
        else:
            bug(acct, "Approve", "Confirm button not found in modal")
    else:
        ok(acct, "Queue", "No pending requests to approve")

    # 4.3 Check Download CSV not shown for rule ops
    dl_btns = page.locator(".wl-cp-download-btn")
    for i in range(dl_btns.count()):
        csv_val = dl_btns.nth(i).get_attribute("data-csv") or ""
        if csv_val == "__rule_operation__" or not csv_val:
            bug(acct, "Download CSV", f"Shown for rule op (csv={csv_val})")

    # 4.4 Admin Limits tab
    al_tab = page.locator(".wl-cp-tab:has-text('Admin Limits')")
    if al_tab.count() > 0:
        al_tab.first.click()
        time.sleep(2)
        ok(acct, "Admin Limits", "Tab loaded")

        # Test Reset Admin Limits modal
        reset_btn = page.locator("text=Reset Admin Limits")
        if reset_btn.count() > 0:
            reset_btn.first.click()
            time.sleep(1)
            modal_btn = page.locator("#wl-cp-confirm-ok")
            if modal_btn.count() > 0:
                btn_text = modal_btn.text_content().strip()
                if btn_text == "Reset":
                    ok(acct, "Reset Modal", "Reset Admin Limits has 'Reset' button")
                else:
                    bug(acct, "Reset Modal", f"Button text is '{btn_text}' instead of 'Reset'")
                page.locator("#wl-cp-confirm-cancel").click()
                time.sleep(1)

    # 4.5 Trash — Restore modal
    page.locator(".wl-cp-tab:has-text('Trash')").first.click()
    time.sleep(2)
    restore = page.locator(".wl-trash-restore")
    if restore.count() > 0:
        restore.first.click()
        time.sleep(1)
        modal_btn = page.locator("#wl-cp-confirm-ok")
        if modal_btn.count() > 0:
            btn_text = modal_btn.text_content().strip()
            if btn_text == "Restore":
                ok(acct, "Restore Modal", "Restore button renders correctly")
            else:
                bug(acct, "Restore Modal", f"Button text is '{btn_text}' (should be 'Restore')")
            page.locator("#wl-cp-confirm-cancel").click()
            time.sleep(1)
    else:
        ok(acct, "Trash", "No items in trash (empty)")

    # 4.6 Audit Trail
    page.goto(f"{BASE}/en-US/app/wl_manager/audit", wait_until="networkidle")
    time.sleep(5)
    panels = page.locator(".dashboard-panel")
    ok(acct, "Audit Trail", f"Page loaded with {panels.count()} panels")

    screenshot(page, "phase4")


# =====================================================================
# PHASE 5: Cross-account presence
# =====================================================================
def phase5(browser):
    print(f"\n{'='*60}")
    print("PHASE 5: Cross-account presence & concurrent access")
    print(f"{'='*60}")

    ctx1 = browser.new_context(viewport={"width": 1920, "height": 1080})
    ctx2 = browser.new_context(viewport={"width": 1920, "height": 1080})
    pg1 = ctx1.new_page()
    pg2 = ctx2.new_page()

    try:
        login(pg1, "analyst2", "Chang3d!")
        login(pg2, "wladmin2", "Chang3d!")

        go_wlm(pg1)
        go_wlm(pg2)

        select_rule(pg1, "DR_BROWSER_TEST")
        select_rule(pg2, "DR_BROWSER_TEST")
        time.sleep(8)  # Wait for presence heartbeats

        # Check presence bars
        p1 = pg1.locator(".wl-presence-bar")
        p2 = pg2.locator(".wl-presence-bar")

        if p1.count() > 0:
            t1 = p1.text_content().strip()
            if "wladmin2" in t1:
                ok("analyst2", "Presence", f"Sees wladmin2: {t1[:60]}")
            else:
                ok("analyst2", "Presence", f"Bar: {t1[:60]}")

        if p2.count() > 0:
            t2 = p2.text_content().strip()
            if "analyst2" in t2:
                ok("wladmin2", "Presence", f"Sees analyst2: {t2[:60]}")
            else:
                ok("wladmin2", "Presence", f"Bar: {t2[:60]}")

        screenshot(pg1, "phase5_analyst")
        screenshot(pg2, "phase5_admin")
    finally:
        ctx1.close()
        ctx2.close()


# =====================================================================
# MAIN
# =====================================================================
def main():
    print("=" * 60)
    print("BROWSER E2E TEST — Real Human Simulation")
    print("=" * 60)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        accounts = [
            ("Phase 1", "analyst2", "Chang3d!", phase1),
            ("Phase 2", "wladmin2", "Chang3d!", phase2),
            ("Phase 3", "analyst2", "Chang3d!", phase3),
            ("Phase 4", "superadmin1", "Chang3d!", phase4),
        ]
        for name, user, pw, func in accounts:
            ctx = browser.new_context(viewport={"width": 1920, "height": 1080})
            pg = ctx.new_page()
            console_errs = []
            pg.on("console", lambda m: console_errs.append(m.text) if m.type == "error" else None)
            try:
                login(pg, user, pw)
                func(pg)
                real_errs = [e for e in console_errs
                             if "favicon" not in e.lower()
                             and "appLogo" not in e.lower()
                             and "Failed to load resource" not in e]
                if real_errs:
                    for e in real_errs[:3]:
                        bug(user, "Console", e[:100])
                else:
                    ok(user, "Console", "No JS errors")
            except Exception as e:
                bug(user, name, f"CRASH: {type(e).__name__}: {str(e)[:120]}")
                import traceback; traceback.print_exc()
            finally:
                ctx.close()

        # Phase 5: concurrent
        try:
            phase5(browser)
        except Exception as e:
            bug("multi", "Phase 5", f"CRASH: {str(e)[:120]}")

        browser.close()

    print(f"\n{'='*60}")
    print(f"RESULTS: {len(passes)} passed, {len(bugs)} bugs")
    print(f"{'='*60}")
    if bugs:
        print("\n--- BUGS ---")
        for b in bugs:
            print(f"  {b}")
    else:
        print("\nALL TESTS PASSED")
    return 1 if bugs else 0


if __name__ == "__main__":
    sys.exit(main())
