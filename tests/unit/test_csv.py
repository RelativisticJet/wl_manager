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
    remove_expired_rows, get_column_widths, set_column_widths
)


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
