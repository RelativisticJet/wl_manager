#!/usr/bin/env python3
"""Generate Demo_Guide.pdf for the Whitelist Manager quick demo."""

import os
from fpdf import FPDF


class DemoGuide(FPDF):
    BLUE = (41, 98, 255)
    DARK = (33, 37, 41)
    GRAY = (108, 117, 125)
    WHITE = (255, 255, 255)
    LIGHT_BG = (248, 249, 250)
    GREEN = (25, 135, 84)

    def header(self):
        if self.page_no() > 1:
            self.set_font("Helvetica", "I", 8)
            self.set_text_color(*self.GRAY)
            self.cell(0, 10, "Whitelist Manager - Demo Guide", align="L")
            self.cell(0, 10, f"Page {self.page_no()}", align="R")
            self.ln(12)

    def title_page(self):
        self.add_page()
        self.ln(50)
        self.set_font("Helvetica", "B", 32)
        self.set_text_color(*self.BLUE)
        self.cell(0, 15, "Whitelist Manager", align="C", new_x="LMARGIN", new_y="NEXT")
        self.set_font("Helvetica", "", 20)
        self.set_text_color(*self.DARK)
        self.cell(0, 12, "Quick Demo Guide", align="C", new_x="LMARGIN", new_y="NEXT")
        self.ln(10)
        self.set_draw_color(*self.BLUE)
        self.set_line_width(0.8)
        x = self.w / 2 - 30
        self.line(x, self.get_y(), x + 60, self.get_y())
        self.ln(15)
        self.set_font("Helvetica", "", 12)
        self.set_text_color(*self.GRAY)
        self.cell(0, 8, "Evaluate the app in Docker before production deployment", align="C", new_x="LMARGIN", new_y="NEXT")
        self.cell(0, 8, "One command to go from zero to a working demo", align="C", new_x="LMARGIN", new_y="NEXT")
        self.ln(40)
        self.set_font("Helvetica", "", 10)
        self.cell(0, 8, "Security Engineering Team", align="C", new_x="LMARGIN", new_y="NEXT")
        self.cell(0, 8, "Version 1.0.0", align="C", new_x="LMARGIN", new_y="NEXT")

    def section(self, number, title):
        self.ln(6)
        self.set_font("Helvetica", "B", 16)
        self.set_text_color(*self.BLUE)
        self.cell(0, 10, f"{number}. {title}", new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(*self.BLUE)
        self.set_line_width(0.4)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(4)

    def sub_section(self, title):
        self.ln(3)
        self.set_font("Helvetica", "B", 12)
        self.set_text_color(*self.DARK)
        self.cell(0, 8, title, new_x="LMARGIN", new_y="NEXT")
        self.ln(1)

    def body(self, text):
        self.set_font("Helvetica", "", 10)
        self.set_text_color(*self.DARK)
        self.multi_cell(0, 6, text)
        self.ln(2)

    def code_block(self, text):
        self.set_fill_color(*self.LIGHT_BG)
        self.set_font("Courier", "", 9)
        self.set_text_color(*self.DARK)
        x = self.l_margin
        w = self.w - self.l_margin - self.r_margin
        lines = text.strip().split("\n")
        h = len(lines) * 5.5 + 6
        self.rect(x, self.get_y(), w, h, style="F")
        self.set_x(x + 4)
        self.ln(3)
        for line in lines:
            self.set_x(x + 4)
            self.cell(0, 5.5, line, new_x="LMARGIN", new_y="NEXT")
        self.ln(4)

    def bullet(self, text, indent=10):
        self.set_font("Helvetica", "", 10)
        self.set_text_color(*self.DARK)
        self.set_x(self.l_margin + indent)
        self.cell(4, 6, "-")
        self.multi_cell(self.w - self.l_margin - self.r_margin - indent - 4, 6, text)
        self.ln(1)

    def numbered(self, num, text):
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(*self.BLUE)
        self.set_x(self.l_margin + 5)
        self.cell(8, 6, f"{num}.")
        self.set_font("Helvetica", "", 10)
        self.set_text_color(*self.DARK)
        self.multi_cell(self.w - self.l_margin - self.r_margin - 13, 6, text)
        self.ln(1)

    def info_box(self, text):
        self.set_fill_color(209, 231, 255)
        self.set_draw_color(*self.BLUE)
        x = self.l_margin
        w = self.w - self.l_margin - self.r_margin
        self.set_font("Helvetica", "", 9)
        self.set_text_color(*self.DARK)
        # Calculate height
        lines = len(text) // 80 + text.count("\n") + 2
        h = lines * 5.5 + 8
        self.rect(x, self.get_y(), w, h, style="DF")
        self.set_xy(x + 4, self.get_y() + 3)
        self.multi_cell(w - 8, 5.5, text)
        self.ln(4)

    def table_row(self, cells, header=False):
        self.set_font("Helvetica", "B" if header else "", 9)
        if header:
            self.set_fill_color(*self.BLUE)
            self.set_text_color(*self.WHITE)
        else:
            self.set_fill_color(*self.WHITE)
            self.set_text_color(*self.DARK)
        col_w = (self.w - self.l_margin - self.r_margin) / len(cells)
        for cell in cells:
            self.cell(col_w, 7, str(cell), border=1, fill=True, align="C")
        self.ln()


def build():
    pdf = DemoGuide()
    pdf.set_auto_page_break(auto=True, margin=20)

    # ── Title Page ───────────────────────────────────────────────
    pdf.title_page()

    # ── Prerequisites ────────────────────────────────────────────
    pdf.add_page()
    pdf.section("1", "Prerequisites")
    pdf.body("Before running the demo, ensure the following are installed and running:")
    pdf.bullet("Docker Desktop (Windows, macOS, or Linux)")
    pdf.bullet("Bash shell (Git Bash on Windows, or native terminal on Linux/macOS)")
    pdf.bullet("Approximately 1 GB of free disk space for the Splunk Docker image")
    pdf.bullet("Internet connection (to pull the Splunk image on first run)")
    pdf.ln(2)
    pdf.info_box(
        "Note: The demo uses ports 9000 (Web UI) and 9089 (API). "
        "Make sure these ports are not in use by other applications. "
        "The demo container is completely separate from any development environment."
    )

    # ── Starting the Demo ────────────────────────────────────────
    pdf.section("2", "Starting the Demo")
    pdf.body("From the root of the wl_manager repository, run:")
    pdf.code_block("bash demo/demo.sh")
    pdf.body("The script will automatically:")
    pdf.numbered(1, "Verify Docker is running")
    pdf.numbered(2, "Build the .spl package (if not already built)")
    pdf.numbered(3, "Start a Splunk 9.3.1 container")
    pdf.numbered(4, "Install the Whitelist Manager app from the .spl")
    pdf.numbered(5, "Seed three demo detection rules with sample whitelist data")
    pdf.numbered(6, "Print the login URL and credentials")
    pdf.ln(2)
    pdf.body("The entire process takes approximately 2-3 minutes (longer on first run while Docker pulls the Splunk image).")
    pdf.ln(2)
    pdf.sub_section("Login Credentials")
    pdf.table_row(["Setting", "Value"], header=True)
    pdf.table_row(["URL", "http://localhost:9000"])
    pdf.table_row(["Username", "admin"])
    pdf.table_row(["Password", "Chang3d!"])

    # ── What to Try ──────────────────────────────────────────────
    pdf.add_page()
    pdf.section("3", "What to Try")

    pdf.sub_section("3.1 Browse Whitelists")
    pdf.numbered(1, "Log in to Splunk Web at http://localhost:9000")
    pdf.numbered(2, 'Navigate to Apps > Whitelist Manager')
    pdf.numbered(3, 'Click the "Detection Rule" dropdown and select Brute_Force_Login')
    pdf.numbered(4, 'The CSV File dropdown auto-populates. Select brute_force_whitelist.csv')
    pdf.numbered(5, "The table loads with 4-5 sample rows including expiration dates")
    pdf.ln(2)
    pdf.info_box(
        "Tip: Notice the yellow banner at the top indicating that one expired row "
        "was automatically removed on load. This demonstrates the auto-expiration feature."
    )

    pdf.sub_section("3.2 Edit a Cell")
    pdf.numbered(1, "Click on any cell in the table (e.g., a Comment field)")
    pdf.numbered(2, "Type a new value")
    pdf.numbered(3, 'Click "Save Changes"')
    pdf.numbered(4, "Enter a comment explaining the change (e.g., \"Demo edit\")")
    pdf.numbered(5, "Review the Git-style diff summary that appears below the table")

    pdf.sub_section("3.3 Add a Row")
    pdf.numbered(1, 'Click "+ Add Row"')
    pdf.numbered(2, "Fill in the fields in the new empty row")
    pdf.numbered(3, 'Click "Save Changes" and provide a comment')

    pdf.sub_section("3.4 Remove a Row")
    pdf.numbered(1, 'Click "Remove" on any row\'s Actions column')
    pdf.numbered(2, "Enter a reason when prompted (required for audit)")
    pdf.numbered(3, "Notice the 10-second Undo bar that appears")

    pdf.sub_section("3.5 Try the Date Picker")
    pdf.numbered(1, "Select the Brute_Force_Login or Impossible_Travel rule")
    pdf.numbered(2, "Click on any cell in the Expires column")
    pdf.numbered(3, "A date/time picker appears with preset buttons (7 Days, 30 Days, etc.)")
    pdf.numbered(4, 'Click "30 Days" to set an expiration 30 days from now')
    pdf.numbered(5, 'Or pick a manual date/time and click "Apply"')

    # ── Audit Trail ──────────────────────────────────────────────
    pdf.add_page()
    pdf.section("4", "Viewing the Audit Trail")
    pdf.numbered(1, 'Click the "Audit Trail" tab in the app navigation bar')
    pdf.numbered(2, "The dashboard shows all changes made during your demo session")
    pdf.numbered(3, "Use the filters at the top to narrow by analyst, rule, or action type")
    pdf.numbered(4, "The Summary Statistics show total changes, adds, removes, and edits")
    pdf.numbered(5, 'Check the "Expiring Soon" panel to see rows approaching their expiration date')
    pdf.ln(2)
    pdf.body("You can also search audit events directly in Splunk's Search & Reporting app:")
    pdf.code_block(
        'index=wl_audit sourcetype=wl_audit\n'
        '| table timestamp analyst action detection_rule csv_file comment'
    )

    # ── Demo Data ────────────────────────────────────────────────
    pdf.section("5", "Demo Data Reference")
    pdf.body("The demo seeds three detection rules with sample whitelists:")
    pdf.ln(2)

    pdf.sub_section("Brute_Force_Login")
    pdf.body("CSV: brute_force_whitelist.csv")
    pdf.body("Columns: user, src_ip, threshold, Comment, Expires")
    pdf.body("Features demonstrated: expiration dates, auto-removal of expired rows, date picker")

    pdf.sub_section("Suspicious_Process")
    pdf.body("CSV: suspicious_process_whitelist.csv")
    pdf.body("Columns: host, process_name, user, Comment")
    pdf.body("Features demonstrated: simple whitelist without expiration, add/edit/remove rows")

    pdf.sub_section("Impossible_Travel")
    pdf.body("CSV: impossible_travel_whitelist.csv")
    pdf.body("Columns: user, src_country, Comment, Expires")
    pdf.body("Features demonstrated: expiration dates, date picker presets")

    # ── Stopping the Demo ────────────────────────────────────────
    pdf.add_page()
    pdf.section("6", "Stopping the Demo")

    pdf.sub_section("Stop and Remove Container")
    pdf.body("This stops the container and removes it, but keeps the data volume for next time:")
    pdf.code_block("bash demo/demo.sh --stop")

    pdf.sub_section("Full Cleanup")
    pdf.body("This removes both the container and the data volume (complete reset):")
    pdf.code_block("bash demo/demo.sh --clean")

    pdf.sub_section("Restart the Demo")
    pdf.body("After stopping, run the demo again to get a fresh environment:")
    pdf.code_block("bash demo/demo.sh")
    pdf.body(
        "If you used --stop (not --clean), the demo restarts faster because the "
        "Splunk image is already cached and the volume retains configuration."
    )

    # ── Troubleshooting ──────────────────────────────────────────
    pdf.section("7", "Troubleshooting")

    pdf.sub_section("Docker is not running")
    pdf.body('If you see "[ERROR] Docker is not running", start Docker Desktop and wait for it to fully initialize before running the script again.')

    pdf.sub_section("Port already in use")
    pdf.body("If port 9000 or 9089 is already in use, stop the conflicting service or edit the WEB_PORT / API_PORT variables at the top of demo.sh.")

    pdf.sub_section("Splunk did not start in time")
    pdf.body("On slower machines or first run (while pulling the image), Splunk may take longer to start. Run the script again -it will detect the existing container and retry. You can also check logs with:")
    pdf.code_block("docker logs wl_manager_demo")

    pdf.sub_section("No detection rules in dropdown")
    pdf.body("If the dropdown is empty after login, Splunk may still be loading. Wait 30 seconds and refresh the page. If it persists, restart the demo container:")
    pdf.code_block("docker restart wl_manager_demo")

    # ── Output ───────────────────────────────────────────────────
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Demo_Guide.pdf")
    pdf.output(out)
    print(f"Generated: {out}")


if __name__ == "__main__":
    build()
