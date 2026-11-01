/**
 * Identity (PROOF v0 §3.3): Ed25519 keypair, agent_id / site_id.
 *
 *   id = base32(SHA-256(pubkey_raw))[:26]  (RFC 4648, uppercase)
 *
 * Key files are byte-compatible with the Python SDK (eyd/identity.py):
 * {kind, id, pubkey, private_key} with the raw 32-byte seed in base64 —
 * either implementation can load the other's identity file.
 */
import {
  createHash,
  createPrivateKey,
  createPublicKey,
  generateKeyPairSync,
  sign as cryptoSign,
  verify as cryptoVerify,
  type KeyObject,
} from "node:crypto";
import { chmodSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";

// DER prefixes so Node accepts raw Ed25519 keys.
const PKCS8_PREFIX = Buffer.from("302e020100300506032b657004220420", "hex");
const SPKI_PREFIX = Buffer.from("302a300506032b6570032100", "hex");

const B32_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";

export function base32Encode(data: Buffer): string {
  let bits = 0;
  let value = 0;
  let out = "";
  for (const byte of data) {
    value = (value << 8) | byte;
    bits += 8;
    while (bits >= 5) {
      out += B32_ALPHABET[(value >>> (bits - 5)) & 31];
      bits -= 5;
    }
  }
  if (bits > 0) out += B32_ALPHABET[(value << (5 - bits)) & 31];
  return out;
}

export function deriveId(pubkeyRaw: Buffer): string {
  const digest = createHash("sha256").update(pubkeyRaw).digest();
  return base32Encode(digest).slice(0, 26);
}

export function privateKeyFromSeed(seed: Buffer): KeyObject {
  return createPrivateKey({
    key: Buffer.concat([PKCS8_PREFIX, seed]),
    format: "der",
    type: "pkcs8",
  });
}

export function publicKeyFromRaw(raw: Buffer): KeyObject {
  return createPublicKey({
    key: Buffer.concat([SPKI_PREFIX, raw]),
    format: "der",
    type: "spki",
  });
}

export function pubkeyRawOf(privateKey: KeyObject): Buffer {
  const der = createPublicKey(privateKey).export({
    format: "der",
    type: "spki",
  }) as Buffer;
  return Buffer.from(der.subarray(der.length - 32));
}

function seedOf(privateKey: KeyObject): Buffer {
  const der = privateKey.export({ format: "der", type: "pkcs8" }) as Buffer;
  return Buffer.from(der.subarray(der.length - 32));
}

export function signB64(privateKey: KeyObject, msg: Buffer): string {
  return "ed25519:" + cryptoSign(null, msg, privateKey).toString("base64");
}

export function verifyB64(pubkeyRaw: Buffer, msg: Buffer, sig: string): boolean {
  try {
    if (!sig.startsWith("ed25519:")) return false;
    const raw = Buffer.from(sig.slice("ed25519:".length), "base64");
    return cryptoVerify(null, msg, publicKeyFromRaw(pubkeyRaw), raw);
  } catch {
    return false;
  }
}

export class Identity {
  readonly kind: string;
  private readonly key: KeyObject;

  private constructor(key: KeyObject, kind: string) {
    this.key = key;
    this.kind = kind;
  }

  static generate(kind = "agent"): Identity {
    const { privateKey } = generateKeyPairSync("ed25519");
    return new Identity(privateKey, kind);
  }

  static fromSeed(seed: Buffer, kind = "agent"): Identity {
    return new Identity(privateKeyFromSeed(seed), kind);
  }

  get pubkeyRaw(): Buffer {
    return pubkeyRawOf(this.key);
  }

  get id(): string {
    return deriveId(this.pubkeyRaw);
  }

  get pubkeyB64(): string {
    return this.pubkeyRaw.toString("base64");
  }

  sign(msg: Buffer): string {
    return signB64(this.key, msg);
  }

  save(path: string): void {
    mkdirSync(dirname(path), { recursive: true });
    const data = {
      kind: this.kind,
      id: this.id,
      pubkey: this.pubkeyB64,
      private_key: seedOf(this.key).toString("base64"),
    };
    writeFileSync(path, JSON.stringify(data, null, 2), { encoding: "utf-8", mode: 0o600 });
    try {
      chmodSync(path, 0o600);
    } catch {
      /* perms are best-effort, as in the Python SDK */
    }
  }

  static load(path: string): Identity {
    const data = JSON.parse(readFileSync(path, "utf-8"));
    const ident = Identity.fromSeed(
      Buffer.from(data.private_key, "base64"),
      data.kind ?? "agent",
    );
    if (data.pubkey && data.pubkey !== ident.pubkeyB64) {
      throw new Error("identity file pubkey does not match private key");
    }
    return ident;
  }
}
