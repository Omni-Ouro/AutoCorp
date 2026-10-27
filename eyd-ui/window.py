"""EyD window (§3.2) — minimal local web view over the local chain.

Live list of actions: time, verb, tool, status, classification badge.
Tap an action for record hash / receipt detail. The verify button in
the page checks the receipt against the clearinghouse pubkey locally
(in Python, server-side here; same math as verifier.verify_receipt).

Run:  python eyd-ui/window.py [--port 8790] [--clearinghouse http://127.0.0.1:8787]
"""
from __future__ import annotations

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "verifier" / "python"))

from eyd.canonical import record_hash  # noqa: E402
from eyd.identity import Identity, default_chain_path, default_identity_path  # noqa: E402
from eyd.reporter import Reporter  # noqa: E402
from verifier import verify_receipt  # noqa: E402

PAGE = """<!doctype html><meta charset="utf-8"><title>EyD</title>
<style>body{font-family:system-ui;margin:2rem;background:#0b0e14;color:#e6e6e6}
.badge{padding:.1rem .5rem;border-radius:1rem;background:#333}
.Expected{background:#1d5c2e}.Unexpected{background:#7a1f1f}.Declined{background:#7a5410}.Unverified{background:#444}
li{margin:.6rem 0}code{color:#9ecbff}button{margin-left:.5rem}</style>
<h1>EyD</h1><p id="who"></p><ul id="list"></ul>
<script>
async function load(){
  const d = await (await fetch('/api/actions')).json();
  document.getElementById('who').textContent = 'agent ' + d.agent_id;
  document.getElementById('list').innerHTML = d.actions.map(a =>
    `<li>${a.ts} <b>${a.verb}</b> ${a.tool} -> ${a.target}
     <span class="badge ${a.classification||''}">${a.classification||a.status}</span>
     <br><code>${a.record_hash}</code>
     ${a.receipt?`<button onclick="verify('${a.record_hash}')">verify</button> <span id="v-${a.record_hash.slice(7,15)}"></span>`:''}
    </li>`).join('');
}
async function verify(rh){
  const d = await (await fetch('/api/verify?record_hash='+encodeURIComponent(rh))).json();
  alert(d.ok ? 'Receipt verified offline against clearinghouse pubkey' : 'Verification FAILED');
}
load(); setInterval(load, 3000);
</script>"""


def make_handler(identity_path: Path, chain_path: Path, reporter: Reporter):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):  # quiet
            pass

        def _json(self, obj, status=200):
            body = json.dumps(obj).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/":
                body = PAGE.encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if self.path.startswith("/api/actions"):
                ident = Identity.load(identity_path)
                records = []
                if chain_path.exists():
                    records = [json.loads(x) for x in chain_path.read_text().splitlines() if x.strip()]
                actions = []
                for rec in records:
                    rh = record_hash(rec)
                    receipt = reporter.get_receipt(rh)
                    actions.append({**rec, "record_hash": rh, "receipt": receipt,
                                    "classification": (receipt or {}).get("classification"),
                                    "status": "receipt" if receipt else "awaiting counterparty"})
                self._json({"agent_id": ident.id, "actions": list(reversed(actions))})
                return
            if self.path.startswith("/api/verify"):
                from urllib.parse import parse_qs, urlparse
                rh = parse_qs(urlparse(self.path).query).get("record_hash", [""])[0]
                receipt = reporter.get_receipt(rh)
                pub = reporter.ch_pubkey()
                self._json({"ok": bool(receipt and pub and verify_receipt(receipt, pub))})
                return
            self._json({"error": "not found"}, 404)

    return Handler


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8790)
    ap.add_argument("--clearinghouse", default="http://127.0.0.1:8787")
    ap.add_argument("--identity", default=None)
    ap.add_argument("--chain", default=None)
    a = ap.parse_args()
    reporter = Reporter(a.clearinghouse)
    handler = make_handler(Path(a.identity) if a.identity else default_identity_path(),
                           Path(a.chain) if a.chain else default_chain_path(), reporter)
    print(f"EyD window: http://127.0.0.1:{a.port}")
    HTTPServer(("127.0.0.1", a.port), handler).serve_forever()
