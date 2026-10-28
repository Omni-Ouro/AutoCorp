"""AI Passport interoperability, in-repo (passport-interop/).

EyD's Passport check run against ServiceNow's published test vectors,
unmodified: one data-driven test per vector file, looping over every
case so a failure names the case id. Vectors are Apache-2.0. The same
vectors pass with the upstream runner (verifier 81/81, caller 74/74 on
2026-10-27); these tests keep that true without the upstream checkout.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "clearinghouse-ref"))

import passport as pp  # noqa: E402

VECTORS = ROOT / "passport-interop" / "vectors"


def test_passport_verification_vectors():
    data = json.loads((VECTORS / "passport-verification.json").read_text())
    jwks = json.loads((VECTORS / "jwks.json").read_text())
    failures = []
    for case in data["vectors"]:
        outcome, step = pp.verify_passport(case["input"], jwks, data["issuer"])
        expected = case["expected"]
        if outcome != expected["outcome"] or step != expected["step"]:
            failures.append(f"{case['id']}: got ({outcome}, {step}), "
                            f"want ({expected['outcome']}, {expected['step']})")
    assert not failures, "\n".join(failures)


def test_revocation_caller_vectors():
    data = json.loads((VECTORS / "revocation-check.json").read_text())
    failures = []
    for case in data["caller"]:
        inp = case["input"]
        outcome = pp.interpret_revocation(
            inp["received"], inp.get("holds_passport"), inp.get("previously_applied"),
            inp.get("asked"), inp.get("now"), inp.get("previously_applied_expired", False))
        if outcome != case["expected"]["outcome"]:
            failures.append(f"{case['id']}: got {outcome}, want {case['expected']['outcome']}")
    assert not failures, "\n".join(failures)
