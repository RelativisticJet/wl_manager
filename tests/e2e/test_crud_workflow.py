"""E2E tests for core CRUD workflow (load, edit, add, remove, save).

Rewritten 2026-05-24 (PR #13 baseline). Old version generated unique
CSVs per test via `rest_client.post_action("create_csv", ...)` — but
the real create_csv REST action requires rule association and the UI
dropdown sources from rule_csv_map.csv (3 mappings only). Dynamic
CSVs are not selectable from the UI. See `tests/e2e/_shared.py`
docstring for the full rationale.

New approach: operate on the standard mapped CSV
(DR55_brute_force_users.csv via DR55_brute_force_login), back it up at
test start, restore at test end. Mirrors the proven pattern from
`tests/e2e/test_wl_save.py`.
"""
import pytest
import time
from tests.e2e.page_objects import WhitelistManagerPage
from tests.e2e._shared import (
    DEFAULT_RULE,
    DEFAULT_CSV,
    setup_clean,
    teardown_clean,
)


@pytest.mark.crud
@pytest.mark.e2e
def test_load_csv_and_view_rows(browser, rest_client):
    """Load a mapped CSV via the UI dropdown and verify rows render."""
    bak = setup_clean(rest_client)
    try:
        page = WhitelistManagerPage(browser)
        page.goto_app()
        page.load_csv(DEFAULT_CSV, rule_name=DEFAULT_RULE)

        rows = page.get_table_rows()
        # DR55_brute_force_users.csv has demo data — non-empty.
        assert len(rows) > 0, f"Expected at least 1 row, got {len(rows)}"
    finally:
        teardown_clean(rest_client, bak)


@pytest.mark.crud
@pytest.mark.e2e
def test_edit_cell_and_save(browser, rest_client):
    """Edit the first data cell, save, verify the value persisted via REST."""
    bak = setup_clean(rest_client)
    new_value = f"e2e_edit_{int(time.time()) % 100000}"
    try:
        page = WhitelistManagerPage(browser)
        page.goto_app()
        page.load_csv(DEFAULT_CSV, rule_name=DEFAULT_RULE)

        # Capture original row count + edit cell (0,0) — first data column
        initial = page.get_row_count()
        assert initial > 0, "Need at least 1 row to edit"

        ok = page.set_cell_value(0, 0, new_value)
        assert ok, "set_cell_value returned False — column not found?"

        msg = page.save_changes(comment="E2E edit cell test")
        # Save outcome: either a non-error message OR no message (save
        # may produce no toast if the backend processes silently).
        if msg:
            assert "error" not in msg.lower(), f"Save returned error: {msg}"

        # Verify via REST
        time.sleep(1)
        after = rest_client.get_action("get_csv_content", {
            "csv_file": DEFAULT_CSV,
            "app": "wl_manager",
        })
        assert after.get("headers"), f"get_csv_content failed: {after}"
        # New value should appear in some row (we can't assert position
        # because diff engine may reorder; just check presence)
        found = any(new_value in str(r) for r in after.get("rows", []))
        assert found, f"Edited value {new_value!r} not found after save"
    finally:
        teardown_clean(rest_client, bak)


