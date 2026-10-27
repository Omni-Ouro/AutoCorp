"""Pairing + classification + PoT score (PROOF v0 §3.5, §3.10). Pure functions."""
from __future__ import annotations

EXPECTED = "Expected"
UNEXPECTED = "Unexpected"
DECLINED = "Declined"
UNVERIFIED = "Unverified"

MIN_RECEIPTS = 5  # N: score is null with fewer than this many scored receipts


def classify(agent_report: dict | None, site_report: dict | None) -> str:
    """Run when both reports are in, or when the window closes."""
    if site_report is not None and site_report.get("outcome") == "declined":
        return DECLINED
    if agent_report is not None and site_report is not None:
        if (
            site_report.get("outcome") == "fulfilled"
            and site_report.get("result_hash") == agent_report.get("output_hash")
        ):
            return EXPECTED
        return UNEXPECTED
    return UNVERIFIED


def compute_score(classifications: list[str], min_receipts: int = MIN_RECEIPTS) -> dict:
    """Score counts exclude Unverified from the denominator (§3.10).

    `classifications` should already exclude `target: local` actions,
    which never affect the score.
    """
    counts = {EXPECTED: 0, UNEXPECTED: 0, DECLINED: 0, UNVERIFIED: 0}
    for c in classifications:
        if c in counts:
            counts[c] += 1
    scored = counts[EXPECTED] + counts[UNEXPECTED] + counts[DECLINED]
    total = sum(counts.values())
    score = (counts[EXPECTED] / scored) if scored >= min_receipts and scored > 0 else None
    # With >= min scored receipts the formula applies; below it, null.
    if scored < min_receipts:
        score = None
    return {
        "score": score,
        "expected": counts[EXPECTED],
        "unexpected": counts[UNEXPECTED],
        "declined": counts[DECLINED],
        "unverified": counts[UNVERIFIED],
        "total": total,
        "scored": scored,
    }
