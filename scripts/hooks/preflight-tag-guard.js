#!/usr/bin/env node
// Tag / release pre-flight guard — PreToolUse Bash hook (project-local).
// Wired into .claude/settings.json with matcher "Bash".
//
// Catches commands that cut a release tag or publish a GitHub release
// (`git tag vX.Y.Z`, `gh release create vX.Y.Z`, `git push --tags`
// when an unreleased local tag exists) and runs the §3.5 Version-Tag
// Consistency pre-flight from docs/RELEASE_CHECKLIST.md.
//
// If the four sources of truth agree (app.conf [launcher].version,
// app.conf [id].version, app.manifest info.id.version, and
// app.conf [package].id == [id].name), exit 0 (allow). If any
// disagree, exit 2 with the drift details — Claude must resolve
// the drift before retrying.
//
// Exit codes:
//   0 = allow (not a tag-cut command, OR pre-flight passes)
//   2 = block + emit stderr (Claude sees it; surfaces to user)
//
// Failure-mode policy: any internal error exits 0 (allow) rather than
// blocking — a buggy guard should not block legitimate work.

'use strict';

const fs = require('fs');
const path = require('path');
const os = require('os');
const { execFileSync } = require('child_process');

const REPO_ROOT = path.resolve(__dirname, '..', '..');
const PREFLIGHT = path.join(REPO_ROOT, 'scripts', 'preflight-tag.sh');
const LOG_FILE = path.join(os.homedir(), '.claude', 'preflight-tag-guard.log');

function log(msg) {
    try {
        const ts = new Date().toISOString();
        fs.appendFileSync(LOG_FILE, `[${ts}] ${msg}\n`);
    } catch (_) { /* ignore */ }
}

function readStdin() {
    return new Promise((resolve) => {
        let data = '';
        if (process.stdin.isTTY) return resolve('');
        process.stdin.setEncoding('utf8');
        process.stdin.on('data', (chunk) => { data += chunk; });
        process.stdin.on('end', () => resolve(data));
        process.stdin.on('error', () => resolve(''));
        setTimeout(() => resolve(data), 2000);
    });
}

// Extract the tag the command intends to cut. Returns null if the
// command is not a tag-cut / release-create command.
function extractIntendedTag(cmd) {
    if (typeof cmd !== 'string') return null;
    const stripped = cmd.replace(/(^|\s)#[^\n]*/g, ' ');

    // Pattern 1: git tag [-a|-s|-f] <tagname> ...
    //   We only care if <tagname> matches semver-ish vX.Y.Z (optionally
    //   with -rcN / -betaN suffix). Anything else is not a release tag.
    let m = stripped.match(/\bgit\s+tag\b(?:\s+-[asuf]\w*)*\s+(v\d+\.\d+\.\d+(?:-[A-Za-z0-9.+-]+)?)\b/);
    if (m) return m[1];

    // Pattern 2: gh release create <tagname> ...
    m = stripped.match(/\bgh\s+release\s+create\s+(v\d+\.\d+\.\d+(?:-[A-Za-z0-9.+-]+)?)\b/);
    if (m) return m[1];

    // Pattern 3: gh api ... releases ... tag_name=vX.Y.Z (curl-style)
    m = stripped.match(/tag_name[=:][\s"']*(v\d+\.\d+\.\d+(?:-[A-Za-z0-9.+-]+)?)\b/);
    if (m) return m[1];

    return null;
}

(async () => {
    const stdin = await readStdin();
    let payload;
    try { payload = JSON.parse(stdin || '{}'); } catch (_) { payload = {}; }

    const tool = payload.tool_name || payload.tool || '';
    if (tool !== 'Bash') {
        process.exit(0);
    }

    const cmd = (payload.tool_input && payload.tool_input.command) || payload.command || '';
    const intended = extractIntendedTag(cmd);
    if (!intended) {
        process.exit(0);
    }

    // Verify the preflight script exists. If not, log and allow — we
    // don't want a missing script to block release work.
    if (!fs.existsSync(PREFLIGHT)) {
        log(`skip: preflight script missing at ${PREFLIGHT}`);
        process.exit(0);
    }

    let stdout = '';
    let stderr = '';
    let status = 0;
    try {
        stdout = execFileSync('bash', [PREFLIGHT, intended], {
            cwd: REPO_ROOT,
            encoding: 'utf8',
            stdio: ['ignore', 'pipe', 'pipe'],
        });
    } catch (err) {
        status = typeof err.status === 'number' ? err.status : 1;
        stdout = err.stdout ? err.stdout.toString() : '';
        stderr = err.stderr ? err.stderr.toString() : '';
    }

    if (status === 0) {
        log(`PASS: ${intended} (${stdout.trim()})`);
        process.exit(0);
    }

    log(`BLOCK: ${intended} drift detected`);

    process.stderr.write(
`[preflight-tag-guard] BLOCKED: version-tag pre-flight failed for \`${intended}\`.

Command: ${cmd.trim().split('\n')[0].slice(0, 300)}

This guard ran \`scripts/preflight-tag.sh ${intended}\` (the canonical
§3.5 check from docs/RELEASE_CHECKLIST.md). At least one of the four
sources-of-truth disagrees with the intended tag:

  - default/app.conf [launcher].version
  - default/app.conf [id].version
  - app.manifest info.id.version
  - default/app.conf [package].id == [id].name

Drift details (from the preflight script):
${stderr.trim() || stdout.trim() || '(no details captured)'}

Required action: edit the disagreeing source(s) to match
${intended.replace(/^v/, '')} BEFORE re-running the tag/release command.
If a release was intentionally renamed mid-cut, run \`make doc-check\`
afterwards so CHANGELOG.md doesn't drift from app.conf.
`);

    process.exit(2);
})();
