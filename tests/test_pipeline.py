import re
from datetime import datetime, timedelta, timezone

from briefing import ingest
from briefing.config import Settings
from briefing.dispatch import SPECS, Edition
from briefing.ingest import Item, score
from briefing.llm import LLMResult, WriterError
from briefing.pipeline import RunOptions, run_edition
from briefing.report import _body_html, render_html

NOW = datetime(2026, 10, 8, 3, 50, tzinfo=timezone.utc)  # Thursday 05:50 Italy
_SECTION = re.compile(r"^## (.+)\n   About", re.MULTILINE)


class FakeWriter:
    """Answers every requested section; `fail` makes runs for a desk raise."""

    def __init__(self, fail: str = "", drop: str = ""):
        self.fail, self.drop, self.calls = fail, drop, []

    def run(self, *, system, user, allowed_domains=None, effort=None):
        self.calls.append({"user": user, "domains": allowed_domains, "effort": effort})
        if self.fail and f"DESK: {self.fail}" in user:
            raise WriterError("usage limit reached")
        heads = _SECTION.findall(user) or re.findall(r"'## ([^']+)'", user)
        body = "\n\n".join(f"## {h}\n\n### {h} story\nFact with 3.2%.\n\n"
                           f"*Sources: [FT](https://ft.com/{i})*" for i, h in enumerate(heads)
                           if h != self.drop)
        return LLMResult(body, "claude-sonnet-5", "end_turn", {"output_tokens": 1}, searches=3)


class FakeTelegram:
    def __init__(self):
        self.messages, self.documents = [], []

    def send_briefing(self, chat, md):
        self.messages.append((chat, md))
        return [1]

    def send_document(self, chat, name, data, caption="", mime="application/pdf"):
        self.documents.append((chat, name, data, caption, mime))
        return 2


def _settings(tmp_path):
    s = Settings()
    s.state_dir, s.archive_dir = tmp_path / "state", tmp_path / "archive"
    s.telegram_chat_ids = ["@test"]
    s.parallel_desks = 2
    return s


OPTS = RunOptions(send=True, web=False, markets=False, feeds=False)


def test_daily_runs_every_desk_then_editor_and_delivers_pdf(tmp_path):
    w, tg = FakeWriter(), FakeTelegram()
    r = run_edition(Edition.DAILY, NOW, _settings(tmp_path), OPTS, writer=w, telegram=tg)
    spec = SPECS[Edition.DAILY]
    assert len(w.calls) == len(spec.desks) + 1 and "Editor-in-chief" in w.calls[-1]["user"]
    assert "## Russia & Ukraine" in w.calls[-1]["user"]  # editor sees the desk reports
    assert r.meta["mode"] == "ai" and r.meta["fallback_sections"] == []
    assert r.pdf.startswith(b"%PDF") and r.pages > 5
    (chat, msg), = tg.messages
    assert msg.startswith("**DAILY INTELLIGENCE REPORT**") and "At a Glance story" in msg
    assert f"{r.pages} pages" in msg
    (_, name, data, caption, mime), = tg.documents
    assert name == "Global-Intelligence_Daily_2026-10-08.pdf" and data == r.pdf
    day = tmp_path / "archive" / "2026-10-08"
    assert (day / "DAILY.pdf").exists() and "## Latin America" in (day / "DAILY.md").read_text()


def test_failed_desk_becomes_headline_digest_rest_still_written(tmp_path, monkeypatch):
    t = "Sudan ceasefire talks collapse in Jeddah"
    item = Item("FT", t, "https://ft.com/x", NOW - timedelta(hours=1), "", ("af",), score(t, ""))
    monkeypatch.setattr(ingest, "fetch_all", lambda feeds: ([item], {"FT": "ok (1)"}))
    w, tg = FakeWriter(fail="World Regions"), FakeTelegram()
    opts = RunOptions(send=True, web=True, markets=False, feeds=True)
    r = run_edition(Edition.DAILY, NOW, _settings(tmp_path), opts, writer=w, telegram=tg)
    assert r.meta["mode"] == "partial" and r.meta["desks"]["world"]["mode"] == "digest"
    assert "Africa" in r.meta["fallback_sections"] and "Italy" not in r.meta["fallback_sections"]
    africa = r.markdown.split("## Africa", 1)[1].split("\n## ", 1)[0]
    assert "Automated headline digest" in africa and t in africa
    assert w.calls[0]["domains"]  # web research enabled
    assert tg.documents


def test_missing_section_triggers_one_repair_pass(tmp_path):
    w = FakeWriter(drop="Space")
    r = run_edition(Edition.DAILY, NOW, _settings(tmp_path), OPTS, writer=w, telegram=FakeTelegram())
    repairs = [c for c in w.calls if c["user"].startswith("The draft below is missing")]
    assert len(repairs) == 1 and repairs[0]["effort"] == "medium"
    assert r.meta["desks"]["sectech"]["repair"] == ["Space"]
    assert "Space" in r.meta["fallback_sections"]  # the fake drops it again on repair


def test_second_trigger_for_same_session_is_skipped(tmp_path):
    s = _settings(tmp_path)
    run_edition(Edition.EVENING, NOW + timedelta(hours=15), s, OPTS, writer=FakeWriter(),
                telegram=FakeTelegram())
    tg = FakeTelegram()
    again = run_edition(Edition.EVENING, NOW + timedelta(hours=16), s, OPTS, writer=FakeWriter(),
                        telegram=tg)
    assert again.skipped and not tg.messages
    forced = run_edition(Edition.EVENING, NOW + timedelta(hours=16), s,
                         RunOptions(send=True, web=False, markets=False, feeds=False, force=True),
                         writer=FakeWriter(), telegram=tg)
    assert not forced.skipped and tg.messages


def test_weekly_editor_gets_the_weeks_daily_front_pages(tmp_path):
    s = _settings(tmp_path)
    run_edition(Edition.DAILY, NOW, s, OPTS, writer=FakeWriter(), telegram=FakeTelegram())
    w = FakeWriter()
    sunday = NOW + timedelta(days=3)
    r = run_edition(Edition.WEEKLY, sunday, s, OPTS, writer=w, telegram=FakeTelegram())
    assert "<this_week_daily_reports" in w.calls[-1]["user"]
    assert "At a Glance story" in w.calls[-1]["user"]
    assert "## Deep Dive" in r.markdown and r.meta["mode"] == "ai"


def test_report_html_neutralises_raw_html_and_unsafe_links():
    out = _body_html("<script>x</script> [a](javascript:alert(1)) [b](https://ft.com/ok)\n\n"
                     "*Sources: [FT](https://ft.com)*")
    assert "<script>" not in out and 'href="#"' in out and 'href="https://ft.com/ok"' in out
    assert '<p class="sources">' in out
    page = render_html(SPECS[Edition.EVENING], NOW, {"What Changed Today": "- **x:** y"}, [])
    assert "Evening Update" in page and "Market data unavailable" in page
