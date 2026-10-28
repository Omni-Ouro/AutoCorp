"""Demo issuer -> clearinghouse Passport check, end to end in-process.

A Passport the demo issuer signs must verify (accept) bound to the
agent's EyD identity, and deny once revoked. Uses the real verifier
(clearinghouse-ref/passport.py), not the vendored vectors.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "clearinghouse-ref"))
sys.path.insert(0, str(ROOT / "passport-demo"))

import passport as pp  # noqa: E402
from issuer import AUTHORITY, make_app  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

ISSUER = "http://localhost:8010"
AGENT = "ZWLA25H6KUYFPKFBHCIIY52UJA"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_issued_passport_accepts_then_denies_when_revoked():
    client = TestClient(make_app(ISSUER))
    passport = client.post("/issue", json={"agent_id": AGENT}).json()
    jwks = client.get("/jwks").json()
    anchors = {ISSUER: {"jwks": jwks, "responders": [ISSUER]}}
    presenter = {"authority": AUTHORITY, "identifier": AGENT}

    def http_get(url):
        r = client.get(url.replace(ISSUER, ""))
        return {"status": r.status_code, "body": r.json()}

    outcome, _ = pp.check_passport_live(passport, anchors, presenter=presenter,
                                        http_get=http_get, now=_now())
    assert outcome == "accept"

    client.post("/revoke", json={"agent_id": AGENT, "revoked": True})
    outcome, step = pp.check_passport_live(passport, anchors, presenter=presenter,
                                           http_get=http_get, now=_now())
    assert (outcome, step) == ("deny", "revocation")


def test_passport_does_not_bind_to_another_agent():
    client = TestClient(make_app(ISSUER))
    passport = client.post("/issue", json={"agent_id": AGENT}).json()
    jwks = client.get("/jwks").json()
    anchors = {ISSUER: {"jwks": jwks, "responders": [ISSUER]}}
    stranger = {"authority": AUTHORITY, "identifier": "AAAAAAAAAAAAAAAAAAAAAAAAAA"}
    outcome, step = pp.check_passport_live(
        passport, anchors, presenter=stranger,
        http_get=lambda url: {"status": 200, "body": {}}, now=_now())
    assert outcome == "refetch" and step == "bindings"  # not attributed to a stranger
