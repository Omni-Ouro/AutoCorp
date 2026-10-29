"""Demo site (§3.7) — one business, three independently gated actions.

  GET  /search   open to all by default
  POST /quote    EyD required, any score
  POST /pay      EyD required, PoT score >= 0.8

Gates are runtime state: the judge console sets them per action and the
next request is checked against the new values. A tamper toggle alters
the response after hashing so the next receipt reads Unexpected.

Run: SITE_PORT=8001 python demo-site/main.py
"""
from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "verifier" / "python"))

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.responses import JSONResponse, Response  # noqa: E402

from eyd.canonical import hash_bytes  # noqa: E402
from eyd.identity import Identity  # noqa: E402
from verifier import (  # noqa: E402
    EyDSite, REFUSAL_LOW, REFUSAL_PASSPORT_REVOKED, REFUSAL_PAUSED,
    REFUSAL_UNKNOWN,
)

COMPANY = "Acme Industrial Supply"
ACTIONS = ("search", "quote", "pay")
DEFAULT_GATES = {
    "search": {"eyd_required": False, "min_score": None},
    "quote": {"eyd_required": True, "min_score": None},
    "pay": {"eyd_required": True, "min_score": 0.8},
}


def make_app(*, clearinghouse_url: str = "http://127.0.0.1:8787",
             identity: Identity | None = None, domain: str = "localhost",
             callback_url: str | None = None) -> FastAPI:
    site_identity = identity or Identity.generate(kind="site")
    site = EyDSite(site_identity, clearinghouse_url=clearinghouse_url,
                   domain=domain, callback_url=callback_url)
    site.enroll()
    app = FastAPI(title=COMPANY)
    app.state.site = site
    app.state.gates = {k: dict(v) for k, v in DEFAULT_GATES.items()}
    app.state.actions: list[dict] = []

    def ledger(agent, action, result, classification=None, record_hash_=None):
        entry = {"agent": agent, "action": action, "result": result}
        if classification:
            entry["classification"] = classification
        if record_hash_:
            entry["record_hash"] = record_hash_
        app.state.actions.append(entry)

    def perform(action: str, data: dict, agent_id, record_hash_) -> Response:
        body = _action_body(action, data)
        body_bytes = _body_bytes(body)
        receipt = None
        if record_hash_ and agent_id:
            # Report what we meant to send; tamper alters it after hashing.
            receipt = site.report(record_hash_, agent_id, "fulfilled", body_bytes)
        sent = body_bytes
        if site.tamper:
            sent = _body_bytes({**body, "note": "altered after hashing"})
        ledger(agent_id, action, "admitted", (receipt or {}).get("classification"),
               record_hash_)
        return Response(content=sent, media_type="application/json",
                        headers={"EyD-Result-Hash": hash_bytes(body_bytes)})

    def gated(action: str, request: Request, data: dict) -> Response:
        gate = app.state.gates[action]
        record_hash_ = request.headers.get("EyD-Record")
        agent_id = request.headers.get("EyD-Agent")
        if not gate["eyd_required"]:
            # Open to all — but an EyD agent that shows up still gets
            # its side reported, so open actions produce receipts too.
            return perform(action, data, agent_id, record_hash_)

        session_agent = site.session_agent(request.headers.get("EyD-Session"))
        session_token = None
        if session_agent:
            agent_id = session_agent
        elif request.headers.get("EyD-Attestation"):
            try:
                att = json.loads(base64.b64decode(request.headers["EyD-Attestation"]))
            except Exception:
                att = {}
            agent_id = att.get("agent_id")
            token = site.accept_attestation(att) if att else None
            if token is None:
                return _refusal(site, REFUSAL_UNKNOWN, challenge=True)
            if not site.score_allows(agent_id, gate["min_score"]):
                score = site.scores.get(agent_id)
                reason = REFUSAL_UNKNOWN if score is None else REFUSAL_LOW
                if record_hash_ and agent_id:
                    site.report(record_hash_, agent_id, "declined", _body_bytes(reason))
                ledger(agent_id, action, f"refused: {reason['reason']}", None, record_hash_)
                return JSONResponse(reason, status_code=403)
            passport = site.passport_status(agent_id) if agent_id else "unknown"
            if passport in ("revoked", "paused"):
                reason = REFUSAL_PASSPORT_REVOKED if passport == "revoked" else REFUSAL_PAUSED
                if record_hash_:
                    site.report(record_hash_, agent_id, "declined", _body_bytes(reason))
                ledger(agent_id, action, f"refused: {reason['reason']}", None, record_hash_)
                return JSONResponse(reason, status_code=403)
            session_token = token
        else:
            return _refusal(site, REFUSAL_UNKNOWN, challenge=True)

        resp = perform(action, data, agent_id, record_hash_)
        if session_token:
            resp.headers["EyD-Session"] = session_token
        return resp

    @app.get("/")
    def home():
        return {"company": COMPANY, "site_id": site_identity.id, "gates": app.state.gates}

    @app.get("/gates")
    def get_gates():
        return {"gates": app.state.gates, "tamper": site.tamper}

    @app.post("/gates")
    async def set_gates(request: Request):
        payload = await request.json()
        action = payload.get("action")
        if action not in ACTIONS:
            return JSONResponse({"error": "unknown action"}, status_code=400)
        gate = app.state.gates[action]
        if "eyd_required" in payload:
            gate["eyd_required"] = bool(payload["eyd_required"])
        if "min_score" in payload:
            gate["min_score"] = payload["min_score"]  # float 0..1, or null = any
        return {"gates": app.state.gates, "tamper": site.tamper}

    @app.post("/tamper")
    async def tamper(request: Request):
        site.tamper = bool((await request.json()).get("on"))
        return {"tamper": site.tamper}

    @app.post("/revocation-notice")
    async def revocation_notice(request: Request):
        """Push from the clearinghouse: an agent's Passport standing
        changed. Drop its sessions now, not at expiry."""
        payload = await request.json()
        dropped = site.drop_sessions(payload.get("agent_id", ""))
        ledger(payload.get("agent_id"), "—",
               f"revocation notice: {dropped} session(s) dropped")
        return {"dropped_sessions": dropped}

    @app.get("/dashboard")
    def dashboard():
        return {"company": COMPANY, "site_id": site_identity.id,
                "gates": app.state.gates, "tamper": site.tamper,
                "actions": app.state.actions, "receipts": site.receipts,
                "scores_seen": site.scores}

    @app.get("/search")
    def search(request: Request, q: str = ""):
        return gated("search", request, {"need": q})

    @app.post("/quote")
    async def quote(request: Request):
        return gated("quote", request, await _json_body(request))

    @app.post("/pay")
    async def pay(request: Request):
        return gated("pay", request, await _json_body(request))

    return app


