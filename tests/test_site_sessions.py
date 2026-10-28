"""Site session handling: a revocation push drops live sessions."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "verifier" / "python"))

from eyd.identity import Identity  # noqa: E402
from verifier import EyDSite  # noqa: E402


def test_drop_sessions_kills_only_that_agent():
    site = EyDSite(Identity.generate(kind="site"), clearinghouse_url="http://x",
                   domain="localhost")
    t1 = site.issue_session("AGENT1")
    t2 = site.issue_session("AGENT2")
    assert site.drop_sessions("AGENT1") == 1
    assert site.session_agent(t1) is None       # revoked: dead immediately
    assert site.session_agent(t2) == "AGENT2"   # others untouched
    assert site.drop_sessions("AGENT1") == 0
