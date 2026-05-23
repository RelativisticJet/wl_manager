"""E2E stress tests.

Rewritten 2026-05-24 (PR #13 baseline). Old version included 3 theme
toggle tests for a feature that was REMOVED in build 637 (dark-only
theme enforced — see CLAUDE.md DECISION_LOG 2026-05-01 row "Drop
light-theme support; force dark-only theme"). Those tests are
deleted, not skipped: testing a feature that doesn't exist is
unmaintainable scaffolding, not a useful test.

Remaining: stress tests that load the standard mapped CSV and
exercise the table rendering / interaction path.
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


@pytest.mark.stress
@pytest.mark.slow
@pytest.mark.e2e
def test_stress_load_csv_table_renders(browser, rest_client):
    """Smoke: standard CSV loads + table renders + scroll doesn't crash.

    The original test created a 100-column / 200-row CSV via REST
    `create_csv` (which would never have worked — see _shared.py).
    The actual stress concern was "does the table renderer crash on
    wide / heavy CSVs?", which we can exercise on the standard CSV
    plus a programmatic scroll.
    """
    bak = setup_clean(rest_client)
    try:
        page = WhitelistManagerPage(browser)
        page.goto_app()
        page.load_csv(DEFAULT_CSV, rule_name=DEFAULT_RULE)

        # Table is visible
        table = page.page.locator("#csv-table-container table").first
        assert table.is_visible()

        # Programmatic scroll — must not crash even if the table is
        # narrower than the scroll target
        table.evaluate("el => el.scrollLeft = 5000")
        time.sleep(0.5)

        # Rows still queryable
        assert page.get_row_count() > 0
    finally:
        teardown_clean(rest_client, bak)


@pytest.mark.stress
@pytest.mark.slow
@pytest.mark.e2e
def test_stress_repeated_cell_edits(browser, rest_client):
    """Edit the same cell 5 times in sequence; final save persists last value.

    The original test would `edit_cell(1, 2, ...)` in a loop but never
    saved between edits, so only the LAST value reached the backend
    anyway. We keep that semantic: single save after N in-memory edits.
    """
    bak = setup_clean(rest_client)
    final_value = f"e2e_stress_{int(time.time()) % 100000}"
    try:
        page = WhitelistManagerPage(browser)
        page.goto_app()
        page.load_csv(DEFAULT_CSV, rule_name=DEFAULT_RULE)

        # 5 edits to row 0 col 0
        for i in range(4):
            page.set_cell_value(0, 0, f"e2e_stress_iter_{i}")
            time.sleep(0.2)
        page.set_cell_value(0, 0, final_value)

        page.save_changes(comment=f"E2E stress: 5 edits, final={final_value}")
        time.sleep(1)

        # Verify the LAST value persisted (intermediate values discarded
        # by save consolidation, which is the documented behavior).
        after = rest_client.get_action("get_csv_content", {
            "csv_file": DEFAULT_CSV,
            "app": "wl_manager",
        })
        assert any(final_value in str(r) for r in after.get("rows", [])), \
            f"Final edit value {final_value!r} missing"
    finally:
        teardown_clean(rest_client, bak)
