# Agent demo

One Meta-model agent ([agent.py](agent.py)), three identities. A plain
Python tool loop stands in for a framework: Agent A's tools are
undecorated; B's and C's carry `@eyd.tool` with different keys. The model
code is identical across all three. `eyd run` only opens the window and
attaches it to the agent's local chain; recording happens inside the
framework via the SDK.

| Agent | Setup | Seeded history |
|---|---|---|
| A | launched bare | none |
| B | `eyd run`, key B | mixed, score ≈ 0.4 |
| C | `eyd run`, key C | long clean run, score ≈ 0.97 |

```bash
python agent-demo/run_agents.py            # full 3x3 matrix (real LLM runs)
python agent-demo/run_agents.py --tamper   # plus the tamper -> Unexpected run
python agent-demo/run.py                   # same matrix, no LLM (fast, deterministic)
```

EyD Required LLC runs the combined tier (EyD + AI Passport; B and C hold
demo Passports issued by `passport-demo/issuer.py`, registered at the
clearinghouse). `run.py` adds a revoked-Passport run: valid EyD, revoked
Passport -> refused there, Declined.

Validated live 2026-10-27: A refused at both gated sites ("PoT score
unknown"); B Unverified/Expected/Declined; C Unverified/Expected/Expected;
tamper run Unexpected; revoked-Passport run refused ("AI Passport
revoked"), Declined.
