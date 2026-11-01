# EyD Clearing House (single-node, v0.1.0)

The pairing, classification, receipt, and PoT score service. This is
the same code that runs locally for testing and as the hosted beta at
`clearinghouse.omni-ouro.com` — one codebase, two modes.

Stores hashes, signatures, timestamps, classifications, and the
counterparty of each action. Never inputs, outputs, or tool arguments.

## Model expectation (vector two, advisory)

With a model gateway configured, each intent also gets a pre-registered
one-sentence sketch of what a successful result should look like,
generated from the declared action alone (verb, tool, target) — never
arguments, never result content — and labeled with a category from a
fixed taxonomy. The sketch is bound into the signed
receipt, and the site may attest in its signed report whether its
result matched (`expectation_match`). Advisory only: it never changes
a classification or the PoT score, and any failure yields no
expectation and never blocks an intent. Sites read the sketch at
`GET /expectations/{record_hash}`. The category labels make the
accumulated store training data for a future cheap local decision
model behind the same interface; `other`/`unknown` are its handoff
back to a reasoning model for genuinely new action shapes.

Env: `MODEL_GATEWAY_URL` + `MODEL_GATEWAY_TOKEN` enable the vector
(`ANTHROPIC_BASE_URL` / `ANTHROPIC_AUTH_TOKEN` accepted as fallbacks).
`MODEL_GATEWAY_FORMAT` picks the API shape: `openai` (chat completions
— e.g. Baseten serving the Meta open-weight model) or `messages` (the
default). Model: `EXPECTATION_MODEL`, else
`ANTHROPIC_MODEL`, else `muse-wonder-1.0`; `EXPECTATION_VERBS` optionally restricts which
verbs get sketches; `EXPECTATIONS=off` disables it. Sketches persist
with the rest of the store — over time they accumulate into a
per-site/tool corpus of expected action shapes.

Run (from repo root):

```bash
pip install -e ".[clearinghouse]"
uvicorn main:app --app-dir clearinghouse --port 8787
# or: python clearinghouse/main.py
```

Hosted mode is two environment variables: `CH_STATE_FILE` persists the
whole store to disk (survives restarts), and `CH_ADMIN_TOKEN` locks the
demo-data endpoints (`/seed`, `/agents/{id}/boost`). Unset, it runs
in-memory and open — the local default. See [../deploy/](../deploy/)
for the production setup.

Not in this repo: the multi-tenant hosted tier (site webhooks, PoT
reports, market data) and Eyro governance — operated by Omni-Ouro.
EyD proves; Eyro governs.
