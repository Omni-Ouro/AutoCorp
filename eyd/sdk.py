"""EyD SDK (§3.1) — a library the agent framework imports.

EyD is not a process, not a proxy, not a tool server. It sits in the
framework's tool-call path as a hook: before the call runs, EyD records
and reports; after it returns, EyD hashes the result and reports. The
framework author adds it once; every agent built on that framework is
covered. It has no authority and no policy. Governance is Eyro.

Integration, one of:
- `@eyd.tool` decorator on each tool function
- `eyd.wrap(tool_fn)` for frameworks that build tool tables at runtime
- `eyd.hook(framework)` for frameworks that expose tool-call middleware

Per call (§3.1): resolve verb -> build + sign Action Record -> append
to local chain -> report intent -> run the tool with EyD headers passed
in -> hash the return value -> report outcome -> receipt.

Headers are passed into the call through a context variable the tool's
transport reads via `eyd.current_headers()` (frameworks may also accept
them as an explicit argument). Tool lists, arguments and results seen
by the model are untouched.
"""
from __future__ import annotations

import contextvars
import functools
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .attestation import build_attestation
from .canonical import record_hash
from .chain import LocalChain
from .identity import Identity
from .records import build_agent_report
from .reporter import Reporter

VERBS = ("read", "write", "send", "browse", "execute", "pay")
VERB_MAP = {
    "http.get": "browse",
    "http.post": "send",
    "http.put": "write",
    "http.delete": "write",
    "file.read": "read",
    "file.write": "write",
    "code.execute": "execute",
    "pay.charge": "pay",
}


def verb_for_tool(tool: str) -> str:
    """Default verb inferred from the tool name (configurable per tool)."""
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


@dataclass
class ToolResult:
    """HTTP-like tool result. Tools that return one get attestation
    challenge handling and session capture; any other return value is
    hashed as-is."""

    status: int = 200
    body: bytes | str = b""
    headers: dict = field(default_factory=dict)

    def body_bytes(self) -> bytes:
        return self.body if isinstance(self.body, bytes) else str(self.body).encode()


_current_headers: contextvars.ContextVar[dict] = contextvars.ContextVar(
    "eyd_current_headers", default={})

# The framework passes the agent's current task into the hook (§3.11);
# only (task_hash, task_verb) are kept — never the task text.
_current_task: contextvars.ContextVar[tuple[str, str] | None] = contextvars.ContextVar(
    "eyd_current_task", default=None)


def current_headers() -> dict:
    """Headers EyD passes into the in-flight tool call (§3.1 step 4).

    A tool's transport attaches these to its outbound request. Outside
    a wrapped call this is empty, so undecorated tools are unaffected.
    """
    return dict(_current_headers.get())


def _target_for(args: tuple, kwargs: dict, explicit: str | Callable | None) -> str:
    if callable(explicit):
        return str(explicit(*args, **kwargs))
    if explicit:
        return str(explicit)
    url = kwargs.get("url")
    if not isinstance(url, str):
        for a in args:
            if isinstance(a, str) and a.startswith(("http://", "https://")):
                url = a
                break
    if isinstance(url, str):
        return urlparse(url).hostname or "local"
    return str(kwargs.get("target") or "local")


def _is_http_result(result: Any) -> bool:
    return hasattr(result, "status") and hasattr(result, "body")


def _result_body_bytes(result: Any) -> bytes:
    body = result.body
    return body if isinstance(body, bytes) else str(body).encode()


def _get_header(result: Any, name: str) -> str | None:
    """Case-insensitive header lookup — servers vary in casing
    (uvicorn sends lowercase), and result types vary by framework."""
    headers = getattr(result, "headers", None) or {}
    get = getattr(headers, "get", None)
    if callable(get):  # HTTPMessage / multidict style: already case-insensitive
        try:
            value = get(name)
        except Exception:
            value = None
        if value is not None:
            return value
    lowered = name.lower()
    for key, value in headers.items():
        if str(key).lower() == lowered:
            return value
    return None