@pytest.mark.crud
@pytest.mark.e2e
def test_add_row(browser, rest_client):
    """Add a row, fill the first column + the Comment column, save.

    Two non-obvious traps documented here because both blocked this test
    on every playwright version until 2026-05-24:

    1) PAGINATION TRAP: after `add_row`, wl_table.js:776 jumps to the
       new last page. The new row is the LAST visible row on that page
       (not the first). Calling `set_cell_value(0, ...)` would fill an
       existing row instead, and the empty new row gets filtered out by
       wl_save.js:505 (`filter` keeps rows where SOME visible col is
       non-empty). Net effect on the bad path: 1 silent edit + 1 dropped
       row = no row growth.

    2) COMMENT-COLUMN GATE: `getAuditComment` (wl_save.js:410) does
       NOT show an audit-comment modal when the CSV has a `Comment`
       column. Instead it scans EVERY row's Comment cell; if ANY cell
       is empty (including the new row we just added), the entire save
       aborts client-side with "Comment field cannot be empty." — NO
       save_csv POST is sent.

    Fix: fill the LAST visible row's col 0 AND its Comment cell. The
    Comment column index varies per CSV; we find it dynamically by
    looking at the `data-header` attribute of each cell in the new row.
    """
    bak = setup_clean(rest_client)
    initial_total = len(bak.get("rows", []))
    new_value = f"e2e_add_{int(time.time()) % 100000}"
    try:
        page = WhitelistManagerPage(browser)
        page.goto_app()
        page.load_csv(DEFAULT_CSV, rule_name=DEFAULT_RULE)

        page.add_row()
        time.sleep(0.5)

        # The new row is the LAST visible row on the current (last) page.
        visible_after = page.get_row_count()
        assert visible_after > 0, "Expected at least one visible row after add_row"
        new_row_idx = visible_after - 1

        # Fill col 0
        page.set_cell_value(new_row_idx, 0, new_value)

        # Find the Comment col index in the new row by data-header attr
        new_row = page.page.locator("#csv-table-container table tbody tr").nth(new_row_idx)
        cells = new_row.locator("td textarea.wl-input, td input.wl-input")
        comment_idx = None
        for j in range(cells.count()):
            if cells.nth(j).get_attribute("data-header") == "Comment":
                comment_idx = j
                break
        if comment_idx is not None:
            page.set_cell_value(new_row_idx, comment_idx, f"E2E add row test row note")

        page.save_changes(comment="E2E add row test")

        # REST verification: total row count grew by 1, new value present
        time.sleep(1)
        after = rest_client.get_action("get_csv_content", {
            "csv_file": DEFAULT_CSV,
            "app": "wl_manager",
        })
        after_rows = after.get("rows", [])
        assert len(after_rows) == initial_total + 1, \
            f"Row count: {initial_total} -> {len(after_rows)}, expected +1"
        assert any(new_value in str(r) for r in after_rows), \
            f"Added value {new_value!r} not present after save"
    finally:
        teardown_clean(rest_client, bak)


@pytest.mark.crud
@pytest.mark.e2e
def test_remove_row(browser, rest_client):
    """Remove the first row with a reason, save. Verify count via REST.

    Uses REST to count rows (DOM count is paginated — see test_add_row).
    Operates on row 0 of the visible (first) page since that's the row
    the helper most reliably finds — `remove_row(0)` clicks the .btn-rm
    in the topmost visible row.
    """
    bak = setup_clean(rest_client)
    initial_total = len(bak.get("rows", []))
    if initial_total < 2:
        pytest.skip("Need at least 2 rows in CSV to safely test removal")
    try:
        page = WhitelistManagerPage(browser)
        page.goto_app()
        page.load_csv(DEFAULT_CSV, rule_name=DEFAULT_RULE)

        # Remove row at visible index 0 (first row on first page).
        page.remove_row(0, reason="E2E removal test")
        time.sleep(0.5)

        page.save_changes(comment="E2E remove row test")
        time.sleep(1)

        # REST verification (DOM is paginated; REST gives full count)
        after = rest_client.get_action("get_csv_content", {
            "csv_file": DEFAULT_CSV,
            "app": "wl_manager",
        })
        new_rows = after.get("rows", [])
        assert len(new_rows) < initial_total, \
            f"Row count did not decrease: {initial_total} -> {len(new_rows)}"
    finally:
        teardown_clean(rest_client, bak)


@pytest.mark.crud
@pytest.mark.e2e
def test_search_filter_rows(browser, rest_client):
    """Smoke: search filter input accepts text without crashing."""
    bak = setup_clean(rest_client)
    try:
        page = WhitelistManagerPage(browser)
        page.goto_app()
        page.load_csv(DEFAULT_CSV, rule_name=DEFAULT_RULE)

        initial = page.get_row_count()

        # Search for an unlikely string to force filtered count to 0 or stay
        ok = page.search("zzz_no_match_xyz_e2e")
        # search() returns False if no search input exists; that's
        # not a hard failure on the smoke path
        if ok:
            time.sleep(0.5)
            filtered = page.get_row_count()
            assert filtered <= initial, \
                f"Search filter must not INCREASE row count: {initial} -> {filtered}"
            page.clear_search()
    finally:
        teardown_clean(rest_client, bak)


