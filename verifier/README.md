# Verifier / site SDK

Two implementations, one wire format — Python (`python/`) and
TypeScript (`ts/`, for Node/Express sites). Identity files and
signatures are cross-compatible; both test suites prove it against
shared fixtures.

- `verify_attestation(att, nonce)` — signature against the agent's pubkey (local cache, else clearinghouse).
- `issue_session(agent_id)` — 15-min token bound to `agent_id`.
- `report(record_hash, agent_id, outcome, result_hash)` — signs and posts the site report; also returns `EyD-Result-Hash`.
- `verify_receipt(receipt)` — offline check against clearinghouse pubkey.
- Turnkey gates: `gated(site, ...)` for FastAPI (`python/fastapi_integration.py`), `eydGate(site, ...)` for Express (`ts/src/express.ts`) — challenge/session, attestation, score gate, Passport standing, refusal + fulfilled reporting in one decorator/middleware.

The site keeps its own copy (cached pubkeys, receipts, scores). The
clearinghouse is registry and referee, never in the request path.
