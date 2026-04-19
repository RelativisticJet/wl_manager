#!/usr/bin/env python3
"""
Custom generating search command: | wlexpiringsoon

Reads all CSVs from rule_csv_map.csv, finds rows with future expiration dates,
and returns them sorted by days remaining (soonest first).

Supports multiple expiration column names: Expires, expire, expiration,
expiration_date, expiry, termination, termination_date.

Output columns: detection_rule, csv_file, Expires, value
The "value" field is a multivalue field with all row fields formatted as
"field_row_N: value", sorted alphabetically.
"""

import csv
import os
import sys
from datetime import datetime

SPLUNK_HOME = os.environ.get("SPLUNK_HOME", "/opt/splunk")
APP_NAME = "wl_manager"
APPS_DIR = os.path.join(SPLUNK_HOME, "etc", "apps")
OWN_LOOKUPS = os.path.join(APPS_DIR, APP_NAME, "lookups")
MAPPING_FILE = os.path.join(OWN_LOOKUPS, "rule_csv_map.csv")

# Make the app's ``bin/`` directory importable when this script runs
# as a Splunk custom command (bundled Python may omit it).
_BIN_DIR = os.path.join(APPS_DIR, APP_NAME, "bin")
if _BIN_DIR not in sys.path:
    sys.path.insert(0, _BIN_DIR)

EXPIRE_FORMATS = ("%Y-%m-%d %H:%M", "%Y-%m-%d")
HIDDEN_FIELDS = {"_added_by", "_added_at", "_review_status"}

# Delegate expiration-column detection to the canonical wl_csv helper
# so this script, the scheduled cleanup job, and the handler all agree
# on which headers count as "the expires column" (Phase 3b consolidation
# — see CLAUDE.md 2026-04-19).
from wl_csv import get_expire_column as find_expire_column  # noqa: E402
# Re-export EXPIRE_COLUMN_NAMES for any callers still referencing the
# module-level constant.
from wl_constants import EXPIRE_COLUMN_NAMES  # noqa: E402,F401


def parse_expires(val):
    """Parse an expiration value; return datetime or None."""
    val = (val or "").strip()
    if not val:
        return None
    for fmt in EXPIRE_FORMATS:
        try:
            return datetime.strptime(val, fmt)
        except ValueError:
            continue
    return None


def main():
    now = datetime.now()

    if not os.path.isfile(MAPPING_FILE):
        return

    with open(MAPPING_FILE, "r", newline="", encoding="utf-8-sig") as fh:
        mapping = list(csv.DictReader(fh))

    results = []

    for entry in mapping:
        csv_file = entry.get("csv_file", "")
        app_context = entry.get("app_context", "")
        rule_name = entry.get("rule_name", "")

        if not csv_file:
            continue

        if app_context:
            path = os.path.join(
                APPS_DIR, os.path.basename(app_context), "lookups", csv_file
            )
        else:
            path = os.path.join(OWN_LOOKUPS, csv_file)

        if not os.path.isfile(path):
            continue

        with open(path, "r", newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            headers = list(reader.fieldnames or [])

            expire_col = find_expire_column(headers)
            if not expire_col:
                continue

            for row in reader:
                exp_date = parse_expires(row.get(expire_col))
                if exp_date is None or exp_date <= now:
                    continue

                secs_left = (exp_date - now).total_seconds()
                total_hours = int(secs_left // 3600)
                days_whole = total_hours // 24
                hours_rem = total_hours % 24
                d_word = "day" if days_whole == 1 else "days"
                h_word = "hour" if hours_rem == 1 else "hours"
                if days_whole == 0:
                    time_label = "{} {} left".format(hours_rem, h_word)
                elif hours_rem == 0:
                    time_label = "{} {} left".format(days_whole, d_word)
                else:
                    time_label = "{} {} {} {} left".format(
                        days_whole, d_word, hours_rem, h_word
                    )

                # Build value lines: all visible fields sorted alphabetically
                # Each result is a single row, so always use _row_1
                value_lines = []
                visible = [
                    h for h in headers
                    if h not in HIDDEN_FIELDS and not h.startswith("_")
                ]
                for col in sorted(visible):
                    val = row.get(col, "")
                    if val:
                        value_lines.append(
                            "{}_row_1: {}".format(col, val)
                        )

                results.append({
                    "detection_rule": rule_name,
                    "csv_file": csv_file,
                    "Expires": "{} ({})".format(
                        row.get(expire_col, ""), time_label
                    ),
                    "value": value_lines,
                    "_sort": total_hours,
                })

    results.sort(key=lambda r: r["_sort"])

    if not results:
        return

    fields = ["detection_rule", "csv_file", "Expires", "value", "__mv_value"]
    writer = csv.DictWriter(
        sys.stdout, fieldnames=fields, extrasaction="ignore"
    )
    writer.writeheader()

    for r in results:
        lines = r["value"]
        mv_encoded = ";".join("${}$".format(v) for v in lines)
        writer.writerow({
            "detection_rule": r["detection_rule"],
            "csv_file": r["csv_file"],
            "Expires": r["Expires"],
            "value": lines[0] if lines else "",
            "__mv_value": mv_encoded,
        })


if __name__ == "__main__":
    main()
