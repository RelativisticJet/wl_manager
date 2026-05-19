"""
Unit tests for wl_csv module.

Tests CSV read/write, diff computation, expiration handling, and column width
tracking. All tests run offline with no Docker/Splunk required.

Fixtures:
- tmp_path (pytest built-in): Temporary directory for file I/O tests
- freezegun: Freeze time for expiration tests
"""

import json
import os
import sys
import pytest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from freezegun import freeze_time

# Add bin directory to path to import wl_csv and dependencies
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../bin'))

from wl_csv import (
    read_csv, write_csv, compute_diff, get_expire_column,
    remove_expired_rows, get_column_widths, set_column_widths,
    update_csv_expected_hash, remove_csv_expected_hash,
    bootstrap_csv_expected_hashes, CSV_EXPECTED_HASHES_FILE,
)
from wl_constants import VERSIONS_DIR
from wl_hmac_key import read_expected_hashes


# ═════════════════════════════════════════════════════════════════════════════
# Test: read_csv
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.unit
def test_read_csv_normal_file(tmp_path):
    """Read valid CSV with headers and multiple rows."""
    csv_path = tmp_path / "test.csv"
    csv_path.write_text("name,age,city\njohn,30,NYC\njane,25,LA\n", encoding="utf-8")

    headers, rows = read_csv(str(csv_path))

    assert headers == ["name", "age", "city"]
    assert len(rows) == 2
    assert rows[0] == {"name": "john", "age": "30", "city": "NYC"}
    assert rows[1] == {"name": "jane", "age": "25", "city": "LA"}


@pytest.mark.unit
def test_read_csv_with_utf8_bom(tmp_path):
    """Read CSV with UTF-8 BOM marker — BOM should be stripped."""
    csv_path = tmp_path / "test.csv"
    # Write with BOM
    with open(str(csv_path), "w", encoding="utf-8-sig") as f:
        f.write("name,age\njohn,30\n")

    headers, rows = read_csv(str(csv_path))

    assert headers == ["name", "age"]
    assert rows[0]["name"] == "john"  # BOM stripped


@pytest.mark.unit
def test_read_csv_empty_file(tmp_path):
    """Read CSV with only headers, no data rows."""
    csv_path = tmp_path / "test.csv"
    csv_path.write_text("name,age,city\n", encoding="utf-8")

    headers, rows = read_csv(str(csv_path))

    assert headers == ["name", "age", "city"]
    assert rows == []


@pytest.mark.unit
def test_read_csv_missing_file(tmp_path):
    """Read non-existent file — should raise OSError."""
    csv_path = tmp_path / "nonexistent.csv"

    with pytest.raises(OSError):
        read_csv(str(csv_path))


@pytest.mark.unit
def test_read_csv_with_empty_cells(tmp_path):
    """Read CSV with empty cells — should be empty strings in dicts."""
    csv_path = tmp_path / "test.csv"
    csv_path.write_text("name,age,city\njohn,,NYC\n", encoding="utf-8")

    headers, rows = read_csv(str(csv_path))

    assert rows[0] == {"name": "john", "age": "", "city": "NYC"}


# ═════════════════════════════════════════════════════════════════════════════
# Test: write_csv
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.unit
def test_write_csv_normal(tmp_path):
    """Write CSV with headers and rows."""
    csv_path = tmp_path / "test.csv"
    headers = ["name", "age", "city"]
    rows = [
        {"name": "john", "age": "30", "city": "NYC"},
        {"name": "jane", "age": "25", "city": "LA"},
    ]

    write_csv(str(csv_path), headers, rows)

    # Verify file exists and contains correct content
    assert csv_path.exists()
    content = csv_path.read_text(encoding="utf-8")
    assert "name,age,city" in content
    assert "john,30,NYC" in content
    assert "jane,25,LA" in content


@pytest.mark.unit
def test_write_csv_empty_rows(tmp_path):
    """Write CSV with headers but no rows."""
    csv_path = tmp_path / "test.csv"
    headers = ["name", "age", "city"]
    rows = []

    write_csv(str(csv_path), headers, rows)

    content = csv_path.read_text(encoding="utf-8")
    assert content.strip() == "name,age,city"


