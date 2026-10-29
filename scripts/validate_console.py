"""End-to-end validation of the judge console (real model calls).

Drives every demo setup through the console API and checks outcomes:
baseline refusal, Passport-only insufficiency, newcomer, attach/revoke/
detach on a live agent, tamper. Prints PASS/FAIL per check; exit code
is the number of failures.

Prereqs: issuer :8010, clearinghouse :8787, site :8001, console :8080.
Usage: python scripts/validate_console.py
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request

BASE = os.environ.get("CONSOLE_URL", "http://127.0.0.1:8080")
FAILURES = []


def call(method, path, payload=None, timeout=300):
    req = urllib.request.Request(BASE + path, method=method,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def check(name, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'}  {name}  {detail}")
    if not cond:
        FAILURES.append(name)


def act(agent, action):
    r = call("POST", "/api/act", {"agent": agent, "action": action})
    return r.get("http_status"), (r.get("receipt") or {}).get("classification"), \
        json.dumps(r.get("response_body"))


def agent(key):
    return next(a for a in call("GET", "/api/agents")["agents"] if a["key"] == key)


def passport(agent_key, op):
    return call("POST", "/api/passport", {"agent": agent_key, "op": op})


def main() -> int:
    a, b, c, d, e = (agent(k) for k in "ABCDE")
    check("A baseline", a["score"] is None and a["chip"] == "no EyD", a["chip"])
    check("B EyD low", abs((b["score"] or 0) - 0.4) < 0.06 and b["chip"] == "EyD",
          f'{b["chip"]} {b["score"]}')
    check("C EyD+Passport high", (c["score"] or 0) > 0.9 and c["chip"] == "EyD + Passport"
          and (c["passport_detail"] or {}).get("status") == "valid", c["chip"])
    check("D Passport only", (d["score"] or 0) > 0.9 and d["chip"] == "Passport only",
          d["chip"])
    check("E newcomer", e["score"] is None and e["chip"] == "EyD", e["chip"])
    check("boost A nowhere to land", call("POST", "/api/boost", {"agent": "A"})["ok"] is False)

    status, cls, _ = act("A", "pay")
    check("A pay refused, no receipt", status == 403 and cls is None, f"{status} {cls}")
    status, cls, _ = act("D", "pay")
    check("D pay refused (Passport alone), no receipt", status == 403 and cls is None,
          f"{status} {cls}")
    status, cls, _ = act("E", "quote")
    check("E quote admitted", status == 200 and cls == "Expected", f"{status} {cls}")
    status, cls, body = act("E", "pay")
    check("E pay Declined (score unknown)", status == 403 and cls == "Declined"
          and "PoT score unknown" in body, f"{status} {cls}")

    check("attach passport to B", passport("B", "attach")["passport_status"] == "valid")
    check("B chip updates", agent("B")["chip"] == "EyD + Passport")
    passport("B", "revoke")
    status, cls, body = act("B", "quote")
    check("B quote refused while revoked", status == 403 and cls == "Declined"
          and "AI Passport revoked" in body, f"{status} {cls}")
    passport("B", "reinstate")
    status, cls, _ = act("B", "quote")
    check("B quote admitted after reinstate", status == 200 and cls == "Expected",
          f"{status} {cls}")
    passport("B", "detach")
    check("B chip back to EyD", agent("B")["chip"] == "EyD")

    passport("C", "revoke")
    status, cls, body = act("C", "quote")
    check("C quote refused while revoked", status == 403 and "AI Passport revoked" in body,
          f"{status} {cls}")
    passport("C", "reinstate")

    call("POST", "/api/tamper", {"on": True})
    status, cls, _ = act("C", "quote")
    check("tamper -> Unexpected", status == 200 and cls == "Unexpected", f"{status} {cls}")
    call("POST", "/api/tamper", {"on": False})

    print(f"\n{len(FAILURES)} failure(s)")
    return len(FAILURES)


if __name__ == "__main__":
    sys.exit(main())
