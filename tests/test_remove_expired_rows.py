"""Tests for _remove_expired_rows — expiration date handling."""

import sys
import os
import unittest
from datetime import datetime, timedelta, timezone

# Extract the functions without importing the full module (Splunk deps).

_src = open(
    os.path.join(os.path.dirname(__file__), "..", "bin", "wl_handler.py"),
    encoding="utf-8",
).read()

# Build namespace with required imports
_ns = {
    "datetime": datetime,
    "timedelta": timedelta,
    "timezone": timezone,
}

# Extract _find_expire_column
exec(
    """
EXPIRE_COLUMN_NAMES = {
    "expires", "expire", "expiration", "expiration_date",
    "expiry", "termination", "termination_date",
}

def _find_expire_column(headers):
    for h in headers:
        if h.lower() in EXPIRE_COLUMN_NAMES:
            return h
    return None
""",
    _ns,
)

# Extract _remove_expired_rows
import re

_match = re.search(
    r"(def _remove_expired_rows\(.*?\n)(?=\ndef |\nclass |\n# ═)",
    _src,
    re.DOTALL,
)
if _match:
    exec(_match.group(0), _ns)

_remove_expired_rows = _ns["_remove_expired_rows"]
_find_expire_column = _ns["_find_expire_column"]


class TestFindExpireColumn(unittest.TestCase):
    """Verify case-insensitive expire column detection."""

    def test_expires_lowercase(self):
        self.assertEqual(_find_expire_column(["user", "expires"]), "expires")

    def test_expires_mixed_case(self):
        self.assertEqual(_find_expire_column(["Expires", "user"]), "Expires")

    def test_expiration_date(self):
        self.assertEqual(
            _find_expire_column(["ip", "Expiration_Date"]), "Expiration_Date"
        )

    def test_no_expire_column(self):
        self.assertIsNone(_find_expire_column(["user", "ip", "comment"]))

    def test_termination(self):
        self.assertEqual(
            _find_expire_column(["user", "Termination"]), "Termination"
        )


class TestRemoveExpiredRowsUTC(unittest.TestCase):
    """Test UTC date format (YYYY-MM-DD HH:MM UTC)."""

    def test_expired_utc_removed(self):
        headers = ["user", "Expires"]
        rows = [
            {"user": "alice", "Expires": "2020-01-01 00:00 UTC"},
            {"user": "bob", "Expires": "2099-01-01 00:00 UTC"},
        ]
        kept, expired = _remove_expired_rows(headers, rows)
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["user"], "bob")
        self.assertEqual(len(expired), 1)
        self.assertEqual(expired[0]["user"], "alice")

    def test_empty_expires_kept(self):
        headers = ["user", "Expires"]
        rows = [
            {"user": "alice", "Expires": ""},
            {"user": "bob", "Expires": "2099-12-31 23:59 UTC"},
        ]
        kept, expired = _remove_expired_rows(headers, rows)
        self.assertEqual(len(kept), 2)
        self.assertEqual(len(expired), 0)

    def test_date_only_utc(self):
        """Date-only UTC format (no time component)."""
        headers = ["user", "Expires"]
        rows = [{"user": "alice", "Expires": "2020-06-15 UTC"}]
        kept, expired = _remove_expired_rows(headers, rows)
        self.assertEqual(len(expired), 1)


class TestRemoveExpiredRowsLegacy(unittest.TestCase):
    """Test legacy local date format (YYYY-MM-DD HH:MM)."""

    def test_legacy_expired_removed(self):
        headers = ["user", "Expires"]
        rows = [
            {"user": "alice", "Expires": "2020-01-01 00:00"},
            {"user": "bob", "Expires": "2099-01-01 00:00"},
        ]
        kept, expired = _remove_expired_rows(headers, rows, tz_offset_minutes=0)
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["user"], "bob")

    def test_tz_offset_matters(self):
        """Timezone offset should shift the comparison time for legacy dates."""
        now_utc = datetime.now(timezone.utc)
        # Create a date that's just barely in the past in UTC
        past = now_utc - timedelta(hours=1)
        past_str = past.strftime("%Y-%m-%d %H:%M")

        headers = ["user", "Expires"]
        rows = [{"user": "alice", "Expires": past_str}]

        # With UTC offset (tz_offset_minutes=0), the row should be expired
        kept, expired = _remove_expired_rows(headers, rows, tz_offset_minutes=0)
        self.assertEqual(len(expired), 1)


class TestRemoveExpiredRowsNoColumn(unittest.TestCase):
    """When there's no expire column, all rows should be kept."""

    def test_no_expire_column(self):
        headers = ["user", "ip"]
        rows = [{"user": "alice", "ip": "10.0.0.1"}]
        kept, expired = _remove_expired_rows(headers, rows)
        self.assertEqual(len(kept), 1)
        self.assertEqual(len(expired), 0)


class TestRemoveExpiredRowsInvalidDates(unittest.TestCase):
    """Invalid date values should be kept (not removed)."""

    def test_unparseable_date_kept(self):
        headers = ["user", "Expires"]
        rows = [
            {"user": "alice", "Expires": "not-a-date"},
            {"user": "bob", "Expires": "tomorrow"},
        ]
        kept, expired = _remove_expired_rows(headers, rows)
        self.assertEqual(len(kept), 2)
        self.assertEqual(len(expired), 0)

    def test_mixed_valid_invalid(self):
        headers = ["user", "Expires"]
        rows = [
            {"user": "alice", "Expires": "invalid"},
            {"user": "bob", "Expires": "2020-01-01 00:00 UTC"},
            {"user": "charlie", "Expires": "2099-01-01 00:00 UTC"},
        ]
        kept, expired = _remove_expired_rows(headers, rows)
        self.assertEqual(len(kept), 2)  # alice (invalid = kept) + charlie (future)
        self.assertEqual(len(expired), 1)  # bob (past)


if __name__ == "__main__":
    unittest.main()
