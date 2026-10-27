import json

from eyd.chain import LocalChain
from eyd.identity import Identity
from eyd.records import GENESIS_PREV


def make_chain(tmp_path):
    ident = Identity.generate()
    return ident, LocalChain(tmp_path / "chain.jsonl", ident)


def test_empty_chain_head_is_genesis(tmp_path):
    _, chain = make_chain(tmp_path)
    assert chain.head() == (0, GENESIS_PREV)
    ok, _ = chain.verify()
    assert ok


def test_append_and_verify(tmp_path):
    _, chain = make_chain(tmp_path)
    r1 = chain.append(verb="read", tool="http.get", target="example.com")
    r2 = chain.append(verb="send", tool="http.post", tool_input={"a": 1}, target="example.com")
    assert (r1["seq"], r2["seq"]) == (1, 2)
    assert r2["prev_hash"] != GENESIS_PREV
    ok, msg = chain.verify()
    assert ok, msg


def test_tamper_breaks_verify(tmp_path):
    _, chain = make_chain(tmp_path)
    chain.append(verb="read", tool="http.get")
    chain.append(verb="read", tool="http.get")
    lines = chain.path.read_text(encoding="utf-8").splitlines()
    tampered = json.loads(lines[0])
    tampered["tool"] = "http.post"  # change without re-signing
    lines[0] = json.dumps(tampered, sort_keys=True)
    chain.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    ok, msg = chain.verify()
    assert not ok
    assert "signature" in msg


def test_identity_save_load_roundtrip(tmp_path):
    ident = Identity.generate()
    p = tmp_path / "identity.json"
    ident.save(p)
    loaded = Identity.load(p)
    assert loaded.id == ident.id
    assert loaded.pubkey_raw == ident.pubkey_raw
