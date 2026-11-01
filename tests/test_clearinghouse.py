import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "clearinghouse"))

from classify import DECLINED, EXPECTED, UNEXPECTED, UNVERIFIED, classify, compute_score  # noqa: E402


def agent_rep(h="sha256:a"):
    return {"output_hash": h, "status": "ok"}


def site_rep(outcome="fulfilled", h="sha256:a"):
    return {"outcome": outcome, "result_hash": h}


def test_expected_on_hash_match():
    assert classify(agent_rep(), site_rep()) == EXPECTED


def test_unexpected_on_hash_mismatch():
    assert classify(agent_rep("sha256:a"), site_rep(h="sha256:b")) == UNEXPECTED


def test_declined_regardless_of_hash():
    assert classify(agent_rep(), site_rep(outcome="declined")) == DECLINED


def test_unverified_with_only_one_report():
    assert classify(agent_rep(), None) == UNVERIFIED
    assert classify(None, site_rep()) == UNVERIFIED
    assert classify(None, None) == UNVERIFIED


def test_score_formula_and_null_below_n():
    classes = [EXPECTED] * 4 + [UNEXPECTED] * 4 + [DECLINED] * 2
    s = compute_score(classes)
    assert s["score"] == 0.4
    assert compute_score([EXPECTED] * 3)["score"] is None  # fewer than N=5 scored


def test_score_excludes_unverified_from_denominator():
    s = compute_score([EXPECTED] * 5 + [UNVERIFIED] * 10)
    assert s["score"] == 1.0
    assert s["unverified"] == 10
