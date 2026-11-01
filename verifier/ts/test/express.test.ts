/**
 * eydGate middleware: session identity must not elevate the gate, the
 * admitted agent lands on req.eydAgent, and sends are reported.
 */
import assert from "node:assert";
import test from "node:test";

import { Identity } from "../dist/index.js";
import { eydGate } from "../dist/express.js";

function fakeSite(overrides = {}) {
  return {
    clearinghouseUrl: "http://127.0.0.1:9",
    scores: new Map([["AGENT1", null]]),
    reports: [],
    newChallenge: () => "nonce-1",
    sessionAgent: (t) => (t === "sess-1" ? "AGENT1" : null),
    acceptAttestation: async () => null,
    scoreAllows: async () => false,
    passportStatus: async () => "valid",
    async report(rh, aid, outcome) {
      this.reports.push([rh, aid, outcome]);
      return { classification: "Expected" };
    },
    ...overrides,
  };
}

function fakeRes() {
  return {
    statusCode: 200,
    headers: {},
    body: undefined,
    status(code) { this.statusCode = code; return this; },
    setHeader(k, v) { this.headers[k] = v; return this; },
    json(b) { this.body = b; return this; },
    send(b) { this.body = b; return this; },
  };
}

const HEADERS = {
  "eyd-session": "sess-1",
  "eyd-record": "sha256:" + "ab".repeat(32),
  "eyd-agent": "AGENT1",
};

test("eydGate: session does not elevate past the score gate", async () => {
  const site = fakeSite();
  const req = { headers: { ...HEADERS } };
  const res = fakeRes();
  let nextCalled = false;
  await eydGate(site, { minScore: 0.8 })(req, res, () => { nextCalled = true; });
  assert.equal(nextCalled, false);
  assert.equal(res.statusCode, 403);
  assert.equal(res.body.reason, "PoT score unknown");
  assert.deepEqual(site.reports.map((r) => r[2]), ["declined"]);
});

test("eydGate: admitted agent is attached and sends are reported", async () => {
  const site = fakeSite({ scoreAllows: async () => true });
  const req = { headers: { ...HEADERS } };
  const res = fakeRes();
  let nextCalled = false;
  await eydGate(site, { minScore: 0.8 })(req, res, () => { nextCalled = true; });
  assert.equal(nextCalled, true);
  assert.equal(req.eydAgent, "AGENT1");
  res.json({ status: "paid" });
  assert.deepEqual(site.reports.map((r) => r[2]), ["fulfilled"]);
});

test("eydGate: no attestation gets a challenge", async () => {
  const site = fakeSite();
  const req = { headers: { "eyd-agent": "AGENT1" } };
  const res = fakeRes();
  await eydGate(site, { minScore: 0.8 })(req, res, () => {
    throw new Error("next must not be called");
  });
  assert.equal(res.statusCode, 403);
  assert.equal(res.headers["EyD-Challenge"], "nonce-1");
  assert.equal(res.headers["EyD-Clearinghouse"], site.clearinghouseUrl);
});

test("identity import used by consumers resolves", () => {
  assert.ok(Identity.generate().id.length === 26);
});
