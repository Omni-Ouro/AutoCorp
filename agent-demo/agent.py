"""Demo agent (§3.8) — one agent, three identities.

A plain tool-using agent on Meta models: given a task, the model picks
the `submit_quote_request` tool, the tool posts to a vendor site, the
model reports back. This file contains no reference to EyD, receipts,
or identity — there is nothing EyD-shaped to reference.

The only difference between demo runs is how this file is launched:
  A:  python agent-demo/agent.py --url http://localhost:8002/quote
  B:  eyd run --identity agent-demo/.keys/B.json -- python agent-demo/agent.py --url ...
  C:  eyd run --identity agent-demo/.keys/C.json -- python agent-demo/agent.py --url ...

Model: Meta model API (Anthropic Messages format) via
$ANTHROPIC_BASE_URL / $ANTHROPIC_AUTH_TOKEN / $ANTHROPIC_MODEL.
The model client connects directly (it is not a tool); the quote tool
uses the process's default HTTP routing, like any agent tool would.
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request

TOOL = {
    "name": "submit_quote_request",
    "description": "Submit a quote request to a vendor site",
    "input_schema": {"type": "object",
                     "properties": {"need": {"type": "string"}}, "required": ["need"]},
}
DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def call_model(messages: list[dict]) -> dict:
    base = os.environ["ANTHROPIC_BASE_URL"].rstrip("/")
    payload = {"model": os.environ.get("ANTHROPIC_MODEL", "muse-wonder-1.0"),
               "max_tokens": 1024, "tools": [TOOL], "messages": messages}
    req = urllib.request.Request(
        base + "/v1/messages", data=json.dumps(payload).encode(), method="POST",
        headers={"Content-Type": "application/json",
                 "x-api-key": os.environ.get("ANTHROPIC_AUTH_TOKEN", ""),
                 "Authorization": f"Bearer {os.environ.get('ANTHROPIC_AUTH_TOKEN', '')}",
                 "anthropic-version": "2023-06-01"})
    with DIRECT.open(req, timeout=60) as r:
        return json.loads(r.read())


def submit_quote_request(need: str, url: str) -> str:
    """The agent's one tool: submit a quote request to the vendor."""
    req = urllib.request.Request(
        url, data=json.dumps({"need": need}).encode(), method="POST",
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.read().decode()
    except urllib.error.HTTPError as e:
        return e.read().decode()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8002/quote",
                    help="vendor quote endpoint")
    ap.add_argument("task", nargs="?", default="Get me a quote for a landing page design")
    args = ap.parse_args()

    messages = [{"role": "user", "content": args.task}]
    for _ in range(4):
        resp = call_model(messages)
        messages.append({"role": "assistant", "content": resp["content"]})
        tool_results = []
        for block in resp["content"]:
            if block.get("type") == "text":
                print(block["text"], flush=True)
            elif block.get("type") == "tool_use":
                result = submit_quote_request(block["input"]["need"], args.url)
                print(f"[tool submit_quote_request] -> {result}", flush=True)
                tool_results.append({"type": "tool_result",
                                     "tool_use_id": block["id"], "content": result})
        if not tool_results:
            return 0
        messages.append({"role": "user", "content": tool_results})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
