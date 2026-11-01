#!/usr/bin/env bash
# Stop the demo stack started by start-all.sh.
pkill -f "console/server.py"         || true
pkill -f "demo-site/main.py"         || true
pkill -f "clearinghouse/main.py" || true
pkill -f "passport-demo/issuer.py"   || true
echo "stopped"
