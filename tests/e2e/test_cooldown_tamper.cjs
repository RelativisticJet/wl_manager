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
 * Cooldown Tamper Protection Tests (KV-store backed, build 552+)
 *
 * Verifies that deleting or corrupting the wl_cooldowns KV store
 * record triggers fail-closed mode, and that recovery via
 * reset_cooldowns.sh restores normal operation.
 */
const H = require("./lib_helpers.cjs");
const { execSync } = require("child_process");

// Fail fast if the test harness env var is not set or the test
// container is missing. Every KV/filesystem mutation below is
// destructive; the gate prevents an accidental production run.
H.assertTestHarness();

const CONTAINER = H.EXPECTED_TEST_CONTAINER;
const INIT_MARKER = "/opt/splunk/etc/apps/wl_manager/lookups/_versions/.cooldown_initialized";
const TAMPER_FLAG  = "/opt/splunk/etc/apps/wl_manager/lookups/_versions/.cooldown_tamper";

function dockerExecRaw(args) {
    // args: array of docker-exec command tokens after container name
    const spawnSync = require("child_process").spawnSync;
    const res = spawnSync("docker", ["exec", "-u", "0", CONTAINER, ...args], {
        env: { ...process.env, MSYS_NO_PATHCONV: "1" },
        encoding: "utf8",
    });
    return (res.stdout || "") + (res.stderr || "");
}

function kvGet() {
    const out = dockerExecRaw([
        "curl", "-s", "-k", "-u", "admin:Chang3d!",
        "https://localhost:8089/servicesNS/nobody/wl_manager/storage/collections/data/wl_cooldowns/state?output_mode=json",
    ]).trim();
    if (!out || out.includes("Could not find object")) return "";
    return out;
}

function kvDelete() {
    dockerExecRaw([
        "curl", "-s", "-k", "-u", "admin:Chang3d!", "-X", "DELETE",
        "https://localhost:8089/servicesNS/nobody/wl_manager/storage/collections/data/wl_cooldowns/state",
    ]);
}

function kvCorruptByInsert() {
    // Always delete first, then insert a forged record via the
    // collection endpoint (POST /wl_cooldowns). Trying to UPDATE a
    // missing record returns "Could not find object" in Splunk.
    kvDelete();
    const body = JSON.stringify({
        _key: "state",
        payload: JSON.stringify({ "admin_limit_changes:2099-01-01": 999 }),
        checksum: "deadbeef",
        updated_at: 1,
        updated_by: "attacker",
    });
    dockerExecRaw([
        "curl", "-s", "-k", "-u", "admin:Chang3d!", "-X", "POST",
        "-H", "Content-Type: application/json",
        "-d", body,
        "https://localhost:8089/servicesNS/nobody/wl_manager/storage/collections/data/wl_cooldowns",
    ]);
}

function kvReinsertClean() {
    kvDelete();
    const body = JSON.stringify({
        _key: "state",
        payload: "{}",
        checksum: "attacker",
        updated_at: 0,
        updated_by: "attacker",
    });
    dockerExecRaw([
        "curl", "-s", "-k", "-u", "admin:Chang3d!", "-X", "POST",
        "-H", "Content-Type: application/json",
        "-d", body,
        "https://localhost:8089/servicesNS/nobody/wl_manager/storage/collections/data/wl_cooldowns",
    ]);
}

function resetAllCooldownState() {
    kvDelete();
    dockerExecRaw(["rm", "-f", TAMPER_FLAG, INIT_MARKER]);
}

