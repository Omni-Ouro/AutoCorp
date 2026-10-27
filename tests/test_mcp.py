import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "verifier" / "python"))

from eyd.chain import LocalChain  # noqa: E402
from eyd.identity import Identity  # noqa: E402
from eyd.mcp import McpEydServer, parse_upstream, verb_for_tool  # noqa: E402


def test_mcp_initialize_and_tools_list(tmp_path):
    ident = Identity.generate()
    server = McpEydServer(LocalChain(tmp_path / "c.jsonl", ident), ident, reporter=None)
    resp = server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert resp["result"]["serverInfo"]["name"] == "eyd"
    resp = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    names = [t["name"] for t in resp["result"]["tools"]]
    assert names == ["http.get", "http.post"]


def test_verb_mapping():
    assert verb_for_tool("http.post") == "send"
    assert verb_for_tool("submit_quote_request") == "send"
    assert verb_for_tool("read_file") == "read"
    assert verb_for_tool("pay_charge") == "pay"
    assert verb_for_tool("something_else") == "execute"


def test_parse_upstream_windows_paths():
    parts = parse_upstream(r"C:\Python\python.exe server.py")
    assert parts is not None and parts[1] == "server.py"
    assert "\\" in parts[0] or parts[0].endswith("python.exe")
