"""Generate Splunk Admin Installation Guide PDF."""

import os
from fpdf import FPDF


class AdminPDF(FPDF):
    def header(self):
        self.set_font("Helvetica", "B", 9)
        self.set_text_color(120, 120, 120)
        self.cell(0, 8, "Whitelist Manager - Splunk Admin Installation Guide", align="R")
        self.ln(10)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 10, f"Page {self.page_no()}/{{nb}}", align="C")

    def phase_title(self, title):
        self.set_font("Helvetica", "B", 18)
        self.set_text_color(30, 30, 30)
        self.ln(4)
        self.cell(0, 12, title)
        self.ln(14)

    def step_title(self, title):
        self.set_font("Helvetica", "B", 13)
        self.set_text_color(50, 50, 50)
        self.ln(2)
        self.cell(0, 8, title)
        self.ln(10)

    def sub_step(self, title):
        self.set_font("Helvetica", "B", 11)
        self.set_text_color(60, 60, 60)
        self.ln(1)
        self.cell(0, 7, title)
        self.ln(9)

    def text(self, t):
        self.set_font("Helvetica", "", 10)
        self.set_text_color(40, 40, 40)
        self.multi_cell(0, 5.5, t)
        self.ln(2)

    def cmd(self, t):
        self.set_font("Courier", "", 9)
        self.set_fill_color(240, 240, 240)
        self.set_text_color(50, 50, 50)
        x = self.get_x()
        self.set_x(x + 4)
        self.multi_cell(0, 5, t, fill=True)
        self.ln(3)

    def row(self, cols, widths, bold=False, fill=False):
        style = "B" if bold else ""
        self.set_font("Helvetica", style, 9)
        if fill:
            self.set_fill_color(230, 240, 250)
        self.set_text_color(40, 40, 40)
        h = 6
        for i, col in enumerate(cols):
            self.cell(widths[i], h, col, border=1, fill=fill)
        self.ln(h)

    def bullet(self, t, indent=10):
        self.set_font("Helvetica", "", 10)
        self.set_text_color(40, 40, 40)
        x = self.get_x()
        self.set_x(x + indent)
        self.cell(4, 5.5, "-")
        self.multi_cell(0, 5.5, t)
        self.ln(1)

    def warning_box(self, t):
        self.set_font("Helvetica", "B", 10)
        self.set_fill_color(255, 248, 230)
        self.set_draw_color(200, 170, 80)
        self.set_text_color(120, 80, 0)
        self.cell(0, 7, "  NOTE: " + t, border=1, fill=True)
        self.ln(9)


