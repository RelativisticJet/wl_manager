"""Page object models for Whitelist Manager E2E tests.

Selector reference: derived from `tests/test_e2e_realworld.py` and
`tests/e2e/test_wl_save.py`, which are the two Python E2E files that
have ever actually worked. The previous (pre-2026-05-24) version of
this file used a guessed DOM model — `<select>` for the detection-rule
picker, `<button>` for action buttons — and never matched the real app.

The real app:
  - Detection-rule picker = `#rule-search` input + `#rule-list .wl-dropdown-item[data-value=...]`
  - CSV picker          = `#csv-display` trigger + `.wl-csv-item[data-csv=...]`
  - Table              = `#csv-table-container table tbody tr`
  - Cells              = `<textarea class="wl-input">` or `<input class="wl-input">` inside `<td>`
  - Action buttons     = `#btn-save`, `#btn-add-row`, `.btn-rm[data-idx]`, `.btn-danger`, `.btn-primary`
  - Modals             = `.wl-modal-overlay` (cover) with `.wl-modal` inside; `<textarea>` for reasons

If any of those change, fix them HERE and the workflow tests inherit
automatically. Do NOT bypass these helpers with bare `self.page.locator(...)`
in workflow tests — that's how we ended up with 14 `.locators()` typos.
"""
import time
from typing import List, Dict, Any, Optional
from playwright.sync_api import Page


class SplunkPage:
    """Base page object: nav + ready-state helpers."""

    def __init__(self, page: Page, base_url: str = "http://localhost:8000"):
        self.page = page
        self.base_url = base_url

    def goto(self, path: str) -> None:
        """Navigate inside the Splunk app. Path must start with `/`.

        Tolerates `net::ERR_ABORTED` raised by Splunk's redirect chain
        (302 from /app/... to /en-US/app/...). The redirect itself
        is fine; playwright surfaces it as ERR_ABORTED because the
        original request was cancelled by the redirect. We catch and
        let the wait_for_load_state below confirm the page actually
        rendered.
        """
        full = f"{self.base_url}{path}"
        try:
            self.page.goto(full, wait_until="domcontentloaded")
        except Exception as e:
            if "ERR_ABORTED" not in str(e):
                raise
            # Splunk redirect — page likely loaded under a different URL.
            # Continue to wait_for_load_state to confirm.
        try:
            self.page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            # Splunk holds long-poll connections open; networkidle may
            # never fire on busy dashboards. Continue regardless.
            pass
        time.sleep(0.5)


