import json
from types import SimpleNamespace as NS

import pytest

from briefing.llm import Writer, WriterError

GOOD = "## Italy\n\n### Budget vote\nParliament approved it."


def _proc(payload, code=0):
    return NS(stdout=json.dumps(payload), stderr="", returncode=code)


def test_writer_builds_subscription_command_and_parses_json(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-never-be-used")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "oauth")
    seen = {}

    def runner(cmd, **kw):
        seen["cmd"], seen["env"], seen["input"] = cmd, kw["env"], kw["input"]
        return _proc({"result": GOOD, "is_error": False, "stop_reason": "end_turn",
                      "session_id": "s1", "modelUsage": {"claude-sonnet-5": {}},
                      "usage": {"output_tokens": 7,
                                "server_tool_use": {"web_search_requests": 3,
                                                    "web_fetch_requests": 1}}})

    res = Writer("sonnet", "high", runner=runner).run(system="SYS", user="USER",
                                                      allowed_domains=("ft.com",))
    assert res.text == GOOD and res.searches == 4 and res.model == "claude-sonnet-5"
    assert "ANTHROPIC_API_KEY" not in seen["env"] and seen["env"]["CLAUDE_CODE_OAUTH_TOKEN"]
    cmd = seen["cmd"]
    assert cmd[:2] == ["claude", "-p"] and seen["input"] == "USER"
    assert "WebFetch(domain:ft.com)" in cmd and "WebFetch(domain:*.ft.com)" in cmd
    assert cmd[cmd.index("--permission-mode") + 1] == "dontAsk"


def test_writer_without_domains_disables_tools():
    cmd = Writer("sonnet", "high")._command("s", None, "medium")
    assert cmd[cmd.index("--tools") + 1] == ""


@pytest.mark.parametrize("payload,code", [
    ({"result": "Claude usage limit reached", "is_error": True, "subtype": "error"}, 1),
    ({"result": "", "is_error": False}, 0),
])
def test_writer_raises_on_failure(payload, code):
    with pytest.raises(WriterError):
        Writer("sonnet", "high", runner=lambda c, **k: _proc(payload, code)).run(system="s", user="u")


def test_writer_raises_on_non_json():
    bad = lambda c, **k: NS(stdout="Invalid API key", stderr="", returncode=1)
    with pytest.raises(WriterError):
        Writer("sonnet", "high", runner=bad).run(system="s", user="u")
