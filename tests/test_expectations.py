"""Model expectation (verification vector two): pre-registered at
intent time, bound into the receipt, site-attested match — and never
a classification or score input.
"""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "clearinghouse"))
sys.path.insert(0, str(ROOT / "verifier" / "python"))

from fastapi.testclient import TestClient  # noqa: E402

import main as ch  # noqa: E402  clearinghouse/main.py
import expectations as exp_mod  # noqa: E402
from eyd.canonical import record_hash  # noqa: E402
from eyd.identity import Identity  # noqa: E402
from eyd.records import build_agent_report, utc_now  # noqa: E402
from verifier import build_site_report  # noqa: E402

client = TestClient(ch.app)
SKETCH = "A payment confirmation referencing the paid invoice."


def _enroll(ident: Identity, kind: str, domain: str | None = None):
    p = {"kind": kind, f"{kind}_id": ident.id, "pubkey": ident.pubkey_b64,
         "ts": utc_now()}
    if domain:
        p["domain"] = domain
    p["sig"] = ident.sign(record_hash(p).encode())
    assert client.post("/enroll", json=p).status_code == 200


def _intent(ident: Identity, seq: int, *, verb="pay", task_verb="pay") -> str:
    rh = "sha256:" + hashlib.sha256(f"exp-{ident.id}-{seq}".encode()).hexdigest()
    p = {"record_hash": rh, "agent_id": ident.id, "seq": seq,
         "target": "example.com", "verb": verb, "tool": "pay_invoice",
         "task_verb": task_verb, "ts": utc_now()}
    p["sig"] = ident.sign(record_hash(p).encode())
    r = client.post("/intents", json=p)
    assert r.status_code == 200
    return rh


def _pair(agent: Identity, site: Identity, rh: str, *, match=None):
    rep = build_agent_report(agent, rec_hash=rh, output="paid", status="ok")
    assert client.post("/reports/agent", json=rep).status_code == 200
    srep = build_site_report(site, record_hash_=rh, agent_id=agent.id,
                             outcome="fulfilled", result=b"paid",
                             expectation_match=match)
    r = client.post("/reports/site", json=srep)
    assert r.status_code == 200
    return r.json()["receipt"]


def test_expectation_registered_bound_and_attested(monkeypatch):
    monkeypatch.setattr(
        ch, "generate_expectation",
        lambda **kw: {"sketch": SKETCH, "model": "test-model",
                      "category": "payment"})
    agent, site = Identity.generate(), Identity.generate(kind="site")
    _enroll(agent, "agent")
    _enroll(site, "site", domain="example.com")

    rh = _intent(agent, 1)
    got = client.get(f"/expectations/{rh}")
    assert got.status_code == 200
    assert got.json()["sketch"] == SKETCH

    receipt = _pair(agent, site, rh, match=False)
    assert receipt["classification"] == "Expected"  # vector two never classifies
    assert receipt["expectation"] == {"model": "test-model", "sketch": SKETCH,
                                      "category": "payment"}
    assert receipt["expectation_match"] is False  # advisory annotation only

    score = client.get(f"/agents/{agent.id}/score").json()
    assert score["expected"] == 1 and score["score"] is None  # nor scores


def test_no_expectation_when_vector_disabled(monkeypatch):
    monkeypatch.setattr(ch, "generate_expectation", lambda **kw: None)
    agent, site = Identity.generate(), Identity.generate(kind="site")
    _enroll(agent, "agent")
    _enroll(site, "site", domain="example.com")

    rh = _intent(agent, 1)
    assert client.get(f"/expectations/{rh}").status_code == 404
    receipt = _pair(agent, site, rh)
    assert "expectation" not in receipt
    assert "expectation_match" not in receipt


def test_generate_returns_none_without_gateway(monkeypatch):
    monkeypatch.delenv("MODEL_GATEWAY_URL", raising=False)
    monkeypatch.delenv("MODEL_GATEWAY_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("EXPECTATIONS", raising=False)
    assert exp_mod.generate_expectation(
        verb="pay", tool="pay_invoice", target="example.com") is None


def test_gateway_names_are_meta_neutral(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.setenv("MODEL_GATEWAY_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("MODEL_GATEWAY_TOKEN", "x")
    assert exp_mod.model_name() is not None
    monkeypatch.setenv("EXPECTATIONS", "off")
    assert exp_mod.model_name() is None


class _FakeResponse:
    def __init__(self, body: dict):
        self._body = json.dumps(body).encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_openai_gateway_shape(monkeypatch):
    """MODEL_GATEWAY_FORMAT=openai speaks chat completions (Baseten's
    Meta open-weight serving); reasoning_content is not the sketch."""
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("EXPECTATIONS", raising=False)
    monkeypatch.setenv("MODEL_GATEWAY_URL", "https://inference.example/v1")
    monkeypatch.setenv("MODEL_GATEWAY_TOKEN", "x")
    monkeypatch.setenv("MODEL_GATEWAY_FORMAT", "openai")
    monkeypatch.setenv("EXPECTATION_MODEL", "meta-models/test")
    seen = {}

    def fake_urlopen(req, timeout=0):
        seen["url"] = req.full_url
        return _FakeResponse({"choices": [{"message": {
            "content": "A confirmation that the thing was sent.",
            "reasoning_content": "long private reasoning"}}]})

    monkeypatch.setattr(exp_mod.urllib.request, "urlopen", fake_urlopen)
    out = exp_mod.generate_expectation(
        verb="send", tool="send_thing", target="example.com")
    assert seen["url"].endswith("/chat/completions")
    assert out == {"sketch": "A confirmation that the thing was sent.",
                   "model": "meta-models/test", "category": "unknown"}


def test_parse_reply_categories():
    assert exp_mod._parse_reply(
        "category: payment\nA proof of payment.") == ("payment", "A proof of payment.")
    # A slug outside the taxonomy is the model's own escape hatch.
    assert exp_mod._parse_reply(
        "category: banana\nSome outcome.") == ("other", "Some outcome.")
    # No category line: the whole reply is the sketch, category unknown —
    # the bucket a future decision model hands off to a reasoning model.
    assert exp_mod._parse_reply(
        "Just a sentence.") == ("unknown", "Just a sentence.")
    assert exp_mod._parse_reply("category: listing\n")[0] == "unknown"
