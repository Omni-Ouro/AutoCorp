# Proof Format v0 — EyD

Records, reports, receipts, canonicalization, and attestation exchanged
between an EyD runtime, counterparty sites, and a clearinghouse.
Hashes of what was sent and received, plus who it was sent to — never
inputs, outputs, or tool arguments.

Canonicalization (§4.5): RFC 8785 (JSON Canonicalization Scheme) —
keys sorted by UTF-16 code unit, no whitespace, minimal string
escaping, ECMAScript number serialization, UTF-8. The wider Eyro
stack standardizes on RFC 8785, so EyD records hash identically
across implementations (`eyd/canonical.py`, vectors in
`tests/test_canonical.py`).

Encodings: hashes are `sha256:<hex>`; signatures are `ed25519:<base64>`
over the UTF-8 bytes of the corresponding `sha256:<hex>` hash string;
public keys are base64 of the 32-byte raw Ed25519 key.
`agent_id` / `site_id` = `base32(SHA-256(pubkey_raw))[:26]` (RFC 4648, uppercase, no padding).

## 4.1 Action Record (agent-signed, created before execution)

```json
{
  "eyd": "0.1", "agent_id": "…", "seq": 42, "prev_hash": "sha256:…",
  "ts": "2026-10-28T14:03:11Z", "verb": "send", "tool": "http.post",
  "input_hash": "sha256:…", "target": "quotes.eyd-required.example",
  "sig": "ed25519:…"
}
```

- `verb` ∈ `read | write | send | browse | execute | pay`; every tool maps to exactly one verb.
- `target` is the counterparty domain, a known `site_id`, or `local`.
- `record_hash` = SHA-256 of canonical JSON of all fields except `sig`. `sig` signs `record_hash`.
- `output_hash` is **not** in the record; it goes in the Agent Report, because the record is created and reported before execution.

## 4.2 Agent Report (agent-signed, after execution)

`{record_hash, output_hash, status, ts, sig}` — `status` ∈ `ok | error`. `sig` signs the canonical-hash of the unsigned report.

## 4.3 Site Report (site-signed)

`{record_hash, agent_id, site_id, outcome, result_hash, ts, sig}` — `outcome` ∈ `fulfilled | declined`. `result_hash` is the hash of the canonical response body **before** transfer encoding; the site also returns it as the `EyD-Result-Hash` header.

## 4.4 Proof Receipt (clearinghouse-signed)

`{record_hash, agent_id, site_id, classification, agent_hash, site_hash, ts, ch_sig}` — `site_id`/`site_hash` absent when Unverified. `ch_sig` signs the canonical-hash of the unsigned receipt. Verifiable offline against the clearinghouse pubkey.

## Classification

| Condition | Classification |
|---|---|
| Site `fulfilled` and `result_hash == output_hash` | **Expected** |
| Both reported; hashes differ or statuses conflict | **Unexpected** |
| Site `declined` | **Declined** |
| Window (10 min) closed with only one report | **Unverified** |

A late report upgrades Unverified and reissues the receipt. `target: local` actions are always Unverified and never affect the score.

PoT score = Expected ÷ (Expected + Unexpected + Declined), or `null` with fewer than **5** receipts (N=5, v0 default, configurable).

## 4.6 Attestation (challenge/response)

1. Site answers an unattested request `403` with body `{"error":"refused","reason":"PoT score unknown"}` and headers `EyD-Challenge: <nonce>`, `EyD-Clearinghouse: <url>`.
2. EyD sends `EyD-Attestation: <base64 json>` = `{agent_id, nonce, head_seq, head_hash, ts, sig}` (signed over the canonical-hash of the unsigned attestation).
3. Site verifies signature (local pubkey cache, else clearinghouse), nonce unused, `ts` within 60s; admits and returns `EyD-Session: <token>` (15 min).
4. Later requests carry `EyD-Session` and `EyD-Record`; re-attest on expiry, invisible to the agent.

Refusal bodies (the only thing an agent ever sees): `{"error":"refused","reason":"PoT score unknown"}`, `{"error":"refused","reason":"PoT score below threshold"}`, and at combined-tier sites (EyD + AI Passport, see AI_PASSPORT.md) `{"error":"refused","reason":"AI Passport required"}` or `{"error":"refused","reason":"AI Passport revoked"}`.

## Test vector (canonicalization)

Input object:

```json
{"b": 1, "a": "x"}
```

Canonical bytes: `{"a":"x","b":1}` — SHA-256:

```
cdab067e9f3beb32d1252cfd63e492592fecbf591b0d08cadb24bb17f3864246
```

So `hash_obj({"b":1,"a":"x"}) == "sha256:cdab067e9f3beb32d1252cfd63e492592fecbf591b0d08cadb24bb17f3864246"`. Verified in `tests/test_canonical.py`.

A second, full Action Record vector (fixed key, fixed ts) is generated and locked in `tests/test_records.py` once the demo keys are seeded.

## 4.7 Explicitly out of v0

Key rotation (except fork-recovery re-key signed by the old key), revocation, multi-clearinghouse, privacy of agent_id across sites, record content disclosure, dispute resolution on Unexpected.