def build_pdf(output_path):
    pdf = AdminPDF()
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=20)

    # ── Title Page ──
    pdf.add_page()
    pdf.ln(40)
    pdf.set_font("Helvetica", "B", 26)
    pdf.set_text_color(30, 30, 30)
    pdf.cell(0, 14, "Whitelist Manager", align="C")
    pdf.ln(12)
    pdf.set_font("Helvetica", "", 16)
    pdf.set_text_color(80, 80, 80)
    pdf.cell(0, 10, "Splunk Admin Installation Guide", align="C")
    pdf.ln(25)
    pdf.set_font("Helvetica", "", 12)
    pdf.cell(0, 8, "Before / During / After Installation", align="C")
    pdf.ln(30)
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(0, 7, "Version 1.0.0  |  February 2026", align="C")
    pdf.ln(7)
    pdf.cell(0, 7, "Prepared for: Splunk Infrastructure Team", align="C")

    # ══════════════════════════════════════════════════════════════════════
    # BEFORE
    # ══════════════════════════════════════════════════════════════════════
    pdf.add_page()
    pdf.phase_title("BEFORE Installation (Pre-flight Checklist)")

    # 1
    pdf.step_title("1. Verify Splunk Version")
    pdf.text("The app requires Splunk Enterprise 8.x or 9.x with Python 3 support. It has been tested on Splunk 9.3.1.")
    pdf.cmd("$SPLUNK_HOME/bin/splunk version")
    pdf.text("Confirm the output shows 8.0+ or 9.x.")

    # 2
    pdf.step_title("2. Verify Python 3 Is Enabled")
    pdf.text("The app uses python.version = python3. Check the current setting:")
    pdf.cmd("$SPLUNK_HOME/bin/splunk btool server list --debug | grep python.version")
    pdf.text(
        "If the system-level setting forces Python 2, Python 3 must be enabled. "
        "In most Splunk 8.x+ installations, Python 3 is the default."
    )

    # 3
    pdf.step_title("3. Check for Naming Conflicts")
    pdf.text("The app creates the following objects. Verify none already exist:")
    w = [55, 40, 95]
    pdf.row(["Object", "Type", "Check Command"], w, bold=True, fill=True)
    pdf.row(["wl_manager", "App", "splunk display app"], w)
    pdf.row(["wl_audit", "Index", "splunk list index"], w)
    pdf.row(["wl_editor", "Role", "splunk list role"], w)
    pdf.row(["wl_viewer", "Role", "splunk list role"], w)
    pdf.row(["/custom/wl_manager", "REST endpoint", "(unique per app)"], w)
    pdf.ln(2)
    pdf.text("If any of these already exist, coordinate with the Security Engineering team before proceeding.")

    # 4
    pdf.step_title("4. Review Disk Space for wl_audit Index")
    pdf.text("The app creates a wl_audit index with these defaults:")
    w2 = [60, 40, 90]
    pdf.row(["Setting", "Value", "Meaning"], w2, bold=True, fill=True)
    pdf.row(["maxTotalDataSizeMB", "1024", "Maximum 1 GB of indexed data"], w2)
    pdf.row(["frozenTimePeriodInSecs", "94608000", "Data retained for 3 years"], w2)
    pdf.ln(2)
    pdf.text("Verify at least 2 GB of free disk space at $SPLUNK_DB (1 GB for data + overhead).")
    pdf.text(
        "If your organization requires custom index paths or different retention, "
        "you can create a local/indexes.conf override after installation."
    )

    # 5
    pdf.step_title("5. Review Network Requirements")
    pdf.text("The app makes an internal HTTPS call from the REST handler to Splunk's own management port:")
    pdf.cmd("https://127.0.0.1:8089/services/receivers/simple")
    pdf.text(
        "This is a localhost-only call (Python handler to same Splunk instance) used to index "
        "audit events. No firewall changes are needed. However, if your Splunk uses a custom "
        "management port or custom SSL certificates, see the 'Special Considerations' section."
    )

    # 6
    pdf.step_title("6. Prepare RBAC Role Assignments")
    pdf.text("The app creates two new roles:")
    w3 = [35, 40, 115]
    pdf.row(["Role", "Inherits", "Capabilities"], w3, bold=True, fill=True)
    pdf.row(["wl_editor", "user", "Read + write whitelists, access wl_audit index"], w3)
    pdf.row(["wl_viewer", "user", "Read-only access to whitelists and wl_audit"], w3)
    pdf.ln(2)
    pdf.text("Prepare a list of users who need each role. You will assign these after installation.")

    # 7
    pdf.step_title("7. Identify app_context Folder Names")
    pdf.text(
        "The master mapping CSV references CSV files in other Splunk apps. The app_context value "
        "must exactly match the app's folder name on disk."
    )
    pdf.cmd("ls $SPLUNK_HOME/etc/apps/ | grep -i -E \"security|SA-|DA-\"")
    pdf.text("Share these folder names with the Security Engineering team.")

    # 8
    pdf.step_title("8. Backup (Recommended)")
    pdf.cmd(
        "# Backup apps\n"
        "tar -czf /tmp/splunk_apps_backup_$(date +%Y%m%d).tar.gz \\\n"
        "    $SPLUNK_HOME/etc/apps/\n\n"
        "# Backup roles and users\n"
        "$SPLUNK_HOME/bin/splunk list role > /tmp/roles_backup.txt\n"
        "$SPLUNK_HOME/bin/splunk list user > /tmp/users_backup.txt"
    )

    # ══════════════════════════════════════════════════════════════════════
    # DURING
    # ══════════════════════════════════════════════════════════════════════
    pdf.add_page()
    pdf.phase_title("DURING Installation")

    pdf.step_title("Step 1: Install the .spl Package")

    pdf.sub_step("Option A - Splunk Web (recommended)")
    pdf.bullet("Log in to Splunk Web as admin")
    pdf.bullet("Navigate to Apps > Manage Apps")
    pdf.bullet("Click 'Install app from file'")
    pdf.bullet("Browse to wl_manager-1.0.0.spl and click Upload")
    pdf.bullet("Check 'Restart Splunk' when prompted")

    pdf.sub_step("Option B - Splunk CLI")
    pdf.cmd(
        "$SPLUNK_HOME/bin/splunk install app /path/to/wl_manager-1.0.0.spl \\\n"
        "    -auth admin:password\n"
        "$SPLUNK_HOME/bin/splunk restart"
    )

    pdf.sub_step("Option C - Manual (clustered / restricted environments)")
    pdf.cmd(
        "cd $SPLUNK_HOME/etc/apps/\n"
        "tar -xzf /path/to/wl_manager-1.0.0.spl\n"
        "chown -R splunk:splunk wl_manager/\n"
        "$SPLUNK_HOME/bin/splunk restart"
    )

    pdf.step_title("Step 2: Verify No Errors During Startup")
    pdf.text("After Splunk restarts, check logs for errors:")
    pdf.cmd(
        "grep -i \"wl_manager\\|WhitelistHandler\" \\\n"
        "    $SPLUNK_HOME/var/log/splunk/splunkd.log | tail -20\n\n"
        "grep -i \"wl_handler\\|wl_manager\" \\\n"
        "    $SPLUNK_HOME/var/log/splunk/python_stderr.log | tail -20"
    )
    pdf.text("Expected: No errors. If you see ImportError, check Python 3 configuration.")

    pdf.step_title("Step 3: Verify the REST Endpoint")
    pdf.cmd(
        "curl -sk -u admin:password \\\n"
        "  'https://localhost:8089/services/custom/wl_manager?action=get_mapping'"
    )
    pdf.text("Expected: JSON response with mapping data. If 404, restart Splunk one more time.")

    # ══════════════════════════════════════════════════════════════════════
    # AFTER
    # ══════════════════════════════════════════════════════════════════════
    pdf.add_page()
    pdf.phase_title("AFTER Installation (Post-installation Setup)")

    pdf.step_title("1. Verify the wl_audit Index Exists")
    pdf.cmd("$SPLUNK_HOME/bin/splunk list index wl_audit")
    pdf.text("Or in Splunk Web: Settings > Indexes > find wl_audit.")
    pdf.text("If the index does not appear, create it manually:")
    pdf.cmd(
        "$SPLUNK_HOME/bin/splunk add index wl_audit \\\n"
        "    -maxTotalDataSizeMB 1024 \\\n"
        "    -frozenTimePeriodInSecs 94608000"
    )

    pdf.step_title("2. Verify the App Is Visible")
    pdf.bullet("Open Splunk Web")
    pdf.bullet("Click the Apps dropdown in the top navigation")
    pdf.bullet("'Whitelist Manager' should appear in the list")
    pdf.bullet("Click it - the main dashboard should load with two dropdowns")

    pdf.step_title("3. Assign Roles to Users")
    pdf.text("For analysts who need to EDIT whitelists:")
    pdf.cmd("$SPLUNK_HOME/bin/splunk edit user <username> -role wl_editor -auth admin:password")
    pdf.text("For read-only users:")
    pdf.cmd("$SPLUNK_HOME/bin/splunk edit user <username> -role wl_viewer -auth admin:password")
    pdf.text("Or via Splunk Web: Settings > Access Controls > Users > [user] > Edit > Roles")

    pdf.step_title("4. Populate the Master Mapping CSV")
    pdf.warning_box("This is the most critical post-installation step.")
    pdf.ln(2)
    pdf.text(
        "The Security Engineering team will provide the mapping data. The admin may need to "
        "assist with verifying that app_context values match actual folder names."
    )
    pdf.text("Edit via Splunk Web: Settings > Lookups > Lookup table files > rule_csv_map")
    pdf.text("Or directly on the file system:")
    pdf.cmd("vi $SPLUNK_HOME/etc/apps/wl_manager/lookups/rule_csv_map.csv")
    pdf.text("Format (one row per rule-to-CSV relationship):")
    pdf.cmd(
        "rule_name,csv_file,app_context\n"
        "DR20_malicious_command,DR20_whitelist.csv,SplunkEnterpriseSecuritySuite\n"
        "DR45_suspicious_login,DR45_whitelist_users.csv,SplunkEnterpriseSecuritySuite\n"
        "DR45_suspicious_login,DR45_whitelist_hosts.csv,SplunkEnterpriseSecuritySuite"
    )

    pdf.step_title("5. Verify CSV File Permissions")
    pdf.text(
        "The Splunk process (running as the 'splunk' user) needs read and write access "
        "to every CSV file referenced in the mapping."
    )
    pdf.cmd(
        "# Check permissions on referenced CSV files\n"
        "ls -la $SPLUNK_HOME/etc/apps/<app_context>/lookups/<csv_file>"
    )
    pdf.text("Fix permissions if needed:")
    pdf.cmd(
        "chown splunk:splunk $SPLUNK_HOME/etc/apps/<app>/lookups/<file>.csv\n"
        "chmod 644 $SPLUNK_HOME/etc/apps/<app>/lookups/<file>.csv"
    )

    pdf.step_title("6. Test End-to-End")
    pdf.bullet("Log in as a user with the wl_editor role")
    pdf.bullet("Open Apps > Whitelist Manager")
    pdf.bullet("Select a detection rule, then a CSV file")
    pdf.bullet("The table should load with CSV contents")
    pdf.bullet("Modify a cell, enter a comment, click Save")
    pdf.bullet("Go to the Audit Trail tab - the change should appear")
    pdf.text("Verify in SPL:")
    pdf.cmd(
        "index=wl_audit sourcetype=wl_audit | head 5\n"
        "| spath\n"
        "| table timestamp analyst detection_rule csv_file comment\n"
        "        rows_added rows_removed"
    )

    pdf.step_title("7. Test RBAC Enforcement")
    pdf.bullet("Log in as a user WITHOUT the wl_editor role")
    pdf.bullet("Open the Whitelist Manager dashboard")
    pdf.bullet("Try to save a change - should show 'Permission denied'")

    # ══════════════════════════════════════════════════════════════════════
    # Special Considerations
    # ══════════════════════════════════════════════════════════════════════
    pdf.add_page()
    pdf.phase_title("Special Considerations")

    pdf.step_title("Search Head Cluster (SHC) Deployment")
    pdf.bullet("Place the app in: $SPLUNK_HOME/etc/shcluster/apps/wl_manager/")
    pdf.bullet("Push the bundle: splunk apply shcluster-bundle -target <captain_uri>")
    pdf.bullet("The wl_audit index must also be configured on the indexers")

    pdf.step_title("Indexer Cluster Deployment")
    pdf.text("The wl_audit index must be created on indexers via the cluster master:")
    pdf.cmd(
        "mkdir -p $SPLUNK_HOME/etc/master-apps/wl_manager/default/\n"
        "cp indexes.conf $SPLUNK_HOME/etc/master-apps/wl_manager/default/\n"
        "$SPLUNK_HOME/bin/splunk apply cluster-bundle"
    )

    pdf.step_title("Custom Management Port or SSL")
    pdf.text(
        "If your Splunk uses a non-default management port (not 8089), coordinate with the "
        "Security Engineering team to update the handler's _index_audit() method."
    )

    pdf.step_title("Monitoring (Optional)")
    pdf.text("Consider a saved search to alert on large whitelist changes:")
    pdf.cmd(
        "index=wl_audit sourcetype=wl_audit\n"
        "| spath\n"
        "| where rows_added > 10 OR rows_removed > 10\n"
        "| table timestamp analyst detection_rule csv_file\n"
        "        rows_added rows_removed comment"
    )

    # ══════════════════════════════════════════════════════════════════════
    # Quick Reference
    # ══════════════════════════════════════════════════════════════════════
    pdf.add_page()
    pdf.phase_title("Quick Reference Card")

    w4 = [55, 135]
    pdf.row(["Item", "Value"], w4, bold=True, fill=True)
    pdf.row(["App folder", "$SPLUNK_HOME/etc/apps/wl_manager/"], w4)
    pdf.row(["REST endpoint", "https://<splunk>:8089/services/custom/wl_manager"], w4)
    pdf.row(["Web dashboard", "https://<splunk>:8000/app/wl_manager/whitelist_manager"], w4)
    pdf.row(["Audit index", "wl_audit"], w4)
    pdf.row(["Audit log file", "$SPLUNK_HOME/var/log/splunk/wl_manager_audit.log"], w4)
    pdf.row(["Mapping CSV", "$SPLUNK_HOME/etc/apps/wl_manager/lookups/rule_csv_map.csv"], w4)
    pdf.row(["Edit role", "wl_editor"], w4)
    pdf.row(["View role", "wl_viewer"], w4)
    pdf.row(["Python version", "Python 3"], w4)
    pdf.row(["Splunk version", "8.x+ / 9.x (tested on 9.3.1)"], w4)

    pdf.ln(10)
    pdf.phase_title("Uninstallation")
    pdf.text("To remove the app (preserves audit data):")
    pdf.cmd(
        "$SPLUNK_HOME/bin/splunk remove app wl_manager -auth admin:password\n"
        "$SPLUNK_HOME/bin/splunk restart"
    )
    pdf.text("To also remove the audit index and its data:")
    pdf.cmd("$SPLUNK_HOME/bin/splunk remove index wl_audit")
    pdf.text(
        "The custom roles (wl_editor, wl_viewer) are removed with the app. "
        "Users who had these roles will lose them automatically."
    )

    pdf.output(output_path)
    return output_path


if __name__ == "__main__":
    out = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "docs",
        "Splunk_Admin_Installation_Guide.pdf",
    )
    build_pdf(out)
    print(f"PDF saved to: {out}")
