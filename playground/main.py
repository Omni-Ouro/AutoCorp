"""Omni-Ouro playground — the business side of the EyD beta.

This is what a business installs: the verifier SDK (verifier/python)
in front of three agent-facing actions, checked against the hosted
EyD Clearing House. The human site (omni-ouro.com) is untouched; this
service lives beside it at eyd.omni-ouro.com and is the playground
agents are told to test against.

  GET  /search    open to all — EyD agents that show up still get receipts
  POST /deck      EyD required, any score   (request the pitch deck)
  POST /meeting   EyD required, PoT >= 0.8  (request a meeting)

Everything is sandboxed: requests are recorded on the board below,
nothing is emailed and no calendar invite is ever sent.

Run: PLAYGROUND_PORT=8002 python playground/main.py
Env: CLEARINGHOUSE_URL, PLAYGROUND_DOMAIN (default localhost),
     PLAYGROUND_PUBLIC_URL (revocation-push callback base),
     PLAYGROUND_KEY_FILE (site identity, persisted).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "verifier" / "python"))

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.responses import HTMLResponse  # noqa: E402

from eyd.identity import Identity  # noqa: E402
from fastapi_integration import gated  # noqa: E402
from verifier import EyDSite  # noqa: E402

COMPANY = "Omni-Ouro"
PRODUCTS = [
    ("Eyro", "Accountability for AI agents, enforced by the operating system — "
             "the execution layer where the model has no tool access."),
    ("Coven", "Coordination for fleets of agents working the same problem."),
    ("CovenGo", "Coven on the go: lightweight agent coordination."),
    ("Glove", "Egress control — decides what an agent may reach."),
    ("Eyro Mini", "The Eyro execution layer as dedicated hardware."),
    ("EySight", "Native app: watch what your agents are doing."),
    ("DuePulse", "Native app: keep agent work on schedule."),
]
GATES = {
    "search": {"eyd_required": False, "min_score": None},
    "deck": {"eyd_required": True, "min_score": None},
    "meeting": {"eyd_required": True, "min_score": 0.8},
}


def _site_identity() -> Identity:
    key_file = Path(os.environ.get(
        "PLAYGROUND_KEY_FILE",
        str(Path(__file__).resolve().parent / ".keys" / "site.json")))
    if key_file.exists():
        return Identity.load(key_file)
    ident = Identity.generate(kind="site")
    ident.save(key_file)
    return ident


def make_app(*, clearinghouse_url: str = "http://127.0.0.1:8787",
             identity: Identity | None = None, domain: str = "localhost",
             callback_url: str | None = None) -> FastAPI:
    site_identity = identity or _site_identity()
    site = EyDSite(site_identity, clearinghouse_url=clearinghouse_url,
                   domain=domain, callback_url=callback_url)
    site.enroll()
    app = FastAPI(title=f"{COMPANY} — EyD playground")
    app.state.site = site
    app.state.requests: list[dict] = []

    def board(agent, action, result):
        from eyd.records import utc_now
        app.state.requests.append(
            {"ts": utc_now(), "agent": agent, "action": action, "result": result})

    # The whole gate — attestation, per-action score check, Passport
    # standing, reporting — is the verifier SDK's @gated decorator.
    # What a business writes is the three handlers below.

    @app.get("/", response_class=HTMLResponse)
    def home():
        rows = "".join(
            f"<tr><td>{r['ts']}</td><td>{(r['agent'] or 'anonymous')[:26]}</td>"
            f"<td>{r['action']}</td><td>{r['result']}</td></tr>"
            for r in reversed(app.state.requests[-15:]))
        return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{COMPANY} — EyD playground</title>
<style>body{{font-family:system-ui,sans-serif;max-width:760px;margin:2rem auto;padding:0 1rem}}
table{{border-collapse:collapse;width:100%}}td,th{{border-bottom:1px solid #ddd;padding:.3rem .5rem;text-align:left}}
code{{background:#f2f2f2;padding:.1rem .3rem}}</style></head><body>
<h1>{COMPANY} — EyD beta playground</h1>
<p>This is a real business endpoint running the EyD verifier SDK against the
hosted <b>EyD Clearing House</b>. Point an EyD agent at it and test:</p>
<table><tr><th>Action</th><th>Gate</th></tr>
<tr><td><code>GET /search</code></td><td>open — EyD agents still earn receipts</td></tr>
<tr><td><code>POST /deck</code></td><td>EyD required, any PoT score</td></tr>
<tr><td><code>POST /meeting</code></td><td>EyD required, PoT score &ge; 0.8</td></tr></table>
<p>Everything is sandboxed: requests are recorded, nothing is emailed, no
calendar invite is sent. Site identity: <code>{site_identity.id}</code> ·
Clearinghouse: <code>{site.clearinghouse_url}</code></p>
<h2>Recent requests</h2>
<table><tr><th>time (UTC)</th><th>agent</th><th>action</th><th>result</th></tr>
{rows or '<tr><td colspan="4">No requests yet — be the first.</td></tr>'}
</table></body></html>"""

    @app.post("/revocation-notice")
    async def revocation_notice(request: Request):
        """Push from the clearinghouse: an agent's Passport standing
        changed. Drop its sessions now, not at expiry."""
        payload = await request.json()
        dropped = site.drop_sessions(payload.get("agent_id", ""))
        board(payload.get("agent_id"), "—",
              f"revocation notice: {dropped} session(s) dropped")
        return {"dropped_sessions": dropped}

    @app.get("/dashboard")
    def dashboard():
        return {"company": COMPANY, "site_id": site_identity.id,
                "clearinghouse": site.clearinghouse_url, "gates": GATES,
                "requests": app.state.requests, "receipts": site.receipts,
                "scores_seen": site.scores}

    @app.get("/search")
    @gated(site, eyd_required=False, on_event=board)
    async def search(request: Request, q: str = ""):
        return _action_body("search", {"need": q})

    @app.post("/deck")
    @gated(site, min_score=None, on_event=board, info_url=callback_url)
    async def deck(request: Request):
        return _action_body("deck", await _json_body(request))

    @app.post("/meeting")
    @gated(site, min_score=0.8, on_event=board, info_url=callback_url)
    async def meeting(request: Request):
        return _action_body("meeting", await _json_body(request))

    return app