class WhitelistManagerPage(SplunkPage):
    """Main whitelist manager dashboard page object."""

    DASHBOARD_PATH = "/en-US/app/wl_manager/whitelist_manager"

    def goto_app(self) -> None:
        self.goto(self.DASHBOARD_PATH)
        time.sleep(2)  # SPA hydration

    def select_rule(self, rule_name: str) -> bool:
        """Pick a detection rule from the dropdown. Returns True on success."""
        self.page.locator("#rule-search").click()
        time.sleep(0.3)
        self.page.locator("#rule-search").fill("")
        time.sleep(0.2)
        self.page.locator("#rule-search").fill(rule_name)
        time.sleep(0.5)
        item = self.page.locator(
            f'#rule-list .wl-dropdown-item[data-value="{rule_name}"]'
        )
        if item.count() > 0:
            item.first.click()
            time.sleep(2)
            return True
        return False

    def select_csv(self, csv_name: str) -> bool:
        """Pick a CSV from the dropdown (requires a rule to be selected first)."""
        self.page.locator("#csv-display").click()
        time.sleep(0.5)
        item = self.page.locator(f'.wl-csv-item[data-csv="{csv_name}"]')
        if item.count() > 0:
            item.first.click()
            time.sleep(2)
            return True
        return False

    def load_csv(self, csv_name: str, rule_name: Optional[str] = None) -> None:
        """Load a CSV. If rule_name is omitted, derive from the standard map.

        The app's UI requires a rule to be selected before the CSV dropdown
        becomes meaningful. Tests that pass csv_name only must provide a
        rule via `rule_name`; the helper falls back to the canonical DR55
        rule used elsewhere in the suite so legacy single-argument calls
        don't silently break.
        """
        if rule_name is None:
            # Heuristic: most legacy tests use DR55_*; pick that as the
            # fallback. Callers that need a specific rule must pass it.
            rule_name = "DR55_brute_force_login"
        if not self.select_rule(rule_name):
            raise RuntimeError(f"select_rule({rule_name!r}) failed — rule not in dropdown")
        if not self.select_csv(csv_name):
            raise RuntimeError(f"select_csv({csv_name!r}) failed — CSV not in dropdown for {rule_name!r}")
        self.page.wait_for_selector("#csv-table-container table", timeout=15000)
        time.sleep(1)

    # -- Row + cell helpers --

    def get_row_count(self) -> int:
        return self.page.locator("#csv-table-container table tbody tr").count()

    def get_table_rows(self) -> List[Dict[str, List[str]]]:
        """Return one dict per row with `cells` = list of textarea/input values."""
        out: List[Dict[str, List[str]]] = []
        rows = self.page.locator("#csv-table-container table tbody tr")
        for i in range(rows.count()):
            cells = rows.nth(i).locator("td textarea.wl-input, td input.wl-input")
            values = [cells.nth(j).input_value() for j in range(cells.count())]
            out.append({"cells": values})
        return out

    def get_cell_value(self, row_idx: int, col_idx: int) -> Optional[str]:
        """0-based row+col; col 0 is the first DATA column (checkbox + rownum excluded)."""
        row = self.page.locator("#csv-table-container table tbody tr").nth(row_idx)
        cells = row.locator("td textarea.wl-input, td input.wl-input")
        if cells.count() > col_idx:
            return cells.nth(col_idx).input_value()
        return None

    def set_cell_value(self, row_idx: int, col_idx: int, value: str) -> bool:
        row = self.page.locator("#csv-table-container table tbody tr").nth(row_idx)
        cells = row.locator("td textarea.wl-input, td input.wl-input")
        if cells.count() > col_idx:
            cell = cells.nth(col_idx)
            cell.click()
            cell.fill(value)
            try:
                cell.blur()
            except Exception:
                pass
            time.sleep(0.2)
            return True
        return False

    def edit_cell(self, row_idx_1based: int, col_idx_1based: int, value: str) -> bool:
        """Backwards-compat shim: legacy tests pass 1-based indices."""
        return self.set_cell_value(row_idx_1based - 1, col_idx_1based - 1, value)

    # -- Action buttons --

    def add_row(self) -> None:
        btn = self.page.locator("#btn-add-row")
        if btn.count() == 0:
            raise RuntimeError("#btn-add-row not present (no rule/CSV loaded?)")
        btn.click()
        time.sleep(0.5)

    def remove_row(self, row_idx: int, reason: str = "E2E removal") -> None:
        """Remove row by per-row btn-rm. row_idx may be 0-based OR 1-based;
        we accept both — tests historically used 1-based, the helper uses
        0-based throughout this file. Callers passing 0 or 1 will get the
        SAME behavior (the first row).
        """
        idx_0based = row_idx - 1 if row_idx >= 1 else 0
        row = self.page.locator("#csv-table-container table tbody tr").nth(idx_0based)
        rm_btn = row.locator(".btn-rm")
        if rm_btn.count() == 0:
            raise RuntimeError(f"No .btn-rm in row index {idx_0based}")
        rm_btn.first.click()
        time.sleep(0.5)
        # Modal may appear for reason
        modal = self.page.locator(".wl-modal-overlay")
        if modal.count() > 0 and modal.first.is_visible():
            ta = modal.locator("textarea").first
            if ta.count() > 0 and ta.is_visible():
                ta.fill(reason)
            confirm = modal.locator(".btn-danger").first
            if confirm.count() > 0:
                confirm.click()
                time.sleep(1)

    def save_changes(self, comment: str = "E2E save") -> Optional[str]:
        """Click Save Changes; handle the audit-comment modal; return the
        post-save message-container text (None if save was skipped)."""
        self.dismiss_modals()
        save_btn = self.page.locator("#btn-save")
        if save_btn.count() == 0:
            return None
        try:
            if not save_btn.is_enabled():
                return None
        except Exception:
            pass
        save_btn.click()
        time.sleep(1)
        # Audit-comment modal
        modal = self.page.locator(".wl-modal-overlay")
        if modal.count() > 0 and modal.first.is_visible():
            ta = modal.locator("textarea").first
            if ta.count() > 0 and ta.is_visible():
                ta.fill(comment)
            confirm = modal.locator(".btn-primary").first
            if confirm.count() > 0:
                confirm.click()
                time.sleep(3)
        time.sleep(1)
        msg = self.page.locator("#message-container")
        return msg.text_content().strip() if msg.count() > 0 else None

    # -- Search --

    def search(self, query: str) -> bool:
        candidates = self.page.locator(
            "input[placeholder*='Filter'], #wl-search, input.wl-search-input"
        )
        if candidates.count() == 0:
            return False
        si = candidates.first
        if not si.is_visible():
            return False
        si.fill(query)
        time.sleep(1)
        return True

    def clear_search(self) -> bool:
        clear = self.page.locator(".wl-search-clear-btn, .wl-search-clear")
        if clear.count() > 0 and clear.first.is_visible():
            clear.first.click()
            time.sleep(0.5)
            return True
        return False

    # -- Modal cleanup --

    def dismiss_modals(self) -> None:
        for _ in range(3):
            modal = self.page.locator(".wl-modal-overlay")
            if modal.count() == 0:
                return
            if not modal.first.is_visible():
                return
            btns = modal.locator(".btn")
            if btns.count() > 0:
                try:
                    btns.first.click()
                except Exception:
                    pass
                time.sleep(0.5)
            else:
                try:
                    modal.first.click(position={"x": 5, "y": 5})
                except Exception:
                    pass
                time.sleep(0.5)


