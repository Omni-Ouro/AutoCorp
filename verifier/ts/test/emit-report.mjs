/**
 * Emit a site report signed by the TypeScript SDK (fixture site seed)
 * as JSON on stdout. tests/test_ts_verifier_interop.py verifies the
 * signature with the Python implementation — the reverse direction of
 * fixtures.json.
 */
import { readFileSync } from "node:fs";

import { Identity, buildSiteReport } from "../dist/index.js";

const fixtures = JSON.parse(
  readFileSync(new URL("./fixtures.json", import.meta.url), "utf-8"),
);
const site = Identity.fromSeed(
  Buffer.from(fixtures.site.seed_b64, "base64"),
  "site",
);
const report = buildSiteReport(site, {
  recordHash: "sha256:" + "ab".repeat(32),
  agentId: fixtures.agent.id,
  outcome: "fulfilled",
  result: Buffer.from("hello"),
});
process.stdout.write(JSON.stringify(report));
