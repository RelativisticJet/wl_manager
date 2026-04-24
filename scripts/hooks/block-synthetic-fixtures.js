/**
 * PreToolUse hook: block direct writes to Splunk state that would
 * bypass the handler's production code path.
 *
 * Origin: 2026-04-23 session — synthetic injection into
 * _approval_queue.json masked the dual-admin Invalid Date bug. The
 * existing "Verification Before Done" prose rule in CLAUDE.md did not
 * prevent it. This hook provides mechanical enforcement.
 *
 * Exit codes:
 *   0 allow
 *   2 block (stderr is shown to Claude verbatim)
 *
 * Exceptions:
 *   - Write/Edit under tests/unit/ — pure unit tests of helper
 *     functions do not verify production paths.
 *   - Bash commands that include a `# JUSTIFIED: <reason>` marker.
 *     Use ONLY when no production endpoint exists (e.g. bootstrapping
 *     the FIRST FIM baseline on a fresh install).
 */

"use strict";

// Hidden files ("." prefix) do not appear in a default ls but exist at
// runtime once the handler/FIM cycle writes them. Always include the
// dotted forms in the block list — their absence from disk today does
// not mean they are safe to synthesize tomorrow.
const BLOCKED_FILE_PATTERNS = [
    /_approval_queue\.json/,
    /_daily_limits\.json/,
    /_detection_rules\.json/,
    /_limit_config\.json/,
    /_notifications\.json/,
    /_trash_config\.json/,
    /_emergency_lockdown\.json/,
    /_action_cooldowns\.json/,
    /_fim_deploy_window\.json/,
    /\.fim_baseline\.json/,
    /\.fim_alert_state\.json/,
    /\.csv_expected_hashes\.json/,
    /\.presence\.json/,
    // Synthetic fixture scripts — these typically exist only to inject
    // state and are therefore banned at the path level.
    /tests[\\/]_inject_[^\\/]+\.py/,
    /tests[\\/][^\\/]*_fixture_[^\\/]*\.py/,
    /tests[\\/][^\\/]*synthetic[^\\/]*\.py/,
];

// KV collections that back protected state. Mutations via curl/REST
// bypass the handler exactly like direct file writes. Read-only (GET)
// calls are NOT blocked.
const BLOCKED_KV_COLLECTIONS = [
    "wl_cooldowns",
    "wl_fim_baseline",
    "wl_presence",
    "wl_lockdown",
];

const UNIT_TEST_EXCEPTION = /tests[\\/]unit[\\/]/;
const JUSTIFICATION_MARKER = /#\s*JUSTIFIED:\s*\S+/;

// Indicators that a Bash command is WRITING (not merely reading) the
// path it mentions. Without this check, `grep _approval_queue.json`
// or `cat ... | jq` would false-positive.
const WRITE_INDICATORS =
    /(?:>>?\s|\btee\b|\bjson\.dump\b|open\s*\([^)]*['"]w|\bdocker\s+cp\b|\bcp\b\s|\bmv\b\s)/;

const KV_MUTATING_METHOD = /-X\s+(?:POST|PUT|DELETE|PATCH)/i;

function block(msg) {
    process.stderr.write(msg + "\n");
    process.exit(2);
}

function checkFileWrite(filePath) {
    if (!filePath) return;
    if (UNIT_TEST_EXCEPTION.test(filePath)) return; // pure unit tests allowed

    for (const re of BLOCKED_FILE_PATTERNS) {
        if (re.test(filePath)) {
            block(
                [
                    "[BLOCKED synthetic-fixtures] Direct write to " +
                        filePath,
                    "",
                    "This bypasses the handler's production code path",
                    "and produces audit/verification results that do NOT",
                    "match what the app does for real users.",
                    "",
                    "Use a production endpoint instead:",
                    "  - approval queue  → POST /custom/wl_manager action=submit_approval",
                    "  - daily limits    → exercise real admin actions as analyst1/wladmin1",
                    "  - FIM baseline    → let wl_fim.py rebuild on its 15s cycle,",
                    "                      or call action=bootstrap_csv_hashes",
                    "  - cooldowns       → trigger real rate-limited actions",
                    "  - notifications   → trigger the event that emits them",
                    "",
                    "Exception: place pure-helper tests under tests/unit/",
                    "(those do not claim to verify a feature end-to-end).",
                    "",
                    "Override: this hook has no override for Write/Edit.",
                    "If you genuinely cannot reach the state any other",
                    "way, write a unit test under tests/unit/ OR raise",
                    "the limitation with the user before proceeding.",
                ].join("\n")
            );
        }
    }
}

function checkBash(cmd) {
    if (!cmd) return;
    if (JUSTIFICATION_MARKER.test(cmd)) return; // explicit bypass

    const hasWrite = WRITE_INDICATORS.test(cmd);
    for (const re of BLOCKED_FILE_PATTERNS) {
        if (re.test(cmd) && hasWrite) {
            block(
                [
                    "[BLOCKED synthetic-fixtures] Bash command writes to a",
                    "protected Splunk state file (matched " + re + ").",
                    "",
                    "Same rule as Write/Edit: this bypasses the handler.",
                    "",
                    "To proceed, either (a) use a production endpoint, or",
                    "(b) add the marker '# JUSTIFIED: <reason>' to the",
                    "command if no production path exists (e.g. first-",
                    "install bootstrapping of the FIM baseline).",
                    "",
                    "Command was:",
                    "  " + cmd.replace(/\s+/g, " ").slice(0, 300),
                ].join("\n")
            );
        }
    }

    for (const coll of BLOCKED_KV_COLLECTIONS) {
        const endpoint = "storage/collections/data/" + coll;
        if (cmd.indexOf(endpoint) !== -1 && KV_MUTATING_METHOD.test(cmd)) {
            block(
                [
                    "[BLOCKED synthetic-fixtures] Bash command mutates KV",
                    "collection '" + coll + "' via REST.",
                    "",
                    "Use the handler's action= endpoint (it verifies RBAC,",
                    "increments counters, writes audit trail). A raw",
                    "REST mutation does none of those.",
                    "",
                    "If no production action exists for this mutation,",
                    "add '# JUSTIFIED: <reason>' to the command.",
                ].join("\n")
            );
        }
    }
}

// Claude Code passes tool input via TOOL_INPUT_<key> env vars.
// Keys are lowercase for file_path/command; some environments UPPER.
function envFirst(...keys) {
    for (const k of keys) {
        const v = process.env[k];
        if (v && v.length) return v;
    }
    return "";
}

const toolName = envFirst("TOOL_NAME", "CLAUDE_TOOL_NAME") || "";

if (toolName === "Write" || toolName === "Edit") {
    checkFileWrite(
        envFirst("TOOL_INPUT_file_path", "TOOL_INPUT_FILE_PATH")
    );
} else if (toolName === "Bash") {
    checkBash(envFirst("TOOL_INPUT_command", "TOOL_INPUT_COMMAND"));
}

process.exit(0);
