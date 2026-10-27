"""HTTP forward proxy — the interception behind `eyd run` (§3.1).

`eyd run` starts this proxy and points the child agent at it via the
standard HTTP_PROXY environment variable, which HTTP libraries honour
without any agent code changes. Every request the agent makes is
signed, reported, executed by the Dispatcher, and returned unmodified.
The agent never learns EyD exists.
"""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .dispatch import Dispatcher

HOP_BY_HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
              "te", "trailers", "transfer-encoding", "upgrade", "content-length"}


def make_proxy_server(dispatcher: Dispatcher, host: str = "127.0.0.1", port: int = 0) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):  # quiet
            pass

        def _handle(self):
            url = self.path
            if not url.startswith("http://"):
                self.send_error(400, "proxy expects an absolute http:// URL")
                return
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else None
            out = dispatcher.execute_http(self.command, url, body=body)
            payload = out["body"] or b""
            self.send_response(out["status"] or 502)
            for k, v in (out["headers"] or {}).items():
                if k.lower() not in HOP_BY_HOP:
                    self.send_header(k, v)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(payload)

        do_GET = _handle
        do_POST = _handle
        do_PUT = _handle
        do_DELETE = _handle
        do_PATCH = _handle
        do_HEAD = _handle

    return ThreadingHTTPServer((host, port), Handler)
