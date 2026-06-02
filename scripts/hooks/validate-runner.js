/**
 * PostToolUse hook — runs scripts/validate.sh after edits to config
 * files that the validator actually inspects, and surfaces FAIL/WARN
 * counts to the assistant via stderr.
 *
 * Fires on Edit/Write touching:
 *   - default/*.conf  (app.conf, restmap.conf, indexes.conf,
 *     authorize.conf, web.conf, transforms.conf, etc.)
 *   - app.manifest
 *   - default/data/ui/views/*.xml
 *   - default/data/ui/nav/*.xml
 *
 * Other extensions (.py, .js, .css, .md, .csv) are skipped — they have
 * dedicated checks via post-edit-check.js + the project's pre-commit
 * hooks. The .py syntax check inside validate.sh would re-run on every
 * .py edit and that's the wrong granularity.
 *
 * Output contract: PostToolUse hooks are informational only. We always
 * exit 0 so Claude Code doesn't block on this. FAIL/WARN counts go to
 * stderr where the assistant can see them.
 *
 * Latency: ~7.7s wall time on Windows + Git Bash + Python. Tolerable
 * for the narrow set of files this matches (config edits are rare).
 */

'use strict';

const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');

const REPO_ROOT = path.resolve(__dirname, '..', '..');
const VALIDATE = path.join(REPO_ROOT, 'scripts', 'validate.sh');

function readStdinSync() {
    // Best-effort stdin slurp. PostToolUse hooks receive a JSON payload;
    // if it isn't there (older Claude Code versions), fall back to env vars.
    try {
        if (process.stdin.isTTY) return '';
        const buf = fs.readFileSync(0, 'utf8');
        return buf;
    } catch (_) {
        return '';
    }
}

function envFirst(...keys) {
    for (const k of keys) {
        const v = process.env[k];
        if (v && v.length) return v;
    }
    return '';
}

function getFilePath() {
    // Modern contract: JSON on stdin
    const raw = readStdinSync();
    if (raw) {
        try {
            const obj = JSON.parse(raw);
            const ti = obj.tool_input || {};
            if (ti.file_path) return ti.file_path;
        } catch (_) { /* fall through */ }
    }
    // Older contract: env vars (preserved for block-synthetic-fixtures.js parity)
    return envFirst('TOOL_INPUT_file_path', 'TOOL_INPUT_FILE_PATH');
}

function shouldRun(filePath) {
    if (!filePath) return false;
    const norm = filePath.replace(/\\/g, '/');

    // Map to repo-relative form
    let rel = norm;
    const rootForward = REPO_ROOT.replace(/\\/g, '/');
    if (norm.toLowerCase().startsWith(rootForward.toLowerCase() + '/')) {
        rel = norm.slice(rootForward.length + 1);
    }

    if (rel === 'app.manifest') return true;
    if (/^default\/[^/]+\.conf$/.test(rel)) return true;
    if (/^default\/data\/ui\/views\/[^/]+\.xml$/.test(rel)) return true;
    if (/^default\/data\/ui\/nav\/[^/]+\.xml$/.test(rel)) return true;
    return false;
}

function main() {
    const filePath = getFilePath();
    if (!shouldRun(filePath)) {
        process.exit(0);
    }
    if (!fs.existsSync(VALIDATE)) {
        // Validator missing — fail open, log nothing (this could be a
        // fresh worktree or partial checkout).
        process.exit(0);
    }

    const result = spawnSync('bash', [VALIDATE], {
        cwd: REPO_ROOT,
        encoding: 'utf8',
        stdio: ['ignore', 'pipe', 'pipe'],
        timeout: 30000,
    });

    if (result.error) {
        process.stderr.write(`[validate-runner] could not spawn bash: ${result.error.message}\n`);
        process.exit(0);
    }

    const stdout = result.stdout || '';
    // Pull the summary line. validate.sh ends with one of:
    //   "  RESULT: ALL CHECKS PASSED (N warning(s))"
    //   "  RESULT: N FAILED check(s), M warning(s)"
    const summaryMatch = stdout.match(/RESULT:.*$/m);
    const summary = summaryMatch ? summaryMatch[0].trim() : 'RESULT: (no summary captured)';

    if (result.status === 0) {
        process.stderr.write(`[validate-runner] PASS — ${summary} (triggered by ${path.basename(filePath)})\n`);
    } else {
        // Surface the failing PASS/FAIL lines plus the summary so the
        // assistant has enough context to fix without re-running.
        const failLines = stdout.split('\n').filter((l) => /\[FAIL\]/.test(l));
        const lines = [
            `[validate-runner] FAIL — ${summary} (triggered by ${path.basename(filePath)})`,
            ...failLines.slice(0, 10).map((l) => `  ${l.trim()}`),
        ];
        if (failLines.length > 10) {
            lines.push(`  ... (${failLines.length - 10} more — run \`bash scripts/validate.sh\` to see all)`);
        }
        lines.push('  Re-run: bash scripts/validate.sh');
        process.stderr.write(lines.join('\n') + '\n');
    }

    process.exit(0);
}

main();
