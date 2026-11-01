"""Turnkey EyD gate for FastAPI — the whole check in one decorator.

    from fastapi_integration import gated

    @app.post("/pay")
    @gated(site, min_score=0.8)
    async def pay(request: Request):
        agent_id = request.state.eyd_agent
        return {"status": "paid"}

The decorator runs the §4.6 challenge/attestation handshake, sessions,
the per-action PoT score gate, and Passport standing; reports refusals
as Declined and the fulfilled result after the handler answers. The
handler keeps its normal FastAPI signature and returns a dict; the
admitted agent's id is on `request.state.eyd_agent`.

A session authenticates the agent — the gate for *this* action is
checked on every request, so a session minted at a weaker gate never
elevates. (The demo site keeps hand-written gates because the judge
console mutates them at runtime; fixed-gate sites want this.)

The refusal body never names EyD — an agent learns only that it lacks
a credential. `info_url`, if given, rides the challenge response as an
`EyD-Info` header: an owner-facing pointer to where the credential
comes from, invisible in the acting agent's result.
"""
from __future__ import annotations

import base64
import functools
import inspect
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import Request  # noqa: E402
from fastapi.responses import JSONResponse, Response  # noqa: E402

from eyd.canonical import hash_bytes  # noqa: E402
from verifier import (  # noqa: E402
    REFUSAL_LOW, REFUSAL_PASSPORT_REVOKED, REFUSAL_PAUSED, REFUSAL_UNKNOWN,
)


def _body_bytes(body: dict) -> bytes:
    return json.dumps(body, sort_keys=True).encode()


def gated(site, *, min_score=None, eyd_required=True, on_event=None,
          info_url=None):
    """Decorate a FastAPI endpoint with the EyD gate.

    on_event(agent_id, action_name, result), if given, fires on every
    refusal and admission — the playground's request board hooks here.
    info_url, if given, is sent as the EyD-Info header on challenge
    responses so the agent's owner can find the credential; the refusal
    body itself stays blind.
    """
    def decorator(fn):
        @functools.wraps(fn)
        async def wrapper(request: Request, *args, **kwargs):
            record_hash_ = request.headers.get("EyD-Record")
            agent_id = request.headers.get("EyD-Agent")

            def event(result: str) -> None:
                if on_event:
                    on_event(agent_id, fn.__name__, result)

            def refuse(reason: dict, challenge: bool = False) -> JSONResponse:
                if record_hash_ and agent_id:
                    site.report(record_hash_, agent_id, "declined",
                                _body_bytes(reason))
                event(f"refused: {reason['reason']}")
                headers = {}
                if challenge:
                    headers = {"EyD-Challenge": site.new_challenge(),
                               "EyD-Clearinghouse":
                                   getattr(site, "public_clearinghouse_url",
                                           site.clearinghouse_url)}
                    if info_url:
                        headers["EyD-Info"] = info_url
                return JSONResponse(reason, status_code=403, headers=headers)

            async def perform() -> Response:
                body = fn(request, *args, **kwargs)
                if inspect.isawaitable(body):
                    body = await body
                # Report exactly the bytes sent — the agent hashes the
                # response it received, so any re-rendering by the
                # framework would pair as Unexpected at the clearinghouse.
                body_bytes = _body_bytes(body)
                if record_hash_ and agent_id:
                    site.report(record_hash_, agent_id, "fulfilled", body_bytes)
                event("admitted")
                return Response(
                    content=body_bytes, media_type="application/json",
                    headers={"EyD-Result-Hash": hash_bytes(body_bytes)})

            if not eyd_required:
                # Open to all — an EyD agent that shows up still gets
                # its side reported, so open actions produce receipts.
                agent_id = site.session_agent(
                    request.headers.get("EyD-Session")) or agent_id
                request.state.eyd_agent = agent_id
                return await perform()

            session_token = None
            session_agent = site.session_agent(request.headers.get("EyD-Session"))
            if session_agent:
                agent_id = session_agent
            elif request.headers.get("EyD-Attestation"):
                try:
                    att = json.loads(base64.b64decode(
                        request.headers["EyD-Attestation"]))
                except Exception:
                    att = {}
                agent_id = att.get("agent_id")
                token = site.accept_attestation(att) if att else None
                if token is None:
                    return refuse(REFUSAL_UNKNOWN, challenge=True)
                session_token = token
            else:
                return refuse(REFUSAL_UNKNOWN, challenge=True)

            # Per-action policy, checked on every gated request.
            if not site.score_allows(agent_id, min_score):
                score = site.scores.get(agent_id)
                reason = REFUSAL_UNKNOWN if score is None else REFUSAL_LOW
                return refuse(reason)
            passport = site.passport_status(agent_id) if agent_id else "unknown"
            if passport in ("revoked", "paused"):
                reason = (REFUSAL_PASSPORT_REVOKED if passport == "revoked"
                          else REFUSAL_PAUSED)
                return refuse(reason)

            request.state.eyd_agent = agent_id
            resp = await perform()
            if session_token:
                resp.headers["EyD-Session"] = session_token
            return resp

        return wrapper
    return decorator
