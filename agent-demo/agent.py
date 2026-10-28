"""Demo agent (§3.8) — one Meta-model agent, three identities.

A plain Python tool loop stands in for a framework. The model code
below is identical across all three agents; the only difference is
the framework's tool table:

  A:  tools undecorated                        (no key, no enrollment)
  B:  tools carry @eyd.tool with key B         (seeded score ~0.4)
  C:  tools carry @eyd.tool with key C         (seeded score ~0.97)

The model never sees a difference: same tool name, same arguments,
same results. EyD sits in the framework's tool-call path and passes
its headers into the call; the tool's transport attaches them.

The judge console (console/) drives this agent; standalone usage:
  python agent-demo/agent.py --url http://localhost:8001/quote
  python agent-demo/agent.py --eyd-identity .keys/B.json --url ...
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

TOOL_SCHEMA = {
    "name": "submit_quote_request",
    "description": "Submit a quote request to a vendor site",
    "input_schema": {"type": "object",
                     "properties": {"need": {"type": "string"}}, "required": ["need"]},
}
DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))


@dataclass
class HttpResult:
    status: int
    body: str
    headers: dict = field(default_factory=dict)


def call_model(messages: list[dict], tool: dict | None = None) -> dict:
    base = os.environ["ANTHROPIC_BASE_URL"].rstrip("/")
    payload = {"model": os.environ.get("ANTHROPIC_MODEL", "muse-wonder-1.0"),
               "max_tokens": 1024, "tools": [tool or TOOL_SCHEMA], "messages": messages}
    req = urllib.request.Request(
        base + "/v1/messages", data=json.dumps(payload).encode(), method="POST",
        headers={"Content-Type": "application/json",
                 "x-api-key": os.environ.get("ANTHROPIC_AUTH_TOKEN", ""),
                 "Authorization": f"Bearer {os.environ.get('ANTHROPIC_AUTH_TOKEN', '')}",
                 "anthropic-version": "2023-06-01"})
    with DIRECT.open(req, timeout=60) as r:
        return json.loads(r.read())


def make_submit_quote_request(vendor_url: str):
    """The agent's one tool. Its transport attaches whatever headers
    the framework passes into the call (none for agent A)."""

    def submit_quote_request(need: str) -> HttpResult:
        from eyd import current_headers

        headers = {"Content-Type": "application/json", **current_headers()}
        req = urllib.request.Request(
            vendor_url, data=json.dumps({"need": need}).encode(),
            method="POST", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return HttpResult(r.status, r.read().decode(), dict(r.headers))
        except urllib.error.HTTPError as e:
            return HttpResult(e.code, e.read().decode(), dict(e.headers))

    return submit_quote_request


def build_tool_table(vendor_url: str, eyd_identity: str | None,
                     clearinghouse: str):
    """Framework tool table — the only place A and B/C differ."""
    tool_fn = make_submit_quote_request(vendor_url)
    if eyd_identity is None:
        return {"submit_quote_request": tool_fn}  # A: undecorated
    from urllib.parse import urlparse

    from eyd import EyD

    identity_path = Path(eyd_identity)
    eyd = EyD.load(identity_path, clearinghouse=clearinghouse,
                   chain_path=identity_path.with_suffix("") / "chain.jsonl")
    target = urlparse(vendor_url).hostname or "local"
    return {"submit_quote_request": eyd.tool(verb="send", target=target)(tool_fn)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8001/quote")
    ap.add_argument("--eyd-identity", default=None,
                    help="framework config: decorate tools with @eyd.tool under this key")
    ap.add_argument("--clearinghouse", default="http://127.0.0.1:8787")
    ap.add_argument("task", nargs="?", default="Get me a quote for a landing page design")
    args = ap.parse_args()

    tools = build_tool_table(args.url, args.eyd_identity, args.clearinghouse)
    messages = [{"role": "user", "content": args.task}]
    for _ in range(4):
        resp = call_model(messages)
        messages.append({"role": "assistant", "content": resp["content"]})
        tool_results = []
        for block in resp["content"]:
            if block.get("type") == "text":
                print(block["text"], flush=True)
            elif block.get("type") == "tool_use":
                result = tools[block["name"]](**block["input"])
                body = result.body if isinstance(result, HttpResult) else str(result)
                print(f"[tool submit_quote_request] -> {body}", flush=True)
                tool_results.append({"type": "tool_result",
                                     "tool_use_id": block["id"], "content": body})
        if not tool_results:
            return 0
        messages.append({"role": "user", "content": tool_results})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
