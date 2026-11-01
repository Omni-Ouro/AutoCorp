/**
 * Cross-implementation tests: fixtures.json was produced by the Python
 * SDK (test/gen_fixtures.py), so everything Python-signed must verify
 * here, and every hash must match byte-for-byte.
 */
import assert from "node:assert";
import { readFileSync } from "node:fs";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import {
  EyDSite,
  Identity,
  buildSiteReport,
  canonicalJson,
  hashBytes,
  hashObj,
  recordHash,
  verifyAttestation,
  verifyB64,
  verifyReceipt,
} from "../dist/index.js";

const fixtures = JSON.parse(
  readFileSync(new URL("./fixtures.json", import.meta.url), "utf-8"),
);

// -- canonicalization (vectors shared with tests/test_canonical.py) ---

test("canonical: spec vector", () => {
  assert.equal(canonicalJson({ b: 1, a: "x" }), '{"a":"x","b":1}');
  assert.equal(
    hashObj({ b: 1, a: "x" }),
    "sha256:cdab067e9f3beb32d1252cfd63e492592fecbf591b0d08cadb24bb17f3864246",
  );
});

test("canonical: ECMAScript number formatting", () => {
  const cases: [number, string][] = [
    [1e20, "100000000000000000000"],
    [1e21, "1e+21"],
    [1e30, "1e+30"],
    [1e-6, "0.000001"],
    [1e-7, "1e-7"],
    [4.5, "4.5"],
    [2e-3, "0.002"],
    [333333333.33333329, "333333333.3333333"],
    [1.0, "1"],
    [-0.0, "0"],
    [0, "0"],
    [-42, "-42"],
    [9007199254740991, "9007199254740991"],
  ];
  for (const [value, expected] of cases) {
    assert.equal(canonicalJson(value), expected, String(value));
  }
});

test("canonical: RFC 8785 sample and UTF-16 key order", () => {
  const obj = {
    numbers: [333333333.33333329, 1e30, 4.5, 2e-3, 1e-27],
    string: "€$\u000f\nA'B\"\\/",
    literals: [null, true, false],
  };
  assert.equal(
    canonicalJson(obj),
    '{"literals":[null,true,false],"numbers":[333333333.3333333,1e+30,4.5,0.002,1e-27],"string":"€$\\u000f\\nA\'B\\"\\\\/"}',
  );
  // U+10000 (UTF-16: D800 DC00) sorts before U+E000.
  assert.equal(
    canonicalJson({ "": 1, "\u{10000}": 2 }),
    '{"\u{10000}":2,"":1}',
  );
});

// -- identity ----------------------------------------------------------

test("identity: Python seed derives the same id and pubkey", () => {
  const ident = Identity.fromSeed(
    Buffer.from(fixtures.agent.seed_b64, "base64"),
  );
  assert.equal(ident.id, fixtures.agent.id);
  assert.equal(ident.pubkeyB64, fixtures.agent.pubkey_b64);
});

test("identity: save/load roundtrip in the Python file format", () => {
  const path = join(tmpdir(), `eyd-ts-test-${process.pid}.json`);
  const ident = Identity.generate("site");
  ident.save(path);
  const loaded = Identity.load(path);
  assert.equal(loaded.id, ident.id);
  assert.equal(loaded.kind, "site");
});

// -- Python-signed material verifies here ------------------------------

test("attestation: Python-signed attestation verifies", () => {
  const att = fixtures.attestation;
  const pub = Buffer.from(fixtures.agent.pubkey_b64, "base64");
  const now = Date.parse("2026-01-01T00:00:30Z");
  assert.equal(verifyAttestation(att, "fixture-nonce", pub, now), true);
  assert.equal(verifyAttestation(att, "other-nonce", pub, now), false);
  assert.equal(
    verifyAttestation(att, "fixture-nonce", pub, now + 120_000),
    false,
  );
});

test("site report: Python signature verifies", () => {
  const report = fixtures.site_report;
  const ok = verifyB64(
    Buffer.from(fixtures.site.pubkey_b64, "base64"),
    Buffer.from(recordHash(report), "utf-8"),
    report.sig,
  );
  assert.equal(ok, true);
});

