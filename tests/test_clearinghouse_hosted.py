"""Hosted mode (v0.1.0): admin-locked demo endpoints + state persistence."""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from eyd.canonical import record_hash  # noqa: E402
from eyd.identity import Identity  # noqa: E402
from eyd.records import utc_now  # noqa: E402

CH_MAIN = ROOT / "clearinghouse" / "main.py"


def _load(name: str, monkeypatch, tmp_path: Path, token: str | None):
    monkeypatch.setenv("CH_STATE_FILE", str(tmp_path / "state.json"))
    monkeypatch.setenv("CLEARINGHOUSE_KEY_FILE", str(tmp_path / "ch-key.json"))
    if token is None:
        monkeypatch.delenv("CH_ADMIN_TOKEN", raising=False)
    else:
        monkeypatch.setenv("CH_ADMIN_TOKEN", token)
    spec = importlib.util.spec_from_file_location(name, CH_MAIN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _enroll(client: TestClient, ident: Identity):
    p = {"kind": "agent", "agent_id": ident.id, "pubkey": ident.pubkey_b64,
         "ts": utc_now()}
    p["sig"] = ident.sign(record_hash(p).encode())
    assert client.post("/enroll", json=p).status_code == 200


def test_admin_endpoints_locked_when_token_set(tmp_path, monkeypatch):
    client = TestClient(_load("ch_hosted_a", monkeypatch, tmp_path, "sekrit").app)
    assert client.post("/seed", json={"receipts": []}).status_code == 403
    ident = Identity.generate()
    _enroll(client, ident)
    assert client.post(f"/agents/{ident.id}/boost", json={}).status_code == 403
    hdr = {"x-admin-token": "sekrit"}
    assert client.post("/seed", json={"receipts": []}, headers=hdr).status_code == 200
    assert client.post(f"/agents/{ident.id}/boost", json={},
                       headers=hdr).status_code == 200


def test_admin_endpoints_open_when_token_unset(tmp_path, monkeypatch):
    client = TestClient(_load("ch_hosted_b", monkeypatch, tmp_path, None).app)
    assert client.post("/seed", json={"receipts": []}).status_code == 200


def test_state_survives_restart(tmp_path, monkeypatch):
    hdr = {"x-admin-token": "sekrit"}
    client = TestClient(_load("ch_hosted_c", monkeypatch, tmp_path, "sekrit").app)
    ident = Identity.generate()
    _enroll(client, ident)
    rh = "sha256:" + "ab" * 32
    seeded = [{"record_hash": rh, "agent_id": ident.id, "site_id": "SEEDED",
               "classification": "Expected", "target": "seeded.demo",
               "ts": utc_now(), "ch_sig": "ed25519:demo", "demo_data": True}]
    assert client.post("/seed", json={"receipts": seeded},
                       headers=hdr).status_code == 200
    assert (tmp_path / "state.json").exists()

    # Fresh process, same state file: enrollment + receipt are still there.
    client2 = TestClient(_load("ch_hosted_d", monkeypatch, tmp_path, "sekrit").app)
    assert client2.get(f"/agents/{ident.id}").status_code == 200
    assert client2.get(f"/receipts/{rh}").json()["classification"] == "Expected"
    assert client2.get(f"/agents/{ident.id}/score").status_code == 200
