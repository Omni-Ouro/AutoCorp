# EyD

**Agents act on your behalf. Nobody can prove what they did.**

EyD is a small library and a small window. The agent framework imports
it, and it sits in the tool-call path: every call the agent makes is
signed under the agent's own Ed25519 key and reported to a
clearinghouse before it goes out. The counterparty site reports its
side after. The clearinghouse pairs the two, classifies the result
(Expected, Unexpected, Declined, Unverified), and issues a signed Proof
Receipt to both parties. Agents that don't route through EyD get no receipt.
Sites that gate on EyD only admit agents that do.

Built for the Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026),
Startup track. Design doc: [EYD_DESIGN.md](EYD_DESIGN.md). Proof format:
[spec/PROOF_v0.md](spec/PROOF_v0.md).

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
- **Clearinghouse reference** (`clearinghouse-ref/`) — single-node pairing,
  classification, receipts, PoT score, fork detection. *(reference only — see below)*
- **Verifier / site SDK** (`verifier/python/`) — attestation, sessions,
  reporting, offline `verify_receipt`, site score gating.
- **Demo site** (`demo-site/`) — one business, three independently gated
  actions (search / quote / pay), runtime gate controls, tamper toggle.
- **Judge console** (`console/`) — the demo page: pick an agent, set the
  site's gates, click a task, watch the refusal or the receipt land.
- **EyD window** (`eyd-ui/window.py`) — live action list and receipt viewer (local web view).
- **Demo agents** (`agent-demo/`) — one Meta-model agent ([agent.py](agent-demo/agent.py)), three identities: A's tools undecorated, B's/C's carry `@eyd.tool` under different keys, model code identical. The console drives it, one model call per click.

## Run the demo locally

```bash
pip install -e ".[clearinghouse]"
ISSUER_URL=http://localhost:8010 python passport-demo/issuer.py &   # demo Passport issuer :8010
CLEARINGHOUSE_KEY_FILE=.tmp-ch-key.json PASSPORT_ISSUER=http://localhost:8010 \
  PASSPORT_JWKS_URL=http://localhost:8010/jwks python clearinghouse-ref/main.py &  # :8787
SITE_PORT=8001 python demo-site/main.py &                          # one site, three gated actions
CONSOLE_PORT=8080 python console/server.py &                       # judge console
# open http://127.0.0.1:8080 and drive the demo
```

## Deploy (droplet)

One command starts the whole stack; only the judge console binds
publicly (`:8080`) — the issuer, clearinghouse, and site stay on
localhost and the console reaches them server-side:

```bash
pip install -e ".[clearinghouse]"
export ANTHROPIC_BASE_URL=... ANTHROPIC_AUTH_TOKEN=...   # for the console's model calls
scripts/start-all.sh        # scripts/stop-all.sh to stop
```

## What we didn't build (third-party / hosted)

- The Meta models and any agent framework built on them (the SDK hooks
  into its tool-call path; used, not built here).
- `cryptography` (Ed25519/SHA-256 primitives), FastAPI/uvicorn, pytest.
- The hosted **PoT Clearinghouse** (multi-tenant, webhooks, market data) and
  **Eyro** governance/audit — operated by Omni-Ouro, not in this repo.
  `clearinghouse-ref/` is a single-node reference for local testing.
- Seeded demo history in `fixtures/` is **demo data**, labeled as such everywhere.

## License

Apache-2.0 — see [LICENSE](LICENSE).