test("site report: expectation_match rides along, signed", () => {
  const site = Identity.fromSeed(
    Buffer.from(fixtures.site.seed_b64, "base64"), "site");
  const report = buildSiteReport(site, {
    recordHash: "sha256:" + "ab".repeat(32),
    agentId: fixtures.agent.id,
    outcome: "fulfilled",
    result: "hello",
    expectationMatch: false,
  });
  assert.equal(report.expectation_match, false);
  const ok = verifyB64(
    Buffer.from(fixtures.site.pubkey_b64, "base64"),
    Buffer.from(recordHash(report), "utf-8"),
    report.sig as string,
  );
  assert.equal(ok, true);
});

test("receipt: Python-signed receipt verifies offline", () => {
  assert.equal(verifyReceipt(fixtures.receipt, fixtures.ch_pubkey_b64), true);
  const tampered = { ...fixtures.receipt, classification: "Declined" };
  assert.equal(verifyReceipt(tampered, fixtures.ch_pubkey_b64), false);
});

// -- EyDSite behavior against a stub clearinghouse ----------------------

test("sessions: drop kills only that agent", () => {
  const site = new EyDSite(Identity.generate("site"), {
    clearinghouseUrl: "http://127.0.0.1:9",
    domain: "example.com",
  });
  const t1 = site.issueSession("AGENT1");
  const t2 = site.issueSession("AGENT2");
  assert.equal(site.dropSessions("AGENT1"), 1);
  assert.equal(site.sessionAgent(t1), null);
  assert.equal(site.sessionAgent(t2), "AGENT2");
});

test("EyDSite end-to-end against stub clearinghouse", async () => {
  const agent = Identity.fromSeed(
    Buffer.from(fixtures.agent.seed_b64, "base64"),
  );
  let captured: any = null;
  const server = createServer((req, res) => {
    let body = "";
    req.on("data", (c) => (body += c));
    req.on("end", () => {
      res.setHeader("Content-Type", "application/json");
      if (req.url === `/agents/${agent.id}`) {
        res.end(JSON.stringify({ pubkey: agent.pubkeyB64 }));
      } else if (req.url === `/agents/${agent.id}/score`) {
        res.end(JSON.stringify({ score: 0.9 }));
      } else if (req.url === "/reports/site") {
        captured = JSON.parse(body);
        res.end(JSON.stringify({ receipt: { classification: "Expected" } }));
      } else {
        res.statusCode = 404;
        res.end("{}");
      }
    });
  });
  await new Promise<void>((r) => server.listen(0, "127.0.0.1", r));
  const port = (server.address() as any).port;
  try {
    const site = new EyDSite(Identity.generate("site"), {
      clearinghouseUrl: `http://127.0.0.1:${port}`,
      domain: "example.com",
    });

    // Attestation: agent signs the challenge exactly as the Python SDK does.
    const nonce = site.newChallenge();
    const att: Record<string, unknown> = {
      agent_id: agent.id,
      nonce,
      head_seq: 7,
      head_hash: "sha256:" + "00".repeat(32),
      ts: new Date().toISOString().slice(0, 19) + "Z",
    };
    att.sig = agent.sign(Buffer.from(recordHash(att), "utf-8"));
    const token = await site.acceptAttestation(att);
    assert.ok(token);
    assert.equal(site.sessionAgent(token), agent.id);
    assert.equal(await site.acceptAttestation(att), null); // nonce spent

    // Score gate.
    assert.equal(await site.scoreAllows(agent.id, 0.8), true);
    assert.equal(await site.scoreAllows(agent.id, 0.95), false);

    // Reporting: receipt comes back and the signature is genuine.
    const receipt = await site.report("sha256:" + "ab".repeat(32), agent.id,
                                      "fulfilled", Buffer.from("hello"));
    assert.equal(receipt.classification, "Expected");
    assert.equal(captured.result_hash, hashBytes(Buffer.from("hello")));
    assert.equal(
      verifyB64(
        site.identity.pubkeyRaw,
        Buffer.from(recordHash(captured), "utf-8"),
        captured.sig,
      ),
      true,
    );
  } finally {
    server.close();
  }
});
