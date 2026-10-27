"""Run the demo agents (§3.8): one LLM agent, three identities.

  A  python agent-demo/agent.py                      (bare, no EyD)
  B  eyd run --identity .keys/B.json -- agent.py     (seeded score ~0.4)
  C  eyd run --identity .keys/C.json -- agent.py     (seeded score ~0.97)

The agent file is identical in every run and contains no EyD references.
Prereqs: clearinghouse :8787, demo sites :8001-8003, model API env set.

Usage: python agent-demo/run_agents.py [--tamper] [--task "..."]
Each cell is a real Meta-model run, so the full matrix takes a few minutes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from eyd.canonical import record_hash  # noqa: E402
from eyd.identity import Identity  # noqa: E402
from eyd.records import utc_now  # noqa: E402
from eyd.reporter import Reporter, request_json  # noqa: E402

CH = "http://127.0.0.1:8787"
SITES = [("All Agents Welcome Inc", 8001), ("EyD Required LLC", 8002), ("Only Proven Agents PLC", 8003)]
KEYS = Path(__file__).parent / ".keys"
FIXTURE = ROOT / "fixtures" / "history.json"


def load_or_create(label: str) -> Identity:
    KEYS.mkdir(exist_ok=True)
    p = KEYS / f"{label}.json"
    if p.exists():
        return Identity.load(p)
    ident = Identity.generate()
    ident.save(p)
    return ident


def ensure_seeded(label: str, ident: Identity) -> None:
    marker = KEYS / label / ".seeded"
    if marker.exists():
        return
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
    request_json("POST", f"{CH}/seed", {"receipts": receipts})
    marker.parent.mkdir(exist_ok=True)
    marker.write_text("demo data seeded\n")
    print(f"seeded {label} (DEMO DATA)")


def run_agent(label: str, url: str, task: str, ident: Identity | None) -> str:
    agent = str(Path(__file__).parent / "agent.py")
    if label == "A":
        cmd = [sys.executable, agent, "--url", url, task]
    else:
        cmd = ["eyd", "run", "--identity", str(KEYS / f"{label}.json"),
               "--chain", str(KEYS / label / "chain.jsonl"),
               "--clearinghouse", CH, "--",
               sys.executable, agent, "--url", url, task]
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=240, env=env,
                          encoding="utf-8", errors="replace")
    out = (proc.stdout or "").strip()
    print(f"--- agent {label} -> {url}\n{out}\n")
    return out


def latest_classification(label: str) -> str:
    chain_file = KEYS / label / "chain.jsonl"
    if not chain_file.exists():
        return "-"
    lines = [x for x in chain_file.read_text().splitlines() if x.strip()]
    if not lines:
        return "-"
    rh = record_hash(json.loads(lines[-1]))
    reporter = Reporter(CH)
    receipt = reporter.get_receipt(rh)
    if receipt is None:
        request_json("POST", f"{CH}/sweep?now={time.time() + 601}", {})
        receipt = reporter.get_receipt(rh)
    return (receipt or {}).get("classification", "-")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tamper", action="store_true", help="add the tamper run at the end")
    ap.add_argument("--task", default="Get me a quote for a landing page design")
    ap.add_argument("--only", default=None, help="single agent label: A, B or C")
    args = ap.parse_args()

    reporter = Reporter(CH)
    idents: dict[str, Identity | None] = {"A": None}
    for label in ("B", "C"):
        ident = load_or_create(label)
        reporter.enroll(ident)
        ensure_seeded(label, ident)
        idents[label] = ident
        score = request_json("GET", f"{CH}/agents/{ident.id}/score")[1].get("score")
        print(f"agent {label} {ident.id} seeded score={score}")

    rows = []
    for label in ("A", "B", "C"):
        if args.only and label != args.only:
            continue
        for company, port in SITES:
            run_agent(label, f"http://localhost:{port}/quote", args.task, idents[label])
            rows.append((label, company, "-" if label == "A" else latest_classification(label)))
    if args.tamper:
        request_json("POST", "http://localhost:8002/tamper", {"on": True})
        run_agent("C", "http://localhost:8002/quote", args.task, idents["C"])
        request_json("POST", "http://localhost:8002/tamper", {"on": False})
        rows.append(("C (tamper)", "EyD Required LLC", latest_classification("C")))

    print(f"\n{'agent':<12} {'site':<26} classification")
    for label, company, cls in rows:
        print(f"{label:<12} {company:<26} {cls}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
