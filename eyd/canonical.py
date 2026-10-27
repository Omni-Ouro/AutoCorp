"""Canonical JSON + hashing (PROOF v0 §4.5).

Sorted keys, no whitespace, UTF-8, ensure_ascii=False.
Every implementation must hash identically — see spec test vector.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_bytes(obj: Any) -> bytes:
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def canonical_json(obj: Any) -> str:
    return canonical_bytes(obj).decode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_obj(obj: Any) -> str:
    """sha256:<hex> of the canonical JSON of obj."""
    return "sha256:" + sha256_hex(canonical_bytes(obj))


def hash_bytes(data: bytes) -> str:
    return "sha256:" + sha256_hex(data)


def record_hash(record: dict) -> str:
    """record_hash = SHA-256 of canonical JSON of all fields except `sig`."""
    unsigned = {k: v for k, v in record.items() if k != "sig"}
    return hash_obj(unsigned)
