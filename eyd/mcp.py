"""MCP proxy mode (§3.1, second way in).

The agent's framework points at EyD's MCP endpoint instead of the real
tool servers. EyD signs + reports intent, forwards the call unmodified,
hashes the result, reports the outcome, and returns the result
unmodified. The agent never learns EyD exists.

Two forms:
- standalone: EyD itself exposes http.get / http.post tools.
- upstream proxy (`--upstream <cmd>`): EyD fronts a real MCP server
  process and intercepts every tools/call.

Transport: newline-delimited JSON-RPC 2.0 over stdio (MCP stdio).
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from urllib.parse import urlparse

from .canonical import record_hash
from .chain import LocalChain
from .dispatch import VERB_MAP, Dispatcher
from .identity import Identity
from .records import build_agent_report
from .reporter import Reporter

PROTOCOL = "2024-11-05"
STANDALONE_TOOLS = [
    {"name": "http.get", "description": "GET a URL",
     "inputSchema": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}},
    {"name": "http.post", "description": "POST a JSON body to a URL",
     "inputSchema": {"type": "object", "properties": {"url": {"type": "string"}, "body": {"type": "object"}}, "required": ["url"]}},
]


def verb_for_tool(tool: str) -> str:
    if tool in VERB_MAP:
        return VERB_MAP[tool]
    t = tool.lower()
    if "pay" in t or "charge" in t:
        return "pay"
    if "send" in t or "post" in t or "submit" in t:
        return "send"
    if "get" in t or "read" in t or "list" in t or "fetch" in t:
        return "read"
    if "write" in t or "put" in t or "create" in t or "update" in t:
        return "write"
    if "browse" in t or "search" in t:
        return "browse"
    return "execute"


def target_for(tool: str, arguments: dict) -> str:
    url = arguments.get("url")
    if isinstance(url, str):
        return urlparse(url).hostname or "local"
    return str(arguments.get("target") or "local")


class McpEydServer:
    def __init__(self, chain: LocalChain, identity: Identity,
                 reporter: Reporter | None = None, upstream_cmd: list[str] | None = None):
        self.chain = chain
        self.identity = identity
        self.reporter = reporter
        self.dispatcher = Dispatcher(chain, identity, reporter)
        self.upstream = None
        if upstream_cmd:
            self.upstream = subprocess.Popen(
                upstream_cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                text=True, bufsize=1)

    # -- upstream plumbing ---------------------------------------------
    def _upstream_call(self, msg: dict) -> dict | None:
        assert self.upstream and self.upstream.stdin and self.upstream.stdout
        self.upstream.stdin.write(json.dumps(msg) + "\n")
        self.upstream.stdin.flush()
        if "id" not in msg:  # notification
            return None
        line = self.upstream.stdout.readline()
        return json.loads(line) if line else {"jsonrpc": "2.0", "id": msg.get("id"),
                                               "error": {"code": -32000, "message": "upstream closed"}}

    # -- JSON-RPC handling ----------------------------------------------
    def handle(self, msg: dict) -> dict | None:
        method = msg.get("method", "")
        mid = msg.get("id")
        if method == "initialize":
            if self.upstream:
                return self._upstream_call(msg)
            return self._ok(mid, {"protocolVersion": PROTOCOL,
                                  "capabilities": {"tools": {}},
                                  "serverInfo": {"name": "eyd", "version": "0.1"}})
        if method.startswith("notifications/"):
            if self.upstream:
                self._upstream_call(msg)
            return None
        if method == "ping":
            return self._ok(mid, {})
        if method == "tools/list":
            if self.upstream:
                return self._upstream_call(msg)
            return self._ok(mid, {"tools": STANDALONE_TOOLS})
        if method == "tools/call":
            return self._tools_call(msg)
        if self.upstream:
            return self._upstream_call(msg)
        return self._err(mid, -32601, f"method not found: {method}")

    def _tools_call(self, msg: dict) -> dict:
        mid = msg.get("id")
        params = msg.get("params") or {}
        tool = params.get("name", "")
        arguments = params.get("arguments") or {}

        if self.upstream:
            # Sign + report intent, forward unmodified, report outcome.
            record = self.chain.append(
                verb=verb_for_tool(tool), tool=tool,
                tool_input=arguments, target=target_for(tool, arguments))
            rec_hash = record_hash(record)
            if self.reporter:
                self.reporter.report_intent(self.identity, record)
            resp = self._upstream_call(msg)
            result = (resp or {}).get("result")
            report = build_agent_report(
                self.identity, rec_hash=rec_hash, output=result,
                status="error" if (resp and "error" in resp) else "ok")
            if self.reporter:
                self.reporter.report_agent(report)
            return resp if resp is not None else self._ok(mid, {})
        # Standalone: EyD executes the HTTP tool itself via the Dispatcher.
        url = arguments.get("url")
        if tool == "http.get" and url:
            out = self.dispatcher.execute_http("GET", url, tool=tool)
        elif tool == "http.post" and url:
            body = json.dumps(arguments.get("body") or {}).encode()
            out = self.dispatcher.execute_http("POST", url, body=body, tool=tool)
        else:
            return self._err(mid, -32602, f"unknown tool or missing url: {tool}")
        text = out["body"].decode(errors="replace")
        return self._ok(mid, {"content": [{"type": "text", "text": text}],
                              "isError": bool(out["status"] and out["status"] >= 400)})

    @staticmethod
    def _ok(mid, result):
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    @staticmethod
    def _err(mid, code, message):
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}

    # -- stdio loop --------------------------------------------------------
    def serve_stdio(self, instream=None, outstream=None) -> None:
        instream = instream or sys.stdin
        outstream = outstream or sys.stdout
        for line in instream:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            resp = self.handle(msg)
            if resp is not None:
                outstream.write(json.dumps(resp) + "\n")
                outstream.flush()


def run_mcp(identity: Identity, chain: LocalChain, reporter: Reporter | None,
            upstream: list[str] | None) -> int:
    McpEydServer(chain, identity, reporter, upstream_cmd=upstream).serve_stdio()
    return 0


def parse_upstream(value: str | None) -> list[str] | None:
    if not value:
        return None
    if os.name == "nt":
        # POSIX shlex mangles Windows backslash paths.
        return [p.strip('"') for p in shlex.split(value, posix=False)]
    return shlex.split(value)
