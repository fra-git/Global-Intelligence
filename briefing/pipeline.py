"""End-to-end edition: ingest -> desks (research + writing) -> editor -> PDF -> deliver -> archive."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone

from briefing import digest, ingest, markets
from briefing.config import Settings, load_calendar, load_sources, load_system_prompt
from briefing.dispatch import EDITOR, MARKETS, SPECS, Edition, EditionSpec, local_now
from briefing.llm import Writer, WriterError
from briefing.postprocess import clean, missing, split_sections, word_count
from briefing.prompt import (REPAIR_INSTRUCTION, build_desk_message, build_editor_message,
                             fmt_calendar)
from briefing.report import assemble_markdown, render_html, render_pdf
from briefing.state import State, archive, outline_of, prior_context
from briefing.telegram import Telegram

log = logging.getLogger(__name__)

_CALENDAR_SECTIONS = ("What to Watch", "Week Ahead", "Overnight & Tomorrow")


@dataclass
class RunOptions:
    send: bool = True
    web: bool = True
    markets: bool = True
    feeds: bool = True
    print_prompt: bool = False
    # Send even if this session was already delivered today (manual re-runs).
    force: bool = False


@dataclass
class EditionResult:
    edition: Edition
    markdown: str = ""
    summary: str = ""
    pdf: bytes | None = None
    pages: int = 0
    meta: dict = field(default_factory=dict)
    skipped: bool = False


def write_sections(writer: Writer, system: str, user: str, headings: list[str],
                   domains: tuple[str, ...] | None) -> tuple[dict[str, str], dict]:
    """One Claude Code run for a desk, plus one tool-free repair pass if sections are missing."""
    try:
        res = writer.run(system=system, user=user, allowed_domains=domains)
    except WriterError as exc:
        log.error("desk run failed: %s", exc)
        return {}, {"mode": "digest", "error": str(exc)}
    text = clean(res.text)
    info = {"mode": "ai", "model": res.model, "web_tool_calls": res.searches,
            "usage": dict(res.usage), "session_ids": list(res.request_ids), "repair": None}
    gaps = missing(text, headings)
    if gaps:
        info["repair"] = gaps
        instr = REPAIR_INSTRUCTION.format(missing=", ".join(gaps), draft=text,
                                          headings=", ".join(f"'## {h}'" for h in headings))
        try:
            fix = clean(writer.run(system=system, user=instr, effort="medium").text)
            if len(missing(fix, headings)) < len(gaps):
                text = fix
        except WriterError as exc:
            log.warning("repair pass failed (%s); keeping draft", exc)
    sections = split_sections(text, headings)
    info["missing"] = [h for h in headings if h not in sections]
    info["words"] = word_count(text)
    return sections, info


def _fallback(spec: EditionSpec, heading: str, tags: tuple[str, ...], pool: list[ingest.Item],
              calendar: list[dict], now: datetime) -> str:
    if heading == spec.summary_heading:
        return digest.glance(pool)
    if heading in _CALENDAR_SECTIONS:
        return digest.NOTE + "\n\nScheduled events:\n\n" + fmt_calendar(calendar, now)
    if tags:
        return digest.section(ingest.select(pool, tags, 8, per_tag=8))
    return "*Not available this edition.*"


def _summary_message(spec: EditionSpec, now: datetime, summary: str, pages: int) -> str:
    loc = local_now(now)
    tail = (f"📄 *Full report attached — {pages} pages.*" if pages
            else "📄 *Full report attached.*")
    return (f"**{spec.title.upper()}**\n*{loc:%A %d %B %Y}*\n\n{summary.strip()}\n\n{tail}")


def run_edition(
    edition: Edition,
    now: datetime,
    settings: Settings,
    opts: RunOptions,
    writer: Writer | None = None,
    telegram: Telegram | None = None,
) -> EditionResult:
    spec = SPECS[edition]
    state = State(settings.state_dir)
    loc = local_now(now)
    delivered_key = f"{loc:%Y-%m-%d}:{edition.session}"
    if opts.send and not opts.force and state.was_delivered(delivered_key):
        log.warning("%s session of %s already delivered; skipping (use --force to resend)",
                    edition.session, f"{loc:%Y-%m-%d}")
        return EditionResult(edition, skipped=True)

    sources = load_sources()
    system = load_system_prompt()
    calendar = load_calendar()

    raw, feed_status = ingest.fetch_all(sources.feeds) if opts.feeds else ([], {})
    seen = state.seen_keys(now) if spec.skip_seen else frozenset()
    pool = ingest.window(raw, now, spec.lookback_hours, seen)
    log.info("%s: %d fresh feed items from %d feeds", edition.value, len(pool), len(feed_status))

    quotes = markets.snapshot() if opts.markets else []
    market_block = markets.render(quotes) if opts.markets else None

    prior = prior_context(state, edition.value, now)
    writer = writer or Writer(settings.model, settings.effort, binary=settings.claude_bin,
                              timeout_s=settings.claude_timeout_s)
    domains = sources.allowed_domains if opts.web else None

    def run_desk(desk):
        items = ingest.select(pool, desk.tags, spec.feed_items_per_desk)
        searches = max(1, round(desk.searches * settings.search_scale))
        user = build_desk_message(spec, desk, now, items, market_block, calendar, prior, searches)
        if opts.print_prompt:
            print(f"===== {desk.key} =====\n{user}\n")
        headings = [s.heading for s in spec.sections_for(desk.key)]
        sections, info = write_sections(writer, system, user, headings, domains)
        info["feed_items"] = len(items)
        return desk, items, sections, info

    bodies: dict[str, str] = {}
    desk_meta: dict[str, dict] = {}
    used_keys: list[str] = []
    with ThreadPoolExecutor(max_workers=max(1, settings.parallel_desks)) as pool_ex:
        for desk, items, sections, info in pool_ex.map(run_desk, spec.desks):
            bodies.update(sections)
            desk_meta[desk.key] = info
            if info["mode"] == "ai":
                used_keys += [i.key for i in items]

    editor_sections = spec.sections_for(EDITOR)
    if editor_sections:
        desk_reports = "\n\n".join(f"## {s.heading}\n\n{bodies[s.heading]}"
                                   for s in spec.sections if s.heading in bodies
                                   and s.desk not in (EDITOR, MARKETS))
        searches = round(spec.editor_searches * settings.search_scale)
        user = build_editor_message(
            spec, now, desk_reports or "(no desk reports available this edition)", calendar,
            state.week_memory() if edition is Edition.WEEKLY else None, searches)
        if opts.print_prompt:
            print(f"===== editor =====\n{user[:3000]}\n...")
        sections, info = write_sections(writer, system, user,
                                        [s.heading for s in editor_sections],
                                        domains if searches else None)
        bodies.update(sections)
        desk_meta[EDITOR] = info

    fallbacks = []
    for s in spec.sections:
        if s.desk != MARKETS and not bodies.get(s.heading, "").strip():
            bodies[s.heading] = _fallback(spec, s.heading, s.tags, pool, calendar, now)
            fallbacks.append(s.heading)

    modes = {m["mode"] for m in desk_meta.values()}
    mode = "ai" if modes == {"ai"} and not fallbacks else "digest" if "ai" not in modes else "partial"
    searches_used = sum(m.get("web_tool_calls", 0) for m in desk_meta.values())
    meta_line = (f"{len(pool)} news items scanned · {searches_used} web lookups"
                 + (" · some sections are headline-only this edition" if fallbacks else ""))

    markdown = assemble_markdown(spec, now, bodies, quotes)
    pdf, pages = None, 0
    try:
        pdf, pages = render_pdf(render_html(spec, now, bodies, quotes, meta_line))
    except Exception as exc:  # deliver the summary and markdown rather than nothing
        log.error("PDF rendering failed: %s", exc)

    summary = bodies.get(spec.summary_heading, "")
    meta = {
        "edition": edition.value,
        "generated_at": now.isoformat(),
        "mode": mode,
        "desks": desk_meta,
        "fallback_sections": fallbacks,
        "words": word_count(markdown),
        "pages": pages,
        "feed_items": len(pool),
        "feed_status": feed_status,
        "sent_to": [],
    }
    result = EditionResult(edition, markdown, summary, pdf, pages, meta)
    archive(settings.archive_dir, edition.value, now, markdown, meta, pdf)

    if opts.send:
        deliver(result, spec, now, settings, telegram)
        state.mark_delivered(delivered_key, now)
        archive(settings.archive_dir, edition.value, now, markdown, meta, pdf)

    if mode != "digest":
        state.mark_seen(used_keys, now)
        desk_bodies = {s.heading: bodies[s.heading] for s in spec.sections
                       if s.desk not in (EDITOR, MARKETS)}
        state.set_outline(edition.value, outline_of(summary, desk_bodies), now)
        if edition is Edition.DAILY:
            state.add_week_entry(f"{loc:%Y-%m-%d}", summary, bodies.get("Scenarios", ""))
    state.save()
    return result


def deliver(result: EditionResult, spec: EditionSpec, now: datetime, settings: Settings,
            telegram: Telegram | None = None) -> None:
    """Post the summary and attach the report to every configured chat."""
    telegram = telegram or Telegram(settings.telegram_bot_token)
    if not settings.telegram_chat_ids:
        raise ValueError("TELEGRAM_CHAT_IDS is not set")
    loc = local_now(now)
    stem = f"Global-Intelligence_{spec.edition.value.title()}_{loc:%Y-%m-%d}"
    caption = f"{spec.title} — {loc:%d %B %Y}" + (f" ({result.pages} pages)" if result.pages else "")
    if result.pdf is not None:
        name, data, mime = f"{stem}.pdf", result.pdf, "application/pdf"
    else:
        name, data, mime = f"{stem}.md", result.markdown.encode(), "text/markdown"
    message = _summary_message(spec, now, result.summary, result.pages)
    for chat in settings.telegram_chat_ids:
        ids = telegram.send_briefing(chat, message)
        ids.append(telegram.send_document(chat, name, data, caption, mime))
        result.meta["sent_to"].append({"chat": chat, "message_ids": ids,
                                       "at": datetime.now(timezone.utc).isoformat()})
