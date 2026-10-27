# Agent demo

One Meta-model agent ([agent.py](agent.py)), three identities. The agent
file contains no reference to EyD; the only difference between runs is
whether it's launched bare or via `eyd run`, and which key EyD loads.
`eyd run` interposes EyD via the standard `HTTP_PROXY` env var, so the
agent's own HTTP tool routes through EyD with zero modification.

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

Validated live 2026-10-26: A refused at both gated sites ("PoT score
unknown"); B Unverified/Expected/Declined; C Unverified/Expected/Expected;
tamper run Unexpected.
