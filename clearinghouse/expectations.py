"""Model expectation — the second EyD verification vector.

Hash pairing (vector one) proves the agent and the site agree on what
happened. It cannot say whether what happened is the *kind* of thing
that was asked for. At intent time — before the action runs — this
module asks a model, from the declared action alone (verb, tool,
target, and the task verb when the framework supplies one; never tool
arguments, never result content), for a one-sentence sketch of what a
successful result should look like. The sketch is stored against the
record_hash and bound into the signed Proof Receipt; the site, which
holds the actual result, may attest in its signed report whether the
result matched the sketch (`expectation_match`).

Advisory by construction: an expectation never changes a
classification or the PoT score. It is evidence, not a referee — a
pre-registered prediction a mismatch can be measured against.

Enabled when MODEL_GATEWAY_URL and MODEL_GATEWAY_TOKEN are set (the
Meta model gateway; ANTHROPIC_BASE_URL / ANTHROPIC_AUTH_TOKEN are
accepted as fallbacks — the gateway speaks that API shape). Model:
EXPECTATION_MODEL, else ANTHROPIC_MODEL, else the demo default. EXPECTATION_VERBS (comma list) restricts which
verbs get sketches; unset means all. Any failure — no gateway,
timeout, bad reply — yields no expectation and never blocks an intent.
This module is the registry point for future vectors: each produces
signed receipt annotations, none of them classify.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request

_SYSTEM = (
    "You are the expectation service of the EyD Clearing House. Given a "
    "declared agent action, write ONE sentence describing what a "
    "successful result of that action should look like: the category "
    "and shape of the outcome only. Never invent specific values "
    "(amounts, names, ids, dates). Base the expectation on the task "
    "verb when one is given — that is what was asked for — otherwise "
    "on the action verb. Reply with the sentence only."
)


def _gateway_url() -> str | None:
    return (os.environ.get("MODEL_GATEWAY_URL")
            or os.environ.get("ANTHROPIC_BASE_URL"))


def _gateway_token() -> str | None:
    return (os.environ.get("MODEL_GATEWAY_TOKEN")
            or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def model_name() -> str | None:
    if os.environ.get("EXPECTATIONS", "").lower() == "off":
        return None
    if not (_gateway_url() and _gateway_token()):
        return None
    return (os.environ.get("EXPECTATION_MODEL")
            or os.environ.get("ANTHROPIC_MODEL") or "muse-wonder-1.0")


def _verbs() -> set[str] | None:
    raw = os.environ.get("EXPECTATION_VERBS", "")
    verbs = {v.strip() for v in raw.split(",") if v.strip()}
    return verbs or None


def generate_expectation(*, verb: str, tool: str, target: str,
                         task_verb: str | None = None) -> dict | None:
    """One model call from the declared action alone. None on any
    failure or when the vector is disabled — the intent proceeds."""
    model = model_name()
    if model is None:
        return None
    verbs = _verbs()
    if verbs is not None and verb not in verbs and task_verb not in verbs:
        return None
    lines = [f"verb: {verb}", f"tool: {tool}", f"target: {target}"]
    if task_verb:
        lines.append(f"task_verb: {task_verb}")
    # max_tokens must cover the gateway's hidden thinking plus the
    # one-sentence reply; 300 starved it and yielded empty text.
    payload = {"model": model, "max_tokens": 1024, "system": _SYSTEM,
               "messages": [{"role": "user", "content": "\n".join(lines)}]}
    token = _gateway_token() or ""
    req = urllib.request.Request(
        (_gateway_url() or "").rstrip("/") + "/v1/messages",
        data=json.dumps(payload).encode(), method="POST",
        headers={"Content-Type": "application/json",
                 "x-api-key": token,
                 "Authorization": f"Bearer {token}",
                 "anthropic-version": "2023-06-01"})
    try:
        # Retries: the gateway occasionally returns thinking only.
        for _attempt in range(3):
            with urllib.request.urlopen(req, timeout=20) as r:
                body = json.loads(r.read())
            text = "".join(b.get("text", "") for b in body.get("content", [])
                           if b.get("type") == "text").strip()
            if text:
                break
    except Exception as e:
        print(f"expectations: model call failed: {e}", file=sys.stderr)
        return None
    if not text:
        return None
    return {"sketch": text[:300], "model": model}
