/**
 * Shared code-quality detection patterns used by:
 *   - .claude/hooks/post-edit-check.js  (per-edit, fires on Write/Edit)
 *   - .claude/hooks/stop-check.js       (session-end safety net,
 *                                        catches files modified outside
 *                                        the Claude Code Write/Edit
 *                                        tools — e.g. via Bash `sed`,
 *                                        external editors, git restore)
 *
 * Putting the regex set in one file means a "found another debug
 * statement we should ban" fix lands in one place, not two — that's
 * what the 2026-06-01 consolidation closed.
 *
 * Each rule's `match` returns an array of issue descriptions (or [])
 * given file content + path. `applies` gates by file extension.
 */

'use strict';

const path = require('path');

const RULES = [
    // ── Python ────────────────────────────────────────────────────
    {
        name: 'py-print',
        applies: (ext) => ext === '.py',
        match: (content) => {
            const out = [];
            content.split('\n').forEach((line, i) => {
                if (/^\s*print\s*\(/.test(line) && !/^\s*#/.test(line)) {
                    out.push(`Line ${i + 1}: print() — use _logger instead`);
                }
            });
            return out;
        },
    },
    {
        name: 'py-pdb',
        applies: (ext) => ext === '.py',
        match: (content) => (/import\s+pdb|pdb\.set_trace/.test(content)
            ? ['Debugger (pdb) left in code']
            : []),
    },
    {
        name: 'py-bare-except',
        applies: (ext) => ext === '.py',
        match: (content) => (/except\s*:/.test(content)
            ? ['Bare except: found — specify exception type']
            : []),
    },

    // ── JavaScript ────────────────────────────────────────────────
    {
        name: 'js-console-log',
        applies: (ext) => ext === '.js',
        match: (content) => {
            const out = [];
            content.split('\n').forEach((line, i) => {
                if (/console\.log\(/.test(line) && !/^\s*\/\//.test(line)) {
                    out.push(`Line ${i + 1}: console.log() — remove before deploy`);
                }
            });
            return out;
        },
    },
    {
        name: 'js-debugger',
        applies: (ext) => ext === '.js',
        match: (content) => (/\bdebugger\b/.test(content)
            ? ['debugger statement found — remove before deploy']
            : []),
    },
    {
        name: 'js-inner-html',
        applies: (ext) => ext === '.js',
        match: (content) => (/\.innerHTML\s*=/.test(content) && !/_.escape/.test(content)
            ? ['innerHTML assignment — potential XSS, use _.escape()']
            : []),
    },
];

/**
 * Run all rules that apply to filePath's extension against content.
 * Returns array of issue descriptions (may be empty).
 */
function check(filePath, content) {
    const ext = path.extname(filePath).toLowerCase();
    const issues = [];
    for (const rule of RULES) {
        if (!rule.applies(ext)) continue;
        for (const m of rule.match(content)) {
            issues.push(m);
        }
    }
    return issues;
}

module.exports = { check, RULES };
