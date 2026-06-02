/**
 * PostToolUse hook — keep appserver/static/whitelist_manager.js's
 * RequireJS `urlArgs: "_b=N"` cache-bust in sync with
 * default/app.conf [install].build.
 *
 * Why: Splunk serves /static/@<server-hash>/... with
 * Cache-Control: public, max-age=31536000. The `@<hash>` is keyed to
 * the Splunk server build, NOT the app build — bumping app.conf
 * `build` does NOT invalidate browser cache, so users keep running
 * stale JS until they hard-refresh. The urlArgs trick appends
 * `?_b=N` to every AMD module URL; bumping N forces a fresh fetch.
 *
 * The "Splunk Quirks" section of CLAUDE.md documents this and says:
 * "bumping `build` in `app.conf` REQUIRES also bumping `_b=` in
 * whitelist_manager.js (same number) — otherwise new JS will not
 * reach users." That manual maintenance step is exactly what this
 * hook mechanizes.
 *
 * Fires on Edit/Write to default/app.conf. Reads the current
 * build = N from app.conf, reads the current _b=M from
 * whitelist_manager.js, and if N != M, updates the JS to match.
 *
 * Output: stderr line so the assistant sees the auto-fix. Exit 0
 * — informational only.
 */

'use strict';

const fs = require('fs');
const path = require('path');

const REPO_ROOT = path.resolve(__dirname, '..', '..');
const APP_CONF = path.join(REPO_ROOT, 'default', 'app.conf');
const JS_FILE = path.join(REPO_ROOT, 'appserver', 'static', 'whitelist_manager.js');

function readStdinSync() {
    try {
        if (process.stdin.isTTY) return '';
        return fs.readFileSync(0, 'utf8');
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
    const raw = readStdinSync();
    if (raw) {
        try {
            const obj = JSON.parse(raw);
            const ti = obj.tool_input || {};
            if (ti.file_path) return ti.file_path;
        } catch (_) { /* fall through */ }
    }
    return envFirst('TOOL_INPUT_file_path', 'TOOL_INPUT_FILE_PATH');
}

function isAppConf(filePath) {
    if (!filePath) return false;
    const norm = filePath.replace(/\\/g, '/').toLowerCase();
    return norm.endsWith('/default/app.conf') || norm === 'default/app.conf';
}

function extractBuild(confText) {
    // Match the [install] stanza, then the first `build = N` inside it.
    // We don't rely on a single regex with PCRE lookbehinds — instead,
    // we walk stanzas.
    const lines = confText.split(/\r?\n/);
    let inInstall = false;
    for (const line of lines) {
        const stanza = line.match(/^\s*\[([^\]]+)\]\s*$/);
        if (stanza) {
            inInstall = stanza[1].trim().toLowerCase() === 'install';
            continue;
        }
        if (!inInstall) continue;
        const m = line.match(/^\s*build\s*=\s*(\d+)\s*$/);
        if (m) return m[1];
    }
    return null;
}

function main() {
    const filePath = getFilePath();
    if (!isAppConf(filePath)) {
        process.exit(0);
    }
    if (!fs.existsSync(APP_CONF) || !fs.existsSync(JS_FILE)) {
        process.exit(0);
    }

    const conf = fs.readFileSync(APP_CONF, 'utf8');
    const build = extractBuild(conf);
    if (!build) {
        process.stderr.write('[urlargs-sync] could not read [install].build from default/app.conf\n');
        process.exit(0);
    }

    const js = fs.readFileSync(JS_FILE, 'utf8');
    // Use the global flag so we can detect AND replace every
    // occurrence. Multiple matches are rare (the file ships with
    // exactly one), but if a refactor ever introduces a second
    // require.config block we want to sync them together — otherwise
    // half the AMD modules would load with one cache-bust value and
    // half with another, which is worse than no cache-bust at all.
    const urlArgsReG = /(urlArgs\s*:\s*")_b=(\d+)(")/g;
    const matches = [...js.matchAll(urlArgsReG)];
    if (matches.length === 0) {
        process.stderr.write('[urlargs-sync] urlArgs pattern not found in whitelist_manager.js — manual review needed\n');
        process.exit(0);
    }

    const current = matches[0][2];
    const allInSync = matches.every((m) => m[2] === build);
    if (allInSync) {
        // All occurrences already in sync — silent
        process.exit(0);
    }

    const distinctCurrent = [...new Set(matches.map((m) => m[2]))];
    if (matches.length > 1) {
        process.stderr.write(
            `[urlargs-sync] WARNING: found ${matches.length} urlArgs entries ` +
            `in whitelist_manager.js (values: ${distinctCurrent.join(', ')}). ` +
            `Syncing all to _b=${build}. If this is unexpected, the file may ` +
            `have been refactored — review the diff manually.\n`
        );
    }

    const next = js.replace(urlArgsReG, `$1_b=${build}$3`);
    fs.writeFileSync(JS_FILE, next);
    const fromLabel = distinctCurrent.length === 1 ? `_b=${current}` : `[${distinctCurrent.map((v) => `_b=${v}`).join(', ')}]`;
    process.stderr.write(
        `[urlargs-sync] bumped ${fromLabel} -> _b=${build} in appserver/static/whitelist_manager.js ` +
        `(matched default/app.conf [install].build=${build}; ${matches.length} occurrence(s) updated). ` +
        `Re-read the JS before further edits.\n`
    );
    process.exit(0);
}

main();
