#!/usr/bin/env node
import { homedir } from "node:os";
import { join } from "node:path";
import { loadConfig } from "@coderails/dashboard-lib";
import { sweepOnce } from "./sweep.ts";

const BASE_DIR = join(homedir(), ".claude", "coderails-dashboard");

async function main(): Promise<void> {
  const config = loadConfig();
  const result = await sweepOnce({
    queueDir: join(BASE_DIR, "queue"),
    processingDir: join(BASE_DIR, "processing"),
    archiveDir: join(BASE_DIR, "archive"),
    quarantineDir: join(BASE_DIR, "quarantine"),
    config,
    runsDir: join(BASE_DIR, "runs"),
    vaultNotesDir: config.wikiPaths[0] ? join(config.wikiPaths[0], "dashboard-runs") : undefined,
  });
  console.log(
    `Sweep complete: ${result.claimed} claimed, ${result.succeeded} succeeded, ${result.failed} failed, ${result.quarantined} quarantined`
  );
  process.exit(result.failed > 0 ? 1 : 0);
}

main().catch((err) => {
  console.error("Sweep failed with an uncaught error:", err);
  process.exit(1);
});
