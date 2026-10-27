"""HTTP dispatch (§3.1): sign → report intent → execute → report outcome.

The agent never learns EyD exists: verbs are presented as the agent's own
tools, results come back unmodified, attestation headers and challenge
handling happen entirely inside EyD.
"""
from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from urllib.parse import urlparse

from .canonical import record_hash
from .chain import LocalChain
from .identity import Identity
from .records import build_agent_report, utc_now
from .reporter import Reporter

# EyD always talks to sites/clearinghouse directly, never via a proxy
# (in particular not via its own `eyd run` interception proxy).
_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))

# Default verb map (§3.1): every tool belongs to exactly one verb.
VERB_MAP = {
    "http.get": "browse",
    "http.post": "send",
    "http.put": "write",
    "http.delete": "write",
    "file.read": "read",
    "file.write": "write",
    "code.execute": "execute",
    "pay.charge": "pay",
}


def build_attestation(identity: Identity, *, nonce: str, head_seq: int, head_hash: str) -> str:
    att = {"agent_id": identity.id, "nonce": nonce, "head_seq": head_seq,
           "head_hash": head_hash, "ts": utc_now()}
    att["sig"] = identity.sign(record_hash(att).encode())
    return base64.b64encode(json.dumps(att).encode()).decode()


class Dispatcher:
    def __init__(self, chain: LocalChain, identity: Identity, reporter: Reporter | None = None):
        self.chain = chain
        self.identity = identity
        self.reporter = reporter
        self.sessions: dict[str, str] = {}  # domain -> EyD-Session token

    def execute_http(self, method: str, url: str, body: bytes | None = None,
                     tool: str | None = None, poll_receipt: bool = True) -> dict:
        tool = tool or f"http.{method.lower()}"
        verb = VERB_MAP.get(tool, "browse" if method.upper() == "GET" else "send")
        target = urlparse(url).hostname or "local"

        # 1–3. Build + sign Action Record, append to chain, report intent first.
        record = self.chain.append(verb=verb, tool=tool, tool_input=body, target=target)
        rec_hash = record_hash(record)
        if self.reporter:
            self.reporter.report_intent(self.identity, record)

        # 4. Execute, handling the attestation challenge entirely inside EyD.
        status, resp_body, resp_headers = self._request(method, url, body, rec_hash, target)

        # 5. Hash response, report outcome.
        report = build_agent_report(
            self.identity, rec_hash=rec_hash, output=resp_body,
            status="ok" if status is not None and status < 400 else "error")
        receipt = None
        if self.reporter:
            _, resp = self.reporter.report_agent(report)
            receipt = resp.get("receipt")
            if receipt is None and poll_receipt:
                receipt = self.reporter.get_receipt(rec_hash)

        # 6. Receipt (or receipt=None → Unverified, e.g. non-EyD site).
        return {"status": status, "body": resp_body, "headers": resp_headers,
                "record": record, "record_hash": rec_hash,
                "agent_report": report, "receipt": receipt}

    def _request(self, method: str, url: str, body: bytes | None,
                 rec_hash: str, target: str, retried: bool = False):
        headers = {"EyD-Agent": self.identity.id, "EyD-Record": rec_hash}
        if target in self.sessions:
            headers["EyD-Session"] = self.sessions[target]
        req = urllib.request.Request(url, data=body, method=method.upper(), headers=headers)
        try:
            with _DIRECT.open(req, timeout=10) as resp:
                self._capture_session(target, resp.headers)
                return resp.status, resp.read(), dict(resp.headers)
        except urllib.error.HTTPError as e:
            resp_body = e.read()
            challenge = e.headers.get("EyD-Challenge")
            if e.code == 403 and challenge and not retried:
                seq, head = self.chain.head()
                headers["EyD-Attestation"] = build_attestation(
                    self.identity, nonce=challenge, head_seq=seq, head_hash=head)
                req2 = urllib.request.Request(url, data=body, method=method.upper(), headers=headers)
                try:
                    with _DIRECT.open(req2, timeout=10) as resp:
                        self._capture_session(target, resp.headers)
                        return resp.status, resp.read(), dict(resp.headers)
                except urllib.error.HTTPError as e2:
                    return e2.code, e2.read(), dict(e2.headers)
            return e.code, resp_body, dict(e.headers)
        except Exception:
            return None, b"", {}

    def _capture_session(self, target: str, headers) -> None:
        token = headers.get("EyD-Session")
        if token:
            self.sessions[target] = token
