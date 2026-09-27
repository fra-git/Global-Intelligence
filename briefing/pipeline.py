"""End-to-end dispatch: ingest -> prompt -> research/write -> validate -> deliver -> archive."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from briefing import digest, ingest, markets
from briefing.config import Settings, load_calendar, load_sources, load_system_prompt
from briefing.dispatch import SPECS, DispatchType
from briefing.llm import Writer, WriterError
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
            settings.max_feed_items, state.seen_keys(now), spec.region_quota,
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
        settings.web_search_max_uses,
    )
    if opts.print_prompt:
        print(user)

    writer = writer or Writer(settings.model, settings.effort, binary=settings.claude_bin,
                              timeout_s=settings.claude_timeout_s)
    domains = sources.allowed_domains if opts.web else None
    rewrites: list[str] = []
    usage: dict = {}
    model, stop_reason, tool_calls, request_ids, error = "", "", 0, [], None
    try:
        res = writer.run(system=system, user=user, allowed_domains=domains)
        text = clean(res.text)
        usage, model, stop_reason = dict(res.usage), res.model, res.stop_reason
        tool_calls, request_ids = res.searches, list(res.request_ids)
        mode = "ai"
    except WriterError as exc:
        # Option C: subscription limit hit, token expired, outage -> headline digest.
        log.error("%s: Claude Code unavailable (%s); sending headline digest", dispatch.value, exc)
        text = digest.build(spec, now, items, market_block, settings.max_chars)
        mode, error = "digest", str(exc)

    # Enforce template and length with targeted rewrites (no tools: facts are fixed now).
    for _ in range(MAX_REWRITES if mode == "ai" else 0):
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
        try:
            fix = writer.run(system=system, user=instr, effort="medium")
        except WriterError as exc:
            log.warning("rewrite failed (%s); keeping current draft", exc)
            rewrites.append("rewrite_failed")
            break
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
        "mode": mode,
        "error": error,
        "model": model,
        "stop_reason": stop_reason,
        "web_tool_calls": tool_calls,
        "usage": usage,
        "session_ids": request_ids,
        "chars_utf16": tg_len(text),
        "feed_items": len(items),
        "feed_status": feed_status,
        "rewrites": rewrites,
        "missing_sections": missing_sections(text, spec) if mode == "ai" else [],
        "sent_to": [],
    }

    result = DispatchResult(dispatch, text, tg_len(text), meta)
    if opts.send:
        deliver(result, settings, telegram)

    archive(settings.archive_dir, dispatch.value, now, text, meta)
    if mode == "ai":
        # A digest is not analysis: leave its items available to the next AI edition.
        state.set_last(dispatch.value, text, now)
        state.mark_seen([it.key for it in items], now)
        state.save()
    return result


def deliver(result: DispatchResult, settings: Settings, telegram: Telegram | None = None) -> None:
    """Post a generated briefing to every configured chat and record it in the archive."""
    telegram = telegram or Telegram(settings.telegram_bot_token)
    if not settings.telegram_chat_ids:
        raise ValueError("TELEGRAM_CHAT_IDS is not set")
    for chat in settings.telegram_chat_ids:
        ids = telegram.send_briefing(chat, result.text)
        result.meta["sent_to"].append({"chat": chat, "message_ids": ids,
                                       "at": datetime.now(timezone.utc).isoformat()})
    now = datetime.fromisoformat(result.meta["generated_at"])
    archive(settings.archive_dir, result.dispatch.value, now, result.text, result.meta)


def run_session(parts: list[DispatchType], settings: Settings, opts: RunOptions,
                now: datetime | None = None) -> list[DispatchResult]:
    """Run parts sequentially so Part 2 sees Part 1 (dedup) and quotes are fetched once."""
    results, cache = [], {}
    for d in parts:
        results.append(run_dispatch(d, now or datetime.now(timezone.utc), settings, opts,
                                    quotes_cache=cache))
    return results
