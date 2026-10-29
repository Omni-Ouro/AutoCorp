# Agent demo

One Meta-model agent ([agent.py](agent.py)), three identities. A plain
Python tool loop stands in for a framework: Agent A's tools are
undecorated; B's and C's carry `@eyd.tool` with different keys. The model
code is identical across all three. The judge console (`console/`) drives
the agent — one model call per click; `agent.py` also runs standalone.

| Agent | Identity | Seeded history |
|---|---|---|
| A | none (bare) | none |
| B | EyD, key B | mixed, score ≈ 0.4 |
| C | EyD + AI Passport, key C | long clean run, score ≈ 0.97 |
| D | Passport only (no EyD tools) | score ≈ 0.97 — never presented |
| E | EyD, key E | none — score unknown |

Agents are console config, not code: EyD on/off, a seed profile, and a
Passport flag. From the console, a Passport can be attached to, revoked
on, or detached from any identified agent at runtime (A has no identity
to bind one to). C's Passport is a real one from the demo issuer
(`passport-demo/issuer.py`), registered at the clearinghouse and checked
when presented; revoking it pushes a notice that drops live sessions
immediately.

Validated live 2026-10-28 through the judge console: A pays → refused
("PoT score unknown", no receipt) even after a boost attempt; B pays →
Declined at PoT ≥ 0.8, Expected when the site lowers its gate; C quotes →
Expected, and Unexpected with the tamper toggle on.
