import json
from datetime import datetime, timedelta, timezone

import pytest
from types import SimpleNamespace as NS

from briefing.config import Settings
from briefing.dispatch import DispatchType
from briefing.llm import LLMResult, Writer, WriterError
from briefing.pipeline import RunOptions, run_dispatch

NOW = datetime(2026, 9, 27, 17, 0, tzinfo=timezone.utc)

GOOD = """# PM INTELLIGENCE BRIEFING | PART 1/2
**Macro, Geopolitics & Capital Markets**
*Date: 27 September 2026 | As of: 17:00 UTC*
🇪🇺 **1. European Core (Policy, ECB, Member States)**
🌐 **2. Global Axis (US, China, Russia, BRICS+)**
📊 **3. Market Ledger & Institutional Sentiment**"""


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


class FakeWriter:
    def __init__(self, outputs):
        self.outputs, self.calls = list(outputs), []

    def run(self, **kw):
        self.calls.append(kw)
        out = self.outputs.pop(0)
        if isinstance(out, Exception):
            raise out
        return LLMResult(out, "claude-sonnet-5", "end_turn", {"output_tokens": 1})


class FakeTelegram:
    def __init__(self):
        self.sent = []

    def send_briefing(self, chat, md):
        self.sent.append((chat, md))
        return [1]


def _settings(tmp_path):
    s = Settings()
    s.state_dir, s.archive_dir = tmp_path / "state", tmp_path / "archive"
    s.telegram_chat_ids = ["@test"]
    return s


OPTS = RunOptions(send=True, web=False, markets=False, feeds=False)


def test_pipeline_happy_path_sends_and_archives(tmp_path):
    tg, w = FakeTelegram(), FakeWriter([GOOD])
    r = run_dispatch(DispatchType.PM_PART_1, NOW, _settings(tmp_path), OPTS, writer=w, telegram=tg)
    assert r.text == GOOD and tg.sent == [("@test", GOOD)]
    assert (tmp_path / "archive" / "2026-09-27" / "PM_PART_1.md").read_text() == GOOD
    assert len(w.calls) == 1


def test_pipeline_compresses_overlong_output(tmp_path):
    long = GOOD + "\n" + "- filler detail 12bps\n" * 300
    w = FakeWriter([long, GOOD])
    r = run_dispatch(DispatchType.PM_PART_1, NOW, _settings(tmp_path), OPTS, writer=w,
                     telegram=FakeTelegram())
    assert r.text == GOOD and r.meta["rewrites"][0].startswith("compress")
    assert w.calls[1].get("allowed_domains") is None


def test_pipeline_repairs_missing_section(tmp_path):
    broken = GOOD.replace("3. Market Ledger", "3. Markets")
    w = FakeWriter([broken, GOOD])
    r = run_dispatch(DispatchType.PM_PART_1, NOW, _settings(tmp_path), OPTS, writer=w,
                     telegram=FakeTelegram())
    assert r.meta["missing_sections"] == [] and r.meta["rewrites"][0].startswith("repair")


def test_pipeline_falls_back_to_headline_digest(tmp_path, monkeypatch):
    from briefing import ingest
    from briefing.ingest import Item, score

    t = "Kremlin reroutes Urals crude as EU sanctions bite"
    item = Item("FT", t, "https://ft.com/x", NOW - timedelta(hours=1), "", ("geo",), score(t, ""))
    monkeypatch.setattr(ingest, "collect", lambda *a, **k: ([item], {"FT": "ok (1)"}))
    tg = FakeTelegram()
    w = FakeWriter([WriterError("usage limit reached")])
    opts = RunOptions(send=True, web=True, markets=False, feeds=True)
    r = run_dispatch(DispatchType.PM_PART_1, NOW, _settings(tmp_path), opts, writer=w, telegram=tg)
    assert r.meta["mode"] == "digest" and "usage limit" in r.meta["error"]
    assert r.text.startswith("# PM INTELLIGENCE BRIEFING | PART 1/2")
    assert "🇷🇺 **Russia**" in r.text and t in r.text
    assert tg.sent and len(w.calls) == 1  # no rewrite attempts in digest mode
    assert not (tmp_path / "state" / "state.json").exists()
