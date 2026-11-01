# EyD and AI Passport

## Timeline

The EyD idea came before AI Passport was published, and independently of it.

- **Early October 2026:** EyD framed as a framework-neutral agent credential: each agent gets its own Ed25519 key, and every action is recorded under it.
- **October 20, 2026:** the PoT Clearinghouse named and its business model written up.
- **October 22, 2026:** ServiceNow published AI Passport as an open draft specification.
- **October 26, 2026:** EyD build started, from zero code, at the start of the Meta hackathon.
- **October 27, 2026:** we found AI Passport, read the spec and ran its conformance self-test, which passed. By then the EyD build was already planned and underway.

The EyD idea came first, and nothing in its design came from AI Passport. This document records how the two fit together now that both exist.

## What AI Passport is

An open draft spec from ServiceNow (github.com/ServiceNow/ai-passport). It has two parts:

- **AI Passport v1:** a signed JSON record about an AI asset. It holds identity bindings and business context: the accountable owner and manager, vendor, risk classification and purpose, along with validity and revision.
- **Revocation Check v1:** one HTTP call that answers whether the asset may still act.

Every rule fails closed. If a verifier can't verify something, or can't get an answer, it denies.

The specifications are under the Community Specification License 1.0 and the code and test data are under Apache 2.0, so EyD can implement it royalty-free.

## How EyD relates to it

AI Passport answers "may this agent act." EyD answers "did this agent do what it claimed."

The spec leaves the following out on purpose. Each is EyD's job:

| Gap in AI Passport | Where in the spec | What EyD does |
|---|---|---|
| Holder binding: proving the presenter is the agent the Passport describes | §12, open question 4 | The agent's own Ed25519 key signs every action |
| A record of what the agent did once allowed through | Out of scope | Each action is reported to the PoT Clearinghouse before it runs and paired with the counterparty's report after |
| Provenance: where each value came from | §12, open question 7 | Later |
| Constraints on what an agent may do | Planned for a later version | Out of scope for EyD; this is Eyro's job |

The PoT Clearinghouse reads AI Passports, so a Passport becomes another option alongside EyD. An agent can come to the clearinghouse with EyD, with a Passport, or with both, and the two don't compete.

## Acceptance policy

A Passport is an identity credential. It is not evidence of behavior, and **by default a Passport alone does not admit an agent to a gated action** — the same way a person needs both a passport and a license in certain instances. The passport proves who you are; the license proves you're proven for the activity. For agents:

| Presented | What it proves | Default |
|---|---|---|
| Passport alone | Issuer-attested identity, owner, risk context, revocation status. No holder binding, no record of any action | **Not sufficient** for gated actions |
| EyD alone | Every action signed under the agent's own key, chained, paired with the counterparty's report; PoT score earned from that record | Sufficient for EyD-gated sites today |
| Passport + EyD | The Passport's identity matched to the EyD agent key at the clearinghouse, plus the full signed action record | Highest assurance; required wherever a site demands both |

Combined, you have undeniable proof of an agent's identity along with proof of its trust, based on a hashed record of what it actually did. Neither half substitutes for the other.

This makes the clearinghouse more necessary, not less: something has to check Passport status *and* PoT standing together, at action time, and deny when either is wrong or unknown. That referee is the clearinghouse. The Passport spec's gateway check even needs an authenticated identity to match the Passport against (its step 4) — EyD's per-agent key is exactly that binding.

## Crypto alignment

| | AI Passport | EyD |
|---|---|---|
| Canonical form | RFC 8785 (JCS) | RFC 8785 (JCS) |
| Hash | SHA-256 | SHA-256 |
| Signature | ES256 detached JWS (RFC 7515) | Ed25519 |
| Keys | JWKS | Per-agent Ed25519 key |

EyD keeps Ed25519 for its own action records. The clearinghouse's Passport check uses ES256 with JWKS, as the spec requires.

The shared canonical form is not a coincidence to note in passing: Eyro as a whole already depends on RFC 8785, so EyD's canonicalization implements RFC 8785 exactly (ECMAScript number serialization, UTF-16 key order). EyD records, Passport references, and Eyro governance artifacts can therefore be hashed and cross-referenced in one pipeline with no translation layer.

## Hackathon scope

1. The clearinghouse reads AI Passport as an option alongside EyD. When an agent presents a Passport, the clearinghouse runs AI Passport's six-step gateway check:
   1. Fetch the Passport.
   2. Verify the signature.
   3. Check that it's current.
   4. Match it to the authenticated identity.
   5. Check revocation.
   6. Deny on anything wrong or unknown.
2. A refused agent's reason can cite a missing or revoked Passport, alongside "unknown PoT score."
3. Run ServiceNow's published test vectors against the clearinghouse's Passport check, unmodified.
4. The demo site checks a presented Passport alongside EyD: EyD with a revoked Passport is refused, and revocation is pushed to the site so live sessions die immediately.

## Status (2026-10-28)

Items 1–4 are built, not planned:

- Clearinghouse: `POST /agents/{id}/passport` runs the full gateway check (fetch-on-refetch, ES256/JWKS signature verification, currency, binding matched to the agent's EyD identity, live revocation, fail-closed) and `GET /agents/{id}/standing` reports PoT score and Passport standing together ([clearinghouse/passport.py](clearinghouse/passport.py)).
- Refusals at the combined tier cite `AI Passport required` / `AI Passport revoked`, alongside the PoT reasons.
- ServiceNow's published vectors pass against our check, unmodified: verifier 81/81, caller 74/74, and the demo issuer's revocation endpoint passes the suite's live responder checks 8/8 ([passport-interop/](passport-interop/README.md)).
- The demo site checks C's presented Passport at attestation; a revoked Passport is refused there and classified Declined. Revocation doesn't wait for session expiry: the issuer pushes a signed notice to the clearinghouse, which pushes it to the site, which drops the agent's sessions (`POST /passport/revocations`, `POST /revocation-notice`).

## One line for judges

ServiceNow defined who the agent is. EyD proves what it did.
