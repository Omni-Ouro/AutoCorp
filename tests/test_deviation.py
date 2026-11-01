"""Deviation (§3.11) + streak penalty (§3.10) against the real app."""
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "clearinghouse"))

from fastapi.testclient import TestClient  # noqa: E402

import main as ch  # noqa: E402  clearinghouse/main.py
from classify import DEVIATED, EXPECTED, compute_score  # noqa: E402
from eyd.canonical import record_hash  # noqa: E402
from eyd.identity import Identity  # noqa: E402
from eyd.records import build_agent_report, utc_now  # noqa: E402

client = TestClient(ch.app)


def _enroll(ident: Identity):
    p = {"kind": "agent", "agent_id": ident.id, "pubkey": ident.pubkey_b64,
         "ts": utc_now()}
    p["sig"] = ident.sign(record_hash(p).encode())
    assert client.post("/enroll", json=p).status_code == 200


def _deviated_action(ident: Identity, seq: int) -> str:
    """Task said pay; the agent sent an email instead (target: local,
    so no site report ever arrives — classification waits for sweep)."""
    rh = "sha256:" + hashlib.sha256(f"{ident.id}-{seq}".encode()).hexdigest()
    p = {"record_hash": rh, "agent_id": ident.id, "seq": seq, "target": "local",
         "verb": "send", "tool": "send_email", "task_verb": "pay", "ts": utc_now()}
    p["sig"] = ident.sign(record_hash(p).encode())
    assert client.post("/intents", json=p).status_code == 200
    rep = build_agent_report(ident, rec_hash=rh, output="sent", status="ok")
    assert client.post("/reports/agent", json=rep).status_code == 200
    client.post("/sweep", params={"now": 9_999_999_999})
    return rh


def test_deviated_counts_in_score_denominator():
    s = compute_score([EXPECTED] * 5 + [DEVIATED] * 5)
    assert s["score"] == 0.5
    assert s["deviated"] == 5


def test_deviation_streak_caps_score_and_pauses_passport():
    ident = Identity.generate()
    _enroll(ident)
    # Spotless seeded past (DEMO DATA) so the base sits near 0.99.
    seeded = [{"record_hash": "sha256:" + hashlib.sha256(
                   f"t-{ident.id}-{i}".encode()).hexdigest(),
               "agent_id": ident.id, "site_id": "SEEDED-DEMO-SITE",
               "classification": "Expected", "target": "seeded.demo",
               "ts": utc_now(), "ch_sig": "ed25519:demo", "demo_data": True}
              for i in range(99)]
    assert client.post("/seed", json={"receipts": seeded}).status_code == 200
    ch.passports[ident.id] = {"passport": {}, "subject": "sub-x",
                              "outcome": "accept", "step": ""}

    for seq in (1, 2, 3):
        rh = _deviated_action(ident, seq)
        receipt = client.get(f"/receipts/{rh}").json()
        assert receipt["classification"] == "Deviated"
        assert receipt["task_verb"] == "pay" and receipt["verb"] == "send"

    score = client.get(f"/agents/{ident.id}/score").json()
    assert score["cap"] == 0.75
    assert score["score"] == 0.75  # min(base ~0.97, cap)
    assert score["passport_paused"] is True

    approved = client.post(f"/agents/{ident.id}/passport/approve", json={})
    assert approved.status_code == 200
    score = client.get(f"/agents/{ident.id}/score").json()
    assert score["passport_paused"] is False
    assert score["score"] == 0.75  # approval lifts the pause, not the cap