def _action_body(action: str, data: dict) -> dict:
    if action == "search":
        return {"company": COMPANY, "query": data.get("need", ""),
                "results": ["industrial shelving, 200 units — $48/unit, in stock",
                            "workbench, steel — $310/unit, ships in 3 days"]}
    if action == "quote":
        return {"company": COMPANY, "need": data.get("need", "demo"),
                "quote": f"Q-{abs(hash(data.get('need', 'demo'))) % 10000:04d}",
                "status": "submitted"}
    return {"company": COMPANY, "invoice": data.get("invoice", "2142"),
            "amount": "$9,600.00", "status": "paid"}


async def _json_body(request: Request) -> dict:
    try:
        return json.loads(await request.body() or b"{}")
    except Exception:
        return {}


def _body_bytes(body: dict) -> bytes:
    return json.dumps(body, sort_keys=True).encode()


def _refusal(site: EyDSite, reason: dict, challenge: bool = False) -> JSONResponse:
    headers = {}
    if challenge:
        headers = {"EyD-Challenge": site.new_challenge(),
                   "EyD-Clearinghouse": site.clearinghouse_url}
    return JSONResponse(reason, status_code=403, headers=headers)


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("SITE_PORT", "8001"))
    app = make_app(clearinghouse_url=os.environ.get("CLEARINGHOUSE_URL", "http://127.0.0.1:8787"),
                   domain=os.environ.get("SITE_DOMAIN", "localhost"),
                   callback_url=f"http://localhost:{port}")
    uvicorn.run(app, host=os.environ.get("HOST", "127.0.0.1"), port=port)