(async () => {
    let superSession, superPage;

    async function newSuperSession() {
        if (superSession) {
            try { await superSession.browser.close(); } catch (e) {}
        }
        superSession = await H.createSession("superadmin1", "Chang3d!");
        superPage = superSession.page;
    }

    try {
        H.log("🔧", "Setting up clean state (KV record + marker + tamper flag cleared)...");
        resetAllCooldownState();
        await new Promise(r => setTimeout(r, 500));
        await newSuperSession();

        // ═══════════════════════════════════════════════════════════
        await H.test("CT01 Normal operation: set_admin_limits succeeds", async () => {
            const d = await H.restCall(superPage, "POST", {
                action: "set_admin_limits",
                limits: { csv_save: 19 }
            });
            if (d.error) throw new Error("Expected success, got: " + d.error);
        });

        await H.test("CT02 KV record exists with HMAC checksum", async () => {
            const record = kvGet();
            if (!record || !record.includes("checksum")) {
                throw new Error("KV record missing or lacks checksum: " + record.substring(0, 200));
            }
            if (!record.includes("payload")) {
                throw new Error("KV record lacks payload field: " + record.substring(0, 200));
            }
        });

        // ═══════════════════════════════════════════════════════════
        // SECTION: KV deletion triggers fail-closed
        // ═══════════════════════════════════════════════════════════

        await H.test("CT03 Deleting KV record after init triggers fail-closed", async () => {
            kvDelete();
            await new Promise(r => setTimeout(r, 500));

            const d = await H.restCall(superPage, "POST", {
                action: "set_admin_limits",
                limits: { csv_save: 18 }
            });
            if (!d.error || !d.error.includes("Security lockdown")) {
                throw new Error(
                    "Expected Security lockdown error, got: " +
                    JSON.stringify(d).substring(0, 200));
            }
        });

        await H.test("CT04 Tamper flag persists — reinserting KV record does not recover", async () => {
            // Even if an attacker re-inserts a "clean" empty KV record,
            // the on-disk tamper flag must keep blocking until recovery.
            kvReinsertClean();
            await new Promise(r => setTimeout(r, 500));
            const d = await H.restCall(superPage, "POST", {
                action: "set_admin_limits",
                limits: { csv_save: 17 }
            });
            if (!d.error || !d.error.includes("Security lockdown")) {
                throw new Error(
                    "Tamper flag should persist after reinsert, got: " +
                    JSON.stringify(d).substring(0, 200));
            }
        });

        // ═══════════════════════════════════════════════════════════
        // SECTION: Recovery clears tamper flag
        // ═══════════════════════════════════════════════════════════

        await H.test("CT05 Recovery (tamper flag + init marker + KV cleared) resumes operations", async () => {
            resetAllCooldownState();
            await new Promise(r => setTimeout(r, 500));

            const d = await H.restCall(superPage, "POST", {
                action: "set_admin_limits",
                limits: { csv_save: 20 }
            });
            if (d.error) {
                throw new Error("Should resume after recovery: " + d.error);
            }
        });

        // ═══════════════════════════════════════════════════════════
        // SECTION: HMAC corruption triggers fail-closed
        // ═══════════════════════════════════════════════════════════

        await H.test("CT06 KV record with forged HMAC triggers fail-closed", async () => {
            // Reset state first so CT06 starts from a known-good position
            resetAllCooldownState();
            // Prime a valid KV record + marker
            const prime = await H.restCall(superPage, "POST", {
                action: "set_admin_limits",
                limits: { csv_save: 15 }
            });
            if (prime.error) throw new Error("Prime failed: " + prime.error);
            // Now inject a forged record (attacker overwrites the KV row
            // via direct API — they have the KV endpoint but not the
            // runtime HMAC key so they cannot forge a valid checksum)
            kvCorruptByInsert();
            await new Promise(r => setTimeout(r, 500));

            const d = await H.restCall(superPage, "POST", {
                action: "set_admin_limits",
                limits: { csv_save: 16 }
            });
            if (!d.error || !d.error.includes("Security lockdown")) {
                throw new Error(
                    "Expected Security lockdown for forged HMAC, got: " +
                    JSON.stringify(d).substring(0, 200));
            }
        });

        // ═══════════════════════════════════════════════════════════
        // Cleanup — restore clean state for other tests
        // ═══════════════════════════════════════════════════════════
        H.log("🧹", "Restoring clean state...");
        resetAllCooldownState();

    } catch (err) {
        H.log("💥", "Fatal error: " + err.message);
    } finally {
        if (superSession) {
            try { await superSession.browser.close(); } catch (e) {}
        }
    }

    const s = H.summary("Cooldown Tamper Protection Tests (KV-store)");
    process.exit(s.failed > 0 ? 1 : 0);
})();
