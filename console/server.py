"""Judge console backend (§3.9).

Serves the console page and drives the real path: one Meta-model call
per click, the tool executed through the agent's tool table (bare for
A, @eyd.tool for B/C), gates proxied to the demo site, boost proxied
to the clearinghouse. Nothing here is a special case.

Run: CONSOLE_PORT=8080 python console/server.py
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agent-demo"))

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse  # noqa: E402

from agent import HttpResult, call_model, make_submit_quote_request  # noqa: E402
from eyd import EyD, current_headers  # noqa: E402
from eyd.canonical import record_hash as compute_record_hash  # noqa: E402
from eyd.identity import Identity  # noqa: E402
from eyd.reporter import Reporter, request_json  # noqa: E402

CH = os.environ.get("CH_URL", "http://127.0.0.1:8787")
SITE = os.environ.get("SITE_URL", "http://127.0.0.1:8001")
ISSUER = os.environ.get("ISSUER_URL", "http://localhost:8010")
KEYS = ROOT / "agent-demo" / ".keys"
FIXTURE = ROOT / "fixtures" / "history.json"
DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))

AGENTS = {
    "A": {"name": "Agent A", "chip": "no EyD", "eyd": False},
    "B": {"name": "Agent B", "chip": "EyD", "eyd": True},
    "C": {"name": "Agent C", "chip": "EyD + Passport", "eyd": True, "passport": True},
}

ACTIONS = {
    "search": {
        "task": "Find pricing for industrial shelving.",
        "tool": {"name": "search_pricing",
                 "description": "Search the vendor's catalog for pricing",
                 "input_schema": {"type": "object",
                                  "properties": {"query": {"type": "string"}},
                                  "required": ["query"]}},
        "verb": "search", "request_line": "GET /search",
    },
    "quote": {
        "task": "Get a quote for 200 units of industrial shelving.",
        "tool": {"name": "submit_quote_request",
                 "description": "Submit a quote request to a vendor site",
                 "input_schema": {"type": "object",
                                  "properties": {"need": {"type": "string"}},
                                  "required": ["need"]}},
        "verb": "send", "request_line": "POST /quote",
    },
    "pay": {
        "task": "Pay invoice 2142.",
        "tool": {"name": "pay_invoice",
                 "description": "Pay an outstanding invoice at the vendor",
                 "input_schema": {"type": "object",
                                  "properties": {"invoice": {"type": "string"}},
                                  "required": ["invoice"]}},
        "verb": "pay", "request_line": "POST /pay",
    },
}


def _tool_fn(action: str):
    """Same transport pattern as the demo agent's tool (agent.py)."""
    if action == "search":
        def search_pricing(query: str = "") -> HttpResult:
            url = f"{SITE}/search?" + urllib.parse.urlencode({"q": query})
            req = urllib.request.Request(url, method="GET", headers={**current_headers()})
            try:
                with DIRECT.open(req, timeout=15) as r:
                    return HttpResult(r.status, r.read().decode(), dict(r.headers))
            except urllib.error.HTTPError as e:
                return HttpResult(e.code, e.read().decode(), dict(e.headers))
        return search_pricing
    if action == "quote":
        return make_submit_quote_request(f"{SITE}/quote")

    def pay_invoice(invoice: str = "2142") -> HttpResult:
        headers = {"Content-Type": "application/json", **current_headers()}
        req = urllib.request.Request(f"{SITE}/pay", method="POST", headers=headers,
                                     data=json.dumps({"invoice": invoice}).encode())
        try:
            with DIRECT.open(req, timeout=15) as r:
                return HttpResult(r.status, r.read().decode(), dict(r.headers))
        except urllib.error.HTTPError as e:
            return HttpResult(e.code, e.read().decode(), dict(e.headers))
    return pay_invoice


def load_or_create(label: str) -> Identity:
    KEYS.mkdir(exist_ok=True)
    p = KEYS / f"{label}.json"
    if p.exists():
        return Identity.load(p)
    ident = Identity.generate()
    ident.save(p)
    return ident


def seed_history(label: str, ident: Identity) -> None:
    import hashlib as _hl

    from eyd.records import utc_now

    counts = json.loads(FIXTURE.read_text())["agents"][label]
    receipts, i = [], 0
    for classification, n in (("Expected", counts["expected"]),
                              ("Unexpected", counts["unexpected"]),
                              ("Declined", counts["declined"])):
        for _ in range(n):
            receipts.append({
                "record_hash": "sha256:" + _hl.sha256(f"seed-{label}-{i}".encode()).hexdigest(),
                "agent_id": ident.id, "site_id": "SEEDED-DEMO-SITE",
                "classification": classification, "target": "seeded.demo",
                "ts": utc_now(), "ch_sig": "ed25519:demo"})
            i += 1
    request_json("POST", f"{CH}/seed", {"receipts": receipts})
    print(f"console: seeded {label} (DEMO DATA)")


def setup_agents() -> dict[str, Identity]:
    """Enroll B/C, seed history if the clearinghouse has none, and
    register C's AI Passport (the real demo issuer, not a mock)."""
    reporter = Reporter(CH)
    idents: dict[str, Identity] = {}
    for label in ("B", "C"):
        ident = load_or_create(label)
        reporter.enroll(ident)
        idents[label] = ident
        if request_json("GET", f"{CH}/agents/{ident.id}/score")[1].get("score") is None:
            seed_history(label, ident)
    try:
        _, passport, _ = request_json("POST", f"{ISSUER}/issue",
                                      {"agent_id": idents["C"].id})
        _, body, _ = request_json("POST", f"{CH}/agents/{idents['C'].id}/passport",
                                  {"passport": passport})
        print(f"console: agent C passport {body.get('passport_status')}")
    except Exception as e:
        print(f"console: passport issuer unavailable ({e}); C runs on EyD alone")
    return idents


