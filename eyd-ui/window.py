"""EyD window (§3.2) — standalone entry point.

The window implementation lives in `eyd/window.py` (it is what
`eyd run` attaches to the local chain); this is the same window run
on its own:  python eyd-ui/window.py [--port 8790]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eyd.identity import default_chain_path, default_identity_path  # noqa: E402
from eyd.reporter import Reporter  # noqa: E402
from eyd.window import make_window_server  # noqa: E402

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8790)
    ap.add_argument("--clearinghouse", default="http://127.0.0.1:8787")
    ap.add_argument("--identity", default=None)
    ap.add_argument("--chain", default=None)
    a = ap.parse_args()
    server = make_window_server(
        Path(a.identity) if a.identity else default_identity_path(),
        Path(a.chain) if a.chain else default_chain_path(),
        Reporter(a.clearinghouse), port=a.port)
    print(f"EyD window: http://127.0.0.1:{a.port}")
    server.serve_forever()
