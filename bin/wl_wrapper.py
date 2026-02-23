#!/usr/bin/env python3
"""
Standalone CLI wrapper for managing CSV whitelist files with audit trail.

This is the ALTERNATIVE approach mentioned by the Splunk Infrastructure Team.
It can be used independently of the Splunk dashboard — from the command line,
cron jobs, or automation scripts.

Usage examples
--------------
List contents of a whitelist CSV:
    python wl_wrapper.py list --csv my_whitelist.csv --app SplunkEnterpriseSecuritySuite

Add a row:
    python wl_wrapper.py add \\
        --csv my_whitelist.csv \\
        --app SplunkEnterpriseSecuritySuite \\
        --rule My_Detection_Rule \\
        --values "host=WKSTN-042,user=alice,CommandLine=net use,Comment=Approved" \\
        --user john.doe \\
        --comment "Ticket INC-12345"

Remove rows matching criteria:
    python wl_wrapper.py remove \\
        --csv my_whitelist.csv \\
        --app SplunkEnterpriseSecuritySuite \\
        --rule My_Detection_Rule \\
        --match "host=WKSTN-001,user=bob" \\
        --user john.doe \\
        --comment "No longer needed"

Show the diff between two snapshots (dry-run a planned change):
    python wl_wrapper.py diff \\
        --csv my_whitelist.csv \\
        --app SplunkEnterpriseSecuritySuite \\
        --values "host=SRV-099,user=svc_backup,CommandLine=robocopy,Comment=test"
"""

import argparse
import csv
import difflib
import json
import os
import sys
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Configuration — adjust for your environment
# ---------------------------------------------------------------------------
SPLUNK_HOME = os.environ.get("SPLUNK_HOME", "/opt/splunk")
APPS_DIR = os.path.join(SPLUNK_HOME, "etc", "apps")
AUDIT_LOG = os.path.join(
    SPLUNK_HOME, "var", "log", "splunk", "wl_manager_audit.log"
)


# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------

def resolve_path(csv_file, app):
    """Build full path to a CSV lookup file."""
    basename = os.path.basename(csv_file)
    if basename != csv_file or csv_file.startswith("."):
        print(f"Error: invalid CSV filename (must be a plain filename): {csv_file}")
        sys.exit(1)
    if app:
        safe_app = os.path.basename(app)
        return os.path.join(APPS_DIR, safe_app, "lookups", csv_file)
    return csv_file


