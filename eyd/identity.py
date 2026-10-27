"""Identity (PROOF v0 §3.3): Ed25519 keypair, agent_id / site_id.

agent_id = base32(SHA-256(pubkey_raw))[:26]  (RFC 4648, uppercase)
Private key never leaves the device. Keys from the OS CSPRNG only
(cryptography library delegates to the OS RNG).
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


def derive_id(pubkey_raw: bytes) -> str:
    digest = hashlib.sha256(pubkey_raw).digest()
    return base64.b32encode(digest).decode("ascii").rstrip("=")[:26]


def pubkey_b64(pubkey_raw: bytes) -> str:
    return base64.b64encode(pubkey_raw).decode("ascii")


def sign_b64(private_key: Ed25519PrivateKey, msg: bytes) -> str:
    return "ed25519:" + base64.b64encode(private_key.sign(msg)).decode("ascii")


def verify_b64(pubkey_raw: bytes, msg: bytes, sig: str) -> bool:
    try:
        if not sig.startswith("ed25519:"):
            return False
        raw = base64.b64decode(sig[len("ed25519:"):])
        Ed25519PublicKey.from_public_bytes(pubkey_raw).verify(raw, msg)
        return True
    except Exception:
        return False


@dataclass
class Identity:
    private_key: Ed25519PrivateKey
    kind: str = "agent"  # "agent" | "site"

    @property
    def pubkey_raw(self) -> bytes:
        return self.private_key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )

    @property
    def id(self) -> str:
        return derive_id(self.pubkey_raw)

    @property
    def agent_id(self) -> str:
        return self.id

    @property
    def pubkey_b64(self) -> str:
        return pubkey_b64(self.pubkey_raw)

    def sign(self, msg: bytes) -> str:
        return sign_b64(self.private_key, msg)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = self.private_key.private_bytes(
            serialization.Encoding.Raw,
            serialization.PrivateFormat.Raw,
            serialization.NoEncryption(),
        )
        data = {
            "kind": self.kind,
            "id": self.id,
            "pubkey": self.pubkey_b64,
            "private_key": base64.b64encode(raw).decode("ascii"),
        }
        # Private key on disk, local only. Tighten perms where the OS allows.
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

    @classmethod
    def load(cls, path: Path) -> "Identity":
        data = json.loads(path.read_text(encoding="utf-8"))
        raw = base64.b64decode(data["private_key"])
        key = Ed25519PrivateKey.from_private_bytes(raw)
        ident = cls(private_key=key, kind=data.get("kind", "agent"))
        if "pubkey" in data and data["pubkey"] != ident.pubkey_b64:
            raise ValueError("identity file pubkey does not match private key")
        return ident

    @classmethod
    def generate(cls, kind: str = "agent") -> "Identity":
        return cls(private_key=Ed25519PrivateKey.generate(), kind=kind)


def default_home() -> Path:
    return Path(os.environ.get("EYD_HOME", Path.home() / ".eyd"))


def default_identity_path() -> Path:
    return default_home() / "identity.json"


def default_chain_path() -> Path:
    return default_home() / "chain.jsonl"
