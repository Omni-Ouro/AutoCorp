"""Demo sites — three companies, one codebase, three configs (§3.7).

Each exposes POST /quote ("submit a quote request") and GET /dashboard.
Run: SITE_MODE=required SITE_PORT=8002 python demo-sites/main.py
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
    EyDSite, REFUSAL_LOW, REFUSAL_NO_PASSPORT, REFUSAL_PASSPORT_REVOKED, REFUSAL_UNKNOWN,
)

MODES = {
    "welcome": {"company": "All Agents Welcome Inc", "min_score": None, "gated": False},
    # Combined tier (AI_PASSPORT.md): EyD + AI Passport, both required.
    "required": {"company": "EyD Required LLC", "min_score": None, "gated": True, "passport": True},
    "proven": {"company": "Only Proven Agents PLC", "min_score": 0.8, "gated": True},
}


def make_app(mode: str, *, clearinghouse_url: str = "http://127.0.0.1:8787",
             identity: Identity | None = None, domain: str = "localhost") -> FastAPI:
    cfg = MODES[mode]
    site_identity = identity or Identity.generate(kind="site")
    site = EyDSite(site_identity, clearinghouse_url=clearinghouse_url,
                   domain=domain, min_score=cfg["min_score"] if cfg["gated"] else None,
                   require_passport=bool(cfg.get("passport")))
    site.enroll()
    app = FastAPI(title=cfg["company"])
    app.state.site = site
    app.state.mode = mode
    app.state.actions: list[dict] = []

    @app.get("/")
    def home():
        return {"company": cfg["company"], "mode": mode, "site_id": site_identity.id}

    @app.post("/tamper")
    async def tamper(request: Request):
        payload = await request.json()
        site.tamper = bool(payload.get("on"))
        return {"tamper": site.tamper}

    @app.get("/dashboard")
    def dashboard():
        return {"company": cfg["company"], "mode": mode, "site_id": site_identity.id,
                "tamper": site.tamper, "actions": app.state.actions,
                "receipts": site.receipts, "scores_seen": site.scores}

    @app.post("/quote")
    async def quote(request: Request):
        raw = await request.body()
        try:
            data = json.loads(raw or b"{}")
        except Exception:
            data = {}
        record_hash_ = request.headers.get("EyD-Record")
        agent_id = request.headers.get("EyD-Agent")

        if not cfg["gated"]:
            body = _quote_body(cfg["company"], data)
            app.state.actions.append({"agent": agent_id, "result": "admitted (no EyD)"})
            return JSONResponse(body, status_code=200)

        # Gated: session, else attestation, else challenge (§4.6).
        session_agent = site.session_agent(request.headers.get("EyD-Session"))
        att_agent = None
        session_token = None
        if session_agent:
            att_agent = session_agent
        elif request.headers.get("EyD-Attestation"):
            try:
                att = json.loads(base64.b64decode(request.headers["EyD-Attestation"]))
            except Exception:
                att = {}
            att_agent = att.get("agent_id")
            token = site.accept_attestation(att) if att else None
            if token is None:
                return _refusal(site, REFUSAL_UNKNOWN, challenge=True)
            if not site.score_allows(att_agent):
                score = site.scores.get(att_agent)
                reason = REFUSAL_UNKNOWN if score is None else REFUSAL_LOW
                if record_hash_ and att_agent:
                    site.report(record_hash_, att_agent, "declined", _body_bytes(reason))
                app.state.actions.append({"agent": att_agent, "result": f"refused: {reason['reason']}"})
                return JSONResponse(reason, status_code=403)
            if site.require_passport:
                pstatus = site.passport_status(att_agent)
                if pstatus != "valid":
                    reason = REFUSAL_PASSPORT_REVOKED if pstatus == "revoked" \
                        else REFUSAL_NO_PASSPORT
                    if record_hash_ and att_agent:
                        site.report(record_hash_, att_agent, "declined", _body_bytes(reason))
                    app.state.actions.append({"agent": att_agent, "result": f"refused: {reason['reason']}"})
                    return JSONResponse(reason, status_code=403)
            session_token = token
        else:
            return _refusal(site, REFUSAL_UNKNOWN, challenge=True)

        body = _quote_body(cfg["company"], data)
        body_bytes = _body_bytes(body)
        receipt = None
        if record_hash_ and att_agent:
            # Report what we meant to send; tamper alters it after hashing.
            receipt = site.report(record_hash_, att_agent, "fulfilled", body_bytes)
        sent_bytes = body_bytes
        if site.tamper:
            sent_bytes = _body_bytes({**body, "quote": body["quote"] + " (altered)"})
        app.state.actions.append({"agent": att_agent, "result": "admitted",
                                  "classification": (receipt or {}).get("classification")})
        headers = {"EyD-Result-Hash": hash_bytes(body_bytes)}
        if session_token:
            headers["EyD-Session"] = session_token
        # Return the exact bytes that were hashed, so the agent's
        # output_hash compares against what the site meant to send (§3.6).
        return Response(content=sent_bytes, media_type="application/json", headers=headers)

    return app


def _quote_body(company: str, data: dict) -> dict:
    return {"company": company, "quote": f"Q-{abs(hash(data.get('need', 'demo'))) % 10000:04d}",
            "need": data.get("need", "demo"), "status": "submitted"}


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

    mode = os.environ.get("SITE_MODE", "required")
    app = make_app(mode, clearinghouse_url=os.environ.get("CLEARINGHOUSE_URL", "http://127.0.0.1:8787"),
                   domain=os.environ.get("SITE_DOMAIN", "localhost"))
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("SITE_PORT", "8002")))
