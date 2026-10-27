"""Action Records, Agent Reports (PROOF v0 §4.1–4.2)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from . import EYD_VERSION
from .canonical import hash_bytes, hash_obj, record_hash
from .identity import Identity

GENESIS_PREV = "sha256:" + "0" * 64
VERBS = ("read", "write", "send", "browse", "execute", "pay")


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def input_hash_for(tool_input: Any) -> str:
    if tool_input is None:
        return hash_bytes(b"")
    if isinstance(tool_input, (bytes, bytearray)):
        return hash_bytes(bytes(tool_input))
    if isinstance(tool_input, str):
        return hash_bytes(tool_input.encode("utf-8"))
    return hash_obj(tool_input)


def build_action_record(
    identity: Identity,
    *,
    seq: int,
    prev_hash: str,
    verb: str,
    tool: str,
    tool_input: Any = None,
    target: str = "local",
    ts: str | None = None,
) -> dict:
    if verb not in VERBS:
        raise ValueError(f"verb must be one of {VERBS}, got {verb!r}")
    record = {
        "eyd": EYD_VERSION,
        "agent_id": identity.id,
        "seq": seq,
        "prev_hash": prev_hash,
        "ts": ts or utc_now(),
        "verb": verb,
        "tool": tool,
        "input_hash": input_hash_for(tool_input),
        "target": target,
    }
    rh = record_hash(record)
    record["sig"] = identity.sign(rh.encode("utf-8"))
    return record


def build_agent_report(
    identity: Identity, *, rec_hash: str, output: Any, status: str = "ok",
    ts: str | None = None,
) -> dict:
    if status not in ("ok", "error"):
        raise ValueError("status must be ok|error")
    if isinstance(output, (bytes, bytearray)):
        output_hash = hash_bytes(bytes(output))
    elif isinstance(output, str):
        output_hash = hash_bytes(output.encode("utf-8"))
    elif output is None:
        output_hash = hash_bytes(b"")
    else:
        output_hash = hash_obj(output)
    report = {
        "record_hash": rec_hash,
        "output_hash": output_hash,
        "status": status,
        "ts": ts or utc_now(),
    }
    # Sign the hash of the unsigned report (same rule as Action Records).
    report["sig"] = identity.sign(record_hash(report).encode("utf-8"))
    return report
