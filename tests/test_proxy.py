import json
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from eyd.chain import LocalChain
from eyd.dispatch import Dispatcher
from eyd.identity import Identity
from eyd.proxy import make_proxy_server


class Upstream(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        payload = json.dumps({"echo": json.loads(body or b"{}")}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def test_eyd_run_proxy_signs_and_forwards_unmodified(tmp_path):
    upstream = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    threading.Thread(target=upstream.serve_forever, daemon=True).start()
    up_port = upstream.server_address[1]

    ident = Identity.generate()
    chain = LocalChain(tmp_path / "chain.jsonl", ident)
    proxy = make_proxy_server(Dispatcher(chain, ident, reporter=None))
    threading.Thread(target=proxy.serve_forever, daemon=True).start()
    proxy_port = proxy.server_address[1]
    try:
        # An ordinary HTTP client that only knows the standard proxy env:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": f"http://127.0.0.1:{proxy_port}"}))
        req = urllib.request.Request(
            f"http://127.0.0.1:{up_port}/quote",
            data=json.dumps({"need": "x"}).encode(), method="POST",
            headers={"Content-Type": "application/json"})
        with opener.open(req, timeout=10) as r:
            assert json.loads(r.read()) == {"echo": {"need": "x"}}
    finally:
        proxy.shutdown()
        upstream.shutdown()
    ok, msg = chain.verify()
    assert ok, msg
    assert chain.head()[0] == 1
