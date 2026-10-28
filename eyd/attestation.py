"""Attestation (PROOF v0 §4.6): challenge/response for site gating."""
from __future__ import annotations

import base64
import json

from .canonical import record_hash
from .identity import Identity
from .records import utc_now


def build_attestation(identity: Identity, *, nonce: str, head_seq: int, head_hash: str) -> str:
    att = {"agent_id": identity.id, "nonce": nonce, "head_seq": head_seq,
           "head_hash": head_hash, "ts": utc_now()}
    att["sig"] = identity.sign(record_hash(att).encode())
    return base64.b64encode(json.dumps(att).encode()).decode()
