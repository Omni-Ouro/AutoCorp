"""ES256 key handling for the demo issuer (demo only — not a key store)."""
from __future__ import annotations

import base64
import json
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric import ec


def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def b64u_dec(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def load_or_create_key(path: Path):
    """Returns (private_key, public_jwk). Persists a demo ES256 key."""
    if path.exists():
        jwk = json.loads(path.read_text())
        d = int.from_bytes(b64u_dec(jwk["d"]), "big")
        priv = ec.derive_private_key(d, ec.SECP256R1())
        return priv, {k: jwk[k] for k in ("kty", "crv", "kid", "alg", "use", "x", "y")}
    priv = ec.generate_private_key(ec.SECP256R1())
    numbers = priv.private_numbers()
    pub = numbers.public_numbers
    jwk = {"kty": "EC", "crv": "P-256", "kid": "demo-issuer-1", "alg": "ES256",
           "use": "sig",
           "x": b64u(pub.x.to_bytes(32, "big")), "y": b64u(pub.y.to_bytes(32, "big")),
           "d": b64u(numbers.private_value.to_bytes(32, "big"))}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(jwk, indent=1))
    return priv, {k: jwk[k] for k in ("kty", "crv", "kid", "alg", "use", "x", "y")}