@pytest.mark.crud
@pytest.mark.e2e
def test_horizontal_scroll_wide_csv(browser, rest_client):
    """Smoke: scroll the table horizontally on the standard CSV.

    The original test created a 15-column CSV; we can't do that on the
    mapped CSV (DR55_brute_force_users.csv has fewer columns). Test
    just exercises the scroll mechanic, which is what the original
    was primarily verifying (no crash on scroll)."""
    bak = setup_clean(rest_client)
    try:
        page = WhitelistManagerPage(browser)
        page.goto_app()
        page.load_csv(DEFAULT_CSV, rule_name=DEFAULT_RULE)

        table = page.page.locator("#csv-table-container table").first
        assert table.is_visible(), "Table should be visible"
        # Scroll (may be a no-op on narrow tables, but must not crash)
        try:
            table.evaluate("el => el.scrollLeft = 500")
            time.sleep(0.3)
        except Exception as e:
            pytest.fail(f"Horizontal scroll raised: {e}")

        # Rows still queryable
        assert page.get_row_count() > 0
    finally:
        teardown_clean(rest_client, bak)


@pytest.mark.crud
@pytest.mark.e2e
def test_crud_workflow_end_to_end(browser, rest_client):
    """End-to-end: load, edit, add, save, verify all via REST.

    Edit happens on visible page 1; add_row jumps to last page (per
    wl_table.js pagination semantics). The new row is the LAST visible
    row on the new last page (see test_add_row docstring for the
    pagination-trap explanation).
    """
    bak = setup_clean(rest_client)
    initial_total = len(bak.get("rows", []))
    edit_value = f"e2e_e2e_edit_{int(time.time()) % 100000}"
    add_value = f"e2e_e2e_add_{int(time.time()) % 100000}"
    try:
        page = WhitelistManagerPage(browser)
        page.goto_app()
        page.load_csv(DEFAULT_CSV, rule_name=DEFAULT_RULE)

        # Edit visible row 0, col 0 (on first page)
        assert page.set_cell_value(0, 0, edit_value)

        # Add a row; this jumps to last page where the new row is the
        # LAST visible one. Fill col 0 AND Comment (see test_add_row
        # docstring for why Comment is required).
        page.add_row()
        time.sleep(0.5)
        visible_after_add = page.get_row_count()
        assert visible_after_add > 0, "Expected at least one visible row after add_row"
        new_row_idx = visible_after_add - 1
        page.set_cell_value(new_row_idx, 0, add_value)
        # Fill Comment col by data-header lookup
        new_row = page.page.locator("#csv-table-container table tbody tr").nth(new_row_idx)
        cells = new_row.locator("td textarea.wl-input, td input.wl-input")
        for j in range(cells.count()):
            if cells.nth(j).get_attribute("data-header") == "Comment":
                page.set_cell_value(new_row_idx, j, "E2E e2e row note")
                break

        # Single save commits both changes
        page.save_changes(comment="E2E e2e: edit + add + save")
        time.sleep(1)

        # REST verification (full row set, not paginated DOM)
        after = rest_client.get_action("get_csv_content", {
            "csv_file": DEFAULT_CSV,
            "app": "wl_manager",
        })
        rows = after.get("rows", [])
        assert len(rows) == initial_total + 1, \
            f"Row count: {initial_total} -> {len(rows)}, expected +1"
        assert any(edit_value in str(r) for r in rows), \
            f"Edited value {edit_value!r} missing"
        assert any(add_value in str(r) for r in rows), \
            f"Added value {add_value!r} missing"
    finally:
        teardown_clean(rest_client, bak)