@pytest.mark.unit
def test_write_csv_extra_fields_ignored(tmp_path):
    """Write CSV where rows have extra fields not in headers — extra fields should be excluded."""
    csv_path = tmp_path / "test.csv"
    headers = ["name", "age"]
    rows = [
        {"name": "john", "age": "30", "extra": "ignored"},
    ]

    write_csv(str(csv_path), headers, rows)

    content = csv_path.read_text(encoding="utf-8")
    # Extra field should not appear in output
    assert "extra" not in content
    assert "john,30" in content


@pytest.mark.unit
def test_write_csv_atomic_write(tmp_path):
    """Verify write_csv uses atomic temp->rename pattern."""
    csv_path = tmp_path / "test.csv"
    headers = ["name"]
    rows = [{"name": "john"}]

    write_csv(str(csv_path), headers, rows)

    # Verify final file exists (temp file should be gone)
    assert csv_path.exists()
    assert not (tmp_path / "test.csv.tmp").exists()


# ═════════════════════════════════════════════════════════════════════════════
# Test: compute_diff
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.unit
def test_compute_diff_no_changes():
    """Compare identical old and new — all counts should be 0."""
    headers = ["name", "age"]
    rows = [
        {"name": "john", "age": "30"},
        {"name": "jane", "age": "25"},
    ]

    diff = compute_diff(headers, rows, headers, rows)

    assert diff["added"] == []
    assert diff["removed"] == []
    assert diff["edited"] == []
    assert diff["added_count"] == 0
    assert diff["removed_count"] == 0
    assert diff["edited_count"] == 0
    assert diff["added_columns"] == []
    assert diff["removed_columns"] == []


@pytest.mark.unit
def test_compute_diff_added_rows():
    """Add 2 new rows to CSV."""
    headers = ["name", "age"]
    old_rows = [{"name": "john", "age": "30"}]
    new_rows = [
        {"name": "john", "age": "30"},
        {"name": "jane", "age": "25"},
        {"name": "bob", "age": "35"},
    ]

    diff = compute_diff(headers, old_rows, headers, new_rows)

    assert diff["added_count"] == 2
    assert len(diff["added"]) == 2
    assert {"name": "jane", "age": "25"} in diff["added"]
    assert {"name": "bob", "age": "35"} in diff["added"]


@pytest.mark.unit
def test_compute_diff_removed_rows():
    """Remove 2 rows from CSV."""
    headers = ["name", "age"]
    old_rows = [
        {"name": "john", "age": "30"},
        {"name": "jane", "age": "25"},
        {"name": "bob", "age": "35"},
    ]
    new_rows = [{"name": "john", "age": "30"}]

    diff = compute_diff(headers, old_rows, headers, new_rows)

    assert diff["removed_count"] == 2
    assert len(diff["removed"]) == 2
    assert {"name": "jane", "age": "25"} in diff["removed"]
    assert {"name": "bob", "age": "35"} in diff["removed"]


@pytest.mark.unit
def test_compute_diff_edited_row():
    """Edit one field in one row."""
    headers = ["name", "age"]
    old_rows = [{"name": "john", "age": "30"}]
    new_rows = [{"name": "john", "age": "31"}]  # age changed

    diff = compute_diff(headers, old_rows, headers, new_rows)

    assert diff["edited_count"] == 1
    assert len(diff["edited"]) == 1
    assert diff["edited"][0]["old_row"] == {"name": "john", "age": "30"}
    assert diff["edited"][0]["new_row"] == {"name": "john", "age": "31"}
    assert len(diff["edited"][0]["changed_fields"]) == 1
    assert diff["edited"][0]["changed_fields"][0]["field"] == "age"
    assert diff["edited"][0]["changed_fields"][0]["before"] == "30"
    assert diff["edited"][0]["changed_fields"][0]["after"] == "31"


@pytest.mark.unit
def test_compute_diff_duplicate_rows():
    """Add duplicate rows — should count both as added."""
    headers = ["name"]
    old_rows = []
    new_rows = [
        {"name": "john"},
        {"name": "john"},  # duplicate
    ]

    diff = compute_diff(headers, old_rows, headers, new_rows)

    assert diff["added_count"] == 2
    assert len(diff["added"]) == 2


