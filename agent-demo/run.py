"""Deterministic 3x3 matrix (§3.9) without LLM calls.

Same tool the LLM agent uses, driven directly through the framework
tool table: A's tool undecorated, B/C decorated with @eyd.tool under
their keys. For the live LLM version see run_agents.py.

Prereqs: clearinghouse :8787, demo sites :8001-8003.
Usage: python agent-demo/run.py
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent import HttpResult, make_submit_quote_request  # noqa: E402  (agent-demo/agent.py)
from eyd import EyD  # noqa: E402
from eyd.canonical import record_hash  # noqa: E402
from eyd.identity import Identity  # noqa: E402
from eyd.records import utc_now  # noqa: E402
from eyd.reporter import Reporter, request_json  # noqa: E402

CH = "http://127.0.0.1:8787"
ISSUER = "http://127.0.0.1:8010"
SITES = [("All Agents Welcome Inc", 8001), ("EyD Required LLC", 8002), ("Only Proven Agents PLC", 8003)]
KEYS = Path(__file__).parent / ".keys"
FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "history.json"
NEED = "landing page design"


def load_or_create(label: str) -> Identity:
    KEYS.mkdir(exist_ok=True)
    p = KEYS / f"{label}.json"
    if p.exists():
        return Identity.load(p)
    ident = Identity.generate()
    ident.save(p)
    return ident


def seed_history(label: str, ident: Identity) -> None:
    counts = json.loads(FIXTURE.read_text())["agents"][label]
    receipts, i = [], 0
    for classification, n in (("Expected", counts["expected"]),
                              ("Unexpected", counts["unexpected"]),
                              ("Declined", counts["declined"])):
        for _ in range(n):
            receipts.append({
                "record_hash": "sha256:" + hashlib.sha256(f"seed-{label}-{i}".encode()).hexdigest(),
                "agent_id": ident.id, "site_id": "SEEDED-DEMO-SITE",
                "classification": classification, "target": "seeded.demo",
                "ts": utc_now(), "ch_sig": "ed25519:demo"})
            i += 1
    _, body, _ = request_json("POST", f"{CH}/seed", {"receipts": receipts})
    print(f"seeded {label}: {body} (DEMO DATA)")


def ensure_passport(label: str, ident: Identity) -> bool:
    """Combined tier: B/C also hold AI Passports, registered at the
    clearinghouse. Passport alone would not suffice anywhere."""
    try:
        _, passport, _ = request_json("POST", f"{ISSUER}/issue", {"agent_id": ident.id})
        _, body, _ = request_json("POST", f"{CH}/agents/{ident.id}/passport",
                                  {"passport": passport})
        print(f"passport {label}: {body.get('passport_status')} "
              f"(subject {body.get('subject', '')[:8]}…)")
        return body.get("passport_status") == "valid"
    except Exception as e:
        print(f"passport {label}: issuer unavailable ({e}); "
              "EyD Required LLC will refuse — start passport-demo/issuer.py")
        return False


def bare_tool(url: str):
    return {"submit_quote_request": make_submit_quote_request(url)}


def eyd_tool(url: str, label: str, ident: Identity):
    chain_path = KEYS / label / "chain.jsonl"
    eyd = EyD.load(KEYS / f"{label}.json", clearinghouse=CH, chain_path=chain_path)
    from urllib.parse import urlparse
    fn = make_submit_quote_request(url)
    return {"submit_quote_request": eyd.tool(verb="send", target=urlparse(url).hostname)(fn)}, eyd


def latest_receipt(label: str, reporter: Reporter) -> str:
    chain_file = KEYS / label / "chain.jsonl"
    lines = [x for x in chain_file.read_text().splitlines() if x.strip()]
    rh = record_hash(json.loads(lines[-1]))
    receipt = reporter.get_receipt(rh)
    if receipt is None:
        request_json("POST", f"{CH}/sweep?now={time.time() + 601}", {})
        receipt = reporter.get_receipt(rh)
    return (receipt or {}).get("classification", "-")


def main() -> int:
    reporter = Reporter(CH)
    idents, seeded = {}, {}
    for label in ("B", "C"):
        ident = load_or_create(label)
        reporter.enroll(ident)
        idents[label] = ident
        # Seed unless the clearinghouse already holds the history (its
        # store is in-memory; a restart needs the demo data reloaded).
        seeded[label] = request_json("GET", f"{CH}/agents/{ident.id}/score")[1].get("score")
        if seeded[label] is None:
            seed_history(label, ident)
            (KEYS / label).mkdir(exist_ok=True)
            (KEYS / label / ".seeded").write_text("demo data seeded\n")
            seeded[label] = request_json("GET", f"{CH}/agents/{ident.id}/score")[1].get("score")
        print(f"agent {label} {ident.id} score={seeded[label]}")
        ensure_passport(label, ident)

    rows = []
    for company, port in SITES:  # A bare
        result = bare_tool(f"http://localhost:{port}/quote")["submit_quote_request"](need=NEED)
        rows.append(["A (bare)", company, result.status, result.body[:60], "-"])
    for label in ("B", "C"):
        for company, port in SITES:
            tools, _eyd = eyd_tool(f"http://localhost:{port}/quote", label, idents[label])
            result = tools["submit_quote_request"](need=NEED)
            rows.append([label, company, result.status, result.body[:60],
                         latest_receipt(label, reporter)])
    # Tamper run
    request_json("POST", "http://localhost:8002/tamper", {"on": True})
    tools, _ = eyd_tool("http://localhost:8002/quote", "C", idents["C"])
    result = tools["submit_quote_request"](need=NEED)
    request_json("POST", "http://localhost:8002/tamper", {"on": False})
    rows.append(["C (tamper)", "EyD Required LLC", result.status, result.body[:60],
                 latest_receipt("C", reporter)])
    # Revoked Passport run: EyD still valid, Passport revoked -> refused.
    try:
        request_json("POST", f"{ISSUER}/revoke", {"agent_id": idents["C"].id, "revoked": True})
        tools, _ = eyd_tool("http://localhost:8002/quote", "C", idents["C"])
        result = tools["submit_quote_request"](need=NEED)
        rows.append(["C (revoked)", "EyD Required LLC", result.status, result.body[:60],
                     latest_receipt("C", reporter)])
        request_json("POST", f"{ISSUER}/revoke", {"agent_id": idents["C"].id, "revoked": False})
    except Exception as e:
        print(f"revoked-passport run skipped: {e}")

    print(f"\n{'agent':<12} {'site':<26} {'http':<5} {'classification':<15} body")
    for agent, company, status, body, cls in rows:
        print(f"{agent:<12} {company:<26} {status:<5} {cls:<15} {body}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
