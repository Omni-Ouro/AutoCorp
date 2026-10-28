from dataclasses import dataclass, field

from eyd import EyD, ToolResult, current_headers
from eyd.chain import LocalChain
from eyd.identity import Identity


@dataclass
class FakeHttpResult:
    status: int
    body: str
    headers: dict = field(default_factory=dict)


def make_eyd(tmp_path):
    ident = Identity.generate()
    return EyD(ident, chain=LocalChain(tmp_path / "chain.jsonl", ident), reporter=None)


def test_decorator_records_and_passes_headers(tmp_path):
    eyd = make_eyd(tmp_path)
    seen = {}

    @eyd.tool(verb="send", target="example.com")
    def submit_quote_request(need: str):
        seen.update(current_headers())
        return f"quoted:{need}"

    assert submit_quote_request.__eyd_verb__ == "send"
    assert submit_quote_request(need="landing page") == "quoted:landing page"
    assert seen["EyD-Agent"] == eyd.identity.id
    assert seen["EyD-Record"].startswith("sha256:")
    ok, _ = eyd.chain.verify()
    assert ok
    assert eyd.chain.head()[0] == 1


def test_bare_decorator_and_wrap_infers_verb(tmp_path):
    eyd = make_eyd(tmp_path)

    @eyd.tool
    def read_file(path: str):
        return "contents"

    wrapped = eyd.wrap(lambda need: f"sent:{need}", verb="send")
    # wrap's tool name falls back to the function's __name__ ("<lambda>")
    # only for the record; the returned callable still works.
    assert read_file.__eyd_verb__ == "read"
    assert read_file(path="x") == "contents"
    # `wrap` is the runtime-table form of the same hook.
    send = eyd.wrap(lambda need: f"sent:{need}")
    assert send(need="x") == "sent:x"


def test_hook_wraps_framework_execute_tool(tmp_path):
    eyd = make_eyd(tmp_path)

    class Framework:
        def execute_tool(self, name, fn, args):
            return fn(**args)

    fw = Framework()
    assert eyd.hook(fw) is fw
    out = fw.execute_tool("submit_quote_request", lambda need: f"q:{need}", {"need": "x"})
    assert out == "q:x"
    ok, _ = eyd.chain.verify()
    assert ok and eyd.chain.head()[0] == 1


def test_challenge_retry_uses_same_record(tmp_path):
    eyd = make_eyd(tmp_path)
    calls = []

    @eyd.tool(verb="send", target="localhost")
    def submit(need: str):
        calls.append(current_headers())
        if len(calls) == 1:
            # uvicorn lowercases response headers; lookup must not care.
            return FakeHttpResult(403, "refused", {"eyd-challenge": "nonce-1"})
        return FakeHttpResult(200, "ok", {"eyd-session": "sess-1"})

    result = submit(need="x")
    assert result.status == 200
    assert len(calls) == 2
    assert calls[0]["EyD-Record"] == calls[1]["EyD-Record"]  # one Action Record
    assert "EyD-Attestation" in calls[1]
    assert eyd.sessions["localhost"] == "sess-1"
    assert eyd.chain.head()[0] == 1  # retry did not append a second record


def test_tool_result_output_hash_status(tmp_path):
    eyd = make_eyd(tmp_path)

    @eyd.tool(verb="send", target="localhost")
    def submit(need: str):
        return ToolResult(status=403, body="refused", headers={})

    result = submit(need="x")
    assert result.status == 403
    # Receipt slot recorded for the window; None without a clearinghouse.
    assert len(eyd.last_receipt) == 1 and list(eyd.last_receipt.values()) == [None]
