# EyD

**Agents act on your behalf. Nobody can prove what they did.**

EyD is a thin runtime and a small window. Whatever agent you already use is
run through it. The model picks verbs; EyD executes the tool, signs a record
of the action under the agent's own Ed25519 key, and reports it to a
clearinghouse before the call goes out. The counterparty site reports its
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

- **EyD runtime** (`eyd/`) — identity, canonicalization, Action Records,
  local hash chain, CLI (`init`/`enroll`/`run`/`verify-local`), HTTP dispatch
  with intent-before-execution and in-runtime attestation, offline queue.
- **Proof format v0** (`spec/PROOF_v0.md`) — records, reports, receipts,
  canonicalization + test vectors, attestation.
- **Clearinghouse reference** (`clearinghouse-ref/`) — single-node pairing,
  classification, receipts, PoT score, fork detection. *(reference only — see below)*
- **Verifier / site SDK** (`verifier/python/`) — attestation, sessions,
  reporting, offline `verify_receipt`, site score gating.
- **Demo sites** (`demo-sites/`) — three companies, one codebase, tamper toggle.
- **Agent demo** (`agent-demo/run.py`) — three identities, full 3×3 matrix + tamper run.
- **EyD window** (`eyd-ui/window.py`) — live action list and receipt viewer (local web view).
- **Demo agents** (`agent-demo/`) — one Meta-model agent ([agent.py](agent-demo/agent.py)), three identities. Bare vs `eyd run` (HTTP-proxy interception, agent unmodified); `run_agents.py` runs the full matrix on the real model, `run.py` runs it deterministically without the LLM.

## Run the demo locally

```bash
pip install -e ".[clearinghouse]"
python clearinghouse-ref/main.py &            # :8787
SITE_MODE=welcome  SITE_PORT=8001 python demo-sites/main.py &
SITE_MODE=required SITE_PORT=8002 python demo-sites/main.py &
SITE_MODE=proven   SITE_PORT=8003 python demo-sites/main.py &
python agent-demo/run.py                      # the 3x3 matrix + tamper run
```

## What we didn't build (third-party / hosted)

- The Meta models and any Meta agent wrapped by EyD (used, not built here).
- `cryptography` (Ed25519/SHA-256 primitives), FastAPI/uvicorn, pytest.
- The hosted **PoT Clearinghouse** (multi-tenant, webhooks, market data) and
  **Eyro** governance/audit — operated by Omni-Ouro, not in this repo.
  `clearinghouse-ref/` is a single-node reference for local testing.
- Seeded demo history in `fixtures/` is **demo data**, labeled as such everywhere.

## License

Apache-2.0 — see [LICENSE](LICENSE).
