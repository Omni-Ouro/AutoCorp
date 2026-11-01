"""Generate test/fixtures.json for the TypeScript verifier tests.

Everything here is produced by the *Python* implementation with fixed
seeds and timestamps, so the TS tests prove cross-implementation
compatibility: Python-signed attestations/reports/receipts must verify
in TypeScript, and a Python-loaded identity must derive the same id
from the same seed. Re-run after changing any signed format:

    python verifier/ts/test/gen_fixtures.py
"""
import base64
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402

from eyd.canonical import hash_bytes, record_hash  # noqa: E402
from eyd.identity import Identity  # noqa: E402

TS_FIXED = "2026-01-01T00:00:00Z"


def ident(seed: bytes, kind: str) -> Identity:
    return Identity(private_key=Ed25519PrivateKey.from_private_bytes(seed), kind=kind)


def main() -> None:
    agent = ident(bytes(range(32)), "agent")
    site = ident(bytes(range(32, 64)), "site")
    ch = ident(bytes(range(64, 96)), "site")

    rh = "sha256:" + "ab" * 32
    att = {"agent_id": agent.id, "nonce": "fixture-nonce", "head_seq": 7,
           "head_hash": "sha256:" + "00" * 32, "ts": TS_FIXED}
    att["sig"] = agent.sign(record_hash(att).encode())

    report = {"record_hash": rh, "agent_id": agent.id, "site_id": site.id,
              "outcome": "fulfilled", "result_hash": hash_bytes(b"hello"),
              "ts": TS_FIXED}
    report["sig"] = site.sign(record_hash(report).encode())

    receipt = {"record_hash": rh, "agent_id": agent.id, "site_id": site.id,
               "classification": "Expected", "verb": "send", "tool": "fixture",
               "target": "example.com", "ts": TS_FIXED}
    receipt["ch_sig"] = ch.sign(record_hash(receipt).encode())

    fixtures = {
        "agent": {"seed_b64": base64.b64encode(bytes(range(32))).decode(),
                  "id": agent.id, "pubkey_b64": agent.pubkey_b64},
        "site": {"seed_b64": base64.b64encode(bytes(range(32, 64))).decode(),
                 "id": site.id, "pubkey_b64": site.pubkey_b64},
        "attestation": att,
        "attestation_b64": base64.b64encode(json.dumps(att).encode()).decode(),
        "site_report": report,
        "receipt": receipt,
        "ch_pubkey_b64": ch.pubkey_b64,
    }
    out = Path(__file__).with_name("fixtures.json")
    out.write_text(json.dumps(fixtures, indent=2), encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
