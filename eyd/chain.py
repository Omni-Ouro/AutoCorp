"""Local chain (PROOF v0 §3.4): append-only JSONL of signed Action Records.

prev_hash links, seq monotonic from 1. The chain is the source of truth;
the clearinghouse is the referee.
"""
from __future__ import annotations

import json
from pathlib import Path

from .canonical import record_hash
from .identity import Identity, verify_b64
from .records import GENESIS_PREV, build_action_record


class ChainError(Exception):
    pass


class LocalChain:
    def __init__(self, path: Path, identity: Identity):
        self.path = Path(path)
        self.identity = identity
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _records(self) -> list[dict]:
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                out.append(json.loads(line))
        return out

    def head(self) -> tuple[int, str]:
        """(latest seq, latest record_hash); (0, genesis) when empty."""
        records = self._records()
        if not records:
            return 0, GENESIS_PREV
        last = records[-1]
        return int(last["seq"]), record_hash(last)

    def append(self, *, verb: str, tool: str, tool_input=None, target: str = "local", ts=None,
               task_hash: str | None = None, task_verb: str | None = None) -> dict:
        seq, prev = self.head()
        record = build_action_record(
            self.identity, seq=seq + 1, prev_hash=prev,
            verb=verb, tool=tool, tool_input=tool_input, target=target, ts=ts,
            task_hash=task_hash, task_verb=task_verb,
        )
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, sort_keys=True) + "\n")
        return record

    def verify(self, pubkey_raw: bytes | None = None) -> tuple[bool, str]:
        """Walk the chain; fail on any break. Returns (ok, message)."""
        pub = pubkey_raw or self.identity.pubkey_raw
        prev = GENESIS_PREV
        expected_seq = 1
        records = self._records()
        for i, rec in enumerate(records):
            if rec.get("agent_id") != self.identity.id:
                return False, f"line {i+1}: agent_id mismatch"
            if int(rec.get("seq", -1)) != expected_seq:
                return False, f"line {i+1}: seq {rec.get('seq')} != expected {expected_seq}"
            if rec.get("prev_hash") != prev:
                return False, f"line {i+1}: prev_hash break"
            rh = record_hash(rec)
            if not verify_b64(pub, rh.encode("utf-8"), rec.get("sig", "")):
                return False, f"line {i+1}: bad signature"
            prev = rh
            expected_seq += 1
        return True, f"ok: {len(records)} record(s), head seq={expected_seq-1} hash={prev}"