class EyD:
    """One agent, one device, one key (EYD_DESIGN §7)."""

    def __init__(self, identity: Identity, *, chain: LocalChain,
                 reporter: Reporter | None = None):
        self.identity = identity
        self.chain = chain
        self.reporter = reporter
        self.sessions: dict[str, str] = {}  # target -> EyD-Session token
        self.last_receipt: dict[str, dict | None] = {}

    @classmethod
    def load(cls, identity_path: str | Path, *, clearinghouse: str | None = None,
             chain_path: str | Path | None = None,
             operator_id: str | None = None,
             integrator_id: str | None = None) -> "EyD":
        identity_path = Path(identity_path)
        identity = Identity.load(identity_path)
        chain = LocalChain(Path(chain_path) if chain_path else identity_path.parent / "chain.jsonl",
                           identity)
        reporter = Reporter(clearinghouse, operator_id=operator_id,
                            integrator_id=integrator_id) if clearinghouse else None
        if reporter:
            reporter.enroll(identity)
        return cls(identity, chain=chain, reporter=reporter)

    # -- integration: decorator ------------------------------------------
    def tool(self, fn: Callable | None = None, *, verb: str | None = None,
             target: str | Callable | None = None):
        """`@eyd.tool`, `@eyd.tool(verb="send")`, or `eyd.tool(fn, ...)`."""
        def decorate(f: Callable) -> Callable:
            return self.wrap(f, verb=verb, target=target)
        return decorate(fn) if fn is not None else decorate

    # -- integration: wrap a tool function --------------------------------
    def wrap(self, fn: Callable, *, verb: str | None = None,
             target: str | Callable | None = None) -> Callable:
        tool_name = getattr(fn, "__name__", "tool")
        resolved_verb = verb or verb_for_tool(tool_name)
        if resolved_verb not in VERBS:
            raise ValueError(f"verb must be one of {VERBS}")

        @functools.wraps(fn)
        def wrapped(*args, **kwargs):
            return self._invoke(fn, tool_name, resolved_verb, target, args, kwargs)

        wrapped.__eyd_tool__ = tool_name  # type: ignore[attr-defined]
        wrapped.__eyd_verb__ = resolved_verb  # type: ignore[attr-defined]
        return wrapped

    # -- integration: hook a framework's tool-call path -------------------
    def hook(self, framework):
        """Wrap a framework's tool execution.

        Accepts either an object with `execute_tool(name, fn, args)` or a
        plain callable `execute(name, fn, args) -> result`, and returns
        the hooked equivalent. Every tool the framework runs is recorded.
        """
        execute = getattr(framework, "execute_tool", framework)
        if not callable(execute):
            raise TypeError("framework must be callable or expose execute_tool(name, fn, args)")

        def hooked(name: str, fn: Callable, args: dict):
            return self._invoke(fn, name, verb_for_tool(name), None, (), dict(args))

        if hasattr(framework, "execute_tool"):
            framework.execute_tool = hooked  # type: ignore[method-assign]
            return framework
        return hooked

    # -- task context (deviation, §3.11) -----------------------------------
    def task_context(self, task: str, verb: str):
        """Mark the task the agent is currently serving, e.g.
        `with eyd.task_context("Pay invoice 2142.", "pay"):`. Action
        Records built inside carry `task_hash`/`task_verb`; the
        clearinghouse classifies verb ≠ task_verb as Deviated."""
        import contextlib

        from .canonical import hash_bytes

        @contextlib.contextmanager
        def _ctx():
            token = _current_task.set((hash_bytes(task.encode("utf-8")), verb))
            try:
                yield
            finally:
                _current_task.reset(token)

        return _ctx()

    # -- turnkey HTTP for tool bodies --------------------------------------
    def http(self, method: str, url: str, *, json_body=None, data: bytes | None = None,
             headers: dict | None = None, timeout: float = 15) -> ToolResult:
        """HTTP call with the EyD headers already attached.

        Inside an `@eyd.tool` function, `return eyd.http("POST", url, {...})`
        is the whole transport: the in-flight Action Record's headers
        (EyD-Agent / EyD-Record / EyD-Session / EyD-Attestation) ride
        along via current_headers(), and the ToolResult plugs straight
        into the SDK's receipt flow — no hand-wired headers.
        """
        import urllib.error
        import urllib.request

        hdrs = dict(headers or {})
        body = data
        if json_body is not None:
            body = json.dumps(json_body).encode()
            hdrs.setdefault("Content-Type", "application/json")
        hdrs.update(current_headers())
        req = urllib.request.Request(url, data=body, method=method.upper(),
                                     headers=hdrs)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return ToolResult(r.status, r.read().decode(), dict(r.headers))
        except urllib.error.HTTPError as e:
            return ToolResult(e.code, e.read().decode(), dict(e.headers))

    # -- the hook itself (§3.1 per-call flow) ------------------------------
    def _invoke(self, fn, tool_name, verb, target_spec, args, kwargs):
        target = _target_for(args, kwargs, target_spec)
        tool_input = kwargs if kwargs else (args[0] if len(args) == 1 else list(args))
        # 1-3. Resolve verb, build + sign record, chain, report intent.
        task = _current_task.get()
        record = self.chain.append(
            verb=verb, tool=tool_name, tool_input=tool_input, target=target,
            task_hash=task[0] if task else None,
            task_verb=task[1] if task else None)
        rec_hash = record_hash(record)
        if self.reporter:
            self.reporter.report_intent(self.identity, record)

        # 4. Run the tool with EyD headers passed into the call.
        result = self._run_with_headers(fn, args, kwargs, target, rec_hash)

        # 5. Hash the return value, report outcome.
        is_http = _is_http_result(result)
        output = _result_body_bytes(result) if is_http else result
        status = "ok"
        if is_http and result.status >= 400:
            status = "error"
        report = build_agent_report(self.identity, rec_hash=rec_hash,
                                    output=output, status=status)
        receipt = None
        if self.reporter:
            _, body = self.reporter.report_agent(report)
            receipt = body.get("receipt") or self.reporter.get_receipt(rec_hash)
        self.last_receipt[rec_hash] = receipt
        # 6. Receipt is for the operator/window; the model sees only the
        # tool's own return value, untouched.
        return result

    def _run_with_headers(self, fn, args, kwargs, target, rec_hash):
        headers = {"EyD-Agent": self.identity.id, "EyD-Record": rec_hash}
        if target in self.sessions:
            headers["EyD-Session"] = self.sessions[target]
        token = _current_headers.set(headers)
        try:
            result = fn(*args, **kwargs)
        finally:
            _current_headers.reset(token)
        # Attestation challenge (§4.6): the site refused before executing
        # anything, so one retry with the attestation header is the same
        # tool invocation under the same Action Record.
        if _is_http_result(result) and result.status == 403:
            challenge = _get_header(result, "EyD-Challenge")
            if challenge:
                seq, head = self.chain.head()
                retry_headers = {**headers, "EyD-Attestation": build_attestation(
                    self.identity, nonce=challenge, head_seq=seq, head_hash=head)}
                token = _current_headers.set(retry_headers)
                try:
                    result = fn(*args, **kwargs)
                finally:
                    _current_headers.reset(token)
        if _is_http_result(result):
            session = _get_header(result, "EyD-Session")
            if session:
                self.sessions[target] = session
        return result


def eyd_headers_json() -> str:
    """Convenience for transports that want the headers serialized."""
    return json.dumps(current_headers())
