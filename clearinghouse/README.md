# EyD Clearing House (single-node, v0.1.0)

The pairing, classification, receipt, and PoT score service. This is
the same code that runs locally for testing and as the hosted beta at
`clearinghouse.omni-ouro.com` — one codebase, two modes.

Stores hashes, signatures, timestamps, classifications, and the
counterparty of each action. Never inputs, outputs, or tool arguments.

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
