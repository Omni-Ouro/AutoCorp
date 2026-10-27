import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from eyd.canonical import record_hash
from eyd.identity import Identity, derive_id, verify_b64
from eyd.records import build_action_record, build_agent_report

# Fixed test key (bytes 0..31) so the vector is reproducible.
FIXED_SEED = bytes(range(32))
FIXED_TS = "2026-10-28T14:03:11Z"


def fixed_identity() -> Identity:
    return Identity(private_key=Ed25519PrivateKey.from_private_bytes(FIXED_SEED))


def test_agent_id_derivation():
    ident = fixed_identity()
    assert ident.id == derive_id(ident.pubkey_raw)
    assert len(ident.id) == 26
    assert ident.id == ident.id.upper()


def test_sign_verify_roundtrip():
    ident = fixed_identity()
    sig = ident.sign(b"hello")
    assert verify_b64(ident.pubkey_raw, b"hello", sig)
    assert not verify_b64(ident.pubkey_raw, b"tampered", sig)


def test_action_record_vector():
    ident = fixed_identity()
    rec = build_action_record(
        ident, seq=1, prev_hash="sha256:" + "0" * 64,
        verb="send", tool="http.post", tool_input={"q": "x"}, target="example.com",
        ts=FIXED_TS,
    )
    assert rec["eyd"] == "0.1"
    assert rec["agent_id"] == ident.id
    rh = record_hash(rec)
    assert rh.startswith("sha256:") and len(rh) == 71
    assert verify_b64(ident.pubkey_raw, rh.encode(), rec["sig"])
    # Rebuilding with the same inputs yields the identical record (Ed25519 is deterministic).
    again = build_action_record(
        ident, seq=1, prev_hash="sha256:" + "0" * 64,
        verb="send", tool="http.post", tool_input={"q": "x"}, target="example.com",
        ts=FIXED_TS,
    )
    assert again == rec


def test_agent_report_signs():
    ident = fixed_identity()
    rep = build_agent_report(ident, rec_hash="sha256:" + "a" * 64, output=b"body", status="ok", ts=FIXED_TS)
    assert rep["output_hash"].startswith("sha256:")
    assert verify_b64(ident.pubkey_raw, record_hash(rep).encode(), rep["sig"])


def test_pubkey_b64_is_raw_32_bytes():
    ident = fixed_identity()
    raw = base64.b64decode(ident.pubkey_b64)
    assert len(raw) == 32
    assert raw == ident.private_key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
