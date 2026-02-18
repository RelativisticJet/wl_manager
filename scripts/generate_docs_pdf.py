"""Generate project documentation PDF for the Whitelist Manager app."""

import os
from fpdf import FPDF


class DocsPDF(FPDF):
    """Custom PDF with headers and footers."""

    def header(self):
        self.set_font("Helvetica", "B", 9)
        self.set_text_color(120, 120, 120)
        self.cell(0, 8, "Whitelist Manager for Splunk ES - Project Documentation", align="R")
        self.ln(10)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 10, f"Page {self.page_no()}/{{nb}}", align="C")

    def section_title(self, title):
        self.set_font("Helvetica", "B", 16)
        self.set_text_color(30, 30, 30)
        self.ln(4)
        self.cell(0, 10, title)
        self.ln(12)

    def sub_title(self, title):
        self.set_font("Helvetica", "B", 13)
        self.set_text_color(50, 50, 50)
        self.ln(2)
        self.cell(0, 8, title)
        self.ln(10)

    def sub_sub_title(self, title):
        self.set_font("Helvetica", "B", 11)
        self.set_text_color(60, 60, 60)
        self.ln(1)
        self.cell(0, 7, title)
        self.ln(9)

    def body_text(self, text):
        self.set_font("Helvetica", "", 10)
        self.set_text_color(40, 40, 40)
        self.multi_cell(0, 5.5, text)
        self.ln(2)

    def code_block(self, text):
        self.set_font("Courier", "", 9)
        self.set_fill_color(240, 240, 240)
        self.set_text_color(50, 50, 50)
        x = self.get_x()
        self.set_x(x + 4)
        self.multi_cell(0, 5, text, fill=True)
        self.ln(3)

    def table_row(self, cols, widths, bold=False, fill=False):
        style = "B" if bold else ""
        self.set_font("Helvetica", style, 9)
        if fill:
            self.set_fill_color(230, 240, 250)
        self.set_text_color(40, 40, 40)
        h = 6
        for i, col in enumerate(cols):
            self.cell(widths[i], h, col, border=1, fill=fill)
        self.ln(h)

    def bullet(self, text, indent=10):
        self.set_font("Helvetica", "", 10)
        self.set_text_color(40, 40, 40)
        x = self.get_x()
        self.set_x(x + indent)
        self.cell(4, 5.5, "-")
        self.multi_cell(0, 5.5, text)
        self.ln(1)


