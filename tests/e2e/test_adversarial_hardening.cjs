// ╔═══════════════════════════════════════════════════════════════════╗
// ║  ⚠  DESTRUCTIVE TEST FILE — MODIFIES CONTAINER STATE           ║
// ║                                                                 ║
// ║  This file deletes/corrupts KV store records, filesystem        ║
// ║  sentinels, and cooldown state inside the Splunk container.     ║
// ║                                                                 ║
// ║  REQUIRES:  WL_TEST_HARNESS=1  environment variable             ║
// ║  REQUIRES:  Container "wl_manager_test" running                 ║
// ║                                                                 ║
// ║  DO NOT run against production. The assertTestHarness() gate    ║
// ║  will refuse, but defense in depth: read this banner first.     ║
// ╚═══════════════════════════════════════════════════════════════════╝
/**
 * Adversarial Hardening Tests — tests the 5 hardening tasks:
 *   (a) KV-store backed cooldowns  (tested in test_cooldown_tamper.cjs)
 *   (b) First-install bootstrap
 *   (c) Recovery script audit trail
 *   (d) Runtime HMAC key (not source-derived)
 *   (e) Stale view detection via content hash
 *
 * Plus threat-model driven adversarial scenarios using all three
 * user tiers (analyst1 / wladmin1 / superadmin1) and out-of-band
 * attack vectors (direct filesystem, SPL, Splunk REST).
 */
const H = require("./lib_helpers.cjs");
const { spawnSync } = require("child_process");

// Gate — see lib_helpers.cjs :: assertTestHarness
H.assertTestHarness();

const CONTAINER = H.EXPECTED_TEST_CONTAINER;
const VERSIONS_DIR = "/opt/splunk/etc/apps/wl_manager/lookups/_versions";
const LOOKUPS_DIR  = "/opt/splunk/etc/apps/wl_manager/lookups";

function dockerExec(args) {
    const res = spawnSync("docker", ["exec", "-u", "0", CONTAINER, ...args], {
        env: { ...process.env, MSYS_NO_PATHCONV: "1" },
        encoding: "utf8",
    });
    return { stdout: res.stdout || "", stderr: res.stderr || "", code: res.status };
}

function dockerExecStr(cmd) {
    // Exec a full shell command inside the container (careful with quoting).
    const res = spawnSync("docker", ["exec", "-u", "0", CONTAINER, "bash", "-lc", cmd], {
        env: { ...process.env, MSYS_NO_PATHCONV: "1" },
        encoding: "utf8",
    });
    return { stdout: res.stdout || "", stderr: res.stderr || "", code: res.status };
}

function kvDelete() {
    dockerExec([
        "curl", "-s", "-k", "-u", "admin:Chang3d!", "-X", "DELETE",
        "https://localhost:8089/servicesNS/nobody/wl_manager/storage/collections/data/wl_cooldowns/state",
    ]);
}

function kvGet() {
    const out = dockerExec([
        "curl", "-s", "-k", "-u", "admin:Chang3d!",
        "https://localhost:8089/servicesNS/nobody/wl_manager/storage/collections/data/wl_cooldowns/state?output_mode=json",
    ]).stdout.trim();
    if (!out || out.includes("Could not find object")) return null;
    try { return JSON.parse(out); } catch (e) { return null; }
}

function resetCooldownState() {
    kvDelete();
    dockerExec(["rm", "-f",
        `${VERSIONS_DIR}/.cooldown_tamper`,
        `${VERSIONS_DIR}/.cooldown_initialized`,
    ]);
}

// Inject a forged KV record (wrong checksum)
function kvForge(payloadObj) {
    kvDelete();
    const body = JSON.stringify({
        _key: "state",
        payload: JSON.stringify(payloadObj || {}),
        checksum: "attacker_does_not_know_runtime_key",
        updated_at: 1,
        updated_by: "attacker",
    });
    dockerExec([
        "curl", "-s", "-k", "-u", "admin:Chang3d!", "-X", "POST",
        "-H", "Content-Type: application/json",
        "-d", body,
        "https://localhost:8089/servicesNS/nobody/wl_manager/storage/collections/data/wl_cooldowns",
    ]);
}

