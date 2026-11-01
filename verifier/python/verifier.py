"""Verifier / site SDK (PROOF v0 §3.6) — Python first.

A site keeps its own copy: cached pubkeys, every receipt it has received,
last-seen score per agent. The clearinghouse is registry and referee,
never in the request path.
"""
from __future__ import annotations

import base64
import calendar
import json
import secrets
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from eyd.canonical import hash_bytes, hash_obj, record_hash  # noqa: E402
from eyd.identity import Identity, verify_b64  # noqa: E402
from eyd.records import utc_now  # noqa: E402

SESSION_TTL = 900  # 15 min
REFUSAL_UNKNOWN = {"error": "refused", "reason": "PoT score unknown"}
REFUSAL_LOW = {"error": "refused", "reason": "PoT score below threshold"}
REFUSAL_NO_PASSPORT = {"error": "refused", "reason": "AI Passport required"}
REFUSAL_PASSPORT_REVOKED = {"error": "refused", "reason": "AI Passport revoked"}
REFUSAL_PAUSED = {"error": "refused", "reason": "Passport paused"}


def _request_json(method: str, url: str, payload: dict | None = None, timeout: float = 5.0):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except Exception:
            return e.code, {}
    except Exception:
        return None, {}  # clearinghouse unreachable


def verify_receipt(receipt: dict, ch_pubkey_b64: str) -> bool:
    """Offline check against the clearinghouse pubkey (§3.6)."""
    try:
        unsigned = {k: v for k, v in receipt.items() if k != "ch_sig"}
        return verify_b64(base64.b64decode(ch_pubkey_b64),
                          record_hash(unsigned).encode(), receipt.get("ch_sig", ""))
    except Exception:
        return False


def verify_attestation(att: dict, expected_nonce: str, pubkey_raw: bytes,
                       now: float | None = None) -> bool:
    """Signature, nonce, and 60s timestamp window (§4.6)."""
    if att.get("nonce") != expected_nonce:
        return False
    try:
        ts = att["ts"]
        epoch = calendar.timegm(time.strptime(ts, "%Y-%m-%dT%H:%M:%SZ"))
    except Exception:
        return False
    if abs((now if now is not None else time.time()) - epoch) > 60:
        return False
    unsigned = {k: v for k, v in att.items() if k != "sig"}
    return verify_b64(pubkey_raw, record_hash(unsigned).encode(), att.get("sig", ""))


def build_site_report(identity: Identity, *, record_hash_: str, agent_id: str,
                      outcome: str, result: bytes | str | dict | None,
                      expectation_match: bool | None = None) -> dict:
    if outcome not in ("fulfilled", "declined"):
        raise ValueError("outcome must be fulfilled|declined")
    if isinstance(result, bytes):
        result_hash = hash_bytes(result)
    elif isinstance(result, str):
        result_hash = hash_bytes(result.encode())
    elif result is None:
        result_hash = hash_bytes(b"")
    else:
        result_hash = hash_obj(result)
    report = {
        "record_hash": record_hash_, "agent_id": agent_id, "site_id": identity.id,
        "outcome": outcome, "result_hash": result_hash, "ts": utc_now(),
    }
    if expectation_match is not None:
        # Vector two: the site's signed attestation that its result
        # matched the Clearing House's pre-registered model expectation.
        report["expectation_match"] = bool(expectation_match)
    report["sig"] = identity.sign(record_hash(report).encode())
    return report


_USE_DEFAULT = object()


