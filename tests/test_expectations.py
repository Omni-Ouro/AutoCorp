"""Model expectation (verification vector two): pre-registered at
intent time, bound into the receipt, site-attested match — and never
a classification or score input.
"""
import hashlib
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
        lambda **kw: {"sketch": SKETCH, "model": "test-model"})
    agent, site = Identity.generate(), Identity.generate(kind="site")
    _enroll(agent, "agent")
    _enroll(site, "site", domain="example.com")

    rh = _intent(agent, 1)
    got = client.get(f"/expectations/{rh}")
    assert got.status_code == 200
    assert got.json()["sketch"] == SKETCH

    receipt = _pair(agent, site, rh, match=False)
    assert receipt["classification"] == "Expected"  # vector two never classifies
    assert receipt["expectation"] == {"model": "test-model", "sketch": SKETCH}
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
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("EXPECTATIONS", raising=False)
    assert exp_mod.generate_expectation(
        verb="pay", tool="pay_invoice", target="example.com") is None