@pytest.mark.unit
def test_compute_diff_added_column():
    """Add a new column — should track in added_columns."""
    old_headers = ["name", "age"]
    old_rows = [{"name": "john", "age": "30"}]

    new_headers = ["name", "age", "city"]
    new_rows = [{"name": "john", "age": "30", "city": "NYC"}]

    diff = compute_diff(old_headers, old_rows, new_headers, new_rows)

    assert "city" in diff["added_columns"]
    # Adding a column shouldn't create false edits on existing rows
    assert diff["edited_count"] == 0
    assert diff["added_count"] == 0
    assert diff["removed_count"] == 0


@pytest.mark.unit
def test_compute_diff_removed_column():
    """Remove a column."""
    old_headers = ["name", "age", "city"]
    old_rows = [{"name": "john", "age": "30", "city": "NYC"}]

    new_headers = ["name", "age"]
    new_rows = [{"name": "john", "age": "30"}]

    diff = compute_diff(old_headers, old_rows, new_headers, new_rows)

    assert "city" in diff["removed_columns"]
    assert diff["edited_count"] == 0


@pytest.mark.unit
def test_compute_diff_skip_edit_detection_large():
    """When >MAX_DIFF_ROWS on either side, skip expensive edit detection."""
    from wl_constants import MAX_DIFF_ROWS

    headers = ["id", "name"]
    # Create more than MAX_DIFF_ROWS added and removed rows
    old_rows = [{"id": str(i), "name": f"user_{i}"} for i in range(MAX_DIFF_ROWS + 10)]
    new_rows = [{"id": str(i + MAX_DIFF_ROWS + 20), "name": f"user_{i + MAX_DIFF_ROWS + 20}"}
                for i in range(MAX_DIFF_ROWS + 10)]

    diff = compute_diff(headers, old_rows, headers, new_rows)

    # With skip_edit_detection=True, all changes are pure adds/removes (no edits)
    assert diff["edited_count"] == 0
    assert diff["added_count"] == MAX_DIFF_ROWS + 10
    assert diff["removed_count"] == MAX_DIFF_ROWS + 10


@pytest.mark.unit
def test_compute_diff_edit_similarity_threshold():
    """Edit must match >50% of fields to pair as edit (not add+remove)."""
    headers = ["field1", "field2", "field3", "field4"]
    old_rows = [{"field1": "a", "field2": "b", "field3": "c", "field4": "d"}]
    new_rows = [{"field1": "X", "field2": "Y", "field3": "c", "field4": "d"}]  # 50% match

    diff = compute_diff(headers, old_rows, headers, new_rows)

    # Exactly 50% match threshold — should be paired as edit
    # (50% = len(common_headers)/2 is the boundary; >= means edit)
    assert diff["edited_count"] == 1


@pytest.mark.unit
def test_compute_diff_reverse_iteration():
    """When new has 2 copies of row X (old has 0), both should be added (not mistaken for pre-existing)."""
    headers = ["name"]
    old_rows = []
    new_rows = [
        {"name": "john"},
        {"name": "john"},  # both are new, not pre-existing duplicates
    ]

    diff = compute_diff(headers, old_rows, headers, new_rows)

    assert diff["added_count"] == 2
    assert len(diff["added"]) == 2


@pytest.mark.unit
def test_compute_diff_ignores_metadata_columns():
    """Columns starting with _ are internal metadata and should be ignored for diff."""
    headers = ["name", "_added_by", "_added_at"]
    old_rows = [{"name": "john", "_added_by": "admin", "_added_at": "2026-01-01"}]
    new_rows = [{"name": "john", "_added_by": "analyst", "_added_at": "2026-01-02"}]

    diff = compute_diff(headers, old_rows, headers, new_rows)

    # Metadata columns changed, but shouldn't create edit event
    assert diff["edited_count"] == 0
    assert diff["added_count"] == 0


# ═════════════════════════════════════════════════════════════════════════════
# Test: get_expire_column
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.unit
def test_get_expire_column_found():
    """Find 'Expires' column in headers."""
    headers = ["name", "age", "Expires"]
    result = get_expire_column(headers)
    assert result == "Expires"


