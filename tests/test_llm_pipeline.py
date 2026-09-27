from datetime import datetime, timezone
from types import SimpleNamespace as NS

from briefing.config import Settings
from briefing.dispatch import DispatchType
from briefing.llm import LLMResult, Writer, final_text
from briefing.pipeline import RunOptions, run_dispatch

NOW = datetime(2026, 9, 27, 17, 0, tzinfo=timezone.utc)

GOOD = """# PM INTELLIGENCE BRIEFING | PART 1/2
**Macro, Geopolitics & Capital Markets**
*Date: 27 September 2026 | As of: 17:00 UTC*
🇪🇺 **1. European Core (Policy, ECB, Member States)**
🌐 **2. Global Axis (US, China, Russia, BRICS+)**
📊 **3. Market Ledger & Institutional Sentiment**"""


def test_final_text_ignores_narration_before_last_search():
    content = [NS(type="text", text="Let me search."), NS(type="server_tool_use", id="1"),
               NS(type="web_search_tool_result", tool_use_id="1"),
               NS(type="text", text="# Brief"), NS(type="text", text=" body")]
    assert final_text(content) == "# Brief body"


class _Stream:
    def __init__(self, msg):
        self.msg = msg

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        return self.msg


def _msg(stop, content):
    usage = NS(input_tokens=10, output_tokens=5, cache_read_input_tokens=0,
               cache_creation_input_tokens=0)
    return NS(stop_reason=stop, content=content, usage=usage, model="claude-opus-5",
              _request_id="req_1")


def test_writer_resumes_pause_turn():
    calls = []
    msgs = [_msg("pause_turn", [NS(type="server_tool_use", id="a"),
                                NS(type="web_search_tool_result", tool_use_id="a")]),
            _msg("end_turn", [NS(type="text", text=GOOD)])]

    def stream(**kw):
        calls.append(kw)
        return _Stream(msgs[len(calls) - 1])

    client = NS(beta=NS(messages=NS(stream=stream)))
    res = Writer("claude-opus-5", "high", client=client).run(system="s", user="u", tools=[{}])
    assert res.text == GOOD and res.searches == 1
    assert calls[1]["messages"][1]["role"] == "assistant"
    assert calls[0]["fallbacks"] == "default" and calls[0]["thinking"] == {"type": "adaptive"}


class FakeWriter:
    def __init__(self, outputs):
        self.outputs, self.calls = list(outputs), []

    def run(self, **kw):
        self.calls.append(kw)
        return LLMResult(self.outputs.pop(0), "claude-opus-5", "end_turn", {"output_tokens": 1})


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
    assert "tools" not in w.calls[1] or w.calls[1].get("tools") is None


def test_pipeline_repairs_missing_section(tmp_path):
    broken = GOOD.replace("3. Market Ledger", "3. Markets")
    w = FakeWriter([broken, GOOD])
    r = run_dispatch(DispatchType.PM_PART_1, NOW, _settings(tmp_path), OPTS, writer=w,
                     telegram=FakeTelegram())
    assert r.meta["missing_sections"] == [] and r.meta["rewrites"][0].startswith("repair")
