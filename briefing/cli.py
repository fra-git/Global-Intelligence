"""Command line entry point: `python -m briefing <command>`."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone

from briefing import ingest
from briefing.config import Settings, load_sources
from briefing.dispatch import START_LOCAL, SPECS, TIMEZONE, parts_for, utc_offset_hours
from briefing.pipeline import RunOptions, run_session
from briefing.telegram import Telegram


def _parse_now(value: str | None) -> datetime | None:
    if not value:
        return None
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def cmd_run(args) -> int:
    settings = Settings()
    opts = RunOptions(send=not args.no_send, web=not args.no_web, markets=not args.no_markets,
                      feeds=not args.no_feeds, print_prompt=args.print_prompt)
    results = run_session(parts_for(args.dispatch), settings, opts, _parse_now(args.now))

    for r in results:
        print(f"\n===== {r.dispatch.value} ({r.chars} chars) =====\n{r.text}")
        print(json.dumps({k: r.meta[k] for k in ("mode", "error", "model", "web_tool_calls",
                                                  "usage", "rewrites", "missing_sections")},
                         indent=2), file=sys.stderr)
    return 1 if any(r.meta["missing_sections"] for r in results) else 0


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
    settings = Settings()
    tg = Telegram(settings.telegram_bot_token)
    me = tg.get_me()
    print(f"Bot: @{me.get('username')}")
    for chat in settings.telegram_chat_ids:
        tg.send_briefing(chat, "**Global Intelligence** — delivery test ✅\n*Formatting check:* "
                               "BTP-Bund 110bp | EUR/USD 1.10 | <tags> & ampersands")
        print(f"sent test to {chat}")
    return 0


def cmd_schedule(args) -> int:
    for session, t in START_LOCAL.items():
        for part in (1, 2):
            spec = SPECS[parts_for(f"{session}_PART_{part}")[0]]
            print(f"starts {t:%H:%M} {TIMEZONE.key}  {spec.type.value:<10} {spec.title}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="briefing", description=__doc__)
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="generate (and send) a dispatch")
    r.add_argument("dispatch", nargs="?", default="auto",
                   help="AM | PM | AM_PART_1 | AM_PART_2 | PM_PART_1 | PM_PART_2 | auto")
    r.add_argument("--now", help="override dispatch time (ISO-8601, UTC)")
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
    sub.add_parser("schedule", help="show the daily dispatch schedule").set_defaults(
        func=cmd_schedule)

    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return args.func(args)
