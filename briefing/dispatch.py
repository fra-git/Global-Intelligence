"""Editions (daily report, evening update, Sunday weekly), their desks and sections, and the schedule.

Each edition is written by several research "desks" (one Claude Code run each,
with web research) plus an editor run that writes the front page and outlook
from the desks' output. Sections are H2 headings; the report is assembled in
the order of `parts`, regardless of the order the desks wrote them in.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from enum import Enum
from zoneinfo import ZoneInfo


class Edition(str, Enum):
    DAILY = "DAILY"
    EVENING = "EVENING"
    WEEKLY = "WEEKLY"

    @property
    def session(self) -> str:
        return "PM" if self is Edition.EVENING else "AM"


EDITOR = "editor"
MARKETS = "markets"  # rendered from the price snapshot by code, not written by a desk


@dataclass(frozen=True)
class Section:
    heading: str
    desk: str
    guidance: str
    words: int = 0
    # Feed tags used for this section's headline fallback if its desk fails.
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class Part:
    title: str
    sections: tuple[Section, ...]


@dataclass(frozen=True)
class Desk:
    key: str
    title: str
    # Region/topic tags (see ingest.TAGS) whose feed items this desk receives.
    tags: tuple[str, ...]
    searches: int
    wants_markets: bool = False


@dataclass(frozen=True)
class EditionSpec:
    edition: Edition
    title: str
    lookback_hours: int
    parts: tuple[Part, ...]
    desks: tuple[Desk, ...]
    editor_searches: int
    # The editor section quoted as the Telegram summary.
    summary_heading: str
    # Evening skips items the morning report already used.
    skip_seen: bool = False
    feed_items_per_desk: int = 45

    @property
    def sections(self) -> tuple[Section, ...]:
        return tuple(s for p in self.parts for s in p.sections)

    def sections_for(self, desk: str) -> tuple[Section, ...]:
        return tuple(s for s in self.sections if s.desk == desk)


_ALL_TAGS = ("it", "eu", "us", "cn", "ru", "me", "ip", "af", "la", "brics",
             "defence", "cyber", "tech", "space", "econ", "energy")

_EUROPE = Desk("europe", "Europe & Italy", ("it", "eu"), searches=10)
_POWERS = Desk("powers", "Great Powers", ("us", "cn", "ru"), searches=10)
_WORLD = Desk("world", "World Regions", ("me", "ip", "af", "la", "brics"), searches=12)
_SECTECH = Desk("sectech", "Security, Technology & Space", ("defence", "cyber", "tech", "space"),
                searches=10)
_ECONOMY = Desk("economy", "Economy, Markets & Energy", ("econ", "energy"), searches=10,
                wants_markets=True)

_GLANCE = Section(
    "At a Glance", EDITOR,
    "The 8-10 most important developments across the whole report, most consequential first. "
    "One bullet each: '- **Short headline:** one or two sentences with the key fact and why it "
    "matters.' Cover a mix of regions and topics, not only Europe.", 350)


def _daily_parts(scale: float = 1.0, weekly: bool = False) -> tuple[Part, ...]:
    def s(heading: str, desk: str, guidance: str, words: int, tags: tuple[str, ...]) -> Section:
        if weekly:
            guidance = ("Cover the WHOLE WEEK: the main developments, how each story evolved day by "
                        "day, and where it stands now. " + guidance)
        return Section(heading, desk, guidance, int(words * scale), tags)

    return (
        Part("Europe & Italy", (
            s("Italy", "europe",
              "Domestic politics (government, parliament, parties, coalition tensions, polls, "
              "regional politics, justice), the economy (growth, jobs, inflation, budget and debt, "
              "BTP-Bund spread, banks, industry, strikes), and major national news. Italy's role in "
              "EU and foreign policy.", 800, ("it",)),
            s("European Union", "europe",
              "Commission, Council, Parliament and ECB: legislation, enlargement, budget, defence "
              "integration, migration, competitiveness, trade policy, rule-of-law disputes.", 600, ("eu",)),
            s("Across Europe", "europe",
              "Country-by-country roundup, one '### Country' item per country with real news: "
              "Germany, France, Spain, Poland, Netherlands, Belgium, Nordics, Baltics, Central & "
              "Eastern Europe (Hungary, Czechia, Slovakia, Romania...), Greece, Portugal, Austria, "
              "the Balkans, the UK, Switzerland and Norway. Politics, elections, economy, unrest. "
              "Skip countries with nothing notable.", 800, ("eu",)),
        )),
        Part("Great Powers", (
            s("United States", "powers",
              "White House and Congress, domestic politics and courts, foreign policy, trade and "
              "tariffs, the Fed and economy, and what it means for Europe.", 650, ("us",)),
            s("China", "powers",
              "Leadership and policy, economy (growth, property, deflation, stimulus, exports), "
              "foreign policy, Taiwan, export controls, relations with the EU and US.", 600, ("cn",)),
            s("Russia & Ukraine", "powers",
              "The front line and military situation, diplomacy and ceasefire talks, Russia's "
              "economy and sanctions, Ukraine's politics and support from allies, hybrid attacks "
              "on Europe.", 650, ("ru",)),
        )),
        Part("World Regions", (
            s("Middle East & Gulf", "world",
              "Israel, Gaza, the West Bank and Lebanon; Iran; Syria and Iraq; Saudi Arabia, the "
              "UAE and Qatar; Turkey; Yemen and Red Sea shipping; oil politics.", 600, ("me",)),
            s("Indo-Pacific", "world",
              "Japan, South Korea, North Korea, Taiwan, India and South Asia, Southeast Asia and "
              "Australia: politics, security, chips and supply chains.", 600, ("ip",)),
            s("BRICS+ & Global South", "world",
              "BRICS+ as a bloc and its members' moves (India, Brazil, South Africa, Gulf members, "
              "Indonesia...), de-dollarisation, the New Development Bank, Global South diplomacy.",
              400, ("brics",)),
            s("Africa", "world",
              "Coups and conflicts (Sahel, Sudan, DRC, Horn of Africa), elections, economies, "
              "critical minerals, and Chinese, Russian, Gulf and European influence.", 450, ("af",)),
            s("Latin America", "world",
              "Brazil, Mexico, Argentina, Venezuela, Colombia, Chile and others: politics, "
              "economy, lithium and commodities, migration, US-China competition.", 450, ("la",)),
        )),
        Part("Security, Technology & Space", (
            s("Defence & Security", "sectech",
              "Wars and military moves worldwide, NATO and European defence, arms deals and "
              "budgets, defence industry, nuclear issues, terrorism.", 650, ("defence",)),
            s("Cyber & Information Warfare", "sectech",
              "Major hacks and ransomware, state cyber operations, attacks on infrastructure, "
              "disinformation and influence campaigns, espionage, digital sanctions evasion.", 400, ("cyber",)),
            s("Technology & AI", "sectech",
              "AI models, labs and companies; chips and semiconductors; export controls; big tech "
              "and regulation (EU AI Act, DMA); quantum, biotech and other frontier tech.", 700, ("tech",)),
            s("Space", "sectech",
              "Launches, satellite constellations, military space, ESA/EU programmes (IRIS², "
              "Ariane), NASA, SpaceX, China's and India's programmes, commercial space.", 400, ("space",)),
        )),
        Part("Economy, Markets & Energy", (
            s("Global Economy & Central Banks", "economy",
              "ECB, Fed, BoJ, PBoC, BoE and other central banks; inflation, growth and jobs data; "
              "IMF/OECD outlooks; public debt.", 600, ("econ",)),
            s("Markets & Finance", "economy",
              "Equities, bonds and spreads, currencies, commodities, crypto; banks and big deals; "
              "what moved and why. Separate facts from market expectations.", 500, ("econ",)),
            s("Trade, Tariffs & Sanctions", "economy",
              "Tariffs and trade deals, export controls, sanctions packages and enforcement, WTO, "
              "supply chains.", 450, ("econ",)),
            s("Energy & Critical Minerals", "economy",
              "Oil, gas and LNG, power prices and grids, nuclear and renewables, OPEC+, lithium, "
              "rare earths, copper and other critical minerals; climate and energy policy.", 550, ("energy",)),
        )),
    )


_DAILY_OUTLOOK = Part("Outlook", (
    Section("Scenarios", EDITOR,
            "Pick the 3 stories with the biggest consequences. For each: '### Story', then a "
            "base case, an upside and a downside scenario (1-2 sentences each, with rough "
            "likelihood words like 'likely'/'unlikely', not invented percentages) and the "
            "signposts that would show which way it is going.", 600),
    Section("What to Watch", EDITOR,
            "The next 7 days: a markdown table with columns Date | Event | Why it matters. "
            "Central bank meetings, data releases, summits, elections, votes, deadlines, "
            "launches, earnings. Verify dates.", 350),
    Section("Glossary", EDITOR,
            "8-12 terms, acronyms, institutions or people used in today's report that a "
            "non-specialist may not know: '- **Term:** plain-language explanation.'", 300),
))

_DAILY_DESKS = (_EUROPE, _POWERS, _WORLD, _SECTECH, _ECONOMY)

SPECS: dict[Edition, EditionSpec] = {
    Edition.DAILY: EditionSpec(
        Edition.DAILY,
        "Daily Intelligence Report",
        lookback_hours=24,
        parts=(Part("Front Page", (_GLANCE, Section("Markets Dashboard", MARKETS, ""))),
               *_daily_parts(), _DAILY_OUTLOOK),
        desks=_DAILY_DESKS,
        editor_searches=4,
        summary_heading="At a Glance",
    ),
    Edition.EVENING: EditionSpec(
        Edition.EVENING,
        "Evening Update",
        lookback_hours=15,
        parts=(Part("Evening Update", (
            Section("What Changed Today", "evening",
                    "The 6-8 most important developments since this morning's report, most "
                    "consequential first, one bullet each: '- **Short headline:** what happened "
                    "and why it matters.'", 350, _ALL_TAGS),
            Section("Europe & Italy", "evening",
                    "The day's news from Italy, the EU and other European countries.", 450, ("it", "eu")),
            Section("World", "evening",
                    "The day's news from the US, China, Russia/Ukraine, the Middle East, "
                    "Indo-Pacific, Africa and Latin America.", 550, ("us", "cn", "ru", "me", "ip", "af", "la", "brics")),
            Section("Markets Close", "evening",
                    "How European and US markets, bonds, currencies, oil and gas moved today, "
                    "and why.", 250, ("econ", "energy")),
            Section("Technology, Defence & Space", "evening",
                    "The day's news in AI and tech, defence and security, cyber and space.", 350, ("tech", "defence", "cyber", "space")),
            Section("Overnight & Tomorrow", "evening",
                    "What to watch overnight in Asia and tomorrow: data, meetings, deadlines, "
                    "risks.", 200),
            Section("Markets Dashboard", MARKETS, ""),
        )),),
        desks=(Desk("evening", "Evening Desk", _ALL_TAGS, searches=10, wants_markets=True),),
        editor_searches=0,
        summary_heading="What Changed Today",
        skip_seen=True,
        feed_items_per_desk=60,
    ),
    Edition.WEEKLY: EditionSpec(
        Edition.WEEKLY,
        "Weekly Deep-Dive",
        lookback_hours=24 * 7,
        parts=(
            Part("Front Page", (
                Section("The Week in One Page", EDITOR,
                        "The 10-12 most important developments of the week, most consequential "
                        "first. One bullet each: '- **Short headline:** two sentences on what "
                        "happened and why it matters.'", 500),
                Section("Markets Dashboard", MARKETS, ""),
            )),
            *_daily_parts(scale=1.4, weekly=True),
            Part("Analysis & Outlook", (
                Section("Trends of the Week", EDITOR,
                        "4-6 big-picture trends that connect the week's events across regions "
                        "and topics. '### Trend' then 2-3 paragraphs each.", 900),
                Section("Deep Dive", EDITOR,
                        "One long analytical essay on the single most consequential theme of "
                        "the week: '### Title', background, the actors and their interests, "
                        "what changed this week, implications for Europe and Italy, and how it "
                        "could evolve.", 1400),
                Section("Scenario Scorecard", EDITOR,
                        "Review the scenarios from this week's daily reports (given below): "
                        "which played out, which did not, and what we learned. Then updated "
                        "scenarios for the 3 most important stories going into next week.", 600),
                Section("Week Ahead", EDITOR,
                        "The next 7 days: a markdown table with columns Date | Event | Why it "
                        "matters. Verify dates.", 400),
                Section("Glossary", EDITOR,
                        "10-15 terms, acronyms, institutions or people from this report, "
                        "explained in plain language: '- **Term:** explanation.'", 400),
            )),
        ),
        desks=tuple(Desk(d.key, d.title, d.tags, d.searches + 2, d.wants_markets)
                    for d in _DAILY_DESKS),
        editor_searches=6,
        summary_heading="The Week in One Page",
        feed_items_per_desk=60,
    ),
}

# Session start times on the reader's local clock (default Italy, DST-aware),
# aligned with the owner's Claude Pro usage reset.
TIMEZONE = ZoneInfo(os.environ.get("BRIEFING_TZ", "Europe/Rome"))
START_LOCAL: dict[str, time] = {"AM": time(5, 50), "PM": time(20, 50)}


def local_now(now: datetime | None = None) -> datetime:
    return (now or datetime.now(timezone.utc)).astimezone(TIMEZONE)


def utc_offset_hours(now: datetime | None = None) -> float:
    """Current UTC offset of the local timezone (Italy: 1 in winter, 2 in summer)."""
    return local_now(now).utcoffset().total_seconds() / 3600


def slot_for(now: datetime) -> tuple[str, str]:
    """The session slot a moment belongs to, as (session, local date).

    AM runs from the morning start until the evening start; PM from the evening
    start until the next morning start, so a PM run after midnight still belongs
    to the previous day's evening.
    """
    loc = local_now(now)
    t = loc.time()
    if START_LOCAL["AM"] <= t < START_LOCAL["PM"]:
        return "AM", f"{loc.date()}"
    day = loc.date() if t >= START_LOCAL["PM"] else loc.date() - timedelta(days=1)
    return "PM", f"{day}"


def session_for(now: datetime) -> str:
    return slot_for(now)[0]


def edition_for(selector: str, now: datetime) -> Edition:
    """Resolve a selector: an edition name, a session ("AM"/"PM"), or "auto".

    The morning session is the weekly deep-dive on Sundays and the daily report otherwise.
    """
    sel = selector.upper()
    if sel in Edition.__members__:
        return Edition(sel)
    if sel == "AUTO":
        sel = session_for(now)
    if sel == "PM":
        return Edition.EVENING
    if sel == "AM":
        return Edition.WEEKLY if local_now(now).weekday() == 6 else Edition.DAILY
    raise ValueError(f"Unknown edition selector: {selector!r}")
