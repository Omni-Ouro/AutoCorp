# Verifier / site SDK

Python first (`python/`), TypeScript if time (`ts/`).

- `verify_attestation(att, nonce)` — signature against the agent's pubkey (local cache, else clearinghouse).
- `issue_session(agent_id)` — 15-min token bound to `agent_id`.
- `report(record_hash, agent_id, outcome, result_hash)` — signs and posts the site report; also returns `EyD-Result-Hash`.
- `verify_receipt(receipt)` — offline check against clearinghouse pubkey.
- `require_eyd(handler, min_score=None)` — challenge/session, attestation, optional score gate, report. Two lines for a site developer.

The site keeps its own copy (cached pubkeys, receipts, scores). The
clearinghouse is registry and referee, never in the request path.
