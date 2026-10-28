"""Demo AI Passport issuer — for the hackathon demo only.

Issues ES256-signed AI Passports (spec: github.com/ServiceNow/ai-passport)
bound to EyD agent identities, and answers revocation checks by subject.
The binding's authority is the EyD clearinghouse: the presenter of a
Passport is an EyD agent_id, authenticated by its own Ed25519 key at
attestation time — that is the holder binding the spec leaves open.

Run: ISSUER_URL=http://localhost:8010 python passport-demo/issuer.py
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402

from cryptography.hazmat.primitives import hashes  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec, utils  # noqa: E402

from eyd.canonical import canonical_bytes  # noqa: E402
from passport_signing import b64u, load_or_create_key  # noqa: E402

AUTHORITY = os.environ.get("PASSPORT_AUTHORITY", "urn:eyd:clearinghouse")
ISSUER_URL = os.environ.get("ISSUER_URL", "http://localhost:8010")
KEY_FILE = Path(__file__).parent / ".keys" / "issuer.json"


def utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def make_app(issuer_url: str = ISSUER_URL) -> FastAPI:
    priv, jwk_public = load_or_create_key(KEY_FILE)
    app = FastAPI(title="EyD demo AI Passport issuer (DEMO)")
    app.state.subjects: dict[str, dict] = {}  # subject -> revocation state

    def subject_for(agent_id: str) -> str:
        return hashlib.sha256(agent_id.encode()).hexdigest()[:32]

    def build_passport(agent_id: str, revision: int = 1) -> dict:
        now = datetime.now(timezone.utc)
        return {
            "schema_version": "1",
            "subject": subject_for(agent_id),
            "subject_type": "agent",
            "issuer": issuer_url,
            "issuance_class": "owned",
            "revision": revision,
            "name": f"EyD demo agent {agent_id[:8]}",
            "valid_from": utc(now - timedelta(days=1)),
            "valid_to": utc(now + timedelta(days=90)),
            "status": {"revocation_check": {"uri": f"{issuer_url}/revocation?subject={{subject}}"}},
            "bindings": [{"authority": {"id": AUTHORITY, "name": "EyD Clearinghouse"},
                          "identifier": agent_id, "type": "agent_id"}],
            "business_context": {
                "accountable": [
                    {"role": "owner", "principal": "urn:eyd:demo:owner"},
                    {"role": "manager", "principal": "urn:eyd:demo:manager"}],
                "org_unit": {"id": "urn:eyd:demo:org"},
                "risk_classification": {"value": "medium"},
                "purpose": {"additional_details": "hackathon demo agent",
                            "autonomy_level": "semi_automated",
                            "human_involvement_level": "ai_initiated_with_approval"}},
        }

    def sign(payload: dict) -> dict:
        protected = b64u(json.dumps({"alg": "ES256", "kid": jwk_public["kid"],
                                     "typ": "ai-passport+jws"},
                                    separators=(",", ":")).encode())
        signing_input = (protected + "." + b64u(canonical_bytes(payload))).encode()
        der = priv.sign(signing_input, ec.ECDSA(hashes.SHA256()))
        r, s = utils.decode_dss_signature(der)
        sig = r.to_bytes(32, "big") + s.to_bytes(32, "big")
        return {**payload, "signatures": [{"protected": protected, "signature": b64u(sig)}]}

    @app.get("/")
    def home():
        return {"issuer": issuer_url, "demo": True}

    @app.get("/jwks")
    def jwks():
        return {"keys": [jwk_public]}

    @app.post("/issue")
    async def issue(request: Request):
        agent_id = (await request.json()).get("agent_id")
        if not agent_id:
            return JSONResponse({"error": "agent_id required"}, status_code=400)
        subject = subject_for(agent_id)
        state = app.state.subjects.setdefault(
            subject, {"agent_id": agent_id, "revoked": False, "revision": 1,
                      "state_version": 1, "min_required_revision": 1})
        return sign(build_passport(agent_id, state["revision"]))

    @app.get("/passports")
    def fetch_passport(authority: str = "", identifier: str = ""):
        """Retrieval by the presenter's binding pair (01 §10 refetch)."""
        for subject, state in app.state.subjects.items():
            if state["agent_id"] == identifier:
                return sign(build_passport(identifier, state["revision"]))
        return JSONResponse({"error": "not found"}, status_code=404)

    @app.post("/revoke")
    async def revoke(request: Request):
        payload = await request.json()
        agent_id = payload.get("agent_id")
        subject = payload.get("subject") or (subject_for(agent_id) if agent_id else None)
        state = app.state.subjects.get(subject or "")
        if state is None:
            return JSONResponse({"error": "unknown subject"}, status_code=404)
        state["revoked"] = bool(payload.get("revoked", True))
        state["state_version"] += 1
        # Off the event loop: the clearinghouse re-checks /revocation
        # while this notify is in flight; blocking here would deadlock
        # the push until timeouts. Revocation has taken effect (sessions
        # dropped) by the time this returns.
        await asyncio.to_thread(_notify_clearinghouse, subject, state)
        return {"subject": subject, "revoked": state["revoked"],
                "state_version": state["state_version"]}

    def _notify_clearinghouse(subject: str, state: dict) -> None:
        """Signed push: revocation changed, kill live sessions now."""
        notice = {"subject": subject, "agent_id": state["agent_id"],
                  "revoked": state["revoked"], "state_version": state["state_version"],
                  "ts": utc(datetime.now(timezone.utc))}
        der = priv.sign(canonical_bytes(notice), ec.ECDSA(hashes.SHA256()))
        r, s = utils.decode_dss_signature(der)
        notice["sig"] = b64u(r.to_bytes(32, "big") + s.to_bytes(32, "big"))
        ch_url = os.environ.get("CLEARINGHOUSE_URL", "http://127.0.0.1:8787")
        try:
            req = urllib.request.Request(
                ch_url + "/passport/revocations", data=json.dumps(notice).encode(),
                method="POST", headers={"Content-Type": "application/json"})
            # Wait for the clearinghouse to finish pushing to the sites:
            # revocation takes effect when this returns, not at expiry.
            urllib.request.urlopen(req, timeout=15).read()
        except Exception:
            pass  # push is best-effort; session expiry is the fallback

    @app.get("/revocation")
    def revocation(request: Request):
        """Revocation Check v1, by subject only (no identity answers)."""
        q = request.query_params
        headers = {"Cache-Control": "max-age=60"}
        if re.search(r"%(?![0-9A-Fa-f]{2})", request.url.query):
            return JSONResponse({"error": "malformed query"}, status_code=400)
        if "subject" in q and ("authority" in q or "identifier" in q):
            return JSONResponse({"error": "one form or the other"}, status_code=400)
        if "subject" not in q:
            return JSONResponse({"error": "subject required"}, status_code=400)
        subject = q["subject"]
        if not subject:
            return JSONResponse({"error": "subject required"}, status_code=400)
        now = utc(datetime.now(timezone.utc))
        state = app.state.subjects.get(subject)
        if state is None:
            body = {"subject": subject, "revoked": True, "revoked_scopes": [],
                    "min_required_revision": 0, "evaluated_at": now,
                    "state_version": 0, "reason": "no_passport_issued"}
        else:
            body = {"subject": subject, "revoked": state["revoked"],
                    "revoked_scopes": [],
                    "min_required_revision": state["min_required_revision"],
                    "evaluated_at": now, "state_version": state["state_version"]}
            if state["revoked"]:
                body["reason"] = "withdrawn_by_operator"
        return JSONResponse(body, headers=headers)

    return app


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(make_app(), host=os.environ.get("HOST", "127.0.0.1"),
                port=int(os.environ.get("ISSUER_PORT", "8010")))
