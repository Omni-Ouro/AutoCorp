"""Turnkey integrations (step 3): the FastAPI @gated decorator and the
agent-side EyD.http helper.
"""
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "verifier" / "python"))

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from eyd.chain import LocalChain  # noqa: E402
from eyd.identity import Identity  # noqa: E402
from eyd.sdk import EyD  # noqa: E402
from fastapi_integration import gated  # noqa: E402
from verifier import EyDSite  # noqa: E402

RECORD_HASH = "sha256:" + "ab" * 32


def _app_with_gate():
    app = FastAPI()
    site = EyDSite(Identity.generate(kind="site"),
                   clearinghouse_url="http://127.0.0.1:9", domain="127.0.0.1",
                   public_clearinghouse_url="https://ch.example.com")
    site.passport_status = lambda agent_id: "valid"
    reports = []
    site.report = lambda rh, aid, outcome, result: reports.append(
        (rh, aid, outcome)) or {"classification": "Expected"}
    app.state.site = site
    app.state.reports = reports

    @app.post("/pay")
    @gated(site, min_score=0.8, info_url="https://example.com/eyd")
    async def pay(request: Request):
        return {"status": "paid", "agent": request.state.eyd_agent}

    return app, site


def test_gated_challenges_without_attestation():
    app, _site = _app_with_gate()
    client = TestClient(app)
    r = client.post("/pay", json={}, headers={"EyD-Record": RECORD_HASH,
                                              "EyD-Agent": "AGENT1"})
    assert r.status_code == 403
    assert r.json()["reason"] == "PoT score unknown"
    assert r.headers.get("eyd-challenge")  # agent SDK will attest + retry
    # Advertised Clearing House is the public one, not the internal URL.
    assert r.headers.get("eyd-clearinghouse") == "https://ch.example.com"
    # Owner-facing pointer; the refusal body itself never names EyD.
    assert r.headers.get("eyd-info") == "https://example.com/eyd"


def test_gated_session_does_not_elevate_and_admits_when_earned():
    app, site = _app_with_gate()
    client = TestClient(app)
    token = site.issue_session("AGENT1")
    headers = {"EyD-Session": token, "EyD-Record": RECORD_HASH,
               "EyD-Agent": "AGENT1"}

    site.scores["AGENT1"] = None
    site.score_allows = lambda agent_id, min_score=None: False
    r = client.post("/pay", json={}, headers=headers)
    assert r.status_code == 403
    assert app.state.reports[-1][2] == "declined"

    site.score_allows = lambda agent_id, min_score=None: True
    r = client.post("/pay", json={}, headers=headers)
    assert r.status_code == 200
    assert r.json()["agent"] == "AGENT1"
    assert r.headers.get("eyd-result-hash", "").startswith("sha256:")
    assert app.state.reports[-1][2] == "fulfilled"


class _FakeResponse:
    status = 200
    headers = {"Content-Type": "application/json"}

    def read(self):
        return b'{"ok": true}'

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_eyd_http_attaches_headers_inside_tool(tmp_path, monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["headers"] = dict(req.header_items())
        captured["method"] = req.get_method()
        return _FakeResponse()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    ident = Identity.generate()
    eyd = EyD(ident, chain=LocalChain(tmp_path / "chain.jsonl", ident))

    @eyd.tool(verb="send", target="example.com")
    def call_api(x: int):
        return eyd.http("POST", "http://example.com/pay", json_body={"x": x})

    result = call_api(3)
    assert result.status == 200
    assert captured["method"] == "POST"
    lowered = {k.lower(): v for k, v in captured["headers"].items()}
    assert lowered["eyd-agent"] == eyd.identity.id
    assert lowered["eyd-record"].startswith("sha256:")
    assert lowered["content-type"] == "application/json"