@pytest.mark.unit
def test_get_expire_column_case_insensitive():
    """Find expire column with case-insensitive matching."""
    headers = ["name", "age", "expires"]
    result = get_expire_column(headers)
    assert result == "expires"


@pytest.mark.unit
def test_get_expire_column_not_found():
    """Return None when no expire column."""
    headers = ["name", "age", "city"]
    result = get_expire_column(headers)
    assert result is None


@pytest.mark.unit
def test_get_expire_column_empty_headers():
    """Return None for empty headers list."""
    headers = []
    result = get_expire_column(headers)
    assert result is None


# ═════════════════════════════════════════════════════════════════════════════
# Test: remove_expired_rows
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.unit
def test_remove_expired_rows_no_expires_column():
    """No Expires column — all rows kept."""
    headers = ["name", "age"]
    rows = [{"name": "john", "age": "30"}]

    kept, expired_count = remove_expired_rows(headers, rows)

    assert expired_count == 0
    assert kept == rows


@pytest.mark.unit
@freeze_time("2026-03-31 12:00:00")
def test_remove_expired_rows_future_dates():
    """All Expires dates in future — all rows kept."""
    headers = ["name", "Expires"]
    rows = [
        {"name": "john", "Expires": "2026-04-01 12:00 UTC"},  # tomorrow
        {"name": "jane", "Expires": "2026-05-01 12:00 UTC"},  # next month
    ]

    kept, expired_count = remove_expired_rows(headers, rows)

    assert expired_count == 0
    assert len(kept) == 2


@pytest.mark.unit
@freeze_time("2026-03-31 12:00:00")
def test_remove_expired_rows_past_dates():
    """All Expires dates in past — all rows removed."""
    headers = ["name", "Expires"]
    rows = [
        {"name": "john", "Expires": "2026-03-30 12:00 UTC"},  # yesterday
        {"name": "jane", "Expires": "2026-01-01 12:00 UTC"},  # months ago
    ]

    kept, expired_count = remove_expired_rows(headers, rows)

    assert expired_count == 2
    assert len(kept) == 0


@pytest.mark.unit
@freeze_time("2026-03-31 12:00:00")
def test_remove_expired_rows_mixed_dates():
    """Some past, some future — only past removed."""
    headers = ["name", "Expires"]
    rows = [
        {"name": "john", "Expires": "2026-03-30 12:00 UTC"},  # past
        {"name": "jane", "Expires": "2026-04-01 12:00 UTC"},  # future
    ]

    kept, expired_count = remove_expired_rows(headers, rows)

    assert expired_count == 1
    assert len(kept) == 1
    assert kept[0]["name"] == "jane"


@pytest.mark.unit
@freeze_time("2026-03-31 12:00:00")
def test_remove_expired_rows_tz_offset():
    """Use tz_offset to adjust 'now' for local time comparison."""
    headers = ["name", "Expires"]
    rows = [
        {"name": "john", "Expires": "2026-03-31 08:00"},  # no UTC suffix = local time
    ]

    # With tz_offset=-240 (UTC-4, like EDT), local time is 4 hours behind UTC
    # UTC now: 2026-03-31 12:00
    # Local now: 2026-03-31 08:00
    # Row expires at local 08:00, so it's expired
    kept, expired_count = remove_expired_rows(headers, rows, tz_offset_minutes=-240)

    assert expired_count == 1


@pytest.mark.unit
@freeze_time("2026-03-31 12:00:00")
def test_remove_expired_rows_invalid_date_format():
    """Invalid date in Expires column — row kept (treated as future)."""
    headers = ["name", "Expires"]
    rows = [
        {"name": "john", "Expires": "not-a-date"},
    ]

    kept, expired_count = remove_expired_rows(headers, rows)

    assert expired_count == 0
    assert len(kept) == 1


@pytest.mark.unit
def test_remove_expired_rows_empty_expires_cell():
    """Empty or missing Expires cell — row kept."""
    headers = ["name", "Expires"]
    rows = [
        {"name": "john", "Expires": ""},
        {"name": "jane", "Expires": None},  # CSV fields are strings, but dict might have None
    ]

    kept, expired_count = remove_expired_rows(headers, rows)

    assert expired_count == 0
    assert len(kept) == 2