(async () => {
    let analyst, wladmin, superadmin;
    let superPage, adminPage, analystPage;

    async function newSessions() {
        analyst   = await H.createSession("analyst1",    "Chang3d!");
        wladmin   = await H.createSession("wladmin1",    "Chang3d!");
        superadmin = await H.createSession("superadmin1", "Chang3d!");
        analystPage = analyst.page;
        adminPage   = wladmin.page;
        superPage   = superadmin.page;
    }

    try {
        H.log("🔧", "Cleaning stale test artifacts from previous runs...");
        // Remove FIM deploy window files and test recovery log noise
        // left behind if a previous run crashed mid-test.
        dockerExecStr(`rm -f ${VERSIONS_DIR}/_fim_deploy_window.json 2>/dev/null || true`);
        dockerExecStr(`sed -i '/ADVERSARIAL_TEST_/d' ${VERSIONS_DIR}/_recovery_log.jsonl 2>/dev/null || true`);

        H.log("🔧", "Resetting cooldown state to simulate first install...");
        resetCooldownState();
        await new Promise(r => setTimeout(r, 500));
        await newSessions();

        // ═══════════════════════════════════════════════════════════
        // SECTION B — First install bootstrap
        // ═══════════════════════════════════════════════════════════

        await H.test("AD01 First install: superadmin set_admin_limits bootstraps KV + marker", async () => {
            const d = await H.restCall(superPage, "POST", {
                action: "set_admin_limits",
                limits: { csv_save: 19 }
            });
            if (d.error) throw new Error("Bootstrap failed: " + d.error);
            if (!d.success) throw new Error("Bootstrap response missing success flag");
            // Verify KV record exists
            const rec = kvGet();
            if (!rec) throw new Error("KV record not created on first install");
            if (!rec.checksum || rec.checksum === "deadbeef" || rec.checksum === "attacker") {
                throw new Error("KV checksum missing or forged: " + JSON.stringify(rec));
            }
            // Verify init marker exists
            const ls = dockerExec(["ls", `${VERSIONS_DIR}/.cooldown_initialized`]);
            if (ls.code !== 0) throw new Error("Init marker not created");
        });

        await H.test("AD02 First install: analyst does NOT bootstrap (RBAC rejects)", async () => {
            // Can't really re-bootstrap since we did AD01. But we can
            // verify analyst is 403 on admin action.
            const d = await H.restCall(analystPage, "POST", {
                action: "set_admin_limits",
                limits: { csv_save: 5 }
            });
            // analyst should get an error or 403
            if (d.success) throw new Error("Analyst should not be able to call set_admin_limits");
        });

        // ═══════════════════════════════════════════════════════════
        // SECTION D — Runtime HMAC key behavior
        // ═══════════════════════════════════════════════════════════

        await H.test("AD03 Runtime HMAC key: forged record with deterministic key is rejected", async () => {
            // Reset and prime a valid record
            resetCooldownState();
            const p = await H.restCall(superPage, "POST", {
                action: "set_admin_limits",
                limits: { csv_save: 18 }
            });
            if (p.error) throw new Error("Prime failed: " + p.error);
            // Attacker with full source code knowledge attempts to
            // recompute HMAC using only the source salt. Since the
            // real key mixes in the Splunk server GUID the attacker
            // can't reproduce it. We simulate this by using a raw
            // static salt (what pre-runtime-key code used).
            const forgedBody = JSON.stringify({
                _key: "state",
                payload: JSON.stringify({ "admin_limit_changes:2099-01-01": 999 }),
                // This is what the old v1 code produced — predictable
                // from source alone. Runtime v2 key must reject it.
                checksum: "0000000000000000000000000000000000000000000000000000000000000000",
                updated_at: 1,
                updated_by: "attacker",
            });
            kvDelete();
            dockerExec([
                "curl", "-s", "-k", "-u", "admin:Chang3d!", "-X", "POST",
                "-H", "Content-Type: application/json",
                "-d", forgedBody,
                "https://localhost:8089/servicesNS/nobody/wl_manager/storage/collections/data/wl_cooldowns",
            ]);
            const d = await H.restCall(superPage, "POST", {
                action: "set_admin_limits",
                limits: { csv_save: 17 }
            });
            if (!d.error || !d.error.includes("Security lockdown")) {
                throw new Error("Forged HMAC should fail-close, got: " + JSON.stringify(d));
            }
        });

        // ═══════════════════════════════════════════════════════════
        // SECTION E — Stale view detection (content hash)
        // ═══════════════════════════════════════════════════════════

        await H.test("AD04 check_csv_status returns content_hash", async () => {
            // First recover from AD03 tamper
            resetCooldownState();
            await H.restCall(superPage, "POST", {
                action: "set_admin_limits", limits: { csv_save: 20 }
            });
            const d = await H.restCall(superPage, "GET", {
                action: "check_csv_status",
                csv_file: "DR130_priv_escalation.csv",
                app: ""
            });
            if (!d.content_hash || typeof d.content_hash !== "string" || d.content_hash.length !== 64) {
                throw new Error("check_csv_status did not return valid sha256 content_hash: " + JSON.stringify(d));
            }
            if (!d.file_mtime) throw new Error("file_mtime missing");
        });

        await H.test("AD05 Stale view: mtime-preserving write (touch -r) flips content_hash", async () => {
            const PATH = `${LOOKUPS_DIR}/DR130_priv_escalation.csv`;
            // Snapshot initial hash and mtime
            const before = await H.restCall(superPage, "GET", {
                action: "check_csv_status",
                csv_file: "DR130_priv_escalation.csv",
                app: ""
            });
            const mtimeBefore = before.file_mtime;
            const hashBefore  = before.content_hash;

            // Save a reference copy of mtime
            dockerExec(["cp", "-p", PATH, `${PATH}.ref`]);

            // Attacker modifies file via shell, then restores mtime
            // using touch -r (preserves mtime from reference).
            dockerExecStr(`printf 'user,Comment\\n%s\\n' 'attacker,malicious' >> "${PATH}" && touch -r "${PATH}.ref" "${PATH}" && rm -f "${PATH}.ref"`);

            // Wait a moment for any fs buffering
            await new Promise(r => setTimeout(r, 300));

            // Poll check_csv_status again
            const after = await H.restCall(superPage, "GET", {
                action: "check_csv_status",
                csv_file: "DR130_priv_escalation.csv",
                app: ""
            });

            if (after.file_mtime !== mtimeBefore) {
                // touch -r didn't perfectly preserve, note it but still
                // require hash change (which is the real gap fix)
                H.log("ℹ️", "Note: mtime changed unexpectedly (touch -r limit?)");
            }
            if (after.content_hash === hashBefore) {
                throw new Error("Content hash did not change despite file mutation");
            }
        });

        await H.test("AD06 Stale view: SPL-style writable-lookup editing flips hash", async () => {
            // Simulate SPL `| outputlookup` editing the CSV directly.
            // Writing via Python in the container is the closest
            // analog in the test harness.
            const PATH = `${LOOKUPS_DIR}/DR130_priv_escalation.csv`;
            const before = await H.restCall(superPage, "GET", {
                action: "check_csv_status",
                csv_file: "DR130_priv_escalation.csv",
                app: ""
            });
            dockerExecStr(`python3 -c "
import csv
with open('${PATH}', 'a', newline='') as f:
    w = csv.writer(f)
    w.writerow(['spl_user', 'SPL-injected row'])
"`);
            await new Promise(r => setTimeout(r, 300));
            const after = await H.restCall(superPage, "GET", {
                action: "check_csv_status",
                csv_file: "DR130_priv_escalation.csv",
                app: ""
            });
            if (after.content_hash === before.content_hash) {
                throw new Error("Hash did not update after SPL-style append");
            }
        });

        // ═══════════════════════════════════════════════════════════
        // SECTION — Bypass attempts by each role
        // ═══════════════════════════════════════════════════════════

        await H.test("AD07 Analyst cannot directly write KV cooldown record", async () => {
            // Analyst has REST access but KV store requires higher role.
            // Attempt a direct KV write via Splunk proxy using the
            // analyst session.
            const attack = await analystPage.evaluate(async () => {
                const csrfMatch = document.cookie.match(/splunkweb_csrf_token_8000=([^;]+)/);
                const token = csrfMatch ? csrfMatch[1] : "";
                try {
                    const res = await fetch(
                        "/en-US/splunkd/__raw/servicesNS/nobody/wl_manager/storage/collections/data/wl_cooldowns",
                        {
                            method: "POST",
                            headers: {
                                "X-Splunk-Form-Key": token,
                                "X-Requested-With": "XMLHttpRequest",
                                "Content-Type": "application/json",
                            },
                            body: JSON.stringify({
                                _key: "state",
                                payload: "{}",
                                checksum: "analyst_attack",
                                updated_at: 0,
                                updated_by: "analyst1",
                            }),
                        });
                    return { status: res.status, body: (await res.text()).substring(0, 200) };
                } catch (e) {
                    return { status: 0, body: e.message };
                }
            });
            if (attack.status === 200 || attack.status === 201) {
                throw new Error("Analyst was allowed to write KV store: " + JSON.stringify(attack));
            }
        });

        await H.test("AD08 Analyst cannot call purge_trash (RBAC)", async () => {
            const d = await H.restCall(analystPage, "POST", {
                action: "purge_trash",
                item_id: "any"
            });
            if (d.success) throw new Error("Analyst should not be able to purge");
        });

        await H.test("AD09 Admin cannot call set_admin_limits (superadmin only)", async () => {
            const d = await H.restCall(adminPage, "POST", {
                action: "set_admin_limits",
                limits: { csv_save: 15 }
            });
            if (d.success) throw new Error("Admin should not be able to change admin limits");
        });

        await H.test("AD10 Superadmin rate-limited to 5 admin limit changes per day", async () => {
            // Hard to test hitting the limit in under a minute due to
            // Splunk's built-in REST throttling. Instead verify the
            // counter is being incremented in KV store.
            resetCooldownState();
            await H.restCall(superPage, "POST", {
                action: "set_admin_limits",
                limits: { csv_save: 11 }
            });
            const rec = kvGet();
            if (!rec || !rec.payload) throw new Error("KV record missing after bump");
            const payload = JSON.parse(rec.payload);
            const today = new Date().toISOString().slice(0, 10);
            const counter = payload["admin_limit_changes:" + today];
            if (!counter || counter < 1) {
                throw new Error("Counter not incremented: " + JSON.stringify(payload));
            }
        });

        // ═══════════════════════════════════════════════════════════
        // SECTION — Recovery audit trail
        // ═══════════════════════════════════════════════════════════

        await H.test("AD11 Recovery log path is monitored by scripted input", async () => {
            const out = dockerExec(["cat",
                "/opt/splunk/etc/apps/wl_manager/default/inputs.conf"]).stdout;
            if (!out.includes("_recovery_log.jsonl")) {
                throw new Error("inputs.conf does not reference _recovery_log.jsonl");
            }
            if (!out.includes("sourcetype") || !out.includes("wl_audit_recovery")) {
                throw new Error("sourcetype wl_audit_recovery not configured");
            }
            if (!out.includes("index          = wl_audit")) {
                throw new Error("recovery log not routed to wl_audit index");
            }
        });

        await H.test("AD12 Recovery log append is atomic and visible to Splunk monitor", async () => {
            // Append a test recovery record directly and verify it lands
            // in the wl_audit index via search.
            const marker = "ADVERSARIAL_TEST_" + Date.now();
            dockerExecStr(`python3 -c "
import json, time, os
rec = {'timestamp': int(time.time()), 'timestamp_human': 'test', 'action': 'reset_cooldowns', 'script': 'test_harness', 'container': 'wl_manager_test', 'host_user': 'tester', 'reason': '${marker}'}
path = '${VERSIONS_DIR}/_recovery_log.jsonl'
os.makedirs(os.path.dirname(path), exist_ok=True)
with open(path, 'a') as f:
    f.write(json.dumps(rec) + '\\n')
os.chmod(path, 0o644)
"`);
            // Wait for Splunk to pick up the new line (file monitor
            // batch delay ~500ms but can be longer on first write)
            await new Promise(r => setTimeout(r, 4000));
            const search = dockerExec([
                "/opt/splunk/bin/splunk", "search",
                `index=wl_audit sourcetype=wl_audit_recovery reason="${marker}" | head 5`,
                "-auth", "admin:Chang3d!",
                "-maxout", "5",
            ]).stdout;
            if (!search.includes(marker)) {
                throw new Error("Recovery log event not indexed to wl_audit: " + search.substring(0, 300));
            }
        });

        // ═══════════════════════════════════════════════════════════
        // SECTION — Follow-up hardening (KV schema_version, save-path
        // content-hash lock, FIM scripted input)
        // ═══════════════════════════════════════════════════════════

        await H.test("AD13 KV record with unknown schema_version triggers fail-closed", async () => {
            // Recover from any prior tamper and prime a valid record
            resetCooldownState();
            const p = await H.restCall(superPage, "POST", {
                action: "set_admin_limits", limits: { csv_save: 20 }
            });
            if (p.error) throw new Error("Prime failed: " + p.error);
            // Attacker (or a rolled-back handler) writes a record with
            // a future/unknown schema_version. Must fail-close.
            kvDelete();
            const forged = JSON.stringify({
                _key: "state",
                schema_version: 99,
                payload: "{}",
                checksum: "irrelevant",
                updated_at: 1,
                updated_by: "attacker",
            });
            dockerExec([
                "curl", "-s", "-k", "-u", "admin:Chang3d!", "-X", "POST",
                "-H", "Content-Type: application/json",
                "-d", forged,
                "https://localhost:8089/servicesNS/nobody/wl_manager/storage/collections/data/wl_cooldowns",
            ]);
            const d = await H.restCall(superPage, "POST", {
                action: "set_admin_limits", limits: { csv_save: 19 }
            });
            if (!d.error || !d.error.includes("Security lockdown")) {
                throw new Error("Unknown schema_version should fail-close: "
                    + JSON.stringify(d).substring(0, 200));
            }
            // Recover for subsequent tests
            resetCooldownState();
        });

        await H.test("AD14 save_csv rejects expected_content_hash mismatch (stronger save lock)", async () => {
            // Recover from AD13 tamper
            await H.restCall(superPage, "POST", {
                action: "set_admin_limits", limits: { csv_save: 20 }
            });
            // Load a CSV as admin — capture content_hash
            const mapping = await H.restCall(adminPage, "GET", { action: "get_mapping" });
            if (!mapping.mapping || !mapping.mapping.length) {
                throw new Error("No CSV mapping available");
            }
            const entry = mapping.mapping[0];
            const csvData = await H.restCall(adminPage, "GET", {
                action: "get_csv_content",
                csv_file: entry.csv_file,
                app: entry.app_context || "wl_manager"
            });
            if (!csvData.content_hash) {
                throw new Error("get_csv_content did not return content_hash");
            }
            // Attempt save with a FORGED content_hash (client pretends
            // it saw a different snapshot). Must fail with 409.
            var newRow = {};
            (csvData.headers || []).forEach(function (h) {
                const lh = h.toLowerCase();
                if (lh === "comment") newRow[h] = "AD14_test";
                else if (lh === "expires") newRow[h] = "2099-12-31";
                else newRow[h] = "ad14_val";
            });
            const modifiedRows = (csvData.rows || []).slice();
            modifiedRows.push(newRow);

            const save = await H.restCall(adminPage, "POST", {
                action: "save_csv",
                csv_file: entry.csv_file,
                detection_rule: entry.detection_rule || entry.rule_name,
                app_context: entry.app_context || "wl_manager",
                headers: csvData.headers,
                rows: modifiedRows,
                comment: "AD14 save with stale hash",
                expected_mtime: csvData.file_mtime,
                // Forge an all-zeros hash the server can't match
                expected_content_hash: "0".repeat(64),
            });
            if (!save.error || save.error.indexOf("content hash") === -1) {
                throw new Error(
                    "save with stale content_hash should 409: "
                    + JSON.stringify(save).substring(0, 300));
            }
        });

        await H.test("AD15 save_csv accepts matching expected_content_hash (honest client)", async () => {
            const mapping = await H.restCall(adminPage, "GET", { action: "get_mapping" });
            const entry = mapping.mapping[0];
            const csvData = await H.restCall(adminPage, "GET", {
                action: "get_csv_content",
                csv_file: entry.csv_file,
                app: entry.app_context || "wl_manager"
            });
            var newRow = {};
            (csvData.headers || []).forEach(function (h) {
                const lh = h.toLowerCase();
                if (lh === "comment") newRow[h] = "AD15_test";
                else if (lh === "expires") newRow[h] = "2099-12-31";
                else newRow[h] = "ad15_val";
            });
            const modifiedRows = (csvData.rows || []).slice();
            modifiedRows.push(newRow);

            const save = await H.restCall(adminPage, "POST", {
                action: "save_csv",
                csv_file: entry.csv_file,
                detection_rule: entry.detection_rule || entry.rule_name,
                app_context: entry.app_context || "wl_manager",
                headers: csvData.headers,
                rows: modifiedRows,
                comment: "AD15 honest save",
                expected_mtime: csvData.file_mtime,
                expected_content_hash: csvData.content_hash,
            });
            if (save.error) {
                throw new Error("Honest save should succeed: " + save.error);
            }
        });

        await H.test("AD16 FIM scripted input indexes baseline event", async () => {
            // Force an immediate run by invoking the script directly
            // (scripted inputs run on a 60s interval — we don't want
            // the test to wait that long). With dual-store FIM (build
            // 554+) both the FS baseline AND the KV baseline must be
            // cleared to get a fresh baseline-init event, and a
            // session key must be provided so KV init succeeds.
            dockerExec(["rm", "-f",
                `${VERSIONS_DIR}/.fim_baseline.json`]);
            dockerExec([
                "curl", "-s", "-k", "-u", "admin:Chang3d!", "-X", "DELETE",
                "https://localhost:8089/servicesNS/nobody/wl_manager/storage/collections/data/wl_fim_baseline/state"
            ]);
            const sessionOut = dockerExec([
                "curl", "-s", "-k", "-u", "admin:Chang3d!", "-X", "POST",
                "-d", "username=admin&password=Chang3d!",
                "https://localhost:8089/services/auth/login?output_mode=json"
            ]).stdout;
            const sk = sessionOut.match(/"sessionKey":\s*"([^"]+)"/)[1];
            const out = dockerExec([
                "bash", "-c",
                `WL_FIM_SESSION_KEY='${sk}' python3 /opt/splunk/etc/apps/wl_manager/bin/wl_fim.py`
            ]).stdout;
            if (!out.includes("fim_baseline_initialized")) {
                throw new Error(
                    "FIM direct run did not emit baseline-init event: "
                    + out.substring(0, 300));
            }
        });

        await H.test("AD16a FIM bakes KV baseline when session key is available", async () => {
            // Run FIM directly; without passAuth the script won't
            // have a session key, so we fake one via env var for the
            // test-harness path. Real production path uses passAuth.
            // First clear both stores.
            dockerExec(["rm", "-f", `${VERSIONS_DIR}/.fim_baseline.json`]);
            dockerExec([
                "curl", "-s", "-k", "-u", "admin:Chang3d!", "-X", "DELETE",
                "https://localhost:8089/servicesNS/nobody/wl_manager/storage/collections/data/wl_fim_baseline/state"
            ]);
            // Fetch a session key for superadmin1 via REST login
            const sessionOut = dockerExec([
                "curl", "-s", "-k", "-u", "admin:Chang3d!", "-X", "POST",
                "-d", "username=admin&password=Chang3d!",
                "https://localhost:8089/services/auth/login?output_mode=json"
            ]).stdout;
            const sessionMatch = sessionOut.match(/"sessionKey":\s*"([^"]+)"/);
            if (!sessionMatch) {
                throw new Error("Failed to fetch session key: " + sessionOut.substring(0, 200));
            }
            const sk = sessionMatch[1];
            // Run FIM with the key via env var
            const run = dockerExec([
                "bash", "-c",
                `WL_FIM_SESSION_KEY='${sk}' python3 /opt/splunk/etc/apps/wl_manager/bin/wl_fim.py`
            ]);
            if (!run.stdout.includes("fim_baseline_initialized")) {
                throw new Error("FIM did not init baseline: " + run.stdout.substring(0, 300));
            }
            if (!run.stdout.includes('"kv_store": true')) {
                throw new Error("FIM did not write to KV store: " + run.stdout.substring(0, 300));
            }
            // Verify KV record exists
            const kv = dockerExec([
                "curl", "-s", "-k", "-u", "admin:Chang3d!",
                "https://localhost:8089/servicesNS/nobody/wl_manager/storage/collections/data/wl_fim_baseline/state?output_mode=json"
            ]).stdout;
            if (!kv.includes("checksum")) {
                throw new Error("FIM baseline not in KV store: " + kv.substring(0, 300));
            }
        });

        await H.test("AD16b FIM detects filesystem baseline tampering when KV is intact", async () => {
            // KV baseline is present (from AD16a). Delete the FS
            // baseline to simulate an attacker hiding prior mods.
            dockerExec(["rm", "-f", `${VERSIONS_DIR}/.fim_baseline.json`]);
            // Fetch session key and re-run FIM
            const sessionOut = dockerExec([
                "curl", "-s", "-k", "-u", "admin:Chang3d!", "-X", "POST",
                "-d", "username=admin&password=Chang3d!",
                "https://localhost:8089/services/auth/login?output_mode=json"
            ]).stdout;
            const sk = sessionOut.match(/"sessionKey":\s*"([^"]+)"/)[1];
            const run = dockerExec([
                "bash", "-c",
                `WL_FIM_SESSION_KEY='${sk}' python3 /opt/splunk/etc/apps/wl_manager/bin/wl_fim.py`
            ]);
            if (!run.stdout.includes("fim_fs_baseline_missing_or_tampered")) {
                throw new Error(
                    "FIM should flag FS baseline loss while KV intact: "
                    + run.stdout.substring(0, 300));
            }
        });

        await H.test("AD16c FIM deploy window downgrades modification alerts to INFO", async () => {
            const watchedPath = "/opt/splunk/etc/apps/wl_manager/default/app.conf";
            const originalContent = dockerExec(["cat", watchedPath]).stdout;

            // Get session key
            const sessionOut = dockerExec([
                "curl", "-s", "-k", "-u", "admin:Chang3d!", "-X", "POST",
                "-d", "username=admin&password=Chang3d!",
                "https://localhost:8089/services/auth/login?output_mode=json"
            ]).stdout;
            const sk = sessionOut.match(/"sessionKey":\s*"([^"]+)"/)[1];

            // Re-baseline both stores
            dockerExec(["rm", "-f", `${VERSIONS_DIR}/.fim_baseline.json`]);
            dockerExec([
                "curl", "-s", "-k", "-u", "admin:Chang3d!", "-X", "DELETE",
                "https://localhost:8089/servicesNS/nobody/wl_manager/storage/collections/data/wl_fim_baseline/state"
            ]);
            dockerExec([
                "bash", "-c",
                `WL_FIM_SESSION_KEY='${sk}' python3 /opt/splunk/etc/apps/wl_manager/bin/wl_fim.py`
            ]);

            // Open a deploy window (15 min default, HMAC-signed by script)
            const windowOpen = dockerExec([
                "bash", "-lc",
                `cd /tmp && cat > /tmp/_open.sh <<'EOF'
#!/bin/bash
set -euo pipefail
python3 <<'PY'
import json, hashlib, hmac, os, time
with open("/opt/splunk/etc/instance.cfg") as f:
    for line in f:
        if line.strip().startswith("guid"):
            guid = line.split("=",1)[1].strip()
            break
salt = b"wl_manager_fim_integrity_v1"
key = hashlib.sha256(salt + guid.encode()).digest()
now = int(time.time())
body = {"started_at": now, "expires_at": now + 600, "started_by": "test", "reason": "AD16c"}
filtered = {k: v for k, v in body.items() if k != "_checksum"}
payload = json.dumps(filtered, sort_keys=True, default=str)
body["_checksum"] = hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()
os.makedirs("${VERSIONS_DIR}", exist_ok=True)
with open("${VERSIONS_DIR}/_fim_deploy_window.json", "w") as f:
    json.dump(body, f)
PY
EOF
bash /tmp/_open.sh`
            ]);

            try {
                // Mutate the watched file
                dockerExec(["bash", "-c",
                    `printf '\\n# AD16c test %s\\n' "$(date +%s)" >> ${watchedPath}`]);
                // Re-run FIM
                const run = dockerExec([
                    "bash", "-c",
                    `WL_FIM_SESSION_KEY='${sk}' python3 /opt/splunk/etc/apps/wl_manager/bin/wl_fim.py`
                ]);
                if (!run.stdout.includes("fim_file_modified_during_deploy")) {
                    throw new Error(
                        "Deploy window did not downgrade alert: "
                        + run.stdout.substring(0, 400));
                }
                if (!run.stdout.includes('"severity": "INFO"')) {
                    throw new Error(
                        "Deploy window alert should be INFO severity: "
                        + run.stdout.substring(0, 400));
                }
            } finally {
                // Restore original and close window
                dockerExec(["bash", "-c",
                    `cat > ${watchedPath} <<'RESTORE_EOF'\n${originalContent}RESTORE_EOF`]);
                dockerExec(["rm", "-f",
                    `${VERSIONS_DIR}/_fim_deploy_window.json`,
                    `${VERSIONS_DIR}/.fim_baseline.json`]);
                dockerExec([
                    "curl", "-s", "-k", "-u", "admin:Chang3d!", "-X", "DELETE",
                    "https://localhost:8089/servicesNS/nobody/wl_manager/storage/collections/data/wl_fim_baseline/state"
                ]);
                dockerExec([
                    "bash", "-c",
                    `WL_FIM_SESSION_KEY='${sk}' python3 /opt/splunk/etc/apps/wl_manager/bin/wl_fim.py`
                ]);
            }
        });

        await H.test("AD16d FIM deploy window with forged HMAC is ignored", async () => {
            // Attacker writes a deploy_window file without knowing
            // the GUID-derived key — the signature won't match and
            // FIM should treat the window as inactive.
            const watchedPath = "/opt/splunk/etc/apps/wl_manager/default/app.conf";
            const originalContent = dockerExec(["cat", watchedPath]).stdout;

            const sessionOut = dockerExec([
                "curl", "-s", "-k", "-u", "admin:Chang3d!", "-X", "POST",
                "-d", "username=admin&password=Chang3d!",
                "https://localhost:8089/services/auth/login?output_mode=json"
            ]).stdout;
            const sk = sessionOut.match(/"sessionKey":\s*"([^"]+)"/)[1];

            dockerExec(["rm", "-f", `${VERSIONS_DIR}/.fim_baseline.json`]);
            dockerExec([
                "curl", "-s", "-k", "-u", "admin:Chang3d!", "-X", "DELETE",
                "https://localhost:8089/servicesNS/nobody/wl_manager/storage/collections/data/wl_fim_baseline/state"
            ]);
            dockerExec([
                "bash", "-c",
                `WL_FIM_SESSION_KEY='${sk}' python3 /opt/splunk/etc/apps/wl_manager/bin/wl_fim.py`
            ]);

            // Write a FORGED deploy window (wrong checksum)
            dockerExec([
                "bash", "-c",
                `cat > ${VERSIONS_DIR}/_fim_deploy_window.json <<'JSON'
{"started_at": 1, "expires_at": 9999999999, "started_by": "attacker", "reason": "forever", "_checksum": "deadbeef"}
JSON`
            ]);

            try {
                dockerExec(["bash", "-c",
                    `printf '\\n# AD16d test\\n' >> ${watchedPath}`]);
                const run = dockerExec([
                    "bash", "-c",
                    `WL_FIM_SESSION_KEY='${sk}' python3 /opt/splunk/etc/apps/wl_manager/bin/wl_fim.py`
                ]);
                if (run.stdout.includes("fim_file_modified_during_deploy")) {
                    throw new Error(
                        "Forged deploy window should be ignored, but alert was downgraded: "
                        + run.stdout.substring(0, 400));
                }
                if (!run.stdout.includes("fim_file_modified")) {
                    throw new Error(
                        "FIM should still emit HIGH-severity modification alert: "
                        + run.stdout.substring(0, 400));
                }
            } finally {
                dockerExec(["bash", "-c",
                    `cat > ${watchedPath} <<'RESTORE_EOF2'\n${originalContent}RESTORE_EOF2`]);
                dockerExec(["rm", "-f",
                    `${VERSIONS_DIR}/_fim_deploy_window.json`,
                    `${VERSIONS_DIR}/.fim_baseline.json`]);
                dockerExec([
                    "bash", "-c",
                    `WL_FIM_SESSION_KEY='${sk}' python3 /opt/splunk/etc/apps/wl_manager/bin/wl_fim.py`
                ]);
            }
        });

        await H.test("AD17 FIM detects an unexpected file modification", async () => {
            // Pick a file that is ALWAYS present on disk after a
            // normal deploy — the handler source itself. That
            // eliminates the "file not yet created" race we'd hit
            // with transient sentinels.
            const watchedPath = "/opt/splunk/etc/apps/wl_manager/default/app.conf";

            // Save original content so we can restore it
            const originalContent = dockerExec(["cat", watchedPath]).stdout;

            // Fetch a session key so FIM can dual-store the baseline
            const sessionOut = dockerExec([
                "curl", "-s", "-k", "-u", "admin:Chang3d!", "-X", "POST",
                "-d", "username=admin&password=Chang3d!",
                "https://localhost:8089/services/auth/login?output_mode=json"
            ]).stdout;
            const sk = sessionOut.match(/"sessionKey":\s*"([^"]+)"/)[1];

            // Re-baseline with the watched file in its pristine state
            dockerExec(["rm", "-f", `${VERSIONS_DIR}/.fim_baseline.json`]);
            dockerExec([
                "curl", "-s", "-k", "-u", "admin:Chang3d!", "-X", "DELETE",
                "https://localhost:8089/servicesNS/nobody/wl_manager/storage/collections/data/wl_fim_baseline/state"
            ]);
            const initRun = dockerExec([
                "bash", "-c",
                `WL_FIM_SESSION_KEY='${sk}' python3 /opt/splunk/etc/apps/wl_manager/bin/wl_fim.py`
            ]).stdout;
            if (!initRun.includes("fim_baseline_initialized")) {
                throw new Error("Baseline run failed: " + initRun.substring(0, 300));
            }

            try {
                // Mutate the watched file (append a comment line)
                dockerExecStr(
                    `printf '\\n# FIM test marker %s\\n' "$(date +%s)" >> ${watchedPath}`);
                const out = dockerExec([
                    "bash", "-c",
                    `WL_FIM_SESSION_KEY='${sk}' python3 /opt/splunk/etc/apps/wl_manager/bin/wl_fim.py`
                ]).stdout;
                if (!out.includes("fim_file_modified")) {
                    throw new Error(
                        "FIM did not flag the mutated file: "
                        + out.substring(0, 300));
                }
                if (!out.includes("app.conf")) {
                    throw new Error(
                        "FIM alert missing expected path: "
                        + out.substring(0, 300));
                }
            } finally {
                // Restore original content — important because app.conf
                // drives the build number used by other tests.
                dockerExecStr(
                    `cat > ${watchedPath} <<'FIM_RESTORE_EOF'\n${originalContent}FIM_RESTORE_EOF`);
                // And re-baseline so the restore isn't flagged on next run
                dockerExec(["rm", "-f", `${VERSIONS_DIR}/.fim_baseline.json`]);
                dockerExec([
                    "curl", "-s", "-k", "-u", "admin:Chang3d!", "-X", "DELETE",
                    "https://localhost:8089/servicesNS/nobody/wl_manager/storage/collections/data/wl_fim_baseline/state"
                ]);
                dockerExec([
                    "bash", "-c",
                    `WL_FIM_SESSION_KEY='${sk}' python3 /opt/splunk/etc/apps/wl_manager/bin/wl_fim.py`
                ]);
            }
        });

        await H.test("AD18a save_csv rejects missing expected_content_hash (strict)", async () => {
            const mapping = await H.restCall(adminPage, "GET", { action: "get_mapping" });
            const entry = mapping.mapping[0];
            const csvData = await H.restCall(adminPage, "GET", {
                action: "get_csv_content",
                csv_file: entry.csv_file,
                app: entry.app_context || "wl_manager"
            });
            const save = await H.restCall(adminPage, "POST", {
                action: "save_csv",
                csv_file: entry.csv_file,
                detection_rule: entry.detection_rule || entry.rule_name,
                app_context: entry.app_context || "wl_manager",
                headers: csvData.headers,
                rows: csvData.rows || [],
                comment: "AD18a missing hash",
                expected_mtime: csvData.file_mtime,
                // NO expected_content_hash at all (simulates old client)
            });
            if (!save.error || save.error.indexOf("expected_content_hash") === -1) {
                throw new Error(
                    "Missing hash should 409 with reload hint: "
                    + JSON.stringify(save).substring(0, 300));
            }
            if (!save.reload_required) {
                throw new Error("reload_required flag not set on response");
            }
        });

        await H.test("AD18b save_csv rejects malformed expected_content_hash (strict)", async () => {
            const mapping = await H.restCall(adminPage, "GET", { action: "get_mapping" });
            const entry = mapping.mapping[0];
            const csvData = await H.restCall(adminPage, "GET", {
                action: "get_csv_content",
                csv_file: entry.csv_file,
                app: entry.app_context || "wl_manager"
            });
            const malformed = [
                "not-a-hash",                  // wrong format
                "0".repeat(63),                // too short
                "0".repeat(65),                // too long
                "ZZ" + "0".repeat(62),         // non-hex (Z is not valid hex)
                // Note: "A".repeat(64) is valid — build 555+ accepts uppercase
                // hex via .lower() normalization (Gap 3 fix).
                "",                            // empty string
            ];
            for (const bad of malformed) {
                const save = await H.restCall(adminPage, "POST", {
                    action: "save_csv",
                    csv_file: entry.csv_file,
                    detection_rule: entry.detection_rule || entry.rule_name,
                    app_context: entry.app_context || "wl_manager",
                    headers: csvData.headers,
                    rows: csvData.rows || [],
                    comment: "AD18b malformed hash",
                    expected_mtime: csvData.file_mtime,
                    expected_content_hash: bad,
                });
                if (!save.error || save.error.indexOf("Invalid expected_content_hash") === -1) {
                    throw new Error(
                        "Malformed hash '" + bad.substring(0, 32)
                        + "' should be rejected, got: "
                        + JSON.stringify(save).substring(0, 200));
                }
            }
        });

        await H.test("AD18c wl_migrate_cooldowns v0→v1 migrates legitimate old record", async () => {
            // Clear rate-limit counter so parallel suites don't starve
            // this test of set_admin_limits calls (it needs at least 2).
            H.clearKvCooldownCounter();
            await new Promise(r => setTimeout(r, 300));

            // Inject a v0-format record (no schema_version, HMAC
            // computed over the raw payload without "v1:" prefix).
            // The real handler would reject it, but the migration
            // tool verifies the old format and re-signs it.
            //
            // To compute the valid v0 HMAC we need the runtime key,
            // which is SHA-256(salt || guid). Rather than duplicate
            // that logic in the test, we invoke a small Python
            // one-liner inside the container.
            const writeV0 = `
import json, hmac, hashlib, os, urllib.request, ssl, base64, time

with open("/opt/splunk/etc/instance.cfg") as f:
    guid = [l.strip().split("=",1)[1].strip() for l in f if l.strip().startswith("guid")][0]
salt = b"wl_manager_cooldown_integrity_v2"
key = hashlib.sha256(salt + guid.encode()).digest()
payload = json.dumps({"admin_limit_changes:2020-01-01": 1}, sort_keys=True)
checksum = hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()
record = {
    "_key": "state",
    "payload": payload,
    "checksum": checksum,
    "updated_at": int(time.time()),
    "updated_by": "test_injector",
}
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
# Delete any existing record first so we can insert cleanly
token = base64.b64encode(b"admin:Chang3d!").decode()
req = urllib.request.Request(
    "https://localhost:8089/servicesNS/nobody/wl_manager/storage/collections/data/wl_cooldowns/state",
    method="DELETE")
req.add_header("Authorization", "Basic " + token)
try:
    urllib.request.urlopen(req, context=ctx)
except Exception:
    pass
# Insert via collection endpoint
req = urllib.request.Request(
    "https://localhost:8089/servicesNS/nobody/wl_manager/storage/collections/data/wl_cooldowns",
    method="POST",
    data=json.dumps(record).encode())
req.add_header("Authorization", "Basic " + token)
req.add_header("Content-Type", "application/json")
resp = urllib.request.urlopen(req, context=ctx)
print("inject status:", resp.status)
`;
            dockerExec([
                "python3", "-c", writeV0
            ]);

            // The handler will currently fail-closed on this record
            // (v1 verify against a v0 signature). Confirm that:
            const preMigrate = await H.restCall(superPage, "POST", {
                action: "set_admin_limits",
                limits: { csv_save: 20 }
            });
            if (!preMigrate.error || preMigrate.error.indexOf("Security lockdown") === -1) {
                throw new Error(
                    "Before migration, v0 record should fail-close: "
                    + JSON.stringify(preMigrate).substring(0, 300));
            }

            // Clear the tamper flag the handler just set and run the
            // migration. The migration tool verifies v0, re-signs v1,
            // and writes back.
            dockerExec(["rm", "-f",
                `${VERSIONS_DIR}/.cooldown_tamper`]);
            const migrate = dockerExec([
                "python3",
                "/opt/splunk/etc/apps/wl_manager/bin/wl_migrate_cooldowns.py",
                "--from", "0", "--to", "1",
                "--auth", "admin:Chang3d!",
                "--reason", "test harness AD18c"
            ]);
            if (!migrate.stdout.includes("Migration complete")) {
                throw new Error(
                    "Migration tool did not report success: "
                    + (migrate.stdout + migrate.stderr).substring(0, 400));
            }

            // After migration the handler should accept reads again.
            const postMigrate = await H.restCall(superPage, "POST", {
                action: "set_admin_limits",
                limits: { csv_save: 19 }
            });
            if (postMigrate.error) {
                throw new Error(
                    "After migration, set_admin_limits should succeed: "
                    + JSON.stringify(postMigrate).substring(0, 300));
            }
        });

        await H.test("AD18d wl_migrate_cooldowns refuses tampered records", async () => {
            // Insert a record with a bogus checksum — migration must
            // reject it (verify step fails) and exit non-zero.
            kvDelete();
            const bad = JSON.stringify({
                _key: "state",
                payload: "{\"evil\":1}",
                checksum: "deadbeef" + "0".repeat(56),
                updated_at: 0,
                updated_by: "attacker",
            });
            dockerExec([
                "curl", "-s", "-k", "-u", "admin:Chang3d!", "-X", "POST",
                "-H", "Content-Type: application/json",
                "-d", bad,
                "https://localhost:8089/servicesNS/nobody/wl_manager/storage/collections/data/wl_cooldowns",
            ]);
            const migrate = dockerExec([
                "python3",
                "/opt/splunk/etc/apps/wl_manager/bin/wl_migrate_cooldowns.py",
                "--from", "0", "--to", "1",
                "--auth", "admin:Chang3d!",
                "--reason", "test harness AD18d"
            ]);
            if (migrate.code === 0) {
                throw new Error("Migration should have exited non-zero on tamper");
            }
            if (!(migrate.stdout + migrate.stderr).includes("verification failed")) {
                throw new Error(
                    "Migration tool should report verification failure: "
                    + (migrate.stdout + migrate.stderr).substring(0, 400));
            }
            // Clean up for next test
            resetCooldownState();
            await H.restCall(superPage, "POST", {
                action: "set_admin_limits", limits: { csv_save: 20 }
            });
        });

        await H.test("AD18 Runtime HMAC key cache has bounded TTL", async () => {
            // Verify by reading the handler source for the TTL
            // constant. A runtime test would require waiting 1h; the
            // constant check at least prevents a regression where the
            // TTL is removed or set to zero/infinity.
            const src = dockerExec(["cat",
                "/opt/splunk/etc/apps/wl_manager/bin/wl_handler.py"]).stdout;
            const m = src.match(/_RUNTIME_HMAC_KEY_TTL_SECONDS\s*=\s*(\d+)/);
            if (!m) throw new Error("TTL constant not found in handler source");
            const ttl = parseInt(m[1], 10);
            if (!(ttl > 0 && ttl <= 86400)) {
                throw new Error("TTL out of sane bounds: " + ttl);
            }
        });

        // ═══════════════════════════════════════════════════════════
        // SECTION F — CSV Integrity Monitoring
        // ═══════════════════════════════════════════════════════════

        // Pre-flight: verify wl_fim_watch.py is running (all CSV integrity
        // tests depend on it). Fail fast with a clear message rather than
        // timing out in individual tests.
        const _watcherPs = dockerExecStr("ps aux | grep wl_fim_watch | grep -v grep").stdout || "";
        const _watcherRunning = _watcherPs.includes("wl_fim_watch.py");
        if (!_watcherRunning) {
            H.log("⚠️", "wl_fim_watch.py NOT running — CSV integrity tests " +
                "that require the watcher will fail with a clear error");
        } else {
            H.log("✓", "wl_fim_watch.py is running — CSV integrity tests enabled");
        }

        // Helper: guard for tests that require the watcher
        function requireWatcher(testName) {
            if (!_watcherRunning) {
                throw new Error(
                    testName + " requires wl_fim_watch.py but it is not running. "
                    + "Check default/inputs.conf has interval=0 for the watcher input.");
            }
        }

        // Helper: run a Splunk search via CLI and return raw output
        function splunkSearch(spl, maxWait) {
            maxWait = maxWait || "-5m";
            const cmd = `/opt/splunk/bin/splunk search '${spl} earliest=${maxWait}' -auth admin:Chang3d! -output json 2>/dev/null`;
            return dockerExecStr(cmd).stdout.trim();
        }

        // Helper: wait for a FIM event matching a pattern (polls every 2s, max 30s)
        async function waitForFimEvent(actionPattern, maxSeconds) {
            maxSeconds = maxSeconds || 30;
            const deadline = Date.now() + maxSeconds * 1000;
            while (Date.now() < deadline) {
                const raw = splunkSearch(
                    `index=wl_audit sourcetype=wl_fim action="${actionPattern}"`,
                    "-2m"
                );
                if (raw && raw.length > 10 && !raw.includes('"results":[]')) {
                    return raw;
                }
                await new Promise(r => setTimeout(r, 2000));
            }
            return null;
        }

        // Helper: read the expected-hashes registry directly
        function readHashRegistry() {
            const out = dockerExec(["cat",
                `${VERSIONS_DIR}/.csv_expected_hashes.json`]).stdout.trim();
            if (!out) return null;
            try { return JSON.parse(out); } catch (e) { return null; }
        }

        // AD19: Bootstrap CSV hashes via dedicated action
        await H.test("AD19 bootstrap_csv_hashes creates HMAC-signed registry for all CSVs", async () => {
            // Remove existing registry to test fresh bootstrap
            dockerExec(["rm", "-f", `${VERSIONS_DIR}/.csv_expected_hashes.json`]);

            const d = await H.restCall(superPage, "POST", {
                action: "bootstrap_csv_hashes"
            });
            if (d.error) throw new Error("Bootstrap failed: " + d.error);
            if (!d.success) throw new Error("Missing success flag");
            if (typeof d.hashed_count !== "number" || d.hashed_count < 1) {
                throw new Error("Expected hashed_count > 0, got: " + d.hashed_count);
            }

            // Verify registry file exists and is valid JSON with _checksum
            const reg = readHashRegistry();
            if (!reg) throw new Error("Registry file not created or not valid JSON");
            if (!reg._checksum) throw new Error("Registry missing HMAC _checksum");

            // Verify rule_csv_map.csv is in the registry (sentinel CSV)
            if (!reg["rule_csv_map.csv"]) {
                throw new Error("rule_csv_map.csv not in registry (sentinel CSV missing)");
            }

            H.log("  ", `Bootstrapped ${d.hashed_count} CSVs, ${d.missing_count} missing`);
        });

        // AD20: Bootstrap requires superadmin role
        await H.test("AD20 bootstrap_csv_hashes rejected for non-superadmin", async () => {
            const d = await H.restCall(adminPage, "POST", {
                action: "bootstrap_csv_hashes"
            });
            // wladmin1 has ADMIN_ROLES but not SUPERADMIN_ROLES
            if (!d.error) throw new Error("Expected RBAC rejection for admin role");
            if (!d.error.toLowerCase().includes("permission") &&
                !d.error.toLowerCase().includes("not authorized") &&
                !d.error.toLowerCase().includes("role")) {
                throw new Error("Unexpected error (expected permission): " + d.error);
            }
        });

        // AD21: Bootstrap is idempotent — running twice produces same result
        await H.test("AD21 bootstrap_csv_hashes is idempotent", async () => {
            const d1 = await H.restCall(superPage, "POST", {
                action: "bootstrap_csv_hashes"
            });
            if (d1.error) throw new Error("First bootstrap failed: " + d1.error);
            const reg1 = readHashRegistry();

            const d2 = await H.restCall(superPage, "POST", {
                action: "bootstrap_csv_hashes"
            });
            if (d2.error) throw new Error("Second bootstrap failed: " + d2.error);
            const reg2 = readHashRegistry();

            if (d1.hashed_count !== d2.hashed_count) {
                throw new Error(`Count mismatch: ${d1.hashed_count} vs ${d2.hashed_count}`);
            }

            // Compare hash values (excluding _checksum which may differ due to timing)
            const keys1 = Object.keys(reg1).filter(k => k !== "_checksum").sort();
            const keys2 = Object.keys(reg2).filter(k => k !== "_checksum").sort();
            if (JSON.stringify(keys1) !== JSON.stringify(keys2)) {
                throw new Error("Registry keys differ between runs");
            }
        });

        // AD22: Filesystem direct write detected by watcher
        // This test modifies a CSV via docker exec (simulating filesystem attack)
        // and verifies the stat-watcher detects the change.
        await H.test("AD22 Filesystem CSV write detected by integrity monitor", async () => {
            requireWatcher("AD22");
            // First ensure bootstrap is done so the watcher has expected hashes
            await H.restCall(superPage, "POST", { action: "bootstrap_csv_hashes" });
            await new Promise(r => setTimeout(r, 2000));

            // Pick a test CSV that exists
            const testCsv = "DR130_priv_escalation.csv";
            const csvPath = `${LOOKUPS_DIR}/${testCsv}`;

            // Record current content so we can restore it
            const origContent = dockerExec(["cat", csvPath]).stdout;

            // Tamper: append a rogue row via filesystem
            dockerExecStr(`echo 'ATTACKER_ROW,injected,data' >> ${csvPath}`);

            // Wait for detection (stat watcher runs every 2s)
            await new Promise(r => setTimeout(r, 4000));

            // Check for external modification event in audit index
            const events = splunkSearch(
                `index=wl_audit sourcetype=wl_fim action=fim_csv_external_modification csv_file="${testCsv}"`,
                "-2m"
            );

            // Restore original content
            dockerExecStr(`cat > ${csvPath} << 'RESTORE_EOF'\n${origContent}RESTORE_EOF`);
            // Re-bootstrap to update hash after restore
            await H.restCall(superPage, "POST", { action: "bootstrap_csv_hashes" });

            if (!events || events.length < 5) {
                throw new Error(
                    "Filesystem CSV tamper not detected within 6s. " +
                    "Is wl_fim_watch.py running? (check inputs.conf)"
                );
            }
        });

        // AD23: Hash registry tamper triggers fail-closed
        await H.test("AD23 Hash registry tamper causes fail-closed detection", async () => {
            requireWatcher("AD23");
            // Ensure clean bootstrap first
            await H.restCall(superPage, "POST", { action: "bootstrap_csv_hashes" });
            await new Promise(r => setTimeout(r, 1000));

            // Read current registry
            const reg = readHashRegistry();
            if (!reg || !reg._checksum) throw new Error("Registry not initialized");

            // Corrupt the HMAC checksum
            const corrupted = JSON.parse(JSON.stringify(reg));
            corrupted._checksum = "0".repeat(64);
            dockerExecStr(`cat > ${VERSIONS_DIR}/.csv_expected_hashes.json << 'CORRUPT_EOF'\n${JSON.stringify(corrupted, null, 2)}\nCORRUPT_EOF`);

            // Wait for the watcher to notice
            await new Promise(r => setTimeout(r, 4000));

            // Check for tamper event
            const events = splunkSearch(
                "index=wl_audit sourcetype=wl_fim action=fim_csv_hash_registry_tampered",
                "-2m"
            );

            // Restore the registry
            await H.restCall(superPage, "POST", { action: "bootstrap_csv_hashes" });

            if (!events || events.length < 5) {
                throw new Error(
                    "Hash registry tamper not detected (fail-closed). " +
                    "Expected fim_csv_hash_registry_tampered event."
                );
            }
        });

        // AD24: Legitimate handler save does NOT trigger external modification alert
        await H.test("AD24 Legitimate handler save does not trigger false alarm", async () => {
            requireWatcher("AD24");
            // Bootstrap first
            await H.restCall(superPage, "POST", { action: "bootstrap_csv_hashes" });
            await new Promise(r => setTimeout(r, 3000));

            // Clear any prior FIM events for our test rule
            const testRule = "DR130_privilege_escalation";
            const testCsv = "DR130_priv_escalation.csv";

            // Record the current time marker
            const timeMarker = new Date().toISOString().slice(0, 19);

            // Perform a legitimate save via the handler (as superadmin to bypass gates)
            const getd = await H.restCall(superPage, "GET", {
                action: "get_csv_content",
                csv_file: testCsv,
                detection_rule: testRule,
            });
            if (getd.error) throw new Error("Failed to get CSV: " + getd.error);

            const rows = getd.rows || [];
            // Save with no changes — this still updates the expected hash
            const saved = await H.restCall(superPage, "POST", {
                action: "save_csv",
                csv_file: testCsv,
                detection_rule: testRule,
                headers: getd.headers,
                rows: rows,
                expected_content_hash: getd.content_hash || "",
                comment: "AD24 no-change save test",
            });
            // no-change save may return no_changes or success
            if (saved.error) throw new Error("Legitimate save failed: " + saved.error);

            // Wait for one watcher cycle to pass
            await new Promise(r => setTimeout(r, 5000));

            // Search for external_modification events AFTER our save
            const falseAlarms = splunkSearch(
                `index=wl_audit sourcetype=wl_fim action=fim_csv_external_modification csv_file="${testCsv}"`,
                "-30s"
            );

            // Parse the search output — if we get results, it's a false alarm
            let hasResults = false;
            if (falseAlarms && falseAlarms.length > 10) {
                try {
                    const parsed = JSON.parse(falseAlarms);
                    if (parsed.results && parsed.results.length > 0) {
                        hasResults = true;
                    }
                } catch (e) {
                    // Non-JSON output with content = probably has results
                    if (!falseAlarms.includes("No matching events") &&
                        !falseAlarms.includes('"results":[]')) {
                        hasResults = true;
                    }
                }
            }

            if (hasResults) {
                throw new Error(
                    "False alarm: legitimate handler save triggered " +
                    "fim_csv_external_modification event"
                );
            }
        });

        // AD25: SPL outputlookup attack detected
        await H.test("AD25 SPL outputlookup bypass detected by integrity monitor", async () => {
            requireWatcher("AD25");
            // Bootstrap hashes
            await H.restCall(superPage, "POST", { action: "bootstrap_csv_hashes" });
            await new Promise(r => setTimeout(r, 3000));

            const testCsv = "DR130_priv_escalation.csv";
            const csvPath = `${LOOKUPS_DIR}/${testCsv}`;

            // Save original content for restore
            const origContent = dockerExec(["cat", csvPath]).stdout;

            // Simulate SPL outputlookup attack: use splunk CLI to run SPL
            // that writes directly to the lookup, bypassing the handler entirely
            const spl = `| makeresults | eval user="ATTACKER_SPL", src_ip="6.6.6.6" | outputlookup ${testCsv}`;
            dockerExecStr(
                `/opt/splunk/bin/splunk search '${spl}' -auth admin:Chang3d! 2>/dev/null`
            );

            // Wait for detection
            await new Promise(r => setTimeout(r, 4000));

            // Check for external modification alert
            const events = splunkSearch(
                `index=wl_audit sourcetype=wl_fim action=fim_csv_external_modification csv_file="${testCsv}"`,
                "-1m"
            );

            // Restore original CSV
            dockerExecStr(`cat > ${csvPath} << 'RESTORE_EOF'\n${origContent}RESTORE_EOF`);
            // Fix ownership after root write
            dockerExecStr(`chown splunk:splunk ${csvPath}`);
            // Re-bootstrap
            await H.restCall(superPage, "POST", { action: "bootstrap_csv_hashes" });

            if (!events || events.length < 5) {
                throw new Error(
                    "SPL outputlookup attack not detected within 6s. " +
                    "Expected fim_csv_external_modification event for " + testCsv
                );
            }
        });

        // AD26: Bootstrap emits audit event
        await H.test("AD26 bootstrap_csv_hashes emits audit trail event", async () => {
            const d = await H.restCall(superPage, "POST", {
                action: "bootstrap_csv_hashes"
            });
            if (d.error) throw new Error("Bootstrap failed: " + d.error);

            // Wait for audit event indexing
            await new Promise(r => setTimeout(r, 3000));

            const events = splunkSearch(
                "index=wl_audit action=bootstrap_csv_hashes",
                "-1m"
            );

            if (!events || events.length < 5) {
                throw new Error("Bootstrap audit event not found in wl_audit index");
            }
        });

        // AD27: Diff-aware bootstrap detects laundering attack
        await H.test("AD27 Diff-aware bootstrap detects CSV hash changes (anti-laundering)", async () => {
            // First bootstrap to establish a known baseline
            await H.restCall(superPage, "POST", { action: "bootstrap_csv_hashes" });

            // Tamper with a CSV via filesystem (simulating attacker)
            const testCsv = "DR130_priv_escalation.csv";
            const csvPath = `${LOOKUPS_DIR}/${testCsv}`;
            const origContent = dockerExec(["cat", csvPath]).stdout;
            dockerExecStr(`echo 'LAUNDERING_TEST,attack,data' >> ${csvPath}`);

            // Now bootstrap again — this should detect the hash change
            const d = await H.restCall(superPage, "POST", {
                action: "bootstrap_csv_hashes"
            });
            if (d.error) throw new Error("Bootstrap failed: " + d.error);

            // The response should report the changed CSV
            if (!d.changed_count || d.changed_count < 1) {
                // Restore and fail
                dockerExecStr(`cat > ${csvPath} << 'RESTORE_EOF'\n${origContent}RESTORE_EOF`);
                await H.restCall(superPage, "POST", { action: "bootstrap_csv_hashes" });
                throw new Error("Bootstrap did not detect hash change (changed_count: " +
                    d.changed_count + "). Laundering attack would succeed undetected.");
            }
            if (!d.changed_csvs || !d.changed_csvs.includes(testCsv)) {
                dockerExecStr(`cat > ${csvPath} << 'RESTORE_EOF'\n${origContent}RESTORE_EOF`);
                await H.restCall(superPage, "POST", { action: "bootstrap_csv_hashes" });
                throw new Error("Changed CSVs list doesn't include " + testCsv +
                    ": " + JSON.stringify(d.changed_csvs));
            }

            // Restore original and re-bootstrap
            dockerExecStr(`cat > ${csvPath} << 'RESTORE_EOF'\n${origContent}RESTORE_EOF`);
            dockerExecStr(`chown splunk:splunk ${csvPath}`);
            await H.restCall(superPage, "POST", { action: "bootstrap_csv_hashes" });

            // Verify the per-CSV audit event was emitted
            await new Promise(r => setTimeout(r, 3000));
            const auditEvents = splunkSearch(
                `index=wl_audit action=bootstrap_csv_hash_changed csv_file="${testCsv}"`,
                "-1m"
            );
            if (!auditEvents || auditEvents.length < 5) {
                throw new Error("Per-CSV bootstrap_csv_hash_changed audit event not found");
            }
        });

        // AD28: Auto-bootstrap creates registry on fresh install
        await H.test("AD28 Watcher auto-bootstraps when registry file is missing", async () => {
            // The auto-bootstrap happens at watcher startup, not mid-run.
            // We verify the code path exists by checking the watcher source
            // for the _bootstrap_registry_if_empty function call.
            const src = dockerExec(["cat",
                "/opt/splunk/etc/apps/wl_manager/bin/wl_fim_watch.py"]).stdout;
            if (!src.includes("_bootstrap_registry_if_empty")) {
                throw new Error("Auto-bootstrap function not found in watcher source");
            }
            if (!src.includes("_bootstrap_registry_if_empty()")) {
                throw new Error("Auto-bootstrap function not called at startup");
            }
            // Verify the function checks for file existence before writing
            if (!src.includes("os.path.isfile(EXPECTED_HASHES_FILE)")) {
                throw new Error("Auto-bootstrap doesn't check for existing registry");
            }
        });

        // ═══════════════════════════════════════════════════════════
        // Cleanup
        // ═══════════════════════════════════════════════════════════
        H.log("🧹", "Cleanup: restore cooldown state and remove test artifacts");
        resetCooldownState();
        // Prime a valid record so next test run starts fresh
        await H.restCall(superPage, "POST", {
            action: "set_admin_limits", limits: { csv_save: 20 }
        });
        // Remove test recovery log entries (keep the file but clean noise)
        dockerExecStr(`sed -i '/ADVERSARIAL_TEST_/d' ${VERSIONS_DIR}/_recovery_log.jsonl 2>/dev/null || true`);

    } catch (err) {
        H.log("💥", "Fatal error: " + err.message);
    } finally {
        for (const s of [analyst, wladmin, superadmin]) {
            if (s) { try { await s.browser.close(); } catch (e) {} }
        }
    }

    const s = H.summary("Adversarial Hardening Tests");
    process.exit(s.failed > 0 ? 1 : 0);
})();
