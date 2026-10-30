# Omni-Ouro playground — the business install

A real business endpoint running the **EyD verifier SDK** against the
hosted EyD Clearing House. This is what a business installs to gate
agent traffic on PoT scores; Omni-Ouro runs it on its own domain
(`eyd.omni-ouro.com`) as the public playground for the beta.

| Endpoint | Gate |
|---|---|
| `GET /search` | open — EyD agents that show up still earn receipts |
| `POST /deck` | EyD required, any PoT score (request the pitch deck) |
| `POST /meeting` | EyD required, PoT score ≥ 0.8 (request a meeting) |

Everything is sandboxed: requests land on the board at `/`, nothing is
emailed, no calendar invite is sent. Agents without EyD, or below the
gate, get one of the five refusal reasons and a Declined receipt.

## What "installing" means for a business

```python
from verifier import EyDSite

site = EyDSite(my_site_identity,
               clearinghouse_url="https://clearinghouse.omni-ouro.com",
               domain="eyd.example.com", callback_url="https://eyd.example.com")
site.enroll()
# per request: challenge -> attestation -> session, then
if not site.score_allows(agent_id, min_score=0.8):
    return refusal            # {"error": "refused", "reason": "..."}
site.report(record_hash, agent_id, "fulfilled", response_bytes)
```

[main.py](main.py) is the full working version of that sketch
(~150 lines): attestation, sessions, score and Passport checks,
revocation push handling, and a request board.

## Run it

```bash
CLEARINGHOUSE_URL=https://clearinghouse.omni-ouro.com \
PLAYGROUND_DOMAIN=eyd.omni-ouro.com \
PLAYGROUND_PUBLIC_URL=https://eyd.omni-ouro.com \
python playground/main.py        # PLAYGROUND_PORT, default 8002
```

The site identity persists at `PLAYGROUND_KEY_FILE`
(default `playground/.keys/site.json`, gitignored): the business's
`site_id` is derived from that key, and the private key never leaves
the box.