IDENTS = setup_agents()
app = FastAPI(title="EyD Judge Console")


@app.get("/")
def index():
    return FileResponse(Path(__file__).parent / "index.html")


@app.get("/api/agents")
def agents():
    out = []
    for key, meta in AGENTS.items():
        card = {**meta, "key": key, "agent_id": None, "enrolled_at": None,
                "score": None, "passport_detail": None}
        ident = IDENTS.get(key)
        if ident is not None:
            card["agent_id"] = ident.id
            _, info, _ = request_json("GET", f"{CH}/agents/{ident.id}")
            card["enrolled_at"] = info.get("enrolled_at")
            _, score, _ = request_json("GET", f"{CH}/agents/{ident.id}/score")
            card.update({k: score.get(k) for k in
                         ("score", "expected", "unexpected", "declined",
                          "unverified", "total", "first_seen", "last_seen")})
            if meta.get("passport"):
                _, standing, _ = request_json("GET", f"{CH}/agents/{ident.id}/standing")
                card["passport_detail"] = {
                    "issuer": standing.get("passport_issuer"),
                    "subject": standing.get("passport_subject"),
                    "status": standing.get("passport_status")}
        out.append(card)
    return {"agents": out, "site_url": SITE, "clearinghouse_url": CH}


@app.post("/api/boost")
async def boost(request: Request):
    key = (await request.json()).get("agent")
    if key not in AGENTS:
        return JSONResponse({"error": "unknown agent"}, status_code=400)
    ident = IDENTS.get(key)
    if ident is None:
        return {"ok": False, "score": None,
                "message": "Agent A has no EyD identity — there is no enrollment "
                           "for a score to attach to."}
    status, body, _ = request_json("POST", f"{CH}/agents/{ident.id}/boost", {"step": 0.1})
    if status != 200:
        return JSONResponse({"ok": False, "message": body.get("detail", "boost failed")},
                            status_code=502)
    return {"ok": True, "score": body.get("score"), "added": body.get("added"),
            "message": f"Demo boost applied (+{body.get('added')} demo receipts)."}


@app.get("/api/gates")
def get_gates():
    _, body, _ = request_json("GET", f"{SITE}/gates")
    return body


@app.post("/api/gates")
async def set_gates(request: Request):
    _, body, _ = request_json("POST", f"{SITE}/gates", await request.json())
    return body


@app.post("/api/tamper")
async def set_tamper(request: Request):
    _, body, _ = request_json("POST", f"{SITE}/tamper", await request.json())
    return body


@app.get("/api/ledger")
def ledger():
    _, body, _ = request_json("GET", f"{SITE}/dashboard")
    return {"company": body.get("company"), "actions": body.get("actions", [])[-60:]}


def _receipt_for(label: str) -> dict | None:
    chain_file = KEYS / label / "chain.jsonl"
    if not chain_file.exists():
        return None
    lines = [x for x in chain_file.read_text().splitlines() if x.strip()]
    if not lines:
        return None
    rh = compute_record_hash(json.loads(lines[-1]))
    reporter = Reporter(CH)
    receipt = reporter.get_receipt(rh)
    if receipt is None:  # close the window so the classification lands
        request_json("POST", f"{CH}/sweep?now={time.time() + 601}", {})
        receipt = reporter.get_receipt(rh)
    return receipt


@app.post("/api/act")
async def act(request: Request):
    payload = await request.json()
    key, action = payload.get("agent"), payload.get("action")
    if key not in AGENTS or action not in ACTIONS:
        return JSONResponse({"error": "unknown agent or action"}, status_code=400)
    spec = ACTIONS[action]
    fn = _tool_fn(action)
    ident = IDENTS.get(key)
    if ident is not None:  # fresh tool table per click: gates always re-checked
        eyd = EyD.load(KEYS / f"{key}.json", clearinghouse=CH,
                       chain_path=KEYS / key / "chain.jsonl")
        fn = eyd.tool(verb=spec["verb"], target="localhost")(fn)

    try:
        resp = call_model([{"role": "user", "content": spec["task"]}], spec["tool"])
    except Exception as e:
        return JSONResponse({"error": f"model call failed: {e}"}, status_code=502)

    said, tool_call, result = [], None, None
    for block in resp.get("content", []):
        if block.get("type") == "text":
            said.append(block["text"])
        elif block.get("type") == "tool_use":
            tool_call = {"name": block["name"], "input": block.get("input", {})}
            result = fn(**{k: v for k, v in tool_call["input"].items()
                           if isinstance(v, str)})
    out = {"agent": key, "action": action, "task": spec["task"],
           "agent_said": " ".join(said), "tool_call": tool_call,
           "request_line": spec["request_line"], "http_status": None,
           "response_body": None, "receipt": None,
           "note": None}
    if result is None:
        out["note"] = "The model answered without calling the tool."
        return out
    out["http_status"] = result.status
    try:
        out["response_body"] = json.loads(result.body)
    except Exception:
        out["response_body"] = result.body
    if ident is None:
        out["note"] = ("Agent A has no EyD identity: nothing was signed or "
                       "reported, so no receipt exists for this action.")
    else:
        out["receipt"] = _receipt_for(key)
        if out["receipt"] is None:
            out["note"] = "No receipt yet — the clearinghouse has not paired both reports."
    return out


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=os.environ.get("HOST", "127.0.0.1"),
                port=int(os.environ.get("CONSOLE_PORT", "8080")))
