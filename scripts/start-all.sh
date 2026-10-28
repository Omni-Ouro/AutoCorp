#!/usr/bin/env bash
# Start the whole EyD demo stack (droplet).
# Only the judge console (:8080) binds publicly. The issuer, clearinghouse
# and demo site stay on localhost — the console reaches them server-side,
# so the judge's browser only ever talks to :8080.
# Needs in the environment: ANTHROPIC_BASE_URL, ANTHROPIC_AUTH_TOKEN
# (ANTHROPIC_MODEL optional) for the console's model calls.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p logs

export ISSUER_URL="${ISSUER_URL:-http://localhost:8010}"
export CLEARINGHOUSE_KEY_FILE="${CLEARINGHOUSE_KEY_FILE:-.tmp-ch-key.json}"
export PASSPORT_ISSUER="${PASSPORT_ISSUER:-http://localhost:8010}"
export PASSPORT_JWKS_URL="${PASSPORT_JWKS_URL:-http://localhost:8010/jwks}"

nohup python passport-demo/issuer.py   > logs/issuer.log        2>&1 &
nohup python clearinghouse-ref/main.py > logs/clearinghouse.log 2>&1 &
sleep 2  # the site and console enroll/register at boot; let the CH come up
nohup python demo-site/main.py         > logs/site.log          2>&1 &
HOST=0.0.0.0 nohup python console/server.py > logs/console.log  2>&1 &

echo "judge console: http://<this-host>:8080   (logs in logs/)"
