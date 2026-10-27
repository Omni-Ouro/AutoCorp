# Clearinghouse reference (single-node)

Reference implementation for local testing: pairing, classification,
receipts, PoT score. **Single-node, reference only** — the hosted PoT
Clearinghouse (multi-tenant, site webhooks, PoT reports) is operated by
Omni-Ouro and is not in this repo.

Stores hashes, signatures, timestamps, classifications, and the
counterparty of each action. Never inputs, outputs, or tool arguments.

Run (from repo root):

```bash
pip install -e ".[clearinghouse]"
uvicorn main:app --app-dir clearinghouse-ref --port 8787
# or: python clearinghouse-ref/main.py
```
