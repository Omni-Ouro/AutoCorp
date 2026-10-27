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
  local hash chain, CLI. *(verbs/dispatch/`eyd run`/MCP proxy: Day 2)*
- **Proof format v0** (`spec/PROOF_v0.md`) — records, reports, receipts,
  canonicalization + test vectors, attestation.
- **Clearinghouse reference** (`clearinghouse-ref/`) — single-node pairing,
  classification, receipts, PoT score. *(Day 3; reference only — see below)*
- **Verifier / site SDK** (`verifier/`) — attestation, reporting,
  `require_eyd(min_score=…)`. *(Day 4)*
- **Demo sites** (`demo-sites/`) — three companies, one codebase, tamper toggle. *(Day 5)*
- **Agent demo** (`agent-demo/`) — Meta-model agent, three identities, 3×3 matrix. *(Day 6)*
- **EyD window** (`eyd-ui/`) — live action list and receipt viewer. *(Day 6)*

## What we didn't build (third-party / hosted)

- The Meta models and any Meta agent wrapped by EyD (used, not built here).
- `cryptography` (Ed25519/SHA-256 primitives), FastAPI/uvicorn, pytest.
- The hosted **PoT Clearinghouse** (multi-tenant, webhooks, market data) and
  **Eyro** governance/audit — operated by Omni-Ouro, not in this repo.
  `clearinghouse-ref/` is a single-node reference for local testing.
- Seeded demo history in `fixtures/` is **demo data**, labeled as such everywhere.

## License

Apache-2.0 — see [LICENSE](LICENSE).