# ═════════════════════════════════════════════════════════════════════════════
# Test: get_column_widths
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.unit
def test_get_column_widths_file_exists(tmp_path):
    """Read existing column widths JSON file."""
    csv_path = tmp_path / "test.csv"
    csv_path.write_text("name,age\n")

    # Create _versions directory and widths file
    versions_dir = tmp_path / "_versions"
    versions_dir.mkdir()
    widths_file = versions_dir / "test_colwidths.json"
    widths_file.write_text(json.dumps({"name": 100, "age": 50}))

    widths = get_column_widths(str(csv_path))

    assert widths == {"name": 100, "age": 50}


@pytest.mark.unit
def test_get_column_widths_file_missing(tmp_path):
    """No widths file — return empty dict."""
    csv_path = tmp_path / "test.csv"
    csv_path.write_text("name,age\n")

    widths = get_column_widths(str(csv_path))

    assert widths == {}


@pytest.mark.unit
def test_get_column_widths_invalid_json(tmp_path):
    """Malformed JSON in widths file — return empty dict (silently)."""
    csv_path = tmp_path / "test.csv"
    csv_path.write_text("name,age\n")

    versions_dir = tmp_path / "_versions"
    versions_dir.mkdir()
    widths_file = versions_dir / "test_colwidths.json"
    widths_file.write_text("{invalid json")

    widths = get_column_widths(str(csv_path))

    assert widths == {}


# ═════════════════════════════════════════════════════════════════════════════
# Test: set_column_widths
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.unit
def test_set_column_widths_normal(tmp_path):
    """Write column widths to JSON file."""
    csv_path = tmp_path / "test.csv"
    csv_path.write_text("name,age\n")

    widths = {"name": 100, "age": 50}
    set_column_widths(str(csv_path), widths)

    # Verify file was created
    versions_dir = tmp_path / "_versions"
    widths_file = versions_dir / "test_colwidths.json"
    assert widths_file.exists()

    # Verify content
    read_widths = json.loads(widths_file.read_text())
    assert read_widths == widths


@pytest.mark.unit
def test_set_column_widths_overwrite(tmp_path):
    """Write widths twice — second write should overwrite."""
    csv_path = tmp_path / "test.csv"
    csv_path.write_text("name,age\n")

    set_column_widths(str(csv_path), {"name": 100, "age": 50})
    set_column_widths(str(csv_path), {"name": 200, "age": 75})

    versions_dir = tmp_path / "_versions"
    widths_file = versions_dir / "test_colwidths.json"
    read_widths = json.loads(widths_file.read_text())
    assert read_widths == {"name": 200, "age": 75}


@pytest.mark.unit
def test_set_column_widths_empty_dict(tmp_path):
    """Write empty widths dict."""
    csv_path = tmp_path / "test.csv"
    csv_path.write_text("name,age\n")

    set_column_widths(str(csv_path), {})

    versions_dir = tmp_path / "_versions"
    widths_file = versions_dir / "test_colwidths.json"
    assert widths_file.exists()
    assert widths_file.read_text() == "{}"


# ═════════════════════════════════════════════════════════════════════════════
# Test: CSV expected-hashes registry (item G2 coverage push, 2026-05-19)
#
# Covers lines 125-217 in bin/wl_csv.py: remove_csv_expected_hash and
# bootstrap_csv_expected_hashes. These are security-critical (CSV integrity
# monitoring) and had zero unit-test coverage before item G2. The functions
# are wrapped by HMAC sign/verify via wl_hmac_key — derive_hash_registry_key
# falls back to sha256(FIM_HMAC_SALT) when /opt/splunk/etc/instance.cfg is
# absent (test host), so the registry is signed deterministically and reads
# round-trip cleanly without mocking.
# ═════════════════════════════════════════════════════════════════════════════


def _make_lookups_dir(tmp_path):
    """Build a lookups/ tree with rule_csv_map.csv and _versions/ subdir."""
    lookups = tmp_path / "lookups"
    lookups.mkdir()
    (lookups / VERSIONS_DIR).mkdir()
    return lookups


