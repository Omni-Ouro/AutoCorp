"""Clearinghouse reference — single node (PROOF v0 §3.5).

Stores hashes, signatures, timestamps, classifications, and the
counterparty of each action. Never inputs, outputs, or tool arguments.

Run from repo root:  uvicorn main:app --app-dir clearinghouse-ref --port 8787
"""
from __future__ import annotations

import base64
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import FastAPI, HTTPException  # noqa: E402

from classify import classify, compute_score  # noqa: E402
from eyd.canonical import hash_obj, record_hash  # noqa: E402
from eyd.identity import Identity, derive_id, verify_b64  # noqa: E402
from eyd.records import utc_now  # noqa: E402

WINDOW_SECONDS = int(os.environ.get("CH_WINDOW_SECONDS", "600"))
MIN_RECEIPTS = int(os.environ.get("POT_MIN_RECEIPTS", "5"))

app = FastAPI(title="EyD Clearinghouse (reference)", version="0.1")


def _load_ch_identity() -> Identity:
    key_file = os.environ.get("CLEARINGHOUSE_KEY_FILE")
    if key_file and Path(key_file).exists():
        return Identity.load(Path(key_file))
    ident = Identity.generate(kind="site")
    if key_file:
        ident.save(Path(key_file))
    return ident


CH = _load_ch_identity()

# In-memory single-node store. Keys are record_hash unless noted.
agents: dict[str, dict] = {}   # agent_id -> {pubkey, enrolled_at, domain?, forked}
sites: dict[str, dict] = {}    # site_id -> {pubkey, enrolled_at, domain?}
intents: dict[str, dict] = {}  # record_hash -> intent + state + opened_at (epoch)
agent_reports: dict[str, dict] = {}
site_reports: dict[str, dict] = {}
receipts: dict[str, dict] = {}  # record_hash -> receipt
dropped_site_reports: list[dict] = []
seq_seen: dict[tuple[str, int], str] = {}  # (agent_id, seq) -> record_hash (fork detection)


def _ts_epoch(ts: str) -> float:
    try:
        return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
    except Exception:
        return datetime.now(timezone.utc).timestamp()


def _pubkey_raw(pubkey_b64: str) -> bytes:
    return base64.b64decode(pubkey_b64)


def _verify_signed(payload: dict, pubkey_b64: str) -> bool:
    return verify_b64(_pubkey_raw(pubkey_b64), record_hash(payload).encode(), payload.get("sig", ""))


def issue_receipt(record_hash_: str) -> dict | None:
    intent = intents.get(record_hash_)
    if intent is None:
        return receipts.get(record_hash_)
    agent_id = intent["agent_id"]
    if agents.get(agent_id, {}).get("forked"):
        return None  # forked: score frozen, no receipts (§3.3)
    agent_rep = agent_reports.get(record_hash_)
    site_rep = site_reports.get(record_hash_)
    classification = classify(agent_rep, site_rep)
    receipt = {
        "record_hash": record_hash_,
        "agent_id": agent_id,
        "classification": classification,
        "ts": utc_now(),
    }
    if site_rep is not None:
        receipt["site_id"] = site_rep["site_id"]
        receipt["site_hash"] = site_rep.get("result_hash")
    if agent_rep is not None:
        receipt["agent_hash"] = agent_rep.get("output_hash")
    receipt["ch_sig"] = CH.sign(record_hash(receipt).encode())
    receipts[record_hash_] = receipt
    intents[record_hash_]["state"] = "receipted"
    return receipt


def maybe_issue(record_hash_: str) -> dict | None:
    """Issue as soon as both reports are in; otherwise wait for sweep."""
    if record_hash_ in agent_reports and record_hash_ in site_reports:
        return issue_receipt(record_hash_)
    return receipts.get(record_hash_)


@app.get("/")
def health():
    return {"service": "eyd-clearinghouse-ref", "pubkey": CH.pubkey_b64, "ch_id": CH.id}


@app.get("/pubkey")
def pubkey():
    return {"pubkey": CH.pubkey_b64}


@app.post("/enroll")
def enroll(payload: dict):
    kind = payload.get("kind")
    pid = payload.get("agent_id") or payload.get("site_id") or payload.get("id")
    pub = payload.get("pubkey", "")
    if kind not in ("agent", "site") or not pid or not pub:
        raise HTTPException(400, "need kind, id, pubkey")
    try:
        if derive_id(_pubkey_raw(pub)) != pid:
            raise HTTPException(400, "id does not derive from pubkey")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(400, "bad pubkey")
    if not _verify_signed(payload, pub):
        raise HTTPException(400, "bad signature")
    registry = agents if kind == "agent" else sites
    existing = registry.get(pid)
    if existing and existing["pubkey"] != pub:
        raise HTTPException(409, "id already enrolled with a different pubkey")
    if any(v["pubkey"] == pub and k != pid for k, v in registry.items()):
        raise HTTPException(409, "pubkey already enrolled")
    entry = {"pubkey": pub, "enrolled_at": payload.get("ts") or utc_now()}
    if payload.get("domain"):
        entry["domain"] = payload["domain"]
    if kind == "agent":
        entry["forked"] = existing.get("forked", False) if existing else False
    registry[pid] = entry
    return {"id": pid, "kind": kind, "enrolled": True}


@app.get("/agents/{agent_id}")
def get_agent(agent_id: str):
    entry = agents.get(agent_id)
    if not entry:
        raise HTTPException(404, "unknown agent")
    return {"agent_id": agent_id, **entry}


@app.get("/sites/{site_id}")
def get_site(site_id: str):
    entry = sites.get(site_id)
    if not entry:
        raise HTTPException(404, "unknown site")
    return {"site_id": site_id, **entry}