def read_csv(filepath):
    """Read a CSV → (headers, rows)."""
    with open(filepath, "r", newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        headers = list(reader.fieldnames or [])
        rows = [dict(r) for r in reader]
    return headers, rows


def write_csv(filepath, headers, rows):
    """Write headers + rows back to a CSV."""
    with open(filepath, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def compute_diff(old_headers, old_rows, new_headers, new_rows):
    """Return (added_rows, removed_rows, text_diff_lines)."""
    all_h = list(dict.fromkeys(old_headers + new_headers))

    def rk(row):
        return tuple(row.get(h, "") for h in all_h)

    old_set = {rk(r) for r in old_rows}
    new_set = {rk(r) for r in new_rows}

    added = [r for r in new_rows if rk(r) not in old_set]
    removed = [r for r in old_rows if rk(r) not in new_set]

    def to_lines(headers, rows):
        lines = [",".join(headers)]
        for r in rows:
            lines.append(",".join(r.get(h, "") for h in headers))
        return lines

    text_diff = list(
        difflib.unified_diff(
            to_lines(old_headers or all_h, old_rows),
            to_lines(new_headers or all_h, new_rows),
            fromfile="before",
            tofile="after",
            lineterm="",
        )
    )
    return added, removed, text_diff


def parse_kv(kv_string):
    """Parse 'key1=val1,key2=val2' into a dict. Handles values with =."""
    result = {}
    for pair in kv_string.split(","):
        key, _, value = pair.partition("=")
        result[key.strip()] = value.strip()
    return result


def write_audit(event):
    """Append a JSON audit line to the rotating log file."""
    os.makedirs(os.path.dirname(AUDIT_LOG), exist_ok=True)
    with open(AUDIT_LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, default=str) + "\n")
    print(f"  [AUDIT] Event written → {AUDIT_LOG}")


def print_diff(text_diff):
    """Pretty-print a unified diff to the terminal."""
    for line in text_diff:
        if line.startswith("+") and not line.startswith("+++"):
            print(f"\033[32m{line}\033[0m")  # green
        elif line.startswith("-") and not line.startswith("---"):
            print(f"\033[31m{line}\033[0m")  # red
        elif line.startswith("@@"):
            print(f"\033[36m{line}\033[0m")  # cyan
        else:
            print(line)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_list(args):
    """Print the contents of a whitelist CSV."""
    path = resolve_path(args.csv, args.app)
    if not os.path.isfile(path):
        print(f"Error: file not found → {path}")
        sys.exit(1)

    headers, rows = read_csv(path)
    col_widths = {h: len(h) for h in headers}
    for row in rows:
        for h in headers:
            col_widths[h] = max(col_widths[h], len(row.get(h, "")))

    # Header
    header_line = "  ".join(h.ljust(col_widths[h]) for h in headers)
    print(f"\n{header_line}")
    print("-" * len(header_line))

    # Rows
    for row in rows:
        print("  ".join(row.get(h, "").ljust(col_widths[h]) for h in headers))

    print(f"\nTotal rows: {len(rows)}")


def cmd_add(args):
    """Add a row to a whitelist CSV with audit."""
    path = resolve_path(args.csv, args.app)
    if not os.path.isfile(path):
        print(f"Error: file not found → {path}")
        sys.exit(1)

    headers, old_rows = read_csv(path)
    new_entry = parse_kv(args.values)

    # Warn about keys not in headers
    unknown = set(new_entry.keys()) - set(headers)
    if unknown:
        print(f"Warning: these fields are not in the CSV headers: {unknown}")
        confirm = input("Continue anyway? (y/n): ").strip().lower()
        if confirm != "y":
            print("Aborted.")
            return

    new_rows = old_rows + [new_entry]
    added, removed, text_diff = compute_diff(headers, old_rows, headers, new_rows)

    print("\n--- Proposed change ---")
    print_diff(text_diff)
    print(f"\nRows to add: {len(added)}")

    confirm = input("\nApply this change? (y/n): ").strip().lower()
    if confirm != "y":
        print("Aborted.")
        return

    write_csv(path, headers, new_rows)

    write_audit({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "analyst": args.user or os.environ.get("USER", "unknown"),
        "detection_rule": args.rule or "",
        "csv_file": args.csv,
        "app_context": args.app or "",
        "action": "add",
        "comment": args.comment or "",
        "rows_before": len(old_rows),
        "rows_after": len(new_rows),
        "rows_added": len(added),
        "rows_removed": len(removed),
        "added_entries": added,
        "removed_entries": removed,
        "text_diff": text_diff,
    })

    print(f"Done — {len(added)} row(s) added.  Total rows now: {len(new_rows)}.")


def cmd_remove(args):
    """Remove rows matching criteria from a whitelist CSV with audit."""
    path = resolve_path(args.csv, args.app)
    if not os.path.isfile(path):
        print(f"Error: file not found → {path}")
        sys.exit(1)

    headers, old_rows = read_csv(path)
    match_criteria = parse_kv(args.match)

    new_rows = [
        r for r in old_rows
        if not all(r.get(k, "") == v for k, v in match_criteria.items())
    ]

    if len(new_rows) == len(old_rows):
        print("No matching rows found. Nothing to remove.")
        return

    added, removed, text_diff = compute_diff(headers, old_rows, headers, new_rows)

    print(f"\n--- Proposed removal ({len(removed)} row(s)) ---")
    print_diff(text_diff)

    confirm = input("\nApply this change? (y/n): ").strip().lower()
    if confirm != "y":
        print("Aborted.")
        return

    write_csv(path, headers, new_rows)

    write_audit({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "analyst": args.user or os.environ.get("USER", "unknown"),
        "detection_rule": args.rule or "",
        "csv_file": args.csv,
        "app_context": args.app or "",
        "action": "remove",
        "comment": args.comment or "",
        "rows_before": len(old_rows),
        "rows_after": len(new_rows),
        "rows_added": len(added),
        "rows_removed": len(removed),
        "added_entries": added,
        "removed_entries": removed,
        "text_diff": text_diff,
    })

    print(f"Done — {len(removed)} row(s) removed.  Total rows now: {len(new_rows)}.")


def cmd_diff(args):
    """
    Dry-run: show what would change if a row were added, without writing.
    Useful for previewing changes before committing them.
    """
    path = resolve_path(args.csv, args.app)
    if not os.path.isfile(path):
        print(f"Error: file not found → {path}")
        sys.exit(1)

    headers, old_rows = read_csv(path)
    new_entry = parse_kv(args.values)
    new_rows = old_rows + [new_entry]

    _, _, text_diff = compute_diff(headers, old_rows, headers, new_rows)

    print("\n--- Dry-run diff (no changes will be written) ---")
    print_diff(text_diff)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Whitelist CSV Manager — CLI Wrapper with Audit Trail"
    )
    sub = parser.add_subparsers(dest="command")

    # ── list ──────────────────────────────────────────────────────────
    p_list = sub.add_parser("list", help="Display contents of a whitelist CSV")
    p_list.add_argument("--csv", required=True, help="CSV filename")
    p_list.add_argument("--app", default="", help="Splunk app containing the CSV")

    # ── add ───────────────────────────────────────────────────────────
    p_add = sub.add_parser("add", help="Add a row to a whitelist CSV")
    p_add.add_argument("--csv", required=True, help="CSV filename")
    p_add.add_argument("--app", default="", help="Splunk app containing the CSV")
    p_add.add_argument("--rule", default="", help="Detection rule name")
    p_add.add_argument(
        "--values", required=True,
        help='Comma-separated key=value pairs, e.g. "host=SRV1,user=bob"',
    )
    p_add.add_argument("--user", default="", help="Analyst username for audit")
    p_add.add_argument("--comment", default="", help="Change description for audit")

    # ── remove ────────────────────────────────────────────────────────
    p_rm = sub.add_parser("remove", help="Remove rows matching criteria")
    p_rm.add_argument("--csv", required=True, help="CSV filename")
    p_rm.add_argument("--app", default="", help="Splunk app containing the CSV")
    p_rm.add_argument("--rule", default="", help="Detection rule name")
    p_rm.add_argument(
        "--match", required=True,
        help='Comma-separated key=value criteria, e.g. "host=SRV1,user=bob"',
    )
    p_rm.add_argument("--user", default="", help="Analyst username for audit")
    p_rm.add_argument("--comment", default="", help="Change description for audit")

    # ── diff ──────────────────────────────────────────────────────────
    p_diff = sub.add_parser("diff", help="Dry-run: preview what an add would change")
    p_diff.add_argument("--csv", required=True, help="CSV filename")
    p_diff.add_argument("--app", default="", help="Splunk app containing the CSV")
    p_diff.add_argument(
        "--values", required=True,
        help='Comma-separated key=value pairs to add (preview only)',
    )

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    cmds = {"list": cmd_list, "add": cmd_add, "remove": cmd_remove, "diff": cmd_diff}
    cmds[args.command](args)


if __name__ == "__main__":
    main()