@pytest.mark.unit
def test_remove_csv_expected_hash_removes_existing_entry(tmp_path):
    """remove_csv_expected_hash drops one entry but leaves others intact."""
    lookups = _make_lookups_dir(tmp_path)
    csv_a = lookups / "a.csv"
    csv_a.write_text("name\nAlice\n")
    csv_b = lookups / "b.csv"
    csv_b.write_text("name\nBob\n")
    # Register both
    update_csv_expected_hash(str(csv_a))
    update_csv_expected_hash(str(csv_b))

    remove_csv_expected_hash(str(csv_a))

    hashes_path = lookups / VERSIONS_DIR / CSV_EXPECTED_HASHES_FILE
    hashes = read_expected_hashes(str(hashes_path))
    assert "a.csv" not in hashes
    assert "b.csv" in hashes


@pytest.mark.unit
def test_remove_csv_expected_hash_missing_entry_is_no_op(tmp_path):
    """Removing an entry that isn't registered must not raise or corrupt."""
    lookups = _make_lookups_dir(tmp_path)
    csv_a = lookups / "a.csv"
    csv_a.write_text("name\nAlice\n")
    update_csv_expected_hash(str(csv_a))

    # Try to remove a CSV that was never registered
    fake = lookups / "never_registered.csv"
    remove_csv_expected_hash(str(fake))  # must not raise

    hashes_path = lookups / VERSIONS_DIR / CSV_EXPECTED_HASHES_FILE
    hashes = read_expected_hashes(str(hashes_path))
    assert "a.csv" in hashes  # original entry preserved


@pytest.mark.unit
def test_remove_csv_expected_hash_no_registry_file_is_no_op(tmp_path):
    """Removing from a registry that doesn't exist yet must not raise."""
    lookups = _make_lookups_dir(tmp_path)
    csv_a = lookups / "a.csv"
    csv_a.write_text("name\nAlice\n")
    # No prior update_csv_expected_hash call — registry file absent

    remove_csv_expected_hash(str(csv_a))  # must not raise

    # Registry should still be absent (no spurious write)
    hashes_path = lookups / VERSIONS_DIR / CSV_EXPECTED_HASHES_FILE
    assert not hashes_path.exists()


@pytest.mark.unit
def test_bootstrap_csv_expected_hashes_fresh_install(tmp_path):
    """First bootstrap: every CSV is new, registry is created from scratch."""
    lookups = _make_lookups_dir(tmp_path)
    (lookups / "rule_csv_map.csv").write_text(
        "rule_name,csv_file,app_context\n"
        "R1,a.csv,wl_manager\n"
        "R2,b.csv,wl_manager\n"
    )
    (lookups / "a.csv").write_text("name\nAlice\n")
    (lookups / "b.csv").write_text("name\nBob\n")

    result = bootstrap_csv_expected_hashes(str(lookups))

    # Includes sentinel rule_csv_map.csv plus 2 mapped CSVs = 3
    assert result["hashed_count"] == 3
    assert result["missing_count"] == 0
    assert result["missing_files"] == []
    # All 3 are new on first bootstrap
    assert set(result["new_csvs"]) == {"a.csv", "b.csv", "rule_csv_map.csv"}
    assert result["changed_csvs"] == []
    assert result["removed_csvs"] == []

    # Registry written and HMAC-verifies on round-trip
    hashes_path = lookups / VERSIONS_DIR / CSV_EXPECTED_HASHES_FILE
    assert hashes_path.exists()
    hashes = read_expected_hashes(str(hashes_path))
    assert set(hashes.keys()) == {"a.csv", "b.csv", "rule_csv_map.csv"}


