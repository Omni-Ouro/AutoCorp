/**
 * Verifier / site SDK (PROOF v0 §3.6) — TypeScript mirror of
 * verifier/python/verifier.py, same wire formats throughout.
 *
 * A site keeps its own copy: cached pubkeys, every receipt it has
 * received, last-seen score per agent. The clearinghouse is registry
 * and referee, never in the request path.
 */
import { randomBytes } from "node:crypto";

import { hashBytes, hashObj, recordHash } from "./canonical.js";
import { Identity, verifyB64 } from "./identity.js";

export const SESSION_TTL_MS = 900_000; // 15 min
export const REFUSAL_UNKNOWN = { error: "refused", reason: "PoT score unknown" };
export const REFUSAL_LOW = { error: "refused", reason: "PoT score below threshold" };
export const REFUSAL_NO_PASSPORT = { error: "refused", reason: "AI Passport required" };
export const REFUSAL_PASSPORT_REVOKED = { error: "refused", reason: "AI Passport revoked" };
export const REFUSAL_PAUSED = { error: "refused", reason: "Passport paused" };

export function utcNow(): string {
  return new Date().toISOString().slice(0, 19) + "Z";
}

async function requestJson(
  method: string,
  url: string,
  payload?: unknown,
): Promise<{ status: number | null; body: any }> {
  try {
    const resp = await fetch(url, {
      method,
      headers: { "Content-Type": "application/json" },
      body: payload !== undefined ? JSON.stringify(payload) : undefined,
      signal: AbortSignal.timeout(5000),
    });
    const text = await resp.text();
    let body: any = {};
    try {
      body = text ? JSON.parse(text) : {};
    } catch {
      body = {};
    }
    return { status: resp.status, body };
  } catch {
    return { status: null, body: {} }; // clearinghouse unreachable
  }
}

/** Offline check against the clearinghouse pubkey (§3.6). */
export function verifyReceipt(
  receipt: Record<string, any>,
  chPubkeyB64: string,
): boolean {
  try {
    const unsigned: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(receipt)) {
      if (k !== "ch_sig") unsigned[k] = v;
    }
    return verifyB64(
      Buffer.from(chPubkeyB64, "base64"),
      Buffer.from(recordHash(unsigned), "utf-8"),
      receipt.ch_sig ?? "",
    );
  } catch {
    return false;
  }
}

/** Signature, nonce, and 60s timestamp window (§4.6). */
export function verifyAttestation(
  att: Record<string, any>,
  expectedNonce: string,
  pubkeyRaw: Buffer,
  nowMs?: number,
): boolean {
  if (att.nonce !== expectedNonce) return false;
  const epoch = Date.parse(att.ts);
  if (Number.isNaN(epoch)) return false;
  if (Math.abs((nowMs ?? Date.now()) - epoch) > 60_000) return false;
  const unsigned: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(att)) {
    if (k !== "sig") unsigned[k] = v;
  }
  return verifyB64(pubkeyRaw, Buffer.from(recordHash(unsigned), "utf-8"), att.sig ?? "");
}

export function buildSiteReport(
  identity: Identity,
  opts: {
    recordHash: string;
    agentId: string;
    outcome: "fulfilled" | "declined";
    result: Buffer | string | Record<string, unknown> | null;
  },
): Record<string, unknown> {
  if (opts.outcome !== "fulfilled" && opts.outcome !== "declined") {
    throw new Error("outcome must be fulfilled|declined");
  }
  let resultHash: string;
  if (Buffer.isBuffer(opts.result)) resultHash = hashBytes(opts.result);
  else if (typeof opts.result === "string") resultHash = hashBytes(Buffer.from(opts.result));
  else if (opts.result === null) resultHash = hashBytes(Buffer.alloc(0));
  else resultHash = hashObj(opts.result);
  const report: Record<string, unknown> = {
    record_hash: opts.recordHash,
    agent_id: opts.agentId,
    site_id: identity.id,
    outcome: opts.outcome,
    result_hash: resultHash,
    ts: utcNow(),
  };
  report.sig = identity.sign(Buffer.from(recordHash(report), "utf-8"));
  return report;
}

export interface EyDSiteOptions {
  clearinghouseUrl: string;
  domain: string;
  minScore?: number | null;
  requirePassport?: boolean;
  callbackUrl?: string | null;
}

export class EyDSite {
  readonly identity: Identity;
  readonly clearinghouseUrl: string;
  readonly domain: string;
  readonly minScore: number | null;
  readonly requirePassport: boolean;
  readonly callbackUrl: string | null;
  readonly pubkeyCache = new Map<string, string>();
  readonly sessions = new Map<string, { agentId: string; expires: number }>();
  readonly nonces = new Map<string, number>();
  readonly receipts: any[] = [];
  readonly scores = new Map<string, number | null>();
  tamper = false;

