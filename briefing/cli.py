"""Command line entry point: `python -m briefing <command>`."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone

from briefing import ingest
from briefing.config import Settings, load_sources
from briefing.dispatch import START_LOCAL, SPECS, TIMEZONE, edition_for, utc_offset_hours
from briefing.pipeline import RunOptions, run_edition
from briefing.telegram import Telegram


def _parse_now(value: str | None) -> datetime | None:
    if not value:
        return None
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def cmd_run(args) -> int:
    settings = Settings()
    opts = RunOptions(send=not args.no_send, web=not args.no_web, markets=not args.no_markets,
                      feeds=not args.no_feeds, print_prompt=args.print_prompt, force=args.force)
    now = _parse_now(args.now) or datetime.now(timezone.utc)
    r = run_edition(edition_for(args.edition, now), now, settings, opts)
    if r.skipped:
        print(f"{r.edition.value}: this session was already delivered today; nothing sent.")
        return 0
    print(f"===== {r.edition.value}: {r.meta['words']} words, {r.pages} pages, "
          f"mode={r.meta['mode']} =====\n{r.summary}")
    print(json.dumps({k: r.meta[k] for k in ("mode", "fallback_sections", "words", "pages",
                                              "feed_items")}, indent=2), file=sys.stderr)
    for desk, info in r.meta["desks"].items():
        u = info.get("usage", {})
        print(f"  {desk:<8} {info['mode']:<6} words={info.get('words', 0):<5} "
              f"web={info.get('web_tool_calls', 0):<3} turns={info.get('turns', 0):<3} "
              f"in={u.get('input_tokens', 0):,} "
              f"cache_read={u.get('cache_read_input_tokens', 0):,} "
              f"cache_write={u.get('cache_creation_input_tokens', 0):,} "
              f"out={u.get('output_tokens', 0):,} {info.get('error') or ''}", file=sys.stderr)
    print(f"  total tokens: {r.meta['usage_total']}", file=sys.stderr)
    return 1 if r.meta["mode"] == "digest" else 0


def cmd_gate(args) -> int:
    """Exit 0 if the delivery timezone currently has this UTC offset (DST-pair selection)."""
    current = utc_offset_hours()
    ok = abs(current - args.utc_offset) < 0.01
    print(f"{TIMEZONE.key} is UTC{current:+g}; trigger is for UTC{args.utc_offset:+g} -> "
          f"{'run' if ok else 'skip'}")
    return 0 if ok else 1


def cmd_check_feeds(args) -> int:
    sources = load_sources()
    bad = 0
    for feed in sources.feeds:
        try:
            items = ingest.fetch_feed(feed)
            newest = max((i.published for i in items), default=None)
            print(f"OK    {feed.name:<28} {len(items):>3} items  newest={newest}")
        except Exception as exc:
            bad += 1
            print(f"FAIL  {feed.name:<28} {exc.__class__.__name__}: {exc}")
    print(f"\n{len(sources.feeds) - bad}/{len(sources.feeds)} feeds healthy; "
          f"{len(sources.allowed_domains)} Tier-1 domains whitelisted for web tools.")
    return 1 if bad == len(sources.feeds) else 0


def cmd_test_telegram(args) -> int:
    from briefing.report import render_pdf

    settings = Settings()
    tg = Telegram(settings.telegram_bot_token)
    me = tg.get_me()
    print(f"Bot: @{me.get('username')}")
    pdf, _ = render_pdf("<h1>Global Intelligence</h1><p>PDF delivery test.</p>")
    for chat in settings.telegram_chat_ids:
        tg.send_briefing(chat, "**Global Intelligence** — delivery test ✅\n- *Formatting check:* "
                               "BTP-Bund 110bp | EUR/USD 1.10 | <tags> & ampersands")
        tg.send_document(chat, "delivery-test.pdf", pdf, "PDF delivery test")
        print(f"sent test to {chat}")
    return 0


def cmd_schedule(args) -> int:
    for session, t in START_LOCAL.items():
        names = "WEEKLY (Sundays) / DAILY (other days)" if session == "AM" else "EVENING"
        print(f"starts {t:%H:%M} {TIMEZONE.key}  {session}: {names}")
    for spec in SPECS.values():
        words = sum(s.words for s in spec.sections)
        desks = f"{len(spec.desks)} research desk" + ("s" if len(spec.desks) > 1 else "")
        print(f"  {spec.edition.value:<8} {spec.title:<28} {len(spec.sections):>2} sections, "
              f"~{words:,} words, {desks}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="briefing", description=__doc__)
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="generate (and send) an edition")
    r.add_argument("edition", nargs="?", default="auto",
                   help="AM | PM | DAILY | EVENING | WEEKLY | auto "
                        "(AM = WEEKLY on Sundays, DAILY otherwise; PM = EVENING)")
    r.add_argument("--now", help="override the edition time (ISO-8601, UTC)")
    r.add_argument("--force", action="store_true",
                   help="send even if this session was already delivered today")
    r.add_argument("--no-send", action="store_true", help="do not post to Telegram")
    r.add_argument("--no-web", action="store_true", help="disable WebSearch/WebFetch")
    r.add_argument("--no-markets", action="store_true", help="skip market snapshot")
    r.add_argument("--no-feeds", action="store_true", help="skip RSS ingestion")
    r.add_argument("--print-prompt", action="store_true", help="print the user message sent")
    r.set_defaults(func=cmd_run)

    g = sub.add_parser("gate", help="exit 0 if the local UTC offset matches (for DST cron pairs)")
    g.add_argument("--utc-offset", type=float, required=True)
    g.set_defaults(func=cmd_gate)

    sub.add_parser("check-feeds", help="probe every configured RSS feed").set_defaults(
        func=cmd_check_feeds)
    sub.add_parser("test-telegram", help="send a formatting test message").set_defaults(
        func=cmd_test_telegram)
    sub.add_parser("schedule", help="show the schedule and editions").set_defaults(
        func=cmd_schedule)

    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return args.func(args)