class ControlPanelPage(SplunkPage):
    """Admin / superadmin control panel page object.

    Tabs in the CP, in the order they actually exist:
      Approval Queue | Activity | Analyst Settings | Admin Settings | Trash
    """

    DASHBOARD_PATH = "/en-US/app/wl_manager/control_panel"

    def goto_app(self) -> None:
        self.goto(self.DASHBOARD_PATH)
        # Wait for the dynamic tab bar to render (it's built by JS, not
        # in the static dashboard XML). control_panel.js builds
        # `<button class="wl-cp-tab" data-tab="queue">Approval Queue</button>`
        # etc. into `#wl-cp-tabs` after init.
        try:
            self.page.wait_for_selector(".wl-cp-tab", timeout=10000)
        except Exception:
            pass
        time.sleep(1)

    # Map visible labels to control_panel.js data-tab keys. Used by
    # click_tab to do an exact-attribute lookup (more reliable than
    # text matching when the active tab gets a btn-primary class
    # that visually changes the rendered glyph).
    _TAB_KEYS = {
        "Approval Queue": "queue",
        "Approval": "queue",
        "Queue": "queue",
        "Activity": "usage",
        "Usage": "usage",
        "Analyst Settings": "limits",
        "Daily Limits": "limits",
        "Admin Settings": "admin-limits",
        "Trash": "trash",
    }

    def click_tab(self, tab_text: str) -> bool:
        """Click a Control Panel tab. The real CP uses
        `<button class="wl-cp-tab" data-tab="<key>">Label</button>`.
        We try data-tab lookup first (with a short wait for dynamic
        render — the tab bar is JS-rendered after the initial dashboard
        loads), fall back to text match."""
        # Try data-tab exact attribute lookup with a short wait — the
        # tab bar is dynamically rendered by control_panel.js after
        # page init, so the selector may not be present at the instant
        # we call this on a freshly-loaded page.
        key = self._TAB_KEYS.get(tab_text)
        if key is not None:
            sel = f'.wl-cp-tab[data-tab="{key}"]'
            try:
                self.page.wait_for_selector(sel, timeout=5000, state="visible")
            except Exception:
                pass
            tab = self.page.locator(sel).first
            if tab.count() > 0 and tab.is_visible():
                tab.click()
                time.sleep(1)
                return True
        # Fallback: text match
        tab = self.page.locator(f'.wl-cp-tab:has-text("{tab_text}")').first
        if tab.count() == 0 or not tab.is_visible():
            tab = self.page.locator(
                f'button:has-text("{tab_text}"), .nav-tab:has-text("{tab_text}"), '
                f'a:has-text("{tab_text}")'
            ).first
        if tab.count() > 0 and tab.is_visible():
            tab.click()
            time.sleep(1)
            return True
        return False

    def get_approval_queue(self) -> int:
        """Return the approval queue row count from the UI table. Approval
        Queue is the default tab when opening Control Panel."""
        # Ensure on approval tab (idempotent — clicking when already active is harmless)
        self.click_tab("Approval Queue") or self.click_tab("Approval") or self.click_tab("Queue")
        time.sleep(0.5)
        # Table id varies; fall back to any visible table
        tables = self.page.locator("#approval-queue-table tbody tr, .wl-cp-table tbody tr, table tbody tr")
        return tables.count() if tables.count() > 0 else 0

    def approve_request(self, idx_1based: int, comment: str = "E2E approve") -> bool:
        idx_0based = max(0, idx_1based - 1)
        row = self.page.locator("table tbody tr").nth(idx_0based)
        approve = row.locator(
            'button:has-text("Approve"), .btn-approve, [data-action="approve"]'
        ).first
        if approve.count() == 0:
            return False
        approve.click()
        time.sleep(0.5)
        # Comment modal
        modal = self.page.locator(".wl-modal-overlay")
        if modal.count() > 0 and modal.first.is_visible():
            ta = modal.locator("textarea").first
            if ta.count() > 0 and ta.is_visible():
                ta.fill(comment)
            confirm = modal.locator(".btn-primary, .btn-success").first
            if confirm.count() > 0:
                confirm.click()
                time.sleep(2)
        return True

    def reject_request(self, idx_1based: int, reason: str = "E2E reject") -> bool:
        idx_0based = max(0, idx_1based - 1)
        row = self.page.locator("table tbody tr").nth(idx_0based)
        reject = row.locator(
            'button:has-text("Reject"), .btn-reject, [data-action="reject"]'
        ).first
        if reject.count() == 0:
            return False
        reject.click()
        time.sleep(0.5)
        modal = self.page.locator(".wl-modal-overlay")
        if modal.count() > 0 and modal.first.is_visible():
            ta = modal.locator("textarea").first
            if ta.count() > 0 and ta.is_visible():
                ta.fill(reason)
            confirm = modal.locator(".btn-danger, .btn-primary").first
            if confirm.count() > 0:
                confirm.click()
                time.sleep(2)
        return True

    def get_daily_limits(self) -> Dict[str, Any]:
        """Open Analyst Settings tab and report visibility. (Read-only smoke.)"""
        clicked = self.click_tab("Analyst Settings") or self.click_tab("Daily Limits")
        time.sleep(0.5)
        return {"visible": bool(clicked)}

    def set_daily_limit(self, role: str, limit: int) -> bool:
        """Try to set a limit by role-named input. The real Control Panel
        uses a single `wl_analyst_editor` row + per-action inputs; this is
        a best-effort smoke. Returns True if input was found+filled.
        """
        self.click_tab("Analyst Settings")
        time.sleep(0.5)
        candidates = self.page.locator(
            f'input[name="{role}_limit"], input[data-role="{role}"], input[id*="{role}"]'
        )
        if candidates.count() == 0:
            return False
        inp = candidates.first
        if not inp.is_visible():
            return False
        inp.fill(str(limit))
        time.sleep(0.2)
        save_btn = self.page.locator(
            'button:has-text("Save"), #btn-cp-save, .btn-primary:has-text("Save")'
        ).first
        if save_btn.count() > 0 and save_btn.is_visible():
            save_btn.click()
            time.sleep(1)
        return True

    def get_trash_items(self) -> int:
        self.click_tab("Trash")
        time.sleep(0.5)
        rows = self.page.locator("#trash-table tbody tr, .wl-trash-table tbody tr, table tbody tr")
        return rows.count() if rows.count() > 0 else 0

    def restore_trash_item(self, idx_1based: int) -> bool:
        idx_0based = max(0, idx_1based - 1)
        row = self.page.locator("table tbody tr").nth(idx_0based)
        btn = row.locator(
            'button:has-text("Restore"), .btn-restore, [data-action="restore"]'
        ).first
        if btn.count() == 0:
            return False
        btn.click()
        time.sleep(1)
        return True


class AuditPage(SplunkPage):
    """Audit dashboard page object."""

    DASHBOARD_PATH = "/en-US/app/wl_manager/audit"

    def goto_app(self) -> None:
        self.goto(self.DASHBOARD_PATH)
        time.sleep(3)

    def filter_by_action(self, action: str) -> bool:
        # Splunk's input dropdown on the dashboard
        dd = self.page.locator(
            'div[data-test="select"], div[class*="dropdown"], select'
        ).first
        if dd.count() == 0 or not dd.is_visible():
            return False
        dd.click()
        time.sleep(0.3)
        option = self.page.locator(f'text="{action}"').first
        if option.count() > 0 and option.is_visible():
            option.click()
            time.sleep(1)
            return True
        return False

    def get_event_count(self) -> int:
        rows = self.page.locator("table tbody tr")
        return rows.count()