  constructor(identity: Identity, opts: EyDSiteOptions) {
    this.identity = identity;
    this.clearinghouseUrl = opts.clearinghouseUrl.replace(/\/$/, "");
    this.domain = opts.domain;
    this.minScore = opts.minScore ?? null;
    this.requirePassport = opts.requirePassport ?? false;
    this.callbackUrl = opts.callbackUrl ?? null;
  }

  // -- registry -------------------------------------------------------

  async enroll(): Promise<void> {
    const payload: Record<string, unknown> = {
      kind: "site",
      site_id: this.identity.id,
      pubkey: this.identity.pubkeyB64,
      domain: this.domain,
      ts: utcNow(),
    };
    if (this.callbackUrl) payload.callback_url = this.callbackUrl;
    payload.sig = this.identity.sign(Buffer.from(recordHash(payload), "utf-8"));
    await requestJson("POST", `${this.clearinghouseUrl}/enroll`, payload);
  }

  async agentPubkey(agentId: string): Promise<Buffer | null> {
    const cached = this.pubkeyCache.get(agentId);
    if (cached) return Buffer.from(cached, "base64");
    const { status, body } = await requestJson(
      "GET",
      `${this.clearinghouseUrl}/agents/${agentId}`,
    );
    if (status === 200 && body.pubkey) {
      this.pubkeyCache.set(agentId, body.pubkey);
      return Buffer.from(body.pubkey, "base64");
    }
    return null; // unknown agent (or clearinghouse down + never seen)
  }

  async agentScore(agentId: string): Promise<number | null> {
    const { status, body } = await requestJson(
      "GET",
      `${this.clearinghouseUrl}/agents/${agentId}/score`,
    );
    if (status === 200) {
      this.scores.set(agentId, body.score ?? null);
      return body.score ?? null;
    }
    return this.scores.get(agentId) ?? null;
  }

  // -- attestation / sessions (§4.6) ----------------------------------

  newChallenge(): string {
    const nonce = randomBytes(24).toString("base64url");
    this.nonces.set(nonce, Date.now() + 300_000);
    return nonce;
  }

  async acceptAttestation(att: Record<string, any>): Promise<string | null> {
    const nonce = att.nonce ?? "";
    const expiry = this.nonces.get(nonce);
    if (expiry === undefined || expiry < Date.now()) return null;
    const pub = await this.agentPubkey(att.agent_id ?? "");
    if (pub === null || !verifyAttestation(att, nonce, pub)) return null;
    this.nonces.delete(nonce); // nonce is single-use
    return this.issueSession(att.agent_id);
  }

  issueSession(agentId: string): string {
    const token = randomBytes(32).toString("base64url");
    this.sessions.set(token, { agentId, expires: Date.now() + SESSION_TTL_MS });
    return token;
  }

  sessionAgent(token: string | null | undefined): string | null {
    if (!token) return null;
    const entry = this.sessions.get(token);
    if (!entry || entry.expires < Date.now()) return null;
    return entry.agentId;
  }

  /** Kill an agent's live sessions (revocation push notice). */
  dropSessions(agentId: string): number {
    let dropped = 0;
    for (const [token, entry] of this.sessions) {
      if (entry.agentId === agentId) {
        this.sessions.delete(token);
        dropped++;
      }
    }
    return dropped;
  }

  /** minScore per call overrides the site default (dynamic gates). */
  async scoreAllows(agentId: string, minScore?: number | null): Promise<boolean> {
    const threshold = minScore === undefined ? this.minScore : minScore;
    if (threshold === null) return true;
    const score = await this.agentScore(agentId);
    return score !== null && score >= threshold;
  }

  /** Combined-tier check: Passport standing, re-asked live. */
  async passportStatus(agentId: string): Promise<string> {
    const { status, body } = await requestJson(
      "GET",
      `${this.clearinghouseUrl}/agents/${agentId}/standing`,
    );
    if (status === 200) return body.passport_status ?? "unknown";
    return "unknown"; // fail closed: unable to tell
  }

  // -- reporting --------------------------------------------------------

  async report(
    recordHash_: string,
    agentId: string,
    outcome: "fulfilled" | "declined",
    result: Buffer | string | Record<string, unknown>,
  ): Promise<any | null> {
    const report = buildSiteReport(this.identity, {
      recordHash: recordHash_,
      agentId,
      outcome,
      result,
    });
    const { body } = await requestJson(
      "POST",
      `${this.clearinghouseUrl}/reports/site`,
      report,
    );
    const receipt = body?.receipt ?? null;
    if (receipt) this.receipts.push(receipt);
    return receipt;
  }
}
