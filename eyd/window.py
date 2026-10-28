"""EyD window (§3.2) — local web view attached to the local chain.

`eyd run` opens this window; it only reads the chain and fetches
receipts. Recording happens in the framework via the SDK, never here.
"""
from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .canonical import record_hash
from .identity import Identity
from .reporter import Reporter

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
     ${a.receipt?`<button onclick="verify('${a.record_hash}')">verify</button>`:''}
    </li>`).join('');
}
async function verify(rh){
  const d = await (await fetch('/api/verify?record_hash='+encodeURIComponent(rh))).json();
  alert(d.ok ? 'Receipt verified offline against clearinghouse pubkey' : 'Verification FAILED');
}
load(); setInterval(load, 3000);
</script>"""


def make_window_server(identity_path: Path, chain_path: Path, reporter: Reporter,
                       host: str = "127.0.0.1", port: int = 8790) -> ThreadingHTTPServer:
    # verify_receipt lives in the site SDK; import lazily via sys.path
    # so the runtime has no hard dependency on the verifier package.
    verifier_dir = str(Path(__file__).resolve().parent.parent / "verifier" / "python")
    if verifier_dir not in sys.path:
        sys.path.insert(0, verifier_dir)
    from verifier import verify_receipt

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
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
                rh = parse_qs(urlparse(self.path).query).get("record_hash", [""])[0]
                receipt = reporter.get_receipt(rh)
                pub = reporter.ch_pubkey()
                self._json({"ok": bool(receipt and pub and verify_receipt(receipt, pub))})
                return
            self._json({"error": "not found"}, 404)

    return ThreadingHTTPServer((host, port), Handler)