def build_pdf(output_path):
    pdf = DocsPDF()
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=20)

    # ── Title Page ──
    pdf.add_page()
    pdf.ln(50)
    pdf.set_font("Helvetica", "B", 28)
    pdf.set_text_color(30, 30, 30)
    pdf.cell(0, 15, "Whitelist Manager", align="C")
    pdf.ln(14)
    pdf.set_font("Helvetica", "", 16)
    pdf.set_text_color(80, 80, 80)
    pdf.cell(0, 10, "for Splunk Enterprise Security", align="C")
    pdf.ln(20)
    pdf.set_font("Helvetica", "", 13)
    pdf.cell(0, 8, "Project Documentation", align="C")
    pdf.ln(8)
    pdf.cell(0, 8, "Architecture, Technologies & File Reference", align="C")
    pdf.ln(30)
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(0, 7, "Version 1.0.0", align="C")
    pdf.ln(7)
    pdf.cell(0, 7, "February 2026", align="C")

    # ── Architecture Overview ──
    pdf.add_page()
    pdf.section_title("1. Architecture Overview")
    pdf.body_text(
        "The Whitelist Manager is a Splunk application for managing CSV whitelist files "
        "used by 300+ detection rules in Splunk Enterprise Security. It provides a web-based "
        "editable table with Git-style audit trail, RBAC enforcement, and dual audit storage."
    )
    pdf.body_text("The application has four main layers:")
    pdf.ln(2)
    pdf.code_block(
        "Browser (JS/CSS)  <->  Splunk Web (XML)  <->  REST Handler (Python)  <->  CSV Files + Index\n"
        "    frontend            presentation             backend                    data"
    )
    pdf.body_text(
        "Each layer uses the technology best suited for its purpose. Splunk enforces specific "
        "technology choices in many areas (e.g., Python for REST handlers, Simple XML for dashboards, "
        "INI-style .conf files for configuration). Where Splunk does not prescribe a choice, we use "
        "standard web technologies (JavaScript, CSS, JSON)."
    )

    # ── Splunk Configuration Files ──
    pdf.add_page()
    pdf.section_title("2. Splunk Configuration Files (.conf)")
    pdf.body_text(
        "Splunk uses INI-style configuration files to control every aspect of the platform. "
        "These files are placed in the app's default/ directory and are read by Splunk on startup. "
        "There is no alternative to .conf files - this is Splunk's native configuration language."
    )

    # app.conf
    pdf.sub_title("default/app.conf")
    pdf.body_text(
        "App identity and metadata. Defines the app name (wl_manager), version (1.0.0), author, "
        "description, and package ID. Splunk uses this to display the app in the Apps menu and "
        "to identify it during installation/upgrades."
    )

    # restmap.conf
    pdf.sub_title("default/restmap.conf")
    pdf.body_text(
        "Registers the custom REST API endpoint. This file tells Splunk: 'When someone calls "
        "/custom/wl_manager, route the request to the Python class WhitelistHandler in wl_handler.py.'"
    )
    pdf.body_text("Key settings:")
    pdf.bullet("match = /custom/wl_manager - the URL path for the endpoint")
    pdf.bullet("script = wl_handler.py - the Python file containing the handler")
    pdf.bullet("handler = wl_handler.WhitelistHandler - the Python class to instantiate")
    pdf.bullet("scripttype = persist - keeps the Python process alive (faster than spawning a new process per request)")
    pdf.bullet("requireAuthentication = true - only authenticated Splunk users can call this endpoint")
    pdf.bullet("python.version = python3 - use Python 3 (Splunk also supports Python 2 for legacy apps)")

    # web.conf
    pdf.sub_title("default/web.conf")
    pdf.body_text(
        "Exposes the REST endpoint through Splunk Web (port 8000). Without this file, the endpoint "
        "would only be accessible via the management port (8089). The web.conf 'expose' stanza acts "
        "as a reverse proxy, allowing the browser-based JavaScript to call the REST API."
    )

    # indexes.conf
    pdf.sub_title("default/indexes.conf")
    pdf.body_text(
        "Creates the wl_audit index for storing audit trail events. Configures storage paths, "
        "a 3-year retention policy (frozenTimePeriodInSecs), and a 1GB data cap (maxTotalDataSizeMB). "
        "Having a dedicated index allows separate access controls and retention from other data."
    )

    # authorize.conf
    pdf.sub_title("default/authorize.conf")
    pdf.body_text(
        "Defines two custom RBAC (Role-Based Access Control) roles:"
    )
    pdf.bullet("wl_editor - can read and write whitelists and view the audit trail")
    pdf.bullet("wl_viewer - read-only access to whitelists and audit trail")
    pdf.body_text(
        "Both roles inherit from Splunk's built-in 'user' role and are granted access to the "
        "wl_audit index. The REST handler checks these roles before allowing write operations."
    )

    # transforms.conf
    pdf.sub_title("default/transforms.conf")
    pdf.body_text(
        "Registers rule_csv_map.csv as a Splunk lookup table. This allows dashboard searches "
        "to query it using the SPL command '| inputlookup rule_csv_map'. Without this registration, "
        "the CSV would just be a file on disk with no Splunk integration."
    )

    # ── XML Dashboards ──
    pdf.add_page()
    pdf.section_title("3. XML Dashboards (Simple XML)")
    pdf.body_text(
        "Splunk uses Simple XML as its dashboard definition language. It is a declarative format "
        "specific to Splunk - you describe what you want (dropdowns, tables, charts), and Splunk "
        "renders them with built-in handling for authentication, search execution, and interactivity."
    )

    pdf.sub_title("default/data/ui/nav/default.xml")
    pdf.body_text(
        "The navigation bar (app menu). Defines two tabs: 'Whitelist Manager' (the main editing "
        "dashboard) and 'Audit Trail' (the change history dashboard). Also includes a link to "
        "Splunk's built-in search page for ad-hoc queries."
    )

    pdf.sub_title("default/data/ui/views/whitelist_manager.xml")
    pdf.body_text(
        "The main interactive dashboard. It uses several Splunk XML features:"
    )
    pdf.bullet(
        "Two <input type=\"dropdown\"> elements with the 'search' attribute - these run SPL queries "
        "to populate the dropdown options from the rule_csv_map lookup"
    )
    pdf.bullet(
        "Token system ($rule_token$, $csv_token$) - when you select a detection rule, it sets a "
        "token that the second dropdown uses to filter its options. This is how the dropdowns "
        "are 'codependent'"
    )
    pdf.bullet(
        "A <search> element with a 'depends' attribute that fires when csv_token is set, "
        "resolving the app_context for the selected CSV"
    )
    pdf.bullet(
        "An <html> panel that serves as a container where JavaScript (whitelist_manager.js) "
        "renders the editable table. Simple XML cannot create editable tables natively"
    )
    pdf.body_text(
        "SPL (Search Processing Language) is Splunk's query language, similar to SQL but designed "
        "for time-series event data. Example: '| inputlookup rule_csv_map | dedup rule_name | "
        "sort rule_name' reads the CSV, removes duplicate rule names, and sorts them alphabetically."
    )

    pdf.sub_title("default/data/ui/views/audit.xml")
    pdf.body_text(
        "The audit trail dashboard. More complex than the main dashboard, it includes:"
    )
    pdf.bullet("Time range picker and dropdown filters for analyst/rule selection")
    pdf.bullet("Single-value panels showing total changes, rows added, and rows removed (using stats SPL command)")
    pdf.bullet("A changelog table with drilldown - clicking a row shows the detailed diff")
    pdf.bullet("Unified diff viewer panel that displays Git-style diffs stored in the audit events")
    pdf.body_text(
        "The 'spath' SPL command is used heavily here - it extracts fields from JSON-formatted "
        "audit events that were indexed as raw strings."
    )

    # ── Python Backend ──
    pdf.add_page()
    pdf.section_title("4. Python Backend")
    pdf.body_text(
        "Python is the only language Splunk supports for custom REST endpoints. The handler runs "
        "as a long-lived process inside Splunk's Python environment (PersistentServerConnectionApplication). "
        "Splunk calls the handle() method for each incoming HTTP request."
    )

    pdf.sub_title("bin/wl_handler.py - REST Handler (core of the app)")
    pdf.body_text(
        "This is the server-side engine. It receives HTTP requests from the JavaScript frontend, "
        "reads/writes CSV files, computes diffs, enforces RBAC, and writes audit events."
    )
    pdf.body_text("Python standard libraries used and why:")

    w = [45, 145]
    pdf.table_row(["Library", "Purpose"], w, bold=True, fill=True)
    pdf.table_row(["json", "Parse incoming REST requests and format JSON responses (REST APIs use JSON)"], w)
    pdf.table_row(["csv", "Read/write CSV files safely - handles quoting, escaping, encoding correctly"], w)
    pdf.table_row(["difflib", "Generate unified diffs (the '--- before / +++ after' Git-style format)"], w)
    pdf.table_row(["logging", "Rotating file logger for audit trail backup (10MB files, 5 backups)"], w)
    pdf.table_row(["os / sys", "File paths, environment variables (SPLUNK_HOME), stderr output"], w)
    pdf.table_row(["datetime", "UTC timestamps (ISO-8601) for audit events"], w)
    pdf.table_row(["urllib / ssl", "HTTPS POST to Splunk's receivers/simple endpoint to index audit events"], w)

    pdf.ln(3)
    pdf.body_text("Splunk-internal libraries (built into Splunk's Python, not installable via pip):")

    pdf.table_row(["Library", "Purpose"], w, bold=True, fill=True)
    pdf.table_row(["splunk.persistconn", "Base class for persistent REST handlers (PersistentServerConnectionApplication)"], w)
    pdf.table_row(["splunk.rest", "Query Splunk's REST API internally (used to fetch user roles for RBAC)"], w)

    pdf.ln(3)
    pdf.body_text("Key functions in the handler:")
    pdf.bullet("_safe_filename() - prevents path traversal attacks (e.g., '../../etc/passwd' as filename)")
    pdf.bullet("_resolve_csv_path() - locates CSV files across different Splunk apps via app_context")
    pdf.bullet("_compute_diff() - compares old vs new CSV, returns added/removed rows + unified text diff")
    pdf.bullet("_get_roles() - fetches user roles from Splunk's authentication API (roles are NOT in the session)")
    pdf.bullet("_index_audit() - writes audit events to Splunk index using Python's built-in urllib (no SDK needed)")
    pdf.bullet("handle() - entry point called by Splunk for every request; routes to GET or POST handlers")

    pdf.body_text(
        "Design decision: we use Python's built-in urllib.request instead of the external Splunk SDK "
        "(splunklib) for indexing audit events. This means the app works without any extra package "
        "installation - a key requirement since Splunk admins may not allow pip installs on production servers."
    )

    pdf.sub_title("bin/wl_wrapper.py - CLI Wrapper")
    pdf.body_text(
        "A standalone command-line tool requested by the Splunk Infrastructure Team for bulk operations "
        "and scripting. It provides the same functionality as the REST handler but via terminal commands."
    )
    pdf.body_text("Commands: list, add, remove, diff")
    pdf.body_text("Additional Python libraries used:")
    pdf.bullet("argparse - parses CLI commands and arguments with built-in help text and validation")
    pdf.bullet("ANSI escape codes - colorized terminal output for diffs (green=added, red=removed)")
    pdf.body_text(
        "The CLI wrapper writes to the same audit log file as the REST handler, so all changes "
        "(whether made via the web UI or terminal) appear in a single audit trail."
    )

    # ── Frontend ──
    pdf.add_page()
    pdf.section_title("5. Frontend (JavaScript + CSS)")

    pdf.sub_title("appserver/static/whitelist_manager.js")
    pdf.body_text(
        "JavaScript is needed because Splunk's XML dashboards cannot create editable tables. "
        "This file runs in the browser and handles all user interaction: loading data, rendering "
        "the editable table, saving changes, and displaying diffs."
    )
    pdf.body_text("Technologies and frameworks used:")

    w2 = [55, 135]
    pdf.table_row(["Technology", "Purpose"], w2, bold=True, fill=True)
    pdf.table_row(["require.js (AMD)", "Splunk's module loader - loads Splunk MVC components (bundled with Splunk)"], w2)
    pdf.table_row(["jQuery ($)", "DOM manipulation - builds HTML tables, handles clicks, AJAX calls (bundled)"], w2)
    pdf.table_row(["Underscore.js (_)", "Utility functions for arrays/objects (bundled with Splunk)"], w2)
    pdf.table_row(["Splunk MVC", "Token model listeners - watches dropdown changes and triggers data loading"], w2)
    pdf.table_row(["$.ajax()", "Makes REST API calls to our Python handler (GET to load, POST to save)"], w2)
    pdf.table_row(["Splunk.util", "make_url() generates correct URLs with Splunk's locale prefix"], w2)

    pdf.ln(3)
    pdf.body_text("Key features built in JavaScript:")
    pdf.bullet("Renders an HTML <table> with contenteditable cells for inline editing")
    pdf.bullet("Add Row / Remove Row buttons for managing whitelist entries")
    pdf.bullet("Mandatory comment field before save (required for audit trail)")
    pdf.bullet("After save, displays the diff returned by the Python handler")
    pdf.bullet("Token listeners that respond to dropdown selections and load the corresponding CSV data")

    pdf.sub_title("appserver/static/whitelist_manager.css")
    pdf.body_text(
        "CSS styles for the editable table, buttons, alerts, and diff panel. All class names are "
        "prefixed with 'wl-' to avoid collisions with Splunk's own CSS framework."
    )
    pdf.body_text("Key style sections:")
    pdf.bullet("Dark header row and hover effects for the editable table")
    pdf.bullet("Green/red highlighting for diff display (mimics GitHub's diff view)")
    pdf.bullet("Monospace font for unified diff text (like a terminal)")
    pdf.bullet("Colored alert styles: red (error), green (success), blue (info), orange (warning)")

    # ── Data Files ──
    pdf.add_page()
    pdf.section_title("6. Data Files")

    pdf.sub_title("lookups/rule_csv_map.csv")
    pdf.body_text(
        "The master mapping table - the 'source of truth' that connects detection rules to their "
        "CSV whitelist files. When you select a rule in the dropdown, the app looks up which CSVs "
        "belong to it from this file."
    )
    pdf.body_text("Three columns:")
    pdf.bullet("rule_name - the detection rule identifier (e.g., DR45_suspicious_login)")
    pdf.bullet("csv_file - the CSV filename (e.g., DR45_whitelist_users.csv)")
    pdf.bullet("app_context - which Splunk app contains the CSV (e.g., SplunkEnterpriseSecuritySuite)")
    pdf.body_text(
        "Why CSV? Splunk's lookup system is built around CSV files stored in "
        "$SPLUNK_HOME/etc/apps/<app>/lookups/. They can be queried with '| inputlookup' in SPL."
    )

    pdf.sub_title("metadata/default.meta")
    pdf.body_text(
        "Splunk's permission file. Controls which roles can read and write which app objects "
        "(views, lookups, REST endpoints). This is RBAC at the Splunk platform layer, separate "
        "from the application-level RBAC in the Python handler."
    )

    # ── Docker Testing ──
    pdf.add_page()
    pdf.section_title("7. Docker Testing Environment")
    pdf.body_text(
        "Docker allows us to run a full Splunk instance locally for testing without affecting "
        "production. The containerized Splunk is identical to production, ensuring our tests "
        "are realistic."
    )

    pdf.sub_title("docker-compose.yml")
    pdf.body_text("Declares the containerized Splunk environment using Docker Compose (YAML format).")
    pdf.bullet("Image: splunk/splunk:9.3.1 (official Splunk Enterprise image)")
    pdf.bullet("Ports: 8000 (Splunk Web), 8089 (management API), 8088 (HTTP Event Collector)")
    pdf.bullet("Bind mounts: maps local app directories into the container for live code reloading")
    pdf.bullet("Named volume (splunk_var): persists Splunk data across container restarts")
    pdf.bullet("Environment: pre-configures admin password, accepts license, enables HEC")

    pdf.sub_title(".docker/default.yml")
    pdf.body_text(
        "Ansible-based Splunk configuration. The official Splunk Docker image uses Ansible internally "
        "to configure itself on first boot. This YAML file pre-creates the wl_audit index so it "
        "exists before any tests run."
    )

    # ── Build Scripts ──
    pdf.add_page()
    pdf.section_title("8. Build & Test Scripts (Bash)")
    pdf.body_text(
        "Bash is the standard language for build and CI/CD automation. These scripts work on "
        "Linux (GitHub Actions CI) and Windows (Git Bash)."
    )

    pdf.sub_title("scripts/validate.sh - Pre-flight Validation")
    pdf.body_text("Runs 8 categories of checks before packaging:")
    pdf.bullet("1. Required files - verifies all expected files exist")
    pdf.bullet("2. app.conf structure - checks version, package ID, launcher stanza")
    pdf.bullet("3. Python syntax - calls 'python -c compile(...)' to check for syntax errors")
    pdf.bullet("4. XML well-formedness - parses dashboard XMLs with Python's ElementTree")
    pdf.bullet("5. Security - greps for hardcoded passwords, tokens, dangerous functions (eval, exec, os.system)")
    pdf.bullet("6. CSV validation - checks that lookup CSVs have proper headers")
    pdf.bullet("7. Dangerous patterns - detects risky code patterns")
    pdf.bullet("8. Forbidden files - AppInspect rules: no .pyc, __pycache__, or .git")

    pdf.sub_title("scripts/package.sh - SPL Packaging")
    pdf.body_text(
        "Builds the .spl file for distribution. An .spl file is simply a .tar.gz archive "
        "containing the app directory as the root entry. Splunk extracts it into "
        "$SPLUNK_HOME/etc/apps/ during installation."
    )
    pdf.body_text("Steps: clean artifacts -> run validation -> create tar.gz -> generate SHA-256 checksum")
    pdf.body_text("Output: dist/wl_manager-<version>.spl + .sha256 integrity file")

    pdf.sub_title("scripts/test_integration.sh - Integration Tests")
    pdf.body_text(
        "11 tests that run against the containerized Splunk instance using curl (HTTP client). "
        "Tests the app the same way a real user would - by sending HTTP requests."
    )
    pdf.body_text("Test categories:")
    pdf.bullet("Connectivity - Splunk management API and web interface are reachable")
    pdf.bullet("App installation - wl_manager app is installed and wl_audit index exists")
    pdf.bullet("REST GET - get_rules and get_mapping return valid JSON with expected data")
    pdf.bullet("REST POST - save_csv writes CSV, returns diff, and audit event appears in index")
    pdf.bullet("Dashboards - whitelist_manager and audit views are accessible")

    # ── CI/CD ──
    pdf.add_page()
    pdf.section_title("9. CI/CD Pipelines (GitHub Actions)")
    pdf.body_text(
        "GitHub Actions provides automated build and test pipelines triggered by Git events. "
        "Workflows are defined in YAML files under .github/workflows/."
    )

    pdf.sub_title(".github/workflows/ci.yml - Continuous Integration")
    pdf.body_text("Triggers: every push to main branch and every pull request.")
    pdf.body_text("Steps:")
    pdf.bullet("1. Checkout code (actions/checkout@v4)")
    pdf.bullet("2. Set up Python 3.9 (actions/setup-python@v5)")
    pdf.bullet("3. Run validate.sh - all 28 checks must pass")
    pdf.bullet("4. Run package.sh - builds the .spl file")
    pdf.bullet("5. Upload .spl as artifact (downloadable for 30 days)")
    pdf.body_text(
        "If any step fails, the pipeline stops and the commit/PR is marked as failed. This "
        "prevents broken code from being merged into the main branch."
    )

    pdf.sub_title(".github/workflows/release.yml - Automated Releases")
    pdf.body_text("Triggers: when you publish a GitHub release (create a new tag like v1.1.0).")
    pdf.body_text("Steps:")
    pdf.bullet("1. Validate and build .spl package")
    pdf.bullet("2. Attach the .spl and .sha256 files to the GitHub release")
    pdf.body_text(
        "This means your Splunk admin can download the latest .spl directly from the GitHub "
        "Releases page - no manual packaging needed."
    )

    # ── Other Files ──
    pdf.sub_title("Other Project Files")

    pdf.sub_sub_title("Makefile")
    pdf.body_text(
        "A convenience wrapper providing short commands (make test, make package, make docker-up) "
        "that call the underlying bash scripts. Useful on Linux/macOS; on Windows, the bash scripts "
        "can be called directly."
    )

    pdf.sub_sub_title(".gitignore")
    pdf.body_text(
        "Tells Git which files to exclude from version control: build output (dist/, .spl), "
        "Python bytecode (.pyc, __pycache__), OS files (.DS_Store, Thumbs.db), Splunk runtime "
        "files (local/), and IDE files (.vscode/, .idea/)."
    )

    pdf.sub_sub_title(".dockerignore")
    pdf.body_text(
        "Tells Docker which files to exclude when building images: development files (scripts, "
        "tests, .git, .github, markdown docs). Keeps the Docker context small and fast."
    )

    pdf.sub_sub_title("tests/sample_whitelist.csv")
    pdf.body_text(
        "Sample CSV file with realistic test data (hostnames, usernames, commands). Used by "
        "integration tests to verify CSV read/write operations."
    )

    # ── Technology Summary ──
    pdf.add_page()
    pdf.section_title("10. Technology Summary")

    w3 = [40, 55, 95]
    pdf.table_row(["Technology", "Where Used", "Why"], w3, bold=True, fill=True)
    pdf.table_row(["Python 3", "REST handler, CLI", "Splunk's only language for custom REST endpoints"], w3)
    pdf.table_row(["Simple XML", "Dashboards", "Splunk's native dashboard framework (handles auth, search)"], w3)
    pdf.table_row(["JavaScript", "Frontend controller", "Needed for editable tables (XML can't do this)"], w3)
    pdf.table_row(["CSS", "Styling", "Visual design for table, buttons, diffs, alerts"], w3)
    pdf.table_row(["SPL", "Dashboard queries", "Splunk's query language (only way to query Splunk data)"], w3)
    pdf.table_row(["Bash", "Build/test scripts", "Standard for CI/CD; works on Linux and Git Bash"], w3)
    pdf.table_row(["Docker + YAML", "Local testing", "Isolated Splunk instance for safe testing"], w3)
    pdf.table_row(["GitHub Actions", "CI/CD pipelines", "Automated validation on push, packaging on release"], w3)
    pdf.table_row(["CSV", "Data storage", "Splunk's native lookup format used by 300+ rules"], w3)
    pdf.table_row(["JSON", "REST API + audit", "Industry standard for API communication"], w3)
    pdf.table_row(["INI (.conf)", "Splunk config", "Splunk's native config format (no alternative)"], w3)
    pdf.table_row(["Git", "Version control", "Track changes, collaborate, distribute via releases"], w3)

    # ── Save ──
    pdf.output(output_path)
    return output_path


if __name__ == "__main__":
    out = os.path.join(os.path.dirname(os.path.dirname(__file__)), "Whitelist_Manager_Documentation.pdf")
    build_pdf(out)
    print(f"PDF saved to: {out}")
