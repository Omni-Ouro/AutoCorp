"""Clearinghouse reporter with offline queue (§3.1).

If the clearinghouse is unreachable, the action still runs and is still
chained locally; the report is queued and retried. Local chain is the
source of truth; the clearinghouse is the referee.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

from .canonical import record_hash
from .identity import Identity
from .records import utc_now


def request_json(method: str, url: str, payload: dict | None = None, timeout: float = 5.0):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}"), dict(resp.headers)
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode() or "{}")
        except Exception:
            body = {}
        return e.code, body, dict(e.headers)
    except Exception:
        return None, {}, {}


class Reporter:
    def __init__(self, base_url: str, queue_path: Path | None = None):
        self.base_url = base_url.rstrip("/")
        self.queue_path = queue_path

    # -- offline queue --------------------------------------------------
    def _queue(self, kind: str, payload: dict) -> None:
        if self.queue_path is None:
            return
        self.queue_path.parent.mkdir(parents=True, exist_ok=True)
        with self.queue_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"kind": kind, "payload": payload}) + "\n")

    def flush_queue(self) -> int:
        if self.queue_path is None or not self.queue_path.exists():
            return 0
        lines = [json.loads(x) for x in self.queue_path.read_text(encoding="utf-8").splitlines() if x.strip()]
        sent, kept = 0, []
        for item in lines:
            path = "/intents" if item["kind"] == "intent" else "/reports/agent"
            status, _, _ = request_json("POST", f"{self.base_url}{path}", item["payload"])
            if status is not None and status < 300:
                sent += 1
            else:
                kept.append(item)
        self.queue_path.write_text(
            "".join(json.dumps(x) + "\n" for x in kept), encoding="utf-8")
        return sent

    # -- API --------------------------------------------------------------
    def enroll(self, identity: Identity) -> tuple[int | None, dict]:
        payload = {"kind": "agent", "agent_id": identity.id,
                   "pubkey": identity.pubkey_b64, "ts": utc_now()}
        payload["sig"] = identity.sign(record_hash(payload).encode())
        status, body, _ = request_json("POST", f"{self.base_url}/enroll", payload)
        return status, body

    def report_intent(self, identity: Identity, record: dict) -> tuple[int | None, dict]:
        payload = {
            "record_hash": record_hash(record),
            "agent_id": identity.id,
            "seq": record["seq"],
            "target": record["target"],
            "ts": record["ts"],
        }
        payload["sig"] = identity.sign(record_hash(payload).encode())
        status, body, _ = request_json("POST", f"{self.base_url}/intents", payload)
        if status is None or status >= 500:
            self._queue("intent", payload)
        return status, body

    def report_agent(self, report: dict) -> tuple[int | None, dict]:
        status, body, _ = request_json("POST", f"{self.base_url}/reports/agent", report)
        if status is None or status >= 500:
            self._queue("agent_report", report)
        return status, body

    def get_receipt(self, rec_hash: str) -> dict | None:
        status, body, _ = request_json("GET", f"{self.base_url}/receipts/{rec_hash}")
        return body if status == 200 else None

    def ch_pubkey(self) -> str | None:
        status, body, _ = request_json("GET", f"{self.base_url}/pubkey")
        return body.get("pubkey") if status == 200 else None
