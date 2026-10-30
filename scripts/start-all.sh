#!/usr/bin/env bash
# Start the whole EyD demo stack locally.
# Only the judge console serves HTTP; it binds localhost unless
# HOST=0.0.0.0 is set (do that only when you mean to share it).
# The issuer, clearinghouse and demo site stay on localhost — the
# console reaches them server-side, so a browser only ever talks
# to the console port.
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
HOST="${HOST:-127.0.0.1}" nohup python console/server.py > logs/console.log  2>&1 &

echo "judge console: http://127.0.0.1:8080   (logs in logs/)"
