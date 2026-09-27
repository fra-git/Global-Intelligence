"""End-to-end dispatch: ingest -> prompt -> research/write -> validate -> deliver -> archive."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from briefing import ingest, markets
from briefing.config import Settings, load_calendar, load_sources, load_system_prompt
from briefing.dispatch import SPECS, DispatchType
from briefing.llm import Writer, web_tools
from briefing.postprocess import clean, hard_trim, missing_sections, tg_len
from briefing.prompt import COMPRESS_INSTRUCTION, REPAIR_INSTRUCTION, build_user_message
from briefing.state import State, archive, prior_context
from briefing.telegram import Telegram

log = logging.getLogger(__name__)

MAX_REWRITES = 2


@dataclass
class RunOptions:
    send: bool = True
    web: bool = True
    markets: bool = True
    feeds: bool = True
    print_prompt: bool = False


@dataclass
class DispatchResult:
    dispatch: DispatchType
    text: str
    chars: int
    meta: dict = field(default_factory=dict)


def run_dispatch(
    dispatch: DispatchType,
    now: datetime,
    settings: Settings,
    opts: RunOptions,
    writer: Writer | None = None,
    telegram: Telegram | None = None,
    quotes_cache: dict | None = None,
) -> DispatchResult:
    spec = SPECS[dispatch]
    sources = load_sources()
    state = State(settings.state_dir)
    system = load_system_prompt()

    items, feed_status = [], {}
    if opts.feeds:
        items, feed_status = ingest.collect(
            sources.feeds, spec.pillars, now, spec.lookback_hours,
            settings.max_feed_items, state.seen_keys(now),
        )
    log.info("%s: %d fresh feed items", dispatch.value, len(items))

    market_block = None
    if spec.wants_market_snapshot and opts.markets:
        if quotes_cache is not None and "quotes" in quotes_cache:
            quotes = quotes_cache["quotes"]
        else:
            quotes = markets.snapshot()
            if quotes_cache is not None:
                quotes_cache["quotes"] = quotes
        market_block = markets.render(quotes)

    user = build_user_message(
        spec, now, items, market_block, load_calendar(),
        prior_context(state, dispatch.value, now), settings.max_chars,
    )
    if opts.print_prompt:
        print(user)

    writer = writer or Writer(settings.anthropic_model, settings.effort)
    tools = web_tools(sources.allowed_domains, settings.web_search_max_uses) if opts.web else None
    res = writer.run(system=system, user=user, tools=tools)
    text = clean(res.text)
    usage = dict(res.usage)
    rewrites = []

    # Enforce template and length with targeted rewrites (no tools: facts are fixed now).
    for _ in range(MAX_REWRITES):
        missing = missing_sections(text, spec)
        n = tg_len(text)
        if missing:
            instr = REPAIR_INSTRUCTION.format(missing=", ".join(missing), dispatch=dispatch.value,
                                              limit=settings.max_chars, draft=text)
            rewrites.append(f"repair: {missing}")
        elif n > settings.max_chars:
            instr = COMPRESS_INSTRUCTION.format(length=n, limit=settings.max_chars,
                                                target=int(settings.max_chars * 0.93), draft=text)
            rewrites.append(f"compress: {n}")
        else:
            break
        fix = writer.run(system=system, user=instr, effort="medium", max_tokens=16000)
        for k, v in fix.usage.items():
            usage[k] = usage.get(k, 0) + v
        text = clean(fix.text) or text

    if tg_len(text) > settings.max_chars:
        log.warning("still over limit after rewrites; trimming on line boundary")
        text = hard_trim(text, settings.max_chars)
        rewrites.append("hard_trim")

    meta = {
        "dispatch": dispatch.value,
        "generated_at": now.isoformat(),
        "model": res.model,
        "stop_reason": res.stop_reason,
        "web_tool_calls": res.searches,
        "usage": usage,
        "request_ids": res.request_ids,
        "chars_utf16": tg_len(text),
        "feed_items": len(items),
        "feed_status": feed_status,
        "rewrites": rewrites,
        "missing_sections": missing_sections(text, spec),
        "sent_to": [],
    }

    if opts.send:
        telegram = telegram or Telegram(settings.telegram_bot_token)
        if not settings.telegram_chat_ids:
            raise ValueError("TELEGRAM_CHAT_IDS is not set")
        for chat in settings.telegram_chat_ids:
            meta["sent_to"].append({"chat": chat, "message_ids": telegram.send_briefing(chat, text)})

    archive(settings.archive_dir, dispatch.value, now, text, meta)
    state.set_last(dispatch.value, text, now)
    state.mark_seen([it.key for it in items], now)
    state.save()
    return DispatchResult(dispatch, text, tg_len(text), meta)


def run_session(parts: list[DispatchType], settings: Settings, opts: RunOptions,
                now: datetime | None = None) -> list[DispatchResult]:
    """Run parts sequentially so Part 2 sees Part 1 (dedup) and quotes are fetched once."""
    results, cache = [], {}
    for d in parts:
        results.append(run_dispatch(d, now or datetime.now(timezone.utc), settings, opts,
                                    quotes_cache=cache))
    return results
