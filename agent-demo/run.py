"""Agent demo — 3x3 matrix (§3.8–3.9).

One Meta-model agent happens at Day 6; this runner is the tool-calling
harness it will drive: the same "submit a quote request" action, run bare
(A) and via EyD with two keys (B: seeded score ~0.4, C: seeded ~0.97).
The agent code contains no reference to EyD — the only difference is
whether EyD's Dispatcher makes the call.

Prereqs: clearinghouse on :8787 and the three demo sites on :8001-8003.
Usage:  python agent-demo/run.py [--seed-only]
"""
from __future__ import annotations

import hashlib
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "verifier" / "python"))

from eyd.chain import LocalChain  # noqa: E402
from eyd.dispatch import Dispatcher  # noqa: E402
from eyd.identity import Identity  # noqa: E402
from eyd.records import utc_now  # noqa: E402
from eyd.reporter import Reporter, request_json  # noqa: E402

CH = "http://127.0.0.1:8787"
SITES = [("All Agents Welcome Inc", 8001), ("EyD Required LLC", 8002), ("Only Proven Agents PLC", 8003)]
KEYS = Path(__file__).parent / ".keys"
FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "history.json"
BODY = json.dumps({"need": "landing page design"}).encode()


def load_or_create(label: str) -> Identity:
    KEYS.mkdir(exist_ok=True)
    p = KEYS / f"{label}.json"
    if p.exists():
        return Identity.load(p)
    ident = Identity.generate()
    ident.save(p)
    return ident


def seed_history(reporter: Reporter, label: str, ident: Identity) -> None:
    counts = json.loads(FIXTURE.read_text())["agents"][label]
    receipts = []
    i = 0
    for classification, n in (("Expected", counts["expected"]),
                              ("Unexpected", counts["unexpected"]),
                              ("Declined", counts["declined"])):
        for _ in range(n):
            rh = "sha256:" + hashlib.sha256(f"seed-{label}-{i}".encode()).hexdigest()
            receipts.append({"record_hash": rh, "agent_id": ident.id,
                             "site_id": "SEEDED-DEMO-SITE", "classification": classification,
                             "target": "seeded.demo", "ts": utc_now(), "ch_sig": "ed25519:demo"})
            i += 1
    status, body, _ = request_json("POST", f"{CH}/seed", {"receipts": receipts})
    print(f"seeded {label}: {body} (DEMO DATA)")


def bare(url: str) -> tuple[int, str]:
    req = urllib.request.Request(url, data=BODY, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def main() -> int:
    reporter = Reporter(CH)
    agents: dict[str, Dispatcher] = {}
    for label in ("B", "C"):
        ident = load_or_create(label)
        reporter.enroll(ident)
        home = KEYS / label
        home.mkdir(exist_ok=True)
        chain = LocalChain(home / "chain.jsonl", ident)
        agents[label] = Dispatcher(chain, ident, reporter)
        if "--seed-only" in sys.argv or not (home / ".seeded").exists():
            seed_history(reporter, label, ident)
            (home / ".seeded").write_text("demo data seeded\n")
        score = request_json("GET", f"{CH}/agents/{ident.id}/score")[1]
        print(f"agent {label} {ident.id} score={score.get('score')}")

    if "--seed-only" in sys.argv:
        return 0

    rows = []
    pending: dict[int, str] = {}  # row index -> record_hash awaiting a receipt
    # A: bare, no EyD at all.
    for company, port in SITES:
        status, body = bare(f"http://localhost:{port}/quote")
        rows.append(["A (bare)", company, status, body.strip()[:60], "-"])
    # B and C via EyD.
    for label in ("B", "C"):
        for company, port in SITES:
            out = agents[label].execute_http("POST", f"http://localhost:{port}/quote", body=BODY)
            receipt = (out["receipt"] or {}).get("classification", "-")
            rows.append([label, company, out["status"], out["body"].decode()[:60], receipt])
            if receipt == "-":
                pending[len(rows) - 1] = out["record_hash"]
    # Tamper run: C against Required with the toggle on.
    request_json("POST", "http://localhost:8002/tamper", {"on": True})
    out = agents["C"].execute_http("POST", "http://localhost:8002/quote", body=BODY)
    request_json("POST", "http://localhost:8002/tamper", {"on": False})
    rows.append(["C (tamper)", "EyD Required LLC", out["status"], out["body"].decode()[:60],
                 (out["receipt"] or {}).get("classification", "-")])

    # Close the pairing window so one-sided actions (Welcome never
    # reports) settle as Unverified, as they would after 10 min live.
    import time as _time
    request_json("POST", f"{CH}/sweep?now={_time.time() + 601}", {})
    for idx, rh in pending.items():
        receipt = reporter.get_receipt(rh)
        if receipt:
            rows[idx][4] = receipt["classification"]

    print(f"\n{'agent':<12} {'site':<26} {'http':<5} {'classification':<15} body")
    for agent, company, status, body, cls in rows:
        print(f"{agent:<12} {company:<26} {status:<5} {cls:<15} {body}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
