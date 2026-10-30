"""A site session identifies an agent; it must not elevate its gate.

Regression test: an agent that attested at an any-score action once rode
its session token into a higher-score action. Both site apps now check
the current action's score and Passport standing on every gated request.
"""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from eyd.identity import Identity  # noqa: E402

RECORD_HASH = "sha256:" + "ab" * 32


def _load_app(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    app = mod.make_app(clearinghouse_url="http://127.0.0.1:9",
                       identity=Identity.generate(kind="site"),
                       domain="127.0.0.1")
    site = app.state.site
    site.passport_status = lambda agent_id: "valid"
    site.report = lambda record_hash_, agent_id, outcome, result: {
        "classification": "Declined" if outcome == "declined" else "Expected"}
    return app, site


def _exercise(client: TestClient, site, path: str):
    token = site.issue_session("AGENT1")
    headers = {"EyD-Session": token, "EyD-Record": RECORD_HASH,
               "EyD-Agent": "AGENT1"}

    site.scores["AGENT1"] = None
    site.score_allows = lambda agent_id, min_score=None: False
    refused = client.post(path, json={}, headers=headers)
    assert refused.status_code == 403
    assert refused.json()["reason"] == "PoT score unknown"

    site.score_allows = lambda agent_id, min_score=None: True
    admitted = client.post(path, json={}, headers=headers)
    assert admitted.status_code == 200


def test_playground_session_does_not_elevate_gate():
    app, site = _load_app("playground_main", "playground/main.py")
    _exercise(TestClient(app), site, "/meeting")


def test_demo_site_session_does_not_elevate_gate():
    app, site = _load_app("demo_site_main", "demo-site/main.py")
    _exercise(TestClient(app), site, "/pay")
