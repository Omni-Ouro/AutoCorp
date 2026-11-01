"""Cross-implementation bridge: a site report signed by the TypeScript
verifier must verify under the Python implementation (the fixtures in
verifier/ts/test prove the other direction). Skipped when Node or the
built TS package is unavailable.
"""
import base64
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TS_DIR = ROOT / "verifier" / "ts"

sys.path.insert(0, str(ROOT))

from eyd.canonical import hash_bytes, record_hash  # noqa: E402
from eyd.identity import verify_b64  # noqa: E402

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None or not (TS_DIR / "dist" / "index.js").exists(),
    reason="needs Node and `npm --prefix verifier/ts run build`",
)


def test_ts_signed_report_verifies_in_python():
    out = subprocess.run(
        ["node", str(TS_DIR / "test" / "emit-report.mjs")],
        capture_output=True, text=True, timeout=60, check=True)
    report = json.loads(out.stdout)
    fixtures = json.loads((TS_DIR / "test" / "fixtures.json").read_text())

    assert report["site_id"] == fixtures["site"]["id"]
    assert report["result_hash"] == hash_bytes(b"hello")
    pubkey_raw = base64.b64decode(fixtures["site"]["pubkey_b64"])
    assert verify_b64(pubkey_raw, record_hash(report).encode(), report["sig"])
