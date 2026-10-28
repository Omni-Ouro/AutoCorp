"""Canonical JSON + hashing (PROOF v0 §4.5).

RFC 8785 (JSON Canonicalization Scheme): object keys sorted by UTF-16
code unit, no whitespace, minimal string escaping, and numbers
serialized per ECMAScript's Number::toString. The wider Eyro stack
standardizes on RFC 8785, so EyD records hash identically everywhere.

For the payloads EyD hashed before this upgrade (ASCII keys, strings,
integers) the output is byte-identical to the previous sorted-keys
encoding — existing chains and receipts remain valid. NaN and
infinities serialize as `null`, per JSON.stringify semantics.
"""
from __future__ import annotations

import hashlib
import math
from typing import Any

_SAFE_INT = 2**53  # largest integer magnitude exactly representable as a double

_STRING_ESCAPES = {
    '"': '\\"',
    "\\": "\\\\",
    "\b": "\\b",
    "\t": "\\t",
    "\n": "\\n",
    "\f": "\\f",
    "\r": "\\r",
}


def _serialize_string(value: str, out: list[str]) -> None:
    parts = ['"']
    for ch in value:
        escape = _STRING_ESCAPES.get(ch)
        if escape is not None:
            parts.append(escape)
        elif ord(ch) < 0x20:
            parts.append(f"\\u{ord(ch):04x}")
        else:
            parts.append(ch)
    parts.append('"')
    out.append("".join(parts))


def _serialize_number(value: int | float) -> str:
    if isinstance(value, int):
        if -_SAFE_INT <= value <= _SAFE_INT:
            return str(value)
        value = float(value)  # JCS numbers are IEEE 754 doubles
    if math.isnan(value) or math.isinf(value):
        return "null"
    if value == 0:
        return "0"  # also covers -0.0, per ECMAScript
    sign = "-" if value < 0 else ""
    # repr() yields the shortest digit string that round-trips, the same
    # digits ECMAScript produces; only the formatting differs. Recover
    # digits s and exponent such that value == s * 10^(n-k), k = len(s).
    mantissa = repr(abs(value))
    if "e" in mantissa:
        mant, _, exp = mantissa.partition("e")
        exp10 = int(exp)
    else:
        mant, exp10 = mantissa, 0
    if "." in mant:
        int_part, _, frac_part = mant.partition(".")
        digits = int_part + frac_part
        exp10 -= len(frac_part)
    else:
        digits = mant
    digits = digits.lstrip("0")
    trailing = len(digits) - len(digits.rstrip("0"))
    if trailing:
        digits = digits[:-trailing]
        exp10 += trailing
    k = len(digits)
    n = exp10 + k  # decimal point sits after the first n digits
    if k <= n <= 21:
        return sign + digits + "0" * (n - k)
    if 0 < n <= 21:
        return sign + digits[:n] + "." + digits[n:]
    if -6 < n <= 0:
        return sign + "0." + "0" * (-n) + digits
    exponent = n - 1
    mant_str = digits if k == 1 else digits[0] + "." + digits[1:]
    return f"{sign}{mant_str}e{'+' if exponent >= 0 else '-'}{abs(exponent)}"


def _serialize(obj: Any, out: list[str]) -> None:
    if obj is None:
        out.append("null")
    elif obj is True:
        out.append("true")
    elif obj is False:
        out.append("false")
    elif isinstance(obj, str):
        _serialize_string(obj, out)
    elif isinstance(obj, (int, float)):
        out.append(_serialize_number(obj))
    elif isinstance(obj, dict):
        keys = sorted(obj, key=lambda k: str(k).encode("utf-16-be", "surrogatepass"))
        out.append("{")
        for i, key in enumerate(keys):
            if not isinstance(key, str):
                raise TypeError("JCS object keys must be strings")
            if i:
                out.append(",")
            _serialize_string(key, out)
            out.append(":")
            _serialize(obj[key], out)
        out.append("}")
    elif isinstance(obj, (list, tuple)):
        out.append("[")
        for i, item in enumerate(obj):
            if i:
                out.append(",")
            _serialize(item, out)
        out.append("]")
    else:
        raise TypeError(f"cannot canonicalize {type(obj).__name__}")


def canonical_bytes(obj: Any) -> bytes:
    out: list[str] = []
    _serialize(obj, out)
    return "".join(out).encode("utf-8")


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
