/**
 * Canonical JSON + hashing (PROOF v0 §4.5) — RFC 8785 (JCS).
 *
 * JCS is defined on ECMAScript semantics, so this is the natural
 * implementation: object keys sort by UTF-16 code unit (the default
 * string sort), numbers serialize via Number::toString, and strings
 * escape exactly as JSON.stringify does. Output is byte-identical to
 * the Python implementation in eyd/canonical.py — the shared test
 * vectors in test/ prove it.
 */
import { createHash } from "node:crypto";

function serialize(value: unknown, out: string[]): void {
  if (value === null) {
    out.push("null");
  } else if (value === true) {
    out.push("true");
  } else if (value === false) {
    out.push("false");
  } else if (typeof value === "string") {
    out.push(JSON.stringify(value));
  } else if (typeof value === "number") {
    // JSON.stringify is ECMAScript Number::toString, with NaN and
    // infinities serialized as null — exactly the JCS rule.
    out.push(JSON.stringify(value));
  } else if (Array.isArray(value)) {
    out.push("[");
    value.forEach((item, i) => {
      if (i) out.push(",");
      serialize(item, out);
    });
    out.push("]");
  } else if (typeof value === "object") {
    const obj = value as Record<string, unknown>;
    const keys = Object.keys(obj).sort(); // UTF-16 code-unit order
    out.push("{");
    keys.forEach((key, i) => {
      if (i) out.push(",");
      out.push(JSON.stringify(key), ":");
      serialize(obj[key], out);
    });
    out.push("}");
  } else {
    throw new TypeError(`cannot canonicalize ${typeof value}`);
  }
}

export function canonicalBytes(obj: unknown): Buffer {
  const out: string[] = [];
  serialize(obj, out);
  return Buffer.from(out.join(""), "utf-8");
}

export function canonicalJson(obj: unknown): string {
  return canonicalBytes(obj).toString("utf-8");
}

export function sha256Hex(data: Buffer): string {
  return createHash("sha256").update(data).digest("hex");
}

/** sha256:<hex> of the canonical JSON of obj. */
export function hashObj(obj: unknown): string {
  return "sha256:" + sha256Hex(canonicalBytes(obj));
}

export function hashBytes(data: Buffer): string {
  return "sha256:" + sha256Hex(data);
}

/** record_hash = SHA-256 of canonical JSON of all fields except `sig`. */
export function recordHash(record: Record<string, unknown>): string {
  const unsigned: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(record)) {
    if (k !== "sig") unsigned[k] = v;
  }
  return hashObj(unsigned);
}
