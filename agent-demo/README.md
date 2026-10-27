# Agent demo

One Meta-model agent, three identities (Day 6). The agent code contains no
reference to EyD; the only difference between runs is whether it's launched
bare or via `eyd run`, and which key EyD loads.

| Agent | Setup | Seeded history |
|---|---|---|
| A | launched bare | none |
| B | `eyd run`, key B | mixed, score ≈ 0.4 |
| C | `eyd run`, key C | long clean run, score ≈ 0.97 |
