"""Corroboration: two reports from one operator are a single report
signed twice. Enrollment declares operator_id / integrator_id;
receipts label the reporters' independence; same-operator evidence
counts for less in the PoT score; the score endpoint shows which
verbs a score was built from.
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
from classify import EXPECTED, UNEXPECTED, compute_score  # noqa: E402
from eyd.canonical import record_hash  # noqa: E402
from eyd.identity import Identity  # noqa: E402
from eyd.records import build_agent_report, utc_now  # noqa: E402
from verifier import build_site_report  # noqa: E402

client = TestClient(ch.app)


def _enroll(ident: Identity, kind: str, domain: str | None = None, **extra):
    p = {"kind": kind, f"{kind}_id": ident.id, "pubkey": ident.pubkey_b64,
         "ts": utc_now(), **extra}
    if domain:
        p["domain"] = domain
    p["sig"] = ident.sign(record_hash(p).encode())
    assert client.post("/enroll", json=p).status_code == 200


def _intent(ident: Identity, seq: int, *, verb="pay") -> str:
    rh = "sha256:" + hashlib.sha256(f"corr-{ident.id}-{seq}".encode()).hexdigest()
    p = {"record_hash": rh, "agent_id": ident.id, "seq": seq,
         "target": "example.com", "verb": verb, "tool": "some_tool",
         "ts": utc_now()}
    p["sig"] = ident.sign(record_hash(p).encode())
    assert client.post("/intents", json=p).status_code == 200
    return rh


def _pair(agent: Identity, site: Identity, rh: str, *, agree=True):
    rep = build_agent_report(agent, rec_hash=rh, output="paid", status="ok")
    assert client.post("/reports/agent", json=rep).status_code == 200
    srep = build_site_report(site, record_hash_=rh, agent_id=agent.id,
                             outcome="fulfilled",
                             result=b"paid" if agree else b"different")
    r = client.post("/reports/site", json=srep)
    assert r.status_code == 200
    return r.json()["receipt"]


def _cast(agent, site, seqs, *, verb="pay", agree=True):
    return [_pair(agent, site, _intent(agent, s, verb=verb), agree=agree)
            for s in seqs]


def test_same_operator_labeled_and_downweighted():
    agent, site_a = Identity.generate(), Identity.generate(kind="site")
    site_b = Identity.generate(kind="site")
    _enroll(agent, "agent", operator_id="acme", integrator_id="vendor-x")
    _enroll(site_a, "site", domain="example.com", operator_id="acme",
            integrator_id="vendor-x")
    _enroll(site_b, "site", domain="example.com", operator_id="other")

    receipts = _cast(agent, site_a, range(1, 6))
    # Same operator outranks same integrator: one report signed twice.
    assert {r["corroboration"] for r in receipts} == {"same_operator"}
    _cast(agent, site_b, range(6, 11), agree=False)

    score = client.get(f"/agents/{agent.id}/score").json()
    assert score["expected"] == 5 and score["unexpected"] == 5  # raw counts
    # 5 Expected at weight 0.25 vs 5 Unexpected at 1.0 -> 1.25 / 6.25.
    assert score["score"] == 0.2


def test_integrator_and_independent_labels():
    agent, site = Identity.generate(), Identity.generate(kind="site")
    _enroll(agent, "agent", operator_id="acme-a", integrator_id="vendor-x")
    _enroll(site, "site", domain="example.com", operator_id="acme-b",
            integrator_id="vendor-x")
    assert _cast(agent, site, [1])[0]["corroboration"] == "same_integrator"

    agent2, site2 = Identity.generate(), Identity.generate(kind="site")
    _enroll(agent2, "agent")
    _enroll(site2, "site", domain="example.com")
    assert _cast(agent2, site2, [1])[0]["corroboration"] == "independent"

    # No counterparty report: no receipt issues, so no corroboration
    # claim exists at all.
    rh = _intent(agent2, 99)
    rep = build_agent_report(agent2, rec_hash=rh, output="paid", status="ok")
    r = client.post("/reports/agent", json=rep)
    assert r.json()["receipt"] is None


def test_score_shows_verb_breakdown():
    agent, site = Identity.generate(), Identity.generate(kind="site")
    _enroll(agent, "agent")
    _enroll(site, "site", domain="example.com")
    _cast(agent, site, range(1, 6), verb="pay")
    _cast(agent, site, range(6, 9), verb="browse")

    score = client.get(f"/agents/{agent.id}/score").json()
    assert score["verbs"]["pay"] == {"expected": 5, "unexpected": 0,
                                     "declined": 0, "unverified": 0,
                                     "deviated": 0, "scored": 5, "score": 1.0}
    assert score["verbs"]["browse"]["expected"] == 3
    assert score["verbs"]["browse"]["score"] == 1.0


def test_compute_score_weights_directly():
    s = compute_score([EXPECTED] * 5 + [UNEXPECTED] * 5,
                      weights=[0.25] * 5 + [1.0] * 5)
    assert s["score"] == 0.2 and s["expected"] == 5 and s["scored"] == 10
    # The history gate is on raw receipts, however they are weighted.
    assert compute_score([EXPECTED] * 4, weights=[1.0] * 4)["score"] is None
