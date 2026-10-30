# Deploy runbook — EyD beta droplet

What runs here (and only here): **EyD Clearing House v0.1.0** and the
**Omni-Ouro playground** (the business-SDK install). The judge console
and the hackathon demo stay local — they are not part of this box.

Public names, TLS via Caddy (same pattern as the Eyro droplet):

| Name | Service | Port |
|---|---|---|
| `clearinghouse.omni-ouro.com` | Clearing House | 127.0.0.1:8787 |
| `eyd.omni-ouro.com` | Playground | 127.0.0.1:8002 |

## Owner checklist (before first deploy)

1. Create the droplet: Ubuntu 24.04, 1 GB is enough (two light Python
   services + Caddy). Add the SSH key used for the Eyro box.
2. DNS, wherever omni-ouro.com is managed: A records `clearinghouse`
   and `eyd` → the droplet's IP.
3. Hand the IP to whoever deploys (below is fully scripted from SSH).

## First deploy (over SSH, as root)

```bash
adduser --system --home /opt/eyd eyd
apt-get update && apt-get install -y git python3-venv ufw \
  debian-keyring debian-archive-keyring apt-transport-https curl gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
  | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
  | tee /etc/apt/sources.list.d/caddy-stable.list
apt-get update && apt-get install -y caddy
git clone https://github.com/Omni-Ouro/AutoCorp.git /opt/eyd
cd /opt/eyd && python3 -m venv .venv && .venv/bin/pip install -e ".[clearinghouse]"
mkdir -p state && cp deploy/eyd.env.example eyd.env
# edit eyd.env: set CH_ADMIN_TOKEN (openssl rand -hex 24)
chmod 600 eyd.env && chown -R eyd:eyd /opt/eyd
cp deploy/eyd-clearinghouse.service deploy/eyd-playground.service /etc/systemd/system/
cp deploy/Caddyfile /etc/caddy/Caddyfile
systemctl daemon-reload && systemctl enable --now eyd-clearinghouse eyd-playground caddy
ufw allow 22 && ufw allow 80 && ufw allow 443 && ufw --force enable
```

State lives in `/opt/eyd/state/` (gitignored): the clearinghouse key,
the playground's site key, and `clearinghouse.json` — the persisted
store. Receipts and scores survive restarts; back up that directory.

## Verify (from anywhere)

```bash
curl https://clearinghouse.omni-ouro.com/          # service, version, pubkey
curl https://eyd.omni-ouro.com/                    # playground board
python examples/beta_agent.py                      # the judge's five minutes
curl -X POST https://clearinghouse.omni-ouro.com/seed -d '{}'   # expect 403
```

## Update

```bash
cd /opt/eyd && git pull && systemctl restart eyd-clearinghouse eyd-playground
```

Clearinghouse state reloads from disk on boot; the playground
re-enrolls with the same site identity. A restart costs the playground
its in-memory request board and live sessions only.

## Notes

- No model credentials on this box. Agents bring their own; the beta
  example agent needs none at all.
- `/seed` and `/boost` (demo-data endpoints) answer 403 without the
  `x-admin-token` header. The judge console's boost/reduce buttons are
  a local-demo feature and stay local.
- Passport verification stays wired in the Clearing House; the hosted
  beta gates on EyD + PoT. The demo Passport issuer remains a local
  hackathon component.
