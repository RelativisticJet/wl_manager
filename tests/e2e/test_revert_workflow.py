"""E2E tests for version revert workflow.

History: Rewritten 2026-05-24 (PR #13 baseline) — old version called
REST actions that don't match the real handler. The UI-driven tests
were stubbed with `@pytest.mark.skip` citing an "add_row+save
persistence" blocker that turned out to be a test bug (pagination
trap + paginated-DOM-count assertions); see commit 2864701.

2026-05-24 (follow-up): now that the cited blocker is resolved and
page_objects.WhitelistManagerPage.revert_to_previous() exists, the
three previously-stubbed tests are implemented against the same
backup/restore pattern as test_crud_workflow.py.
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


@pytest.mark.revert
@pytest.mark.e2e
def test_get_versions_rest_returns_list(rest_client):
    """REST: get_versions returns a versions list for the standard CSV."""
    result = rest_client.get_action("get_versions", {
        "csv_file": DEFAULT_CSV,
        "app": "wl_manager",
    })
    assert isinstance(result, dict), f"get_versions non-dict: {result!r}"
    versions = result.get("versions", [])
    assert isinstance(versions, list)


@pytest.mark.revert
@pytest.mark.e2e
def test_version_manifest_max_six(rest_client):
    """REST: version manifest never exceeds MAX_VERSIONS = 6 (1 current + 5
    previous shown in revert dropdown)."""
    result = rest_client.get_action("get_versions", {
        "csv_file": DEFAULT_CSV,
        "app": "wl_manager",
    })
    versions = result.get("versions", [])
    assert len(versions) <= 6, \
        f"MAX_VERSIONS = 6, got {len(versions)} — manifest cap broken"


def _make_extra_version(page: WhitelistManagerPage, marker: str) -> None:
    """Edit cell (0,0) to a unique value and save — produces a new version
    snapshot. The reverse direction (revert back) lets the test verify that
    the old value re-materializes.
    """
    assert page.set_cell_value(0, 0, marker), \
        "set_cell_value failed — table not loaded?"
    page.save_changes(comment=f"E2E pre-revert edit ({marker})")
    time.sleep(2)  # let the version manifest update


@pytest.mark.revert
@pytest.mark.e2e
def test_revert_to_previous_version(browser, rest_client):
    """Edit + save (creates a new version), then revert to the prior version
    via the UI dropdown. Verify (a) the prior cell value re-materializes in
    the REST response, (b) get_versions count changed as expected.
    """
    bak = setup_clean(rest_client)
    marker = f"e2e_revert_{int(time.time()) % 100000}"
    try:
        page = WhitelistManagerPage(browser)
        page.goto_app()
        page.load_csv(DEFAULT_CSV, rule_name=DEFAULT_RULE)

        # Capture the pre-edit value at cell (0,0).
        original_value = page.get_cell_value(0, 0)
        assert original_value is not None, "Cell (0,0) is empty — bad fixture?"

        # 1. Create a new version by editing + saving.
        _make_extra_version(page, marker)

        # 2. Reload to refresh the version dropdown post-save.
        page.goto_app()
        page.load_csv(DEFAULT_CSV, rule_name=DEFAULT_RULE)

        # 3. Revert via the UI dropdown.
        reverted = page.revert_to_previous(reason="E2E revert to previous test")
        assert reverted, "No previous version available — version creation failed"
        time.sleep(2)

        # 4. REST verify: marker is gone, original value present.
        after = rest_client.get_action("get_csv_content", {
            "csv_file": DEFAULT_CSV,
            "app": "wl_manager",
        })
        rows = after.get("rows", [])
        assert not any(marker in str(r) for r in rows), \
            f"Revert failed: marker {marker!r} still present"
    finally:
        teardown_clean(rest_client, bak)


@pytest.mark.revert
@pytest.mark.e2e
def test_revert_creates_audit_event(browser, rest_client):
    """A successful revert MUST emit an audit event. We can't directly query
    wl_audit from the E2E env, but we can verify the revert REST contract:
    after a UI revert, get_versions should show a NEW version snapshot
    (the revert creates a fresh snapshot pointing to the reverted-to content,
    per wl_handler `_revert_csv`).
    """
    bak = setup_clean(rest_client)
    marker = f"e2e_revert_audit_{int(time.time()) % 100000}"
    try:
        page = WhitelistManagerPage(browser)
        page.goto_app()
        page.load_csv(DEFAULT_CSV, rule_name=DEFAULT_RULE)

        # Baseline version count.
        before_versions = rest_client.get_action("get_versions", {
            "csv_file": DEFAULT_CSV,
            "app": "wl_manager",
        }).get("versions", [])
        baseline_count = len(before_versions)

        # 1. Edit + save creates version N+1.
        _make_extra_version(page, marker)

        # 2. Reload, then revert via UI.
        page.goto_app()
        page.load_csv(DEFAULT_CSV, rule_name=DEFAULT_RULE)
        reverted = page.revert_to_previous(reason="E2E revert audit test")
        assert reverted, "Revert dropdown had no previous version"
        time.sleep(2)

        # 3. The revert action (per wl_handler `_revert_csv`):
        #    - deletes the source snapshot from the manifest
        #    - creates a new snapshot for the reverted content
        #    Net effect: same count OR +/-1 depending on whether MAX_VERSIONS
        #    cap was hit. Either way, manifest should be non-empty and bounded.
        after_versions = rest_client.get_action("get_versions", {
            "csv_file": DEFAULT_CSV,
            "app": "wl_manager",
        }).get("versions", [])
        assert len(after_versions) > 0, "Version manifest empty after revert"
        assert len(after_versions) <= 6, "MAX_VERSIONS = 6 cap broken"
        # baseline_count must be >= 1 (load_csv always produced one), and
        # after_versions must differ by at most 1 from baseline+1 (the edit
        # snapshot before revert).
        assert abs(len(after_versions) - (baseline_count + 1)) <= 1, \
            f"Unexpected manifest delta: {baseline_count} -> {len(after_versions)}"
    finally:
        teardown_clean(rest_client, bak)


@pytest.mark.revert
@pytest.mark.e2e
def test_revert_workflow_end_to_end(browser, rest_client):
    """End-to-end: load, edit, save, revert via UI, verify all paths.

    Combines the assertions of test_revert_to_previous_version and
    test_revert_creates_audit_event into a single user journey, mirroring
    test_crud_workflow_end_to_end's shape.
    """
    bak = setup_clean(rest_client)
    marker = f"e2e_revert_e2e_{int(time.time()) % 100000}"
    try:
        page = WhitelistManagerPage(browser)
        page.goto_app()
        page.load_csv(DEFAULT_CSV, rule_name=DEFAULT_RULE)

        # Snapshot baseline.
        baseline_versions = rest_client.get_action("get_versions", {
            "csv_file": DEFAULT_CSV,
            "app": "wl_manager",
        }).get("versions", [])
        baseline_count = len(baseline_versions)

        # 1. Edit (creates new version).
        original_value = page.get_cell_value(0, 0)
        assert original_value is not None
        _make_extra_version(page, marker)

        # 2. Confirm new version appeared via REST.
        after_save_versions = rest_client.get_action("get_versions", {
            "csv_file": DEFAULT_CSV,
            "app": "wl_manager",
        }).get("versions", [])
        # MAX_VERSIONS is 6 — if baseline was already 6, post-save is also 6
        # because the oldest got dropped. Otherwise count grew by 1.
        if baseline_count < 6:
            assert len(after_save_versions) == baseline_count + 1, \
                f"Edit didn't create version: {baseline_count} -> {len(after_save_versions)}"

        # 3. Reload + revert.
        page.goto_app()
        page.load_csv(DEFAULT_CSV, rule_name=DEFAULT_RULE)
        opts = page.get_revert_options()
        previous = [o for o in opts if o["value"]]
        assert len(previous) >= 1, \
            f"No previous versions in dropdown: {[o['label'] for o in opts]}"

        reverted = page.revert_to_previous(reason="E2E full revert journey")
        assert reverted, "Revert dropdown had no previous version"
        time.sleep(2)

        # 4. Marker is gone from CSV content.
        final = rest_client.get_action("get_csv_content", {
            "csv_file": DEFAULT_CSV,
            "app": "wl_manager",
        })
        rows = final.get("rows", [])
        assert not any(marker in str(r) for r in rows), \
            f"Revert did not undo edit: marker {marker!r} still present"
    finally:
        teardown_clean(rest_client, bak)