@app.post("/intents")
def post_intent(payload: dict):
    agent_id = payload.get("agent_id")
    entry = agents.get(agent_id or "")
    if not entry:
        raise HTTPException(404, "unknown agent")
    if not _verify_signed(payload, entry["pubkey"]):
        raise HTTPException(400, "bad signature")
    rh = payload.get("record_hash")
    seq = int(payload.get("seq", 0))
    # Fork detection: same seq, different record_hash (§3.3).
    prior = seq_seen.get((agent_id, seq))
    if prior is not None and prior != rh:
        agents[agent_id]["forked"] = True
        raise HTTPException(409, "forked: same seq, different record_hash")
    seq_seen[(agent_id, seq)] = rh
    intents[rh] = {**payload, "state": "pending", "opened_at": _ts_epoch(payload.get("ts", ""))}
    return {"record_hash": rh, "state": "pending"}


@app.post("/reports/agent")
def post_agent_report(payload: dict):
    rh = payload.get("record_hash")
    intent = intents.get(rh or "")
    if not intent:
        raise HTTPException(404, "unknown record_hash (no intent)")
    entry = agents.get(intent["agent_id"])
    if not entry or not _verify_signed(payload, entry["pubkey"]):
        raise HTTPException(400, "bad signature")
    # Agent reports carry no agent_id in v0; bind via the intent.
    agent_reports[rh] = payload
    if intents[rh]["state"] == "pending":
        intents[rh]["state"] = "awaiting_counterparty"
    receipt = maybe_issue(rh)
    return {"record_hash": rh, "receipt": receipt}


@app.post("/reports/site")
def post_site_report(payload: dict):
    rh = payload.get("record_hash")
    site_id = payload.get("site_id")
    entry = sites.get(site_id or "")
    if not entry:
        raise HTTPException(404, "unknown site (unenrolled site reports are rejected)")
    if not _verify_signed(payload, entry["pubkey"]):
        raise HTTPException(400, "bad signature")
    intent = intents.get(rh or "")
    if intent is None:
        dropped_site_reports.append({**payload, "reason": "no intent"})
        raise HTTPException(404, "unknown record_hash (no intent)")
    # Pair only if the site resolves to the intent's target (§3.5).
    target = intent.get("target")
    if not (target == site_id or target == entry.get("domain") or target == "local"):
        dropped_site_reports.append({**payload, "reason": f"target mismatch: intent target={target}"})
        raise HTTPException(403, "site does not resolve to intent target")
    if payload.get("agent_id") != intent["agent_id"]:
        raise HTTPException(400, "agent_id does not match intent")
    site_reports[rh] = payload  # several reports / one record_hash pair as one action
    receipt = maybe_issue(rh)
    return {"record_hash": rh, "receipt": receipt}


@app.get("/receipts/{record_hash_}")
def get_receipt(record_hash_: str):
    receipt = receipts.get(record_hash_)
    if not receipt:
        raise HTTPException(404, "no receipt issued yet")
    return receipt


@app.get("/agents/{agent_id}/head")
def agent_head(agent_id: str):
    if agent_id not in agents:
        raise HTTPException(404, "unknown agent")
    seqs = [s for (a, s) in seq_seen if a == agent_id]
    if not seqs:
        return {"agent_id": agent_id, "seq": 0, "record_hash": None}
    latest = max(seqs)
    return {"agent_id": agent_id, "seq": latest, "record_hash": seq_seen[(agent_id, latest)]}


@app.get("/agents/{agent_id}/score")
def agent_score(agent_id: str):
    if agent_id not in agents:
        raise HTTPException(404, "unknown agent")
    classes = []
    first = last = None
    for rh, receipt in receipts.items():
        if receipt["agent_id"] != agent_id:
            continue
        if intents.get(rh, {}).get("target") == "local":
            continue  # local actions never affect the score
        classes.append(receipt["classification"])
        ts = receipt["ts"]
        first = ts if first is None or ts < first else first
        last = ts if last is None or ts > last else last
    result = compute_score(classes, min_receipts=MIN_RECEIPTS)
    result.update({"agent_id": agent_id, "first_seen": first, "last_seen": last,
                   "forked": agents[agent_id].get("forked", False)})
    return result


@app.post("/sweep")
def sweep(now: float | None = None):
    """Close expired windows: Unverified if only one report; reissue on late reports."""
    now = now if now is not None else datetime.now(timezone.utc).timestamp()
    issued = []
    for rh, intent in list(intents.items()):
        if intent["state"] == "receipted":
            continue
        if now - intent["opened_at"] >= WINDOW_SECONDS:
            receipt = issue_receipt(rh)
            if receipt:
                issued.append(receipt)
    return {"issued": issued, "count": len(issued)}


@app.post("/seed")
def seed(payload: dict):
    """Load demo fixture receipts (DEMO DATA — see fixtures/README.md)."""
    count = 0
    for item in payload.get("receipts", []):
        # Fixtures are unsigned demo history: enroll stub parties on first sight.
        for kind, registry, key in (("agent", agents, "agent_id"), ("site", sites, "site_id")):
            pid = item.get(key)
            if pid and pid not in registry:
                registry[pid] = {"pubkey": item.get(f"{kind}_pubkey", ""), "enrolled_at": item.get("ts"),
                                 **({"forked": False} if kind == "agent" else {})}
        rh = item["record_hash"]
        intents[rh] = {"record_hash": rh, "agent_id": item["agent_id"],
                       "target": item.get("target", item.get("site_id", "seeded")),
                       "state": "receipted", "opened_at": _ts_epoch(item.get("ts", ""))}
        receipts[rh] = {k: v for k, v in item.items() if not k.endswith("_pubkey")}
        count += 1
    return {"seeded": count, "demo_data": True}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", "8787")))