def _action_body(action: str, data: dict) -> dict:
    if action == "search":
        q = (data.get("need") or "").lower()
        hits = [f"{name} — {desc}" for name, desc in PRODUCTS
                if not q or q in name.lower() or q in desc.lower()]
        return {"company": COMPANY, "query": data.get("need", ""),
                "results": hits or [f"{n} — {d}" for n, d in PRODUCTS]}
    if action == "deck":
        return {"company": COMPANY, "request": "pitch deck",
                "status": "sent",
                "deliverable": "Omni-Ouro pitch deck (sandbox copy) — "
                               "recorded on the playground board; nothing was emailed"}
    return {"company": COMPANY, "request": "meeting", "status": "recorded",
            "note": "Sandbox: your request is on the playground board. "
                    "No calendar invite was sent."}


async def _json_body(request: Request) -> dict:
    try:
        return json.loads(await request.body() or b"{}")
    except Exception:
        return {}


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PLAYGROUND_PORT", "8002"))
    app = make_app(
        clearinghouse_url=os.environ.get("CLEARINGHOUSE_URL", "http://127.0.0.1:8787"),
        domain=os.environ.get("PLAYGROUND_DOMAIN", "localhost"),
        callback_url=os.environ.get("PLAYGROUND_PUBLIC_URL",
                                    f"http://localhost:{port}"))
    uvicorn.run(app, host=os.environ.get("HOST", "127.0.0.1"), port=port)
