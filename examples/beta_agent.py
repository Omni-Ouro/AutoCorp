"""Test the EyD beta as an agent — no model, no API key, five minutes.

This is what an agent installs: the EyD SDK, one identity, tools
decorated once. Every call is signed, reported to the Clearing House
*before* it runs, and paired with the business's report after; you get
a signed Proof Receipt and a PoT score that gates the next call.

    pip install git+https://github.com/Omni-Ouro/AutoCorp.git
    python examples/beta_agent.py

It acts against the Omni-Ouro playground (eyd.omni-ouro.com), a real
business endpoint running the verifier SDK: search is open, the pitch
deck needs EyD, a meeting needs PoT >= 0.8. Watch the meeting get
refused while your score is unknown, then admitted once your clean
actions earn one. Your identity persists (--key), so a second run
starts from the score you built.

Local stack instead:  --site http://127.0.0.1:8002
                      --clearinghouse http://127.0.0.1:8787
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # clone-friendly

from eyd import current_headers  # noqa: E402
from eyd.canonical import record_hash
from eyd.identity import Identity
from eyd.reporter import Reporter, request_json
from eyd.sdk import EyD, ToolResult


def http(method: str, url: str, payload: dict | None = None) -> ToolResult:
    headers = {"Content-Type": "application/json", **current_headers()}
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return ToolResult(r.status, r.read().decode(), dict(r.headers))
    except urllib.error.HTTPError as e:
        return ToolResult(e.code, e.read().decode(), dict(e.headers))


def main() -> int:
    ap = argparse.ArgumentParser(description="EyD beta — agent quickstart")
    ap.add_argument("--site", default="https://eyd.omni-ouro.com",
                    help="the business endpoint (playground by default)")
    ap.add_argument("--clearinghouse", default="https://clearinghouse.omni-ouro.com",
                    help="the EyD Clearing House")
    ap.add_argument("--key", default=str(Path.home() / ".eyd-beta" / "agent.json"),
                    help="identity file (created on first run, then reused)")
    args = ap.parse_args()

    key_path = Path(args.key)
    if not key_path.exists():
        Identity.generate().save(key_path)
        print(f"new EyD identity saved to {key_path}")
    chain_path = key_path.parent / "chain.jsonl"
    try:
        eyd = EyD.load(key_path, clearinghouse=args.clearinghouse,
                       chain_path=chain_path)
    except Exception as e:
        print(f"cannot reach the Clearing House at {args.clearinghouse}: {e}")
        return 1
    reporter = Reporter(args.clearinghouse)
    host = urllib.parse.urlparse(args.site).hostname or "local"
    print(f"agent_id {eyd.identity.id}\nsite {args.site} · "
          f"clearinghouse {args.clearinghouse}\n")

    @eyd.tool(verb="browse", target=host)
    def search_products(query: str) -> ToolResult:
        return http("GET", f"{args.site}/search?" + urllib.parse.urlencode({"q": query}))

    @eyd.tool(verb="send", target=host)
    def request_pitch_deck(topic: str) -> ToolResult:
        return http("POST", f"{args.site}/deck", {"topic": topic})

    @eyd.tool(verb="send", target=host)
    def request_meeting(topic: str) -> ToolResult:
        return http("POST", f"{args.site}/meeting", {"topic": topic})

    def receipt() -> dict | None:
        lines = [x for x in chain_path.read_text().splitlines() if x.strip()]
        if not lines:
            return None
        rh = record_hash(json.loads(lines[-1]))
        rec = reporter.get_receipt(rh)
        if rec is None:  # close the window so the classification lands
            request_json("POST", f"{args.clearinghouse}/sweep?now={time.time() + 601}", {})
            rec = reporter.get_receipt(rh)
        return rec

    def step(label: str, fn, *a) -> None:
        result = fn(*a)
        rec = receipt()
        try:
            body = json.loads(result.body)
        except Exception:
            body = {}
        detail = body.get("reason") or body.get("status") or ""
        score = (rec or {}).get("score_after")
        print(f"{label:<34} HTTP {result.status} {detail:<28} "
              f"receipt: {(rec or {}).get('classification', '—'):<10} "
              f"score: {score if score is not None else 'unknown'}")

    step("search 'agent accountability'", search_products, "agent accountability")
    step("request pitch deck", request_pitch_deck, "Eyro")
    step("request a meeting (too early)", request_meeting, "EyD beta")
    print("  … a fresh agent has no score yet. Earn one with clean actions:")
    step("search 'egress'", search_products, "egress")
    step("request pitch deck", request_pitch_deck, "Glove")
    step("request pitch deck", request_pitch_deck, "Eyro Mini")
    step("request a meeting (score earned)", request_meeting, "EyD beta")

    _, score, _ = request_json("GET", f"{args.clearinghouse}/agents/{eyd.identity.id}/score")
    print(f"\nPoT score now: {score.get('score')} "
          f"({score.get('expected')} Expected / {score.get('declined')} Declined"
          f" of {score.get('total')} receipts). Your agent is enrolled at the "
          f"Clearing House — run this again and it starts from this score.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