@pytest.mark.unit
def test_bootstrap_csv_expected_hashes_detects_changed_csv(tmp_path):
    """Re-bootstrap after a CSV's content changes records old + new hashes."""
    lookups = _make_lookups_dir(tmp_path)
    (lookups / "rule_csv_map.csv").write_text(
        "rule_name,csv_file,app_context\nR1,a.csv,wl_manager\n"
    )
    a_csv = lookups / "a.csv"
    a_csv.write_text("name\nAlice\n")

    # First bootstrap establishes baseline
    first = bootstrap_csv_expected_hashes(str(lookups))
    old_a_hash = first["new_csvs"]  # has a.csv as new
    assert "a.csv" in old_a_hash

    # Mutate the CSV
    a_csv.write_text("name\nAlice\nBob\n")

    # Second bootstrap detects the change
    second = bootstrap_csv_expected_hashes(str(lookups))
    assert second["new_csvs"] == []  # nothing new
    changed_names = [c["csv_file"] for c in second["changed_csvs"]]
    assert "a.csv" in changed_names
    # The diff entry has the old and new hashes
    a_entry = next(c for c in second["changed_csvs"] if c["csv_file"] == "a.csv")
    assert a_entry["old_hash"] != a_entry["new_hash"]
    assert len(a_entry["old_hash"]) == 64  # SHA-256 hex
    assert len(a_entry["new_hash"]) == 64


@pytest.mark.unit
def test_bootstrap_csv_expected_hashes_detects_removed_csv(tmp_path):
    """Re-bootstrap after a CSV is dropped from mapping records it in removed_csvs."""
    lookups = _make_lookups_dir(tmp_path)
    (lookups / "rule_csv_map.csv").write_text(
        "rule_name,csv_file,app_context\n"
        "R1,a.csv,wl_manager\n"
        "R2,b.csv,wl_manager\n"
    )
    (lookups / "a.csv").write_text("name\nAlice\n")
    (lookups / "b.csv").write_text("name\nBob\n")
    bootstrap_csv_expected_hashes(str(lookups))

    # Drop b.csv from the mapping AND remove the file
    (lookups / "rule_csv_map.csv").write_text(
        "rule_name,csv_file,app_context\nR1,a.csv,wl_manager\n"
    )
    (lookups / "b.csv").unlink()

    result = bootstrap_csv_expected_hashes(str(lookups))
    assert "b.csv" in result["removed_csvs"]
    assert result["new_csvs"] == []
    # a.csv content unchanged but rule_csv_map.csv (the sentinel) IS changed
    # — its new content drops the b.csv row, so its hash differs. This is
    # the laundering-correlation signal: mapping edits surface as a
    # sentinel-CSV change in the same audit event as the removal.
    changed_names = [c["csv_file"] for c in result["changed_csvs"]]
    assert "a.csv" not in changed_names
    assert "rule_csv_map.csv" in changed_names


@pytest.mark.unit
def test_bootstrap_csv_expected_hashes_missing_csv_file(tmp_path):
    """CSV listed in mapping but file absent on disk → missing_files entry."""
    lookups = _make_lookups_dir(tmp_path)
    (lookups / "rule_csv_map.csv").write_text(
        "rule_name,csv_file,app_context\n"
        "R1,a.csv,wl_manager\n"
        "R2,ghost.csv,wl_manager\n"
    )
    (lookups / "a.csv").write_text("name\nAlice\n")
    # ghost.csv referenced but never created

    result = bootstrap_csv_expected_hashes(str(lookups))
    assert result["missing_count"] == 1
    assert "ghost.csv" in result["missing_files"]
    # a.csv + sentinel still hashed
    assert result["hashed_count"] == 2


@pytest.mark.unit
def test_bootstrap_csv_expected_hashes_missing_mapping_raises_oserror(tmp_path):
    """Bootstrap with no rule_csv_map.csv must raise OSError (fail-loud)."""
    lookups = _make_lookups_dir(tmp_path)
    # No rule_csv_map.csv written

    with pytest.raises(OSError) as exc_info:
        bootstrap_csv_expected_hashes(str(lookups))
    assert "rule_csv_map.csv" in str(exc_info.value)


@pytest.mark.unit
def test_bootstrap_csv_expected_hashes_sentinel_csv_always_included(tmp_path):
    """rule_csv_map.csv itself is always hashed even when mapping is empty."""
    lookups = _make_lookups_dir(tmp_path)
    (lookups / "rule_csv_map.csv").write_text(
        "rule_name,csv_file,app_context\n"  # header only, no rows
    )

    result = bootstrap_csv_expected_hashes(str(lookups))
    assert result["hashed_count"] == 1
    assert result["new_csvs"] == ["rule_csv_map.csv"]
    assert result["missing_count"] == 0
