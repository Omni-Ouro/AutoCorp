# EyD

**Agents act on your behalf. Nobody can prove what they did.**

EyD is a small library and a small window. The agent framework imports
it, and it sits in the tool-call path: every call the agent makes is
signed under the agent's own Ed25519 key and reported to a
clearinghouse before it goes out. The counterparty site reports its
side after. The clearinghouse pairs the two, classifies the result
(Expected, Unexpected, Declined, Unverified, Deviated), and issues a signed Proof
Receipt to both parties. Agents that don't route through EyD get no receipt.
Sites that gate on EyD only admit agents that do.

Built for the Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026),
Startup track. Design doc: [EYD_DESIGN.md](EYD_DESIGN.md). Proof format:
[spec/PROOF_v0.md](spec/PROOF_v0.md).

## Test the beta (hosted)

EyD Clearing House **v0.1.0** runs hosted, and Omni-Ouro runs the
business SDK on its own domain as a public playground — test against
both, no demo driver needed:

- **Clearing House:** https://clearinghouse.omni-ouro.com — `/` names the service, version, and public key.
- **Playground business:** https://eyd.omni-ouro.com — `/search` open, `/deck` needs EyD, `/meeting` needs PoT ≥ 0.8. Sandboxed: nothing is emailed, ever.

**As an agent** — install the SDK and act (five minutes, no API key):

```bash
pip install git+https://github.com/Omni-Ouro/AutoCorp.git
python examples/beta_agent.py
```

It enrolls, searches, gets a meeting refused while its score is
unknown, earns a score with clean actions, and gets the meeting.
Your identity persists, so the score you build is still there tomorrow.

**As a business** — the verifier SDK in front of your endpoints.
[playground/](playground/) is Omni-Ouro's working install (~150 lines):

```python
site = EyDSite(identity, clearinghouse_url="https://clearinghouse.omni-ouro.com",
               domain="eyd.example.com", callback_url="https://eyd.example.com")
site.enroll()                    # then, per request:
site.score_allows(agent_id, 0.8) # gate on the PoT score
site.report(record_hash, agent_id, "fulfilled", response_bytes)
```

Hosted honesty: the public Clearing House is the single-node v0.1.0
below, run with persistence on and its demo-data endpoints (`/seed`,
`/boost`) admin-locked — nobody can mint trust on it. Seeded history
stays a local-demo fixture, labeled as such everywhere.

## Quickstart (Day 1 core)

```bash
pip install -e .
eyd init            # generate your agent's Ed25519 identity
eyd id              # print agent_id
eyd verify-local    # walk and verify the local action chain
pytest              # canonicalization vectors, records, chain
```

## What we built (this repo, Apache-2.0, all new Oct 26 – Nov 4)

- **EyD SDK** (`eyd/`) — a library the framework imports: `@eyd.tool`
  decorator, `eyd.wrap()`, `eyd.hook(framework)`, verb registration,
  identity, canonicalization, Action Records, local hash chain,
  reporting with offline queue, CLI (`init`/`enroll`/`run`/`verify-local`).
  `eyd run` only opens the window attached to the local chain.
- **Proof format v0** (`spec/PROOF_v0.md`) — records, reports, receipts,
  canonicalization (RFC 8785) + test vectors, attestation.
- **AI Passport interoperability** (`passport-interop/`, [AI_PASSPORT.md](AI_PASSPORT.md)) — the clearinghouse also reads ServiceNow AI Passports as an identity credential alongside EyD (Passport alone never suffices by default; Passport + EyD is the combined tier). ServiceNow's published test vectors pass against our check unmodified: verifier 81/81, caller 74/74.
- **EyD Clearing House** (`clearinghouse/`) — single-node pairing,
  classification, receipts, PoT score, fork detection. The same code
  runs locally and as the hosted beta (see Deploy).
- **Verifier / site SDK** (`verifier/python/`, `verifier/ts/`) — attestation, sessions,
  reporting, offline `verify_receipt`, site score gating. Python and TypeScript
  implementations with cross-compatible keys and signatures; turnkey gates for
  FastAPI (`@gated`) and Express (`eydGate`).
- **Demo site** (`demo-site/`) — one business, three independently gated
  actions (search / quote / pay), runtime gate controls, tamper toggle.
- **Judge console** (`console/`) — the demo page: pick an agent, set the
  site's gates, click a task, watch the refusal or the receipt land.
- **EyD window** (`eyd-ui/window.py`) — live action list and receipt viewer (local web view).
- **Demo agents** (`agent-demo/`) — one Meta-model agent ([agent.py](agent-demo/agent.py)) behind six console identities: bare, low-score EyD, EyD + Passport, Passport-only, newcomer, and the Bad Agent. A's tools are undecorated; the rest carry `@eyd.tool` under different keys; model code identical. The console drives it, one model call per click.

## Run the demo locally

```bash
pip install -e ".[clearinghouse]"
ISSUER_URL=http://localhost:8010 python passport-demo/issuer.py &   # demo Passport issuer :8010
CLEARINGHOUSE_KEY_FILE=.tmp-ch-key.json PASSPORT_ISSUER=http://localhost:8010 \
  PASSPORT_JWKS_URL=http://localhost:8010/jwks python clearinghouse/main.py &  # :8787
SITE_PORT=8001 python demo-site/main.py &                          # one site, three gated actions
CONSOLE_PORT=8080 python console/server.py &                       # judge console
# open http://127.0.0.1:8080 and drive the demo
```

## Deploy (droplet)

The hosted beta is two services — EyD Clearing House v0.1.0 and the
Omni-Ouro playground — behind Caddy on one droplet; the judge console
is a local demo and is not part of it. Runbook:
[deploy/README.md](deploy/README.md). Locally, the whole console
stack also starts in one command (`scripts/start-all.sh`,
`scripts/stop-all.sh` to stop; console binds localhost unless
`HOST=0.0.0.0` is set).

## What we didn't build (third-party / hosted)

- The Meta models and any agent framework built on them (the SDK hooks
  into its tool-call path; used, not built here).
- `cryptography` (Ed25519/SHA-256 primitives), FastAPI/uvicorn, pytest.
- The multi-tenant **PoT Clearinghouse** tier (webhooks, market data) and
  **Eyro** governance/audit — operated by Omni-Ouro, not in this repo.
  `clearinghouse/` here is the single-node v0.1.0: local testing and the
  hosted beta are the same code.
- Seeded demo history in `fixtures/` is **demo data**, labeled as such everywhere.

## License

Apache-2.0 — see [LICENSE](LICENSE).
