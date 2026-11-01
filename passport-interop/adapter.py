#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Adapter connecting EyD's AI Passport check to ServiceNow's published
test-vector runner (conformance/run.py in github.com/ServiceNow/ai-passport),
so our interoperability is measured by their vectors, not our reading.

    python run.py --role verifier --adapter "python passport-interop/adapter.py"
    python run.py --role caller   --adapter "python passport-interop/adapter.py"

Roles verifier and caller map to clearinghouse/passport.py. The
responder role is an issuer-side interface; EyD's demo issuer answers
by subject only and is exercised with the runner's live checks instead.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "clearinghouse"))

import passport as pp  # noqa: E402


def handle(msg: dict) -> dict:
    role = msg.get("role")
    if role == "verifier":
        outcome, step = pp.verify_passport(msg["input"], msg.get("jwks"), msg.get("issuer"))
        return {"outcome": outcome, "step": step}
    if role == "caller":
        inp = msg["input"]
        return {"outcome": pp.interpret_revocation(
            inp["received"], inp.get("holds_passport"), inp.get("previously_applied"),
            inp.get("asked"), inp.get("now"), inp.get("previously_applied_expired", False))}
    return {"error": f"unsupported role {role!r}"}


def main() -> None:
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            out = handle(json.loads(line))
        except Exception as e:  # report, keep serving the next case
            out = {"error": f"{type(e).__name__}: {e}"}
        sys.stdout.write(json.dumps(out) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
