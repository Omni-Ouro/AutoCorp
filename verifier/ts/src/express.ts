/**
 * Express middleware: the whole EyD gate in one line.
 *
 *   import { eydGate } from "eyd-verifier/express";
 *   app.post("/pay", eydGate(site, { minScore: 0.8 }), handler);
 *
 * Handles the §4.6 challenge/attestation handshake, sessions, the
 * per-action PoT score gate, Passport standing, refusal reporting, and
 * the fulfilled report once the handler responds. On success the
 * agent's id is on `req.eydAgent`. A session authenticates the agent;
 * the gate for *this* action is checked on every request, so a session
 * minted at a weaker gate never elevates.
 *
 * Types are structural — no Express dependency; works with Express 4/5
 * and anything with the same req/res shape.
 */
import {
  EyDSite,
  REFUSAL_LOW,
  REFUSAL_PASSPORT_REVOKED,
  REFUSAL_PAUSED,
  REFUSAL_UNKNOWN,
} from "./verifier.js";

export interface EyDGateOptions {
  /** PoT threshold for this action; null/omitted = EyD required, any score. */
  minScore?: number | null;
  /** false = open action; EyD agents that show up still get receipts. */
  eydRequired?: boolean;
  /** Observability hook (the playground board uses it). */
  onEvent?: (agentId: string | null, result: string) => void;
}

export interface EyDRequestLike {
  headers: Record<string, string | string[] | undefined>;
  eydAgent?: string | null;
  [key: string]: unknown;
}

export interface EyDResponseLike {
  status(code: number): EyDResponseLike;
  json(body: unknown): unknown;
  send(body?: unknown): unknown;
  setHeader(name: string, value: string): unknown;
  [key: string]: unknown;
}

function header(req: EyDRequestLike, name: string): string | undefined {
  const v = req.headers[name.toLowerCase()];
  return Array.isArray(v) ? v[0] : v;
}

export function eydGate(site: EyDSite, opts: EyDGateOptions = {}) {
  const minScore = opts.minScore ?? null;
  const eydRequired = opts.eydRequired ?? true;

  return async (
    req: EyDRequestLike,
    res: EyDResponseLike,
    next: (err?: unknown) => void,
  ): Promise<void> => {
    const recordHash = header(req, "EyD-Record");
    let agentId: string | null = header(req, "EyD-Agent") ?? null;
    let sessionToken: string | null = null;

    const refuse = async (reason: Record<string, string>, challenge = false) => {
      if (recordHash && agentId) {
        await site
          .report(recordHash, agentId, "declined", Buffer.from(JSON.stringify(reason)))
          .catch(() => {});
      }
      opts.onEvent?.(agentId, `refused: ${reason.reason}`);
      if (challenge) {
        res.setHeader("EyD-Challenge", site.newChallenge());
        res.setHeader("EyD-Clearinghouse", site.clearinghouseUrl);
      }
      res.status(403).json(reason);
    };

    const wrapSendForReport = () => {
      let reported = false;
      const capture = (body: unknown) => {
        if (reported || !recordHash || !agentId) return;
        reported = true;
        const bytes = Buffer.isBuffer(body)
          ? body
          : Buffer.from(typeof body === "string" ? body : JSON.stringify(body ?? ""));
        void site
          .report(recordHash, agentId, "fulfilled", bytes)
          .catch(() => {});
        opts.onEvent?.(agentId, "admitted");
      };
      const origSend = res.send.bind(res);
      const origJson = res.json.bind(res);
      res.send = (body?: unknown) => {
        capture(body);
        return origSend(body);
      };
      res.json = (body: unknown) => {
        capture(body);
        return origJson(body);
      };
    };

    try {
      if (!eydRequired) {
        req.eydAgent = site.sessionAgent(header(req, "EyD-Session")) ?? agentId;
        agentId = req.eydAgent;
        wrapSendForReport();
        return next();
      }

      const sessionAgent = site.sessionAgent(header(req, "EyD-Session"));
      if (sessionAgent) {
        agentId = sessionAgent;
      } else if (header(req, "EyD-Attestation")) {
        let att: Record<string, any> = {};
        try {
          att = JSON.parse(
            Buffer.from(header(req, "EyD-Attestation")!, "base64").toString("utf-8"),
          );
        } catch {
          att = {};
        }
        agentId = att.agent_id ?? null;
        const token = att.agent_id ? await site.acceptAttestation(att) : null;
        if (token === null) return refuse(REFUSAL_UNKNOWN, true);
        sessionToken = token;
      } else {
        return refuse(REFUSAL_UNKNOWN, true);
      }

      // Per-action policy, checked on every gated request.
      if (!(await site.scoreAllows(agentId!, minScore))) {
        const score = site.scores.get(agentId!) ?? null;
        return refuse(score === null ? REFUSAL_UNKNOWN : REFUSAL_LOW);
      }
      const passport = agentId ? await site.passportStatus(agentId) : "unknown";
      if (passport === "revoked" || passport === "paused") {
        return refuse(
          passport === "revoked" ? REFUSAL_PASSPORT_REVOKED : REFUSAL_PAUSED,
        );
      }

      req.eydAgent = agentId;
      if (sessionToken) res.setHeader("EyD-Session", sessionToken);
      wrapSendForReport();
      return next();
    } catch (err) {
      return next(err);
    }
  };
}
