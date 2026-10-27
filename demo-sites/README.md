# Demo sites

Three fake companies, one codebase, three configs (Day 5):

| Company | Behavior |
|---|---|
| All Agents Welcome Inc | No EyD middleware. Admits everything, reports nothing. |
| EyD Required LLC | `require_eyd()` — any attested EyD. |
| Only Proven Agents PLC | `require_eyd(min_score=0.8)` |

Each exposes "submit a quote request" plus a dashboard. Sites 2–3 have a
tamper toggle that alters the response after hashing → Unexpected.