class EyDSite:
    """Stateful site helper behind `require_eyd` in the demo sites."""

    def __init__(self, identity: Identity, *, clearinghouse_url: str, domain: str,
                 min_score: float | None = None, require_passport: bool = False,
                 callback_url: str | None = None,
                 public_clearinghouse_url: str | None = None,
                 operator_id: str | None = None,
                 integrator_id: str | None = None):
        self.identity = identity
        self.clearinghouse_url = clearinghouse_url.rstrip("/")
        # Advertised in EyD-Clearinghouse challenge headers. API calls
        # keep clearinghouse_url, which may be localhost behind a proxy
        # while agents need the public address.
        self.public_clearinghouse_url = (
            public_clearinghouse_url or clearinghouse_url).rstrip("/")
        self.domain = domain
        self.min_score = min_score
        self.require_passport = require_passport
        self.callback_url = callback_url
        # Declared at enrollment; feeds the receipt corroboration label.
        self.operator_id = operator_id
        self.integrator_id = integrator_id
        self.pubkey_cache: dict[str, str] = {}
        self.sessions: dict[str, tuple[str, float]] = {}
        self.nonces: dict[str, float] = {}
        self.receipts: list[dict] = []
        self.scores: dict[str, float | None] = {}
        self.tamper = False

    # -- registry -----------------------------------------------------
    def enroll(self) -> None:
        payload = {"kind": "site", "site_id": self.identity.id,
                   "pubkey": self.identity.pubkey_b64, "domain": self.domain, "ts": utc_now()}
        if self.callback_url:
            payload["callback_url"] = self.callback_url  # revocation push notices
        if self.operator_id:
            payload["operator_id"] = self.operator_id
        if self.integrator_id:
            payload["integrator_id"] = self.integrator_id
        payload["sig"] = self.identity.sign(record_hash(payload).encode())
        _request_json("POST", f"{self.clearinghouse_url}/enroll", payload)

    def agent_pubkey(self, agent_id: str) -> bytes | None:
        if agent_id in self.pubkey_cache:
            return base64.b64decode(self.pubkey_cache[agent_id])
        status, body = _request_json("GET", f"{self.clearinghouse_url}/agents/{agent_id}")
        if status == 200 and body.get("pubkey"):
            self.pubkey_cache[agent_id] = body["pubkey"]
            return base64.b64decode(body["pubkey"])
        return None  # unknown agent (or clearinghouse down + never seen)

    def agent_score(self, agent_id: str) -> float | None:
        status, body = _request_json("GET", f"{self.clearinghouse_url}/agents/{agent_id}/score")
        if status == 200:
            self.scores[agent_id] = body.get("score")
            return body.get("score")
        return self.scores.get(agent_id)

    # -- attestation / sessions (§4.6) --------------------------------
    def new_challenge(self) -> str:
        nonce = secrets.token_urlsafe(24)
        self.nonces[nonce] = time.time() + 300
        return nonce

    def accept_attestation(self, att: dict) -> str | None:
        nonce = att.get("nonce", "")
        if nonce not in self.nonces or self.nonces[nonce] < time.time():
            return None
        pub = self.agent_pubkey(att.get("agent_id", ""))
        if pub is None or not verify_attestation(att, nonce, pub):
            return None
        del self.nonces[nonce]  # nonce is single-use
        return self.issue_session(att["agent_id"])

    def issue_session(self, agent_id: str) -> str:
        token = secrets.token_urlsafe(32)
        self.sessions[token] = (agent_id, time.time() + SESSION_TTL)
        return token

    def session_agent(self, token: str | None) -> str | None:
        if not token:
            return None
        entry = self.sessions.get(token)
        if not entry or entry[1] < time.time():
            return None
        return entry[0]

    def drop_sessions(self, agent_id: str) -> int:
        """Kill an agent's live sessions (revocation push notice). The
        next request re-attests and is checked afresh."""
        doomed = [t for t, (a, _) in self.sessions.items() if a == agent_id]
        for t in doomed:
            del self.sessions[t]
        return len(doomed)

    def score_allows(self, agent_id: str, min_score=_USE_DEFAULT) -> bool:
        """min_score per call overrides the site default (dynamic gates)."""
        threshold = self.min_score if min_score is _USE_DEFAULT else min_score
        if threshold is None:
            return True
        score = self.agent_score(agent_id)
        return score is not None and score >= threshold

    def passport_status(self, agent_id: str) -> str:
        """Combined-tier check (AI_PASSPORT.md): the clearinghouse holds
        the agent's Passport standing, re-asked live at the issuer."""
        status, body = _request_json(
            "GET", f"{self.clearinghouse_url}/agents/{agent_id}/standing")
        if status == 200:
            return body.get("passport_status", "unknown")
        return "unknown"  # fail closed: unable to tell

    # -- reporting ------------------------------------------------------
    def get_expectation(self, record_hash_: str) -> dict | None:
        """The Clearing House's pre-registered model expectation for an
        action (vector two), or None. Judge your result against it and
        pass the verdict as report(..., expectation_match=...)."""
        status, body = _request_json(
            "GET", f"{self.clearinghouse_url}/expectations/{record_hash_}")
        return body if status == 200 else None

    def report(self, record_hash_: str, agent_id: str, outcome: str,
               result: bytes | str | dict,
               expectation_match: bool | None = None) -> dict | None:
        report = build_site_report(self.identity, record_hash_=record_hash_,
                                   agent_id=agent_id, outcome=outcome, result=result,
                                   expectation_match=expectation_match)
        status, body = _request_json(
            "POST", f"{self.clearinghouse_url}/reports/site", report)
        receipt = (body or {}).get("receipt")
        if receipt:
            self.receipts.append(receipt)
        return receipt
